"""Option A (ADR-021): a customer acts only on their OWN data."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt
from sqlalchemy.orm import sessionmaker

from agents.uid import clean_component, compute_uid
from api.auth import create_access_token
from api.main import app
from db.models import Account, Customer, FraudCase, Merchant, RiskAssessment, Transaction
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


def _make_customer(TestSession, card1, dt=10 * DAY):
    """Pre-create the customer + account that _body(card1, dt) resolves to."""
    with TestSession() as s:
        uid = compute_uid(card1, 300.0, 5.0 + dt / DAY, dt / DAY)
        customer = Customer(
            synthetic_uid=uid, billing_region=clean_component(300.0), name=f"c{card1}",
            email=f"{uid}@example.invalid", hashed_password=_FAST_HASH,
        )
        s.add(customer)
        s.flush()
        s.add(Account(customer_id=customer.customer_id, account_number=f"ACCT-{uid}", account_type="credit"))
        s.commit()
        return customer.customer_id


def _headers(customer_id):
    return {"Authorization": f"Bearer {create_access_token(customer_id, 'customer')}"}


def _counts(TestSession):
    with TestSession() as s:
        return s.query(Customer).count(), s.query(Transaction).count(), s.query(RiskAssessment).count()


def test_customer_can_submit_their_own_transaction(client):
    c, TestSession = client
    me = _make_customer(TestSession, 1000)
    r = c.post("/transaction", json=_body(1000, 10 * DAY), headers=_headers(me))
    assert r.status_code == 201 and r.json()["customer_id"] == me


def test_submitting_for_another_customer_is_403_and_persists_nothing(client):
    c, TestSession = client
    alice = _make_customer(TestSession, 1000)
    _make_customer(TestSession, 2000)  # bob exists too
    before = _counts(TestSession)

    r = c.post("/transaction", json=_body(2000, 10 * DAY), headers=_headers(alice))

    assert r.status_code == 403
    assert r.json()["detail"] == "Transaction does not belong to the logged-in customer"
    assert _counts(TestSession) == before == (2, 0, 0)


def test_a_uid_with_no_customer_is_403_and_creates_no_customer(client):
    c, TestSession = client
    alice = _make_customer(TestSession, 1000)

    r = c.post("/transaction", json=_body(3000, 10 * DAY), headers=_headers(alice))

    assert r.status_code == 403
    assert _counts(TestSession) == (1, 0, 0)  # the customer the pipeline built was rolled back


# ADR-028: GET /transactions/me is customer-safe. A status only, never the score, explanation or case id.
SAFE_ROW_KEYS = {"transaction_id", "amount", "currency", "submitted_at", "status"}


def test_my_transactions_returns_only_my_rows_newest_first_with_status(client):
    c, TestSession = client
    alice = _make_customer(TestSession, 1000)
    bob = _make_customer(TestSession, 2000)
    for i in range(3):
        c.post("/transaction", json=_body(1000, 10 * DAY + i * 7200), headers=_headers(alice))
    c.post("/transaction", json=_body(2000, 10 * DAY), headers=_headers(bob))

    r = c.get("/transactions/me", headers=_headers(alice))

    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert [row["submitted_at"] for row in rows] == sorted((row["submitted_at"] for row in rows), reverse=True)
    assert all(row["status"] == "approved" for row in rows)
    assert all(set(row) == SAFE_ROW_KEYS for row in rows)  # no decision, risk_score, explanation or case_id


def test_my_transactions_includes_seeded_history_without_an_assessment(client):
    """Seeded transactions were loaded straight into the DB (no pipeline run), so
    they have no RiskAssessment: shown with a null status, not dropped."""
    c, TestSession = client
    alice = _make_customer(TestSession, 1000)
    with TestSession() as s:
        merchant = Merchant(name="m", category="W")
        s.add(merchant)
        s.flush()
        account = s.query(Account).filter_by(customer_id=alice).one()
        s.add(Transaction(account_id=account.account_id, merchant_id=merchant.merchant_id, amount=42.0, currency="USD"))
        s.commit()

    rows = c.get("/transactions/me", headers=_headers(alice)).json()
    assert len(rows) == 1
    assert rows[0]["amount"] == 42.0 and rows[0]["status"] is None


def test_flagged_transaction_shows_under_review_and_no_case_id(client):
    """The customer sees 'under_review' and nothing about the case; the case exists server-side
    for investigators (checked in the database here)."""
    c, TestSession = client
    alice = _make_customer(TestSession, 1000)
    for i in range(3):
        c.post("/transaction", json=_body(1000, 10 * DAY + i * 7200), headers=_headers(alice))
    spike = c.post("/transaction", json=_body(1000, 10 * DAY + 3 * 7200, amount=100.0), headers=_headers(alice))

    newest = c.get("/transactions/me", headers=_headers(alice)).json()[0]
    assert newest["transaction_id"] == spike.json()["transaction_id"]
    assert newest["status"] == "under_review"
    assert "case_id" not in newest and "risk_score" not in newest and "decision" not in newest

    with TestSession() as s:
        case = s.query(FraudCase).filter_by(transaction_id=newest["transaction_id"]).one_or_none()
        assert case is not None and case.fraud_case_id == spike.json()["case_id"]
