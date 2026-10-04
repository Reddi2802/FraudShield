"""
Synthetic customer-identity resolution for IEEE-CIS-derived data.

IEEE-CIS has no native customer key. Per ADR-011 (amended — see below),
identity is approximated by combining three signals:

    - card1  : high-cardinality, no missing values in practice (anchor column)
    - addr1  : billing region — breaks ties when card1 collides across
               genuinely different customers
    - D1n    : NORMALIZED day-index the card was first seen —
               floor(days_since_epoch - raw_D1). See amendment below for
               why this replaced raw D1.

This is a probabilistic proxy, not a verified identity key. See
docs/DECISIONS.md ADR-011 for documented limitations (it will not resolve
a single real customer who uses multiple cards, and carries residual
collision/fragmentation risk). See ADR-012 for the leakage-safe,
time-gated requirement on any aggregate features built on top of this UID.

ADR-011 AMENDMENT (Week 3): raw D1 is a tenure COUNTER — it increases by
one for every day that passes. Using it directly in the UID meant the same
real card produced a DIFFERENT UID on different days, fragmenting single
customers across time. The fix is D1n = floor(days_since_epoch - D1), which
removes the calendar drift and leaves a stable per-card anchor instead.
Validated against the real IEEE-CIS CSV before switching: raw D1 fragments
73.3% of UIDs down to a single transaction; D1n brings that down to 57.4%,
shrinks the worst collision outlier from 7,198 rows to 1,414, and more
than doubles the ADR-013 [8,150] seeding pool (6,739 -> 14,493 candidates).

Because D1n is anchored to an absolute calendar reference (not a pure
tenure counter), the caller must supply days_since_epoch consistently —
see REFERENCE_START below. This is why agents/ingestion.py now needs a
transaction_dt input (real or simulated) rather than being able to derive
everything from raw request fields alone.

Kept as a pure function with no DB or pandas dependency so it can be:
  - unit tested trivially (no fixtures needed)
  - reused identically by scripts/seed_db.py (batch, from CSV rows) and
    agents/ingestion.py (single transaction, from an API request)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from numbers import Real

# Sentinel token for a missing value. Kept as an explicit string rather
# than dropping the field entirely, so "both missing" is its own distinct
# bucket instead of silently colliding with some real value.
_MISSING_TOKEN = "NA"

# Community-estimated epoch for IEEE-CIS's TransactionDT (not confirmed by
# Vesta — see scripts/seed_db.py's original comment). Single source of
# truth: both seed_db.py and ingestion.py import this rather than each
# defining their own, so they can't silently drift apart.
REFERENCE_START = datetime(2017, 12, 1, tzinfo=timezone.utc)


def days_since_epoch(dt: datetime) -> float:
    """Convert a real timezone-aware datetime into the same day-offset
    units as IEEE-CIS's TransactionDT/86400, relative to REFERENCE_START."""
    return (dt - REFERENCE_START).total_seconds() / 86400


def clean_component(value: object) -> str:
    """
    Normalize one raw IEEE-CIS field into a stable string token.

    card1 / addr1 / D1 arrive as floats when read via pandas, because any
    column containing NaN gets upcast from int to float64. Without this
    normalization, the same real value (e.g. addr1 = 204) could stringify
    as "204" in one row and "204.0" in another depending on dtype, which
    would silently fragment a single real customer into two UIDs.
    """
    if value is None:
        return _MISSING_TOKEN
    if isinstance(value, Real) and isinstance(value, float) and math.isnan(value):
        return _MISSING_TOKEN
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def compute_d1n(days_since_epoch_value: float, d1: object) -> object:
    """
    Normalize raw D1 (a tenure counter) into D1n (a stable calendar anchor):
    floor(days_since_epoch - d1). Returns None if d1 is missing — never
    imputed, same policy as the rest of this module.
    """
    if d1 is None:
        return None
    if isinstance(d1, Real) and isinstance(d1, float) and math.isnan(d1):
        return None
    return math.floor(days_since_epoch_value - float(d1))


def compute_uid(card1: object, addr1: object, d1: object, days_since_epoch_value: float) -> str:
    """
    Build the synthetic UID string from card1 + addr1 + normalized D1n.

    Args:
        card1: raw `card1` value (int/float; effectively never missing).
        addr1: raw `addr1` value (int/float; may be missing).
        d1: raw `D1` value (int/float; may be missing — treated as its
            own bucket, never imputed to 0 or any other value).
        days_since_epoch_value: the current transaction's time, in the same
            units as IEEE-CIS TransactionDT/86400, relative to
            REFERENCE_START. For seeded data this is TransactionDT/86400
            directly; for live ingestion, see days_since_epoch() above.

    Returns:
        A stable string key, e.g. "13926-315-8". Two rows produce the
        same UID iff all three cleaned tokens match exactly — and because
        D1n removes calendar drift, the SAME real card now produces the
        same UID across different days, which raw D1 did not guarantee.
    """
    d1n = compute_d1n(days_since_epoch_value, d1)
    return f"{clean_component(card1)}-{clean_component(addr1)}-{clean_component(d1n)}"
