"""api/identity: the UID round-trip must hold for ANY time, not just a few examples."""

from __future__ import annotations

import random

import pytest

from agents.uid import compute_uid
from api.identity import d1_for, next_transaction_dt, parse_uid


@pytest.mark.parametrize(
    "uid, expected",
    [
        ("13926-315-8", (13926.0, 315.0, 8.0)),
        ("11401-204--484", (11401.0, 204.0, -484.0)),
        ("12616-NA-491", (12616.0, None, 491.0)),
        ("1000-300-NA", (1000.0, 300.0, None)),
    ],
)
def test_parse_uid(uid, expected):
    assert parse_uid(uid) == expected


@pytest.mark.parametrize("bad", ["", "abc", "1-2", "1-2-3-4", "x-1-2"])
def test_parse_uid_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_uid(bad)


def test_round_trip_holds_for_thousands_of_random_times():
    rng = random.Random(0)
    for _ in range(5000):
        d1n = rng.randint(-500, 400)
        uid = f"{rng.randint(1000, 18000)}-{rng.randint(100, 500)}-{d1n}"
        dt = rng.uniform(0, 16_000_000)
        card1, addr1, parsed = parse_uid(uid)
        assert compute_uid(card1, addr1, d1_for(dt, parsed), dt / 86400) == uid


def test_naive_formula_is_not_safe():
    """Documents WHY the epsilon exists: without it floor() can land one day low."""
    rng = random.Random(0)
    failures = 0
    for _ in range(5000):
        d1n = rng.randint(-500, 400)
        dt = rng.uniform(0, 16_000_000)
        naive_d1 = dt / 86400 - d1n
        if compute_uid(1, 1, naive_d1, dt / 86400) != f"1-1-{d1n}":
            failures += 1
    assert failures > 0


def test_missing_d1n_stays_missing():
    assert d1_for(86400.0, None) is None


def test_next_dt_is_one_hour_after_latest_or_fallback():
    from datetime import timedelta
    from agents.uid import REFERENCE_START

    assert next_transaction_dt(REFERENCE_START + timedelta(days=2)) == 2 * 86400 + 3600
    assert next_transaction_dt(None) == 90 * 86400
