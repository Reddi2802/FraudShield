"""
Tests for api/routes/transactions.py.

Per ROADMAP.md's week-1 checklist: "endpoint returns correct status/shape."

Deliberately does NOT use `with TestClient(app) as client:` — that form
triggers FastAPI's lifespan, which calls db.session.init_db() against the
REAL fraud_detection.db file on disk (see api/main.py). Tests should
never create/modify that file. Instead, the `client` fixture below
overrides the get_session dependency to point every route at a fresh
in-memory test database, and skips lifespan entirely.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt
from sqlalchemy.orm import sessionmaker

from agents.uid import clean_component, compute_uid
from api.auth import create_access_token
from api.main import app
from db.models import Account, Customer
from db.session import get_session


# Hashing with passlib's default bcrypt cost takes ~0.3 s; tests use the cheapest cost.
_FAST_HASH = bcrypt.using(rounds=4).hash("pw")


def make_customer(session, payload) -> Customer:
    """Pre-create the customer + account this payload resolves to, in the same
    shape agents/ingestion.py creates them. POST /transaction now requires a
    logged-in customer (ADR-021), and a token needs a customer id, so the
    customer must exist before the first request."""
    uid = compute_uid(
        payload["card1"], payload.get("addr1"), payload.get("d1"), payload["transaction_dt"] / 86400
    )
    customer = Customer(
        synthetic_uid=uid,
        billing_region=clean_component(payload.get("addr1")),
        name=f"Customer {uid}",
        email=f"{uid}@example.invalid",
        hashed_password=_FAST_HASH,
    )
    session.add(customer)
    session.flush()
    session.add(
        Account(
            customer_id=customer.customer_id,
            account_number=f"ACCT-{uid}",
            account_type=payload.get("card6") or "unknown",
        )
    )
    session.commit()
    return customer


def auth_headers(test_engine, payload) -> dict:
    with sessionmaker(bind=test_engine)() as session:
        customer = make_customer(session, payload)
        return {"Authorization": f"Bearer {create_access_token(customer.customer_id, 'customer')}"}


def any_customer_headers() -> dict:
    """For validation tests: the request is rejected before any customer lookup."""
    return {"Authorization": f"Bearer {create_access_token(1, 'customer')}"}


@pytest.fixture()
def client(test_engine):
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_session():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


VALID_PAYLOAD = {
    "card1": 13926.0,
    "addr1": 315.0,
    "d1": 2.0,
    "transaction_dt": 864000,  # fixes D1n = 8, deterministic UID across runs
    "card6": "credit",
    "amount": 125.50,
    "currency": "usd",
    "product_cd": "W",
    "device_type": "mobile",
    "device_info": "iOS Device",
}


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_submit_transaction_returns_201_with_expected_shape(client, test_engine):
    response = client.post(
        "/transaction", json=VALID_PAYLOAD, headers=auth_headers(test_engine, VALID_PAYLOAD)
    )
    assert response.status_code == 201

    body = response.json()
    expected_keys = {
        "transaction_id", "synthetic_uid", "customer_id", "account_id",
        "merchant_id", "device_id", "amount", "currency", "submitted_at",
    }
    assert expected_keys.issubset(body.keys())
    assert body["synthetic_uid"] == "13926-315-8"
    assert body["currency"] == "USD"  # lowercase input, uppercased by the schema validator
    assert body["device_id"] is not None


def test_repeated_submission_with_same_identity_reuses_customer(client, test_engine):
    headers = auth_headers(test_engine, VALID_PAYLOAD)
    first = client.post("/transaction", json=VALID_PAYLOAD, headers=headers).json()
    second = client.post("/transaction", json=VALID_PAYLOAD, headers=headers).json()

    assert first["customer_id"] == second["customer_id"]
    assert first["transaction_id"] != second["transaction_id"]


def test_submission_with_no_device_info_returns_null_device_id(client, test_engine):
    payload = dict(VALID_PAYLOAD, card1=99999.0, device_type=None, device_info=None)
    response = client.post("/transaction", json=payload, headers=auth_headers(test_engine, payload))
    assert response.status_code == 201
    assert response.json()["device_id"] is None


def test_negative_amount_returns_422(client):
    payload = dict(VALID_PAYLOAD, amount=-5)
    response = client.post("/transaction", json=payload, headers=any_customer_headers())
    assert response.status_code == 422


def test_invalid_currency_length_returns_422(client):
    payload = dict(VALID_PAYLOAD, currency="US")
    response = client.post("/transaction", json=payload, headers=any_customer_headers())
    assert response.status_code == 422


def test_missing_required_field_returns_422(client):
    payload = dict(VALID_PAYLOAD)
    del payload["product_cd"]
    response = client.post("/transaction", json=payload, headers=any_customer_headers())
    assert response.status_code == 422
