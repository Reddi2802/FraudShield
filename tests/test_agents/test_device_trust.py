"""Device Trust Agent (Week 2) — dedicated tests (previously uncovered)."""

from __future__ import annotations

from datetime import timedelta

from agents.device_trust import run_device_trust
from agents.ingestion import process_transaction

DAY = 86400
DEVICE = dict(
    device_type="mobile",
    device_info="SM-G960F Build/R16NW",
    browser="chrome 63.0",
)


def _ingest(session, *, card1, transaction_dt, d1, with_device=True):
    args = dict(
        card1=card1,
        addr1=300.0,
        d1=d1,
        card6="credit",
        amount=25.0,
        currency="USD",
        product_cd="W",
        transaction_dt=transaction_dt,
    )
    if with_device:
        args.update(DEVICE)
    return process_transaction(session, **args)


def test_transaction_with_no_device(db_session):
    t = _ingest(db_session, card1=1000, transaction_dt=10 * DAY, d1=5.0, with_device=False)
    r = run_device_trust(db_session, t)
    assert r.no_device
    assert r.reuse_count == 0
    assert r.device_age is None
    assert not r.is_first_seen_globally
    assert not r.is_new_device_for_customer


def test_first_ever_use_of_a_device(db_session):
    t = _ingest(db_session, card1=1000, transaction_dt=10 * DAY, d1=5.0)
    r = run_device_trust(db_session, t)
    assert r.reuse_count == 1
    assert r.is_first_seen_globally
    assert r.is_new_device_for_customer
    assert r.device_age == timedelta(0)


def test_repeat_use_by_same_customer(db_session):
    _ingest(db_session, card1=1000, transaction_dt=10 * DAY, d1=5.0)
    second = _ingest(db_session, card1=1000, transaction_dt=13 * DAY, d1=8.0)
    r = run_device_trust(db_session, second)
    assert r.reuse_count == 1
    assert not r.is_first_seen_globally
    assert not r.is_new_device_for_customer
    assert r.device_age == timedelta(days=3)


def test_cross_customer_device_reuse(db_session):
    _ingest(db_session, card1=1000, transaction_dt=10 * DAY, d1=5.0)
    other = _ingest(db_session, card1=2000, transaction_dt=11 * DAY, d1=6.0)
    r = run_device_trust(db_session, other)
    assert r.reuse_count == 2  # two distinct customers linked to this device
    assert not r.is_first_seen_globally  # someone else used it first
    assert r.is_new_device_for_customer  # but it's new for THIS customer
    assert r.device_age == timedelta(days=1)
