"""
Tests for agents/device_identity.py — the Week 2 schema change (many-to-many
Device<->Customer via DeviceCustomerLink) and its fingerprint logic.

Covers the three things that actually matter here, per DECISIONS.md ADR-014:
  1. A specific (non-generic) device fingerprint DOES link across customers.
  2. A generic device fingerprint (e.g. "Windows") does NOT merge across
     customers — this is deliberate, not a gap (see device_identity.py).
  3. Regression guard for the browser-churn bug: one customer's browser
     version changing across sessions must NOT fragment their own device
     into multiple rows.
"""

from __future__ import annotations

from agents.device_identity import GENERIC_DEVICE_INFO, build_device_fingerprint
from agents.device_trust import run_device_trust
from agents.ingestion import process_transaction
from db.models import Device, DeviceCustomerLink


SPECIFIC_DEVICE = dict(device_type="mobile", device_info="SM-J700M Build/MMB29K", browser="chrome 63.0 for android")
GENERIC_DEVICE = dict(device_type="desktop", device_info="Windows", browser="chrome 63.0")


def test_specific_device_fingerprint_is_intrinsic():
    fingerprint, is_intrinsic = build_device_fingerprint("13926-315-2", **SPECIFIC_DEVICE)
    assert is_intrinsic is True
    assert "13926-315-2" not in fingerprint, "intrinsic fingerprint must not embed customer identity"


def test_generic_device_fingerprint_falls_back_to_customer_scoped():
    fingerprint, is_intrinsic = build_device_fingerprint("13926-315-2", **GENERIC_DEVICE)
    assert is_intrinsic is False
    assert "13926-315-2" in fingerprint, "fallback fingerprint must be customer-scoped"


def test_all_documented_generic_values_trigger_fallback():
    for generic_value in GENERIC_DEVICE_INFO:
        _, is_intrinsic = build_device_fingerprint(
            "some-uid", "desktop", generic_value, "chrome 63.0"
        )
        assert is_intrinsic is False, f"{generic_value!r} should fall back, not be treated as intrinsic"


def test_specific_device_links_across_two_different_customers(db_session):
    first = process_transaction(
        db_session, card1=11111.0, addr1=100.0, d1=1.0, card6="credit",
        amount=50.0, currency="USD", product_cd="W", transaction_dt=1000000.0, **SPECIFIC_DEVICE,
    )
    db_session.commit()
    second = process_transaction(
        db_session, card1=22222.0, addr1=200.0, d1=5.0, card6="debit",
        amount=75.0, currency="USD", product_cd="W", transaction_dt=1100000.0, **SPECIFIC_DEVICE,
    )
    db_session.commit()

    assert first.device_id == second.device_id, "same specific device should link across customers"
    assert db_session.query(Device).count() == 1
    assert db_session.query(DeviceCustomerLink).count() == 2, "one link row per customer"

    result = run_device_trust(db_session, second)
    assert result.reuse_count == 2


def test_generic_device_does_not_link_across_customers(db_session):
    first = process_transaction(
        db_session, card1=33333.0, addr1=300.0, d1=9.0, card6="credit",
        amount=20.0, currency="USD", product_cd="C", transaction_dt=1000000.0, **GENERIC_DEVICE,
    )
    db_session.commit()
    second = process_transaction(
        db_session, card1=44444.0, addr1=400.0, d1=3.0, card6="credit",
        amount=30.0, currency="USD", product_cd="C", transaction_dt=1100000.0, **GENERIC_DEVICE,
    )
    db_session.commit()

    assert first.device_id != second.device_id, "generic device must not merge across customers"
    assert db_session.query(Device).count() == 2

    result = run_device_trust(db_session, second)
    assert result.reuse_count == 1, "fallback-fingerprint device can never show cross-customer reuse"


def test_browser_version_churn_does_not_fragment_same_customers_device(db_session):
    """Regression guard: the fallback fingerprint must exclude browser, or a
    customer's own browser updates spawn phantom 'new devices' (ADR-014)."""
    kwargs = dict(card1=55555.0, addr1=500.0, d1=1.0, card6="credit", transaction_dt=1000000.0,
                  amount=10.0, currency="USD", product_cd="W", device_type="desktop", device_info="Windows")

    t1 = process_transaction(db_session, browser="chrome 62.0", **kwargs)
    db_session.commit()
    t2 = process_transaction(db_session, browser="chrome 63.0", **kwargs)
    db_session.commit()
    t3 = process_transaction(db_session, browser="chrome 65.0", **kwargs)
    db_session.commit()

    assert t1.device_id == t2.device_id == t3.device_id
    assert db_session.query(Device).count() == 1
    assert db_session.query(DeviceCustomerLink).count() == 1, "same customer, same device -> one link, not three"


def test_device_trust_signals_for_repeat_use_by_same_customer(db_session):
    kwargs = dict(card1=66666.0, addr1=600.0, d1=2.0, card6="debit",
                  amount=15.0, currency="USD", product_cd="W", **SPECIFIC_DEVICE)

    # Distinct transaction_dt per call — same D1n (floor uses whole days, and
    # 100 seconds apart doesn't cross a day boundary) so it's still the same
    # customer, but a real time gap so submitted_at ordering is meaningful
    # for is_first_seen_globally / is_new_device_for_customer below.
    first = process_transaction(db_session, transaction_dt=1000000.0, **kwargs)
    db_session.commit()
    second = process_transaction(db_session, transaction_dt=1000100.0, **kwargs)
    db_session.commit()

    first_result = run_device_trust(db_session, first)
    assert first_result.is_first_seen_globally is True
    assert first_result.is_new_device_for_customer is True

    second_result = run_device_trust(db_session, second)
    assert second_result.is_first_seen_globally is False
    assert second_result.is_new_device_for_customer is False
    assert second_result.device_age is not None
