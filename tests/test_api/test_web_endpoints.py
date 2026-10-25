"""ADR-027 endpoints: /customers/me, POST /transactions/me, signals, /admin/overview."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agents.ingestion as ingestion
import db.models  # noqa: F401
from agents.uid import REFERENCE_START
from api.main import app
from db.base import Base
from db.models import Account, Customer, Investigator, Merchant, Transaction
from db.session import get_session

PASSWORD = "ChangeMe123!"
UID = "13926-315-8"
FAST_HASH = bcrypt.using(rounds=4)
ingestion.bcrypt = FAST_HASH  # new customers in tests would otherwise pay full bcrypt cost


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def client(session_factory):
    def _session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_customer(session_factory, uid=UID, n=4, amount=50.0):
    with session_factory() as s:
        c = Customer(synthetic_uid=uid, billing_region="315", name="Seed Customer 00001",
                     email="seed.customer.00001@example.invalid", hashed_password=FAST_HASH.hash(PASSWORD))
        s.add(c)
        s.flush()
        a = Account(customer_id=c.customer_id, account_number="ACCT-1", account_type="credit")
        m = Merchant(name="Merchant Category W", category="W")
        s.add_all([a, m])
        s.flush()
        for i in range(n):
            s.add(Transaction(account_id=a.account_id, merchant_id=m.merchant_id, amount=amount,
                              currency="USD", submitted_at=REFERENCE_START + timedelta(days=10, hours=i)))
        s.add(Investigator(name="Inv", email="investigator1@example.invalid", hashed_password=FAST_HASH.hash(PASSWORD)))
        s.commit()
        return c.customer_id


def _login(client, email, role):
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD, "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_customers_me_requires_customer_token(client, session_factory):
    _seed_customer(session_factory)
    assert client.get("/customers/me").status_code == 401
    inv = _login(client, "investigator1@example.invalid", "investigator")
    assert client.get("/customers/me", headers=inv).status_code == 403


def test_customers_me_profile(client, session_factory):
    cid = _seed_customer(session_factory, n=4, amount=50.0)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    body = client.get("/customers/me", headers=h).json()
    assert body["customer_id"] == cid
    assert body["card1"] == 13926
    assert body["billing_region"] == "315"
    assert body["typical_amount"] == 50.0
    assert body["transaction_count"] == 4


SAFE_KEYS = {"transaction_id", "amount", "currency", "submitted_at", "status", "message"}
LEAKY_KEYS = {"risk_score", "explanation", "signals", "decision", "case_id", "synthetic_uid", "customer_id", "device_id"}


def test_submit_my_transaction_is_customer_safe(client, session_factory):
    """ADR-028: the customer gets a status and a message, never the scoring internals."""
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    r = client.post("/transactions/me", headers=h, json={"amount": 55.0, "product_cd": "W", "card6": "credit"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == SAFE_KEYS
    assert not (LEAKY_KEYS & set(body))
    assert body["status"] in {"approved", "under_review", "declined"}
    # simulated clock: one hour after the latest seeded transaction (day 10 + 3h)
    assert body["submitted_at"].startswith("2017-12-11T04:00")


def test_status_mapping_and_messages(client, session_factory):
    _seed_customer(session_factory, amount=50.0)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    ok = client.post("/transactions/me", headers=h, json={"amount": 55.0, "product_cd": "W"}).json()
    assert ok["status"] == "approved" and "approved" in ok["message"]
    big = client.post("/transactions/me", headers=h, json={"amount": 5000.0, "product_cd": "W"}).json()
    assert big["status"] in {"under_review", "declined"}
    assert "risk" not in big["message"].lower() and "rule" not in big["message"].lower()


def test_blank_device_fields_do_not_create_a_device(client, session_factory):
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    client.post("/transactions/me", headers=h,
                json={"amount": 55.0, "product_cd": "W", "device_type": "  ", "device_info": ""})
    with session_factory() as s:
        assert s.query(Transaction).order_by(Transaction.transaction_id.desc()).first().device_id is None


def test_device_fields_reach_the_pipeline(client, session_factory):
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    client.post("/transactions/me", headers=h, json={
        "amount": 55.0, "product_cd": "W", "device_type": "mobile",
        "device_info": "SM-G960F Build/R16NW", "browser": "chrome 63.0"})
    with session_factory() as s:
        assert s.query(Transaction).order_by(Transaction.transaction_id.desc()).first().device_id is not None


@pytest.mark.parametrize("payload", [
    {"amount": 0, "product_cd": "W"},
    {"amount": -5, "product_cd": "W"},
    {"amount": 10, "product_cd": "Z"},
    {"amount": 10, "product_cd": "W", "card6": "gold"},
])
def test_submit_my_transaction_validation(client, session_factory, payload):
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    assert client.post("/transactions/me", headers=h, json=payload).status_code == 422


def test_investigator_cannot_use_my_transaction_endpoint(client, session_factory):
    _seed_customer(session_factory)
    inv = _login(client, "investigator1@example.invalid", "investigator")
    assert client.post("/transactions/me", headers=inv, json={"amount": 5, "product_cd": "W"}).status_code == 403


def test_investigator_still_sees_signals_for_a_flagged_transaction(client, session_factory):
    """The scoring detail moved to the investigator view, it did not disappear."""
    _seed_customer(session_factory, amount=50.0)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    client.post("/transactions/me", headers=h, json={"amount": 5000.0, "product_cd": "W"})
    inv = _login(client, "investigator1@example.invalid", "investigator")
    cases = client.get("/cases", headers=inv).json()
    assert len(cases) == 1
    detail = client.get(f"/cases/{cases[0]['case_id']}", headers=inv).json()
    assert [x["agent"] for x in detail["signals"]] == ["rules", "device", "behavioral", "network"]
    by = {x["agent"]: x for x in detail["signals"]}
    assert (by["rules"]["score"] or 0) > 0 and by["rules"]["weight"] == 1.0 and by["device"]["weight"] == 0.8
    assert by["behavioral"]["score"] is None  # no model registered in this test DB: abstains


def test_signals_none_for_a_transaction_that_never_ran_the_pipeline(session_factory):
    _seed_customer(session_factory)
    from api.signals import signals_for_transaction
    with session_factory() as s:
        assert signals_for_transaction(s.query(Transaction).first()) is None


def test_my_transactions_history_is_customer_safe(client, session_factory):
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    client.post("/transactions/me", headers=h, json={"amount": 55.0, "product_cd": "W"})
    rows = client.get("/transactions/me", headers=h).json()
    assert len(rows) == 5
    assert rows[0]["status"] == "approved" and rows[-1]["status"] is None  # seeded history: no status
    for row in rows:
        assert set(row) == {"transaction_id", "amount", "currency", "submitted_at", "status"}


def test_admin_overview_open_and_shaped(client, session_factory):
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    client.post("/transactions/me", headers=h, json={"amount": 5000.0, "product_cd": "W"})
    r = client.get("/admin/overview")  # no token: ADR-010
    assert r.status_code == 200
    body = r.json()
    assert body["customers"] == 1 and body["transactions"] == 5 and body["assessments"] == 1
    assert sum(body["decisions"].values()) == 1
    assert body["model"] is None
    assert body["retraining"] == {"labels_since_model": 0, "threshold": 100, "reached": False}


def test_old_raw_endpoint_still_works(client, session_factory):
    """POST /transaction (raw payload) keeps its contract; Streamlit and scripts use it."""
    _seed_customer(session_factory)
    h = _login(client, "seed.customer.00001@example.invalid", "customer")
    dt = 11 * 86400.0
    r = client.post("/transaction", headers=h, json={
        "card1": 13926, "addr1": 315, "d1": dt / 86400 - 8 - 1e-6, "card6": "credit",
        "amount": 60.0, "product_cd": "W", "transaction_dt": dt})
    assert r.status_code == 201, r.text
    assert r.json()["signals"] is not None
