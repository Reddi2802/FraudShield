"""
Identity round-trip for the customer-facing API (ADR-027).

A customer is identified by synthetic_uid = card1-addr1-D1n, with
D1n = floor(days - D1). To submit a transaction that resolves to the SAME
customer, the server parses the stored UID and sends D1 = days - D1n.

Why the small epsilon in d1_for: days - (days - D1n) is NOT exactly D1n in
floating point; it can land a hair BELOW the integer, and floor() then yields
D1n - 1, silently producing a different UID (the API answers 403). Subtracting
1e-6 day (~0.09 s) first makes the result land safely inside [D1n, D1n + 1).
tests/test_api/test_identity.py checks this over thousands of random times.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from agents.uid import REFERENCE_START

_UID = re.compile(r"^(\d+)-(NA|\d+)-(NA|-?\d+)$")
D1_EPSILON_DAYS = 1e-6
DEFAULT_GAP_SECONDS = 3600      # the next transaction is simulated one hour after the latest
FALLBACK_DT = 90 * 86400        # mid-window time for a customer with no history at all


def parse_uid(uid: str) -> tuple[float, float | None, float | None]:
    """'card1-addr1-D1n' -> (card1, addr1 or None, D1n or None). 'NA' means missing."""
    match = _UID.match(uid)
    if match is None:
        raise ValueError(f"Unexpected synthetic_uid format: {uid!r}")
    card1, addr1, d1n = match.groups()
    return float(card1), None if addr1 == "NA" else float(addr1), None if d1n == "NA" else float(d1n)


def d1_for(transaction_dt: float, d1n: float | None) -> float | None:
    """The D1 to send so the UID's D1n component stays unchanged."""
    return None if d1n is None else transaction_dt / 86400 - d1n - D1_EPSILON_DAYS


def seconds_since_reference(moment: datetime) -> float:
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return (moment - REFERENCE_START).total_seconds()


def next_transaction_dt(latest: datetime | None) -> float:
    """Simulated clock: one hour after the customer's latest transaction, so history
    stays time-ordered and inside the window the model was trained on (ADR-023)."""
    if latest is None:
        return float(FALLBACK_DT)
    return seconds_since_reference(latest) + DEFAULT_GAP_SECONDS
