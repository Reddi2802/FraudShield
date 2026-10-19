"""POST /transaction now runs the full LangGraph pipeline (Week 4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.main import app
from db.models import RiskAssessment
from db.session import get_session

DAY = 86400


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
    c, _ = client
    r = c.post("/transaction", json=_body(10 * DAY))
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
    c, _ = client
    for i in range(3):
        assert c.post("/transaction", json=_body(10 * DAY + i * 7200)).status_code == 201
    r = c.post("/transaction", json=_body(10 * DAY + 3 * 7200, amount=100.0))
    assert r.status_code == 201
    assert r.json()["decision"] == "flag"
    assert "amount_own_history" in r.json()["explanation"]


def test_invalid_amount_is_still_422(client):
    c, _ = client
    r = c.post("/transaction", json=_body(10 * DAY, amount=-5.0))
    assert r.status_code == 422


def test_assessment_is_persisted_and_committed(client):
    c, TestSession = client
    c.post("/transaction", json=_body(10 * DAY))
    with TestSession() as s:  # a fresh session sees it only if the route committed
        assert s.query(RiskAssessment).count() == 1


def test_missing_device_is_reported_as_an_abstention(client):
    c, _ = client
    r = c.post("/transaction", json=_body(10 * DAY))
    assert "device abstained" in r.json()["explanation"]


def test_flagged_transaction_returns_a_case_id(client):
    c, TestSession = client
    for i in range(3):
        c.post("/transaction", json=_body(10 * DAY + i * 7200))
    r = c.post("/transaction", json=_body(10 * DAY + 3 * 7200, amount=100.0))
    data = r.json()
    assert data["decision"] == "flag"
    assert data["case_id"] is not None
    assert data["explanation"].startswith("Flagged for review:")
    from db.models import FraudCase

    with TestSession() as s:  # committed by the route, visible to a fresh session
        case = s.get(FraudCase, data["case_id"])
        assert case is not None and case.transaction_id == data["transaction_id"]
