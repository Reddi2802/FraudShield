"""Investigator case review (ADR-021): list, detail, one feedback resolves a case."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt
from sqlalchemy.orm import sessionmaker

from agents.uid import clean_component, compute_uid
from api.auth import create_access_token
from api.main import app
from db.models import Account, CaseStatusEnum, Customer, Feedback, FraudCase, Investigator
from db.session import get_session

DAY = 86400
_FAST_HASH = bcrypt.using(rounds=4).hash("pw")


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


def _body(card1, dt, amount=10.0):
    return dict(
        card1=card1, addr1=300.0, d1=5.0 + dt / DAY, card6="credit", amount=amount,
        currency="USD", product_cd="W", transaction_dt=dt,
    )


def _customer_headers(TestSession, card1, dt=10 * DAY):
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


def _investigator(TestSession, n=1):
    with TestSession() as s:
        inv = Investigator(name=f"Inv{n}", email=f"inv{n}@example.invalid", hashed_password=_FAST_HASH)
        s.add(inv)
        s.commit()
        return inv.investigator_id, {"Authorization": f"Bearer {create_access_token(inv.investigator_id, 'investigator')}"}


def _flag_case(c, TestSession, card1=1000):
    """Three small transactions then a spike -> a FLAG (risk 0.6) and an open case."""
    h = _customer_headers(TestSession, card1)
    for i in range(3):
        c.post("/transaction", json=_body(card1, 10 * DAY + i * 7200), headers=h)
    return c.post("/transaction", json=_body(card1, 10 * DAY + 3 * 7200, amount=100.0), headers=h).json()


def _block_case(c, TestSession, card1=2000):
    """Five quick transactions then a spike -> velocity + amount = BLOCK (risk >= 0.7)."""
    h = _customer_headers(TestSession, card1)
    for i in range(5):
        c.post("/transaction", json=_body(card1, 10 * DAY + i * 60), headers=h)
    return c.post("/transaction", json=_body(card1, 10 * DAY + 5 * 60, amount=100.0), headers=h).json()


def test_empty_list_when_nothing_is_open(client):
    c, TestSession = client
    _, inv = _investigator(TestSession)
    assert c.get("/cases", headers=inv).json() == []


def test_list_shows_open_cases_highest_risk_first(client):
    c, TestSession = client
    flagged = _flag_case(c, TestSession, 1000)
    blocked = _block_case(c, TestSession, 2000)
    _, inv = _investigator(TestSession)

    rows = c.get("/cases", headers=inv).json()

    assert [r["case_id"] for r in rows] == [blocked["case_id"], flagged["case_id"]]
    assert [r["decision"] for r in rows] == ["block", "flag"]
    assert rows[0]["risk_score"] > rows[1]["risk_score"]
    assert all(r["status"] == "open" for r in rows)


def test_status_filter_and_bad_status(client):
    c, TestSession = client
    case = _flag_case(c, TestSession)
    _, inv = _investigator(TestSession)
    assert c.get("/cases?status=resolved", headers=inv).json() == []
    assert len(c.get("/cases?status=open", headers=inv).json()) == 1
    assert c.get("/cases?status=bogus", headers=inv).status_code == 422
    assert case["case_id"] is not None


def test_detail_includes_the_explanation_and_transaction(client):
    c, TestSession = client
    case = _flag_case(c, TestSession)
    _, inv = _investigator(TestSession)

    r = c.get(f"/cases/{case['case_id']}", headers=inv)

    assert r.status_code == 200
    body = r.json()
    assert body["transaction_id"] == case["transaction_id"]
    assert body["transaction"]["amount"] == 100.0 and body["transaction"]["customer_id"] == case["customer_id"]
    assert body["decision"] == "flag"
    assert body["explanation"].startswith("Flagged for review:")
    assert body["feedback"] is None and body["resolved_at"] is None


def test_feedback_resolves_the_case_and_records_the_investigator(client):
    c, TestSession = client
    case = _flag_case(c, TestSession)
    inv_id, inv = _investigator(TestSession)

    r = c.post(
        f"/cases/{case['case_id']}/feedback", json={"label": "fraud", "notes": "stolen card"}, headers=inv
    )

    assert r.status_code == 201
    assert r.json()["status"] == "resolved" and r.json()["label"] == "fraud"
    with TestSession() as s:
        stored = s.get(FraudCase, case["case_id"])
        assert stored.status == CaseStatusEnum.RESOLVED
        assert stored.resolved_at is not None and stored.investigator_id == inv_id
        assert s.query(Feedback).count() == 1

    detail = c.get(f"/cases/{case['case_id']}", headers=inv).json()
    assert detail["feedback"]["label"] == "fraud" and detail["feedback"]["notes"] == "stolen card"
    assert detail["feedback"]["investigator_id"] == inv_id
    assert c.get("/cases", headers=inv).json() == []  # no longer open
    assert len(c.get("/cases?status=resolved", headers=inv).json()) == 1


def test_second_feedback_is_409_and_changes_nothing(client):
    c, TestSession = client
    case = _flag_case(c, TestSession)
    _, inv = _investigator(TestSession)
    url = f"/cases/{case['case_id']}/feedback"
    assert c.post(url, json={"label": "not_fraud"}, headers=inv).status_code == 201

    _, other = _investigator(TestSession, n=2)
    assert c.post(url, json={"label": "fraud"}, headers=other).status_code == 409
    with TestSession() as s:
        assert s.query(Feedback).count() == 1


def test_unknown_case_is_404_for_read_and_feedback(client):
    c, TestSession = client
    _, inv = _investigator(TestSession)
    assert c.get("/cases/999", headers=inv).status_code == 404
    assert c.post("/cases/999/feedback", json={"label": "fraud"}, headers=inv).status_code == 404


def test_feedback_validation(client):
    c, TestSession = client
    case = _flag_case(c, TestSession)
    _, inv = _investigator(TestSession)
    url = f"/cases/{case['case_id']}/feedback"
    assert c.post(url, json={"label": "maybe"}, headers=inv).status_code == 422
    assert c.post(url, json={"label": "fraud", "notes": "x" * 501}, headers=inv).status_code == 422


def test_cases_require_an_investigator(client):
    c, TestSession = client
    case = _flag_case(c, TestSession)
    assert c.get(f"/cases/{case['case_id']}").status_code == 401
    customer_token = {"Authorization": f"Bearer {create_access_token(1, 'customer')}"}
    assert c.get(f"/cases/{case['case_id']}", headers=customer_token).status_code == 403
    assert c.post(
        f"/cases/{case['case_id']}/feedback", json={"label": "fraud"}, headers=customer_token
    ).status_code == 403
