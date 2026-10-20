"""POST /transaction now runs the full LangGraph pipeline (Week 4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt
from sqlalchemy.orm import sessionmaker

from agents.uid import clean_component, compute_uid
from api.auth import create_access_token
from api.main import app
from db.models import Account, Customer, RiskAssessment
from db.session import get_session

DAY = 86400
_FAST_HASH = bcrypt.using(rounds=4).hash("pw")


def _login(TestSession, dt=10 * DAY, card1=1000):
    """POST /transaction needs a logged-in customer who already exists (ADR-021):
    pre-create the customer + account these payloads resolve to and return a
    Bearer header for them. D1n is constant across _body(dt) calls, so one
    customer covers every dt."""
    with TestSession() as s:
        uid = compute_uid(card1, 300.0, 5.0 + dt / DAY, dt / DAY)
        customer = Customer(
            synthetic_uid=uid, billing_region=clean_component(300.0), name="c",
            email=f"{uid}@example.invalid", hashed_password=_FAST_HASH,
        )
        s.add(customer)
        s.flush()
        s.add(Account(customer_id=customer.customer_id, account_number=f"ACCT-{uid}", account_type="credit"))
        s.commit()
        return {"Authorization": f"Bearer {create_access_token(customer.customer_id, 'customer')}"}


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
    # Deliberately NOT `with TestClient(app)`: that would run the lifespan and
    # create tables in the real fraud_detection.db.
    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _body(dt, amount=10.0, **extra):
    body = dict(
        card1=1000, addr1=300.0, d1=5.0 + dt / DAY, card6="credit",
        amount=amount, currency="USD", product_cd="W", transaction_dt=dt,
    )
    body.update(extra)
    return body


def test_response_carries_decision_score_and_explanation(client):
    c, TestSession = client
    h = _login(TestSession)
    r = c.post("/transaction", json=_body(10 * DAY), headers=h)
    assert r.status_code == 201
    data = r.json()
    assert data["decision"] == "allow"
    assert data["risk_score"] == 0.0
    # Week 5 (ADR-020): plain-language sentence first, technical evidence after it.
    assert data["explanation"].startswith("Allowed: no signal raised enough risk.")
    assert "Evidence: ALLOW (risk 0.00)" in data["explanation"]
    assert data["case_id"] is None  # allowed transactions open no case
    assert data["transaction_id"] > 0  # Week 1 fields still present


def test_amount_spike_is_flagged_through_the_api(client):
    c, TestSession = client
    h = _login(TestSession)
    for i in range(3):
        assert c.post("/transaction", json=_body(10 * DAY + i * 7200), headers=h).status_code == 201
    r = c.post("/transaction", json=_body(10 * DAY + 3 * 7200, amount=100.0), headers=h)
    assert r.status_code == 201
    assert r.json()["decision"] == "flag"
    assert "amount_own_history" in r.json()["explanation"]


def test_invalid_amount_is_still_422(client):
    c, TestSession = client
    h = _login(TestSession)
    r = c.post("/transaction", json=_body(10 * DAY, amount=-5.0), headers=h)
    assert r.status_code == 422


def test_assessment_is_persisted_and_committed(client):
    c, TestSession = client
    h = _login(TestSession)
    c.post("/transaction", json=_body(10 * DAY), headers=h)
    with TestSession() as s:  # a fresh session sees it only if the route committed
        assert s.query(RiskAssessment).count() == 1


def test_missing_device_is_reported_as_an_abstention(client):
    c, TestSession = client
    h = _login(TestSession)
    r = c.post("/transaction", json=_body(10 * DAY), headers=h)
    assert "device abstained" in r.json()["explanation"]


def test_flagged_transaction_returns_a_case_id(client):
    c, TestSession = client
    h = _login(TestSession)
    for i in range(3):
        c.post("/transaction", json=_body(10 * DAY + i * 7200), headers=h)
    r = c.post("/transaction", json=_body(10 * DAY + 3 * 7200, amount=100.0), headers=h)
    data = r.json()
    assert data["decision"] == "flag"
    assert data["case_id"] is not None
    assert data["explanation"].startswith("Flagged for review:")
    from db.models import FraudCase

    with TestSession() as s:  # committed by the route, visible to a fresh session
        case = s.get(FraudCase, data["case_id"])
        assert case is not None and case.transaction_id == data["transaction_id"]
