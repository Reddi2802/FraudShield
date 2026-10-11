"""
Regression tests for the Week 3 timeline fixes:

- transaction_dt drives submitted_at (CSV-replay demos get real gaps)
- Device / DeviceCustomerLink first_seen_at / last_seen_at come from the
  TRANSACTION's time (seen_at), not the wall clock — otherwise replayed
  devices are stamped 2026 against 2017-2018 transactions and Device
  Trust's device_age goes hugely negative.
- D1n normalization: the same card on a later day resolves to the same
  Customer when raw D1 advances with the calendar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.device_trust import run_device_trust
from agents.ingestion import process_transaction
from agents.uid import REFERENCE_START

DAY = 86400
DEVICE = dict(
    device_type="mobile",
    device_info="SM-G960F Build/R16NW",  # specific model -> device-intrinsic fingerprint
    browser="chrome 63.0",
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ingest(session, *, transaction_dt, d1, card1=1000, with_device=True, **kw):
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
    args.update(kw)
    return process_transaction(session, **args)


def test_submitted_at_comes_from_transaction_dt(db_session):
    t = _ingest(db_session, transaction_dt=1_000_000, d1=5.0)
    assert _aware(t.submitted_at) == REFERENCE_START + timedelta(seconds=1_000_000)


def test_device_first_seen_uses_transaction_time_not_wall_clock(db_session):
    t = _ingest(db_session, transaction_dt=1_000_000, d1=5.0)
    expected = REFERENCE_START + timedelta(seconds=1_000_000)
    assert _aware(t.device.first_seen_at) == expected
    assert _aware(t.device.last_seen_at) == expected
    link = t.device.customer_links[0]
    assert _aware(link.first_seen_at) == expected


def test_out_of_order_rows_cannot_move_first_seen_forward(db_session):
    # Same card/UID: d1n = floor(dt/86400 - d1) = 5 for both rows.
    later = _ingest(db_session, transaction_dt=20 * DAY, d1=15.0)
    earlier = _ingest(db_session, transaction_dt=10 * DAY, d1=5.0)
    assert earlier.account_id == later.account_id  # same customer
    assert earlier.device_id == later.device_id  # same device
    device = earlier.device
    assert _aware(device.first_seen_at) == REFERENCE_START + timedelta(days=10)
    assert _aware(device.last_seen_at) == REFERENCE_START + timedelta(days=20)


def test_same_card_on_later_day_resolves_to_same_customer(db_session):
    a = _ingest(db_session, transaction_dt=10 * DAY, d1=5.0, with_device=False)
    b = _ingest(db_session, transaction_dt=20 * DAY, d1=15.0, with_device=False)
    assert a.account_id == b.account_id


def test_different_card_tenure_resolves_to_different_customer(db_session):
    a = _ingest(db_session, transaction_dt=10 * DAY, d1=5.0, with_device=False)
    b = _ingest(db_session, transaction_dt=10 * DAY, d1=9.0, with_device=False)
    assert a.account_id != b.account_id


def test_device_age_is_non_negative_for_replayed_traffic(db_session):
    _ingest(db_session, transaction_dt=10 * DAY, d1=5.0)
    second = _ingest(db_session, transaction_dt=12 * DAY, d1=7.0)
    result = run_device_trust(db_session, second)
    assert result.device_age == timedelta(days=2)
    assert result.device_age >= timedelta(0)


def test_without_transaction_dt_falls_back_to_wall_clock(db_session):
    t = _ingest(db_session, transaction_dt=None, d1=5.0)
    delta = abs(datetime.now(timezone.utc) - _aware(t.submitted_at))
    assert delta < timedelta(seconds=10)
