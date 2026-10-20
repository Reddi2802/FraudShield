"""Login and token rules (ADR-021): who gets in, and who gets which 401 / 403."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from passlib.hash import bcrypt
from sqlalchemy.orm import sessionmaker

from api.auth import ALGORITHM, JWT_SECRET, create_access_token
from api.main import app
from db.models import Customer, Investigator
from db.session import get_session
from scripts.seed_investigators import DEMO_PASSWORD, seed_investigators

PASSWORD = "pw123"
_FAST_HASH = bcrypt.using(rounds=4).hash(PASSWORD)  # cheapest cost: tests only


@pytest.fixture()
def client(test_engine):
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    # Deliberately NOT `with TestClient(app)`: the lifespan would create the real DB file.
    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _add_customer(TestSession, email="alice@example.invalid") -> int:
    with TestSession() as s:
        customer = Customer(
            synthetic_uid="1-1-1", name="Alice", email=email, hashed_password=_FAST_HASH
        )
        s.add(customer)
        s.commit()
        return customer.customer_id


def _add_investigator(TestSession, email="inv@example.invalid") -> int:
    with TestSession() as s:
        investigator = Investigator(name="Inv", email=email, hashed_password=_FAST_HASH)
        s.add(investigator)
        s.commit()
        return investigator.investigator_id


def _login(c, email, role, password=PASSWORD):
    return c.post("/auth/login", json={"email": email, "password": password, "role": role})


# ---- login ----

def test_customer_login_returns_a_token_with_the_right_claims(client):
    c, TestSession = client
    customer_id = _add_customer(TestSession)
    r = _login(c, "alice@example.invalid", "customer")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["role"] == "customer"
    assert body["user_id"] == customer_id
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=[ALGORITHM])
    assert claims["sub"] == str(customer_id) and claims["role"] == "customer"


def test_investigator_login(client):
    c, TestSession = client
    investigator_id = _add_investigator(TestSession)
    r = _login(c, "inv@example.invalid", "investigator")
    assert r.status_code == 200
    assert r.json()["role"] == "investigator" and r.json()["user_id"] == investigator_id


def test_wrong_password_is_401(client):
    c, TestSession = client
    _add_customer(TestSession)
    r = _login(c, "alice@example.invalid", "customer", password="nope")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"


def test_unknown_email_gets_the_identical_401(client):
    c, _ = client
    r = _login(c, "ghost@example.invalid", "customer")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"


def test_role_selects_the_table(client):
    c, TestSession = client
    _add_customer(TestSession)  # exists as a customer only
    assert _login(c, "alice@example.invalid", "investigator").status_code == 401


def test_invalid_role_is_422(client):
    c, _ = client
    assert _login(c, "a@example.invalid", "admin").status_code == 422


# ---- token checks ----

def test_missing_token_is_401_with_a_bearer_challenge(client):
    c, _ = client
    r = c.get("/transactions/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_garbage_token_is_401(client):
    c, _ = client
    r = c.get("/transactions/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_token_signed_with_another_secret_is_401(client):
    c, _ = client
    forged = jwt.encode({"sub": "1", "role": "customer"}, "some-other-secret", algorithm=ALGORITHM)
    assert c.get("/transactions/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_token_is_401(client):
    c, _ = client
    expired = create_access_token(1, "customer", expires_delta=timedelta(seconds=-5))
    assert c.get("/transactions/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_token_with_an_unknown_role_is_401(client):
    c, _ = client
    odd = jwt.encode({"sub": "1", "role": "admin"}, JWT_SECRET, algorithm=ALGORITHM)
    assert c.get("/transactions/me", headers={"Authorization": f"Bearer {odd}"}).status_code == 401


# ---- role checks ----

def test_investigator_token_cannot_submit_transactions(client):
    c, _ = client
    token = create_access_token(1, "investigator")
    payload = dict(
        card1=1000, addr1=300.0, d1=5.0, card6="credit", amount=10.0, currency="USD",
        product_cd="W", transaction_dt=864000,
    )
    r = c.post("/transaction", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_customer_token_cannot_reach_cases(client):
    c, _ = client
    token = create_access_token(1, "customer")
    assert c.get("/cases", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_investigator_token_cannot_read_a_customers_history(client):
    c, _ = client
    token = create_access_token(1, "investigator")
    assert c.get("/transactions/me", headers={"Authorization": f"Bearer {token}"}).status_code == 403


# ---- investigator seeding ----

def test_seed_investigators_is_idempotent_and_the_demo_password_works(client):
    c, TestSession = client
    with TestSession() as s:
        assert seed_investigators(s) == (2, 0)
        s.commit()
    with TestSession() as s:
        assert seed_investigators(s) == (0, 2)
        s.commit()
        assert s.query(Investigator).count() == 2

    r = c.post(
        "/auth/login",
        json={"email": "investigator1@example.invalid", "password": DEMO_PASSWORD, "role": "investigator"},
    )
    assert r.status_code == 200
