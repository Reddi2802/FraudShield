"""
Tests for agents/uid.py — the ADR-011 amendment (D1n normalization).

The regression this guards against: raw D1 is a tenure COUNTER, so it
increases every day. Using it directly in the UID meant the same real
card produced a DIFFERENT UID on different days. D1n removes that drift.
This file's main job is proving that no longer happens.
"""

from __future__ import annotations

from agents.uid import compute_d1n, compute_uid, days_since_epoch


def test_same_card_different_days_produces_same_uid():
    """The actual bug: same card, two transactions a week apart, raw D1
    would differ (it's a day-by-day counter) but D1n should not."""
    card1, addr1 = 13926.0, 315.0

    # Day 10: D1 (tenure) = 2
    uid_day_10 = compute_uid(card1, addr1, d1=2.0, days_since_epoch_value=10.0)
    # Day 17 (a week later): same real card, tenure counter has advanced to 9
    uid_day_17 = compute_uid(card1, addr1, d1=9.0, days_since_epoch_value=17.0)

    assert uid_day_10 == uid_day_17, "same card on different days must resolve to the same UID"


def test_different_cards_same_day_produce_different_uids():
    """Sanity check the fix didn't overcorrect into merging everything."""
    uid_a = compute_uid(13926.0, 315.0, d1=2.0, days_since_epoch_value=10.0)
    uid_b = compute_uid(99999.0, 315.0, d1=2.0, days_since_epoch_value=10.0)
    assert uid_a != uid_b


def test_compute_d1n_handles_missing_d1():
    assert compute_d1n(10.0, None) is None
    assert compute_d1n(10.0, float("nan")) is None


def test_compute_uid_with_missing_d1_uses_na_bucket():
    uid = compute_uid(13926.0, 315.0, d1=None, days_since_epoch_value=10.0)
    assert uid == "13926-315-NA"


def test_days_since_epoch_matches_seed_db_units():
    """seed_db.py uses TransactionDT/86400 directly; a real datetime run
    through days_since_epoch() must land in the same units so live and
    seeded UIDs are computed consistently."""
    from datetime import timedelta

    from agents.uid import REFERENCE_START

    transaction_dt_seconds = 864000  # 10 days, matches the test fixture
    dt = REFERENCE_START + timedelta(seconds=transaction_dt_seconds)

    assert days_since_epoch(dt) == transaction_dt_seconds / 86400
