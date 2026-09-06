"""
Synthetic customer-identity resolution for IEEE-CIS-derived data.

IEEE-CIS has no native customer key. Per ADR-011, identity is approximated
by combining three independently weak signals whose intersection is
"unique enough" to group transactions belonging to the same real-world
card/customer:

    - card1  : high-cardinality, no missing values in practice (anchor column)
    - addr1  : billing region — breaks ties when card1 collides across
               genuinely different customers
    - D1     : days since the card was first used (card tenure) — breaks
               ties when two different customers happen to share both
               card1 and addr1

This is a probabilistic proxy, not a verified identity key. See
docs/DECISIONS.md ADR-011 for documented limitations (it will not resolve
a single real customer who uses multiple cards, and carries residual
collision/fragmentation risk — checked at the week-3 fragmentation
review, see ROADMAP.md). See ADR-012 for the leakage-safe, time-gated
requirement on any aggregate features built on top of this UID.

Kept as a pure function with no DB or pandas dependency so it can be:
  - unit tested trivially (no fixtures needed)
  - reused identically by scripts/seed_db.py (batch, from CSV rows) and
    agents/ingestion.py (single transaction, from an API request)
  - swapped for a richer variant (e.g. card1+card2+addr1+D1) later
    without touching either caller, if the week-3 check calls for it.
"""

from __future__ import annotations

import math
from numbers import Real

# Sentinel token for a missing value. Kept as an explicit string rather
# than dropping the field entirely, so "both missing" is its own distinct
# bucket instead of silently colliding with some real value.
_MISSING_TOKEN = "NA"


def _clean(value: object) -> str:
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


def compute_uid(card1: object, addr1: object, d1: object) -> str:
    """
    Build the synthetic UID string from the three anchor columns.

    Args:
        card1: raw `card1` value (int/float; effectively never missing).
        addr1: raw `addr1` value (int/float; may be missing).
        d1: raw `D1` value (int/float; may be missing — treated as its
            own bucket, never imputed to 0 or any other value, since
            imputing would manufacture false collisions).

    Returns:
        A stable string key, e.g. "13926-315-2". Two rows produce the
        same UID iff all three cleaned tokens match exactly.
    """
    return f"{_clean(card1)}-{_clean(addr1)}-{_clean(d1)}"
