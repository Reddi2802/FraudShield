"""
Rule Compliance Agent — Week 2

Deterministic checks against a transaction: velocity and amount.
Writes RuleViolation rows for any rule that fires.

SCOPE NOTE — "geo" rule dropped, not deferred silently:
IEEE-CIS's addr1 is consumed by agents/uid.py to build synthetic_uid but is
never persisted on Transaction, Account, or Customer. There is currently no
stored billing-address field to compare against. Do not re-add a "geo" rule
without first deciding where addr1 gets stored (Customer? Account?) and
writing that as an ADR — this file intentionally does not guess.

Velocity uses REAL datetimes (Transaction.submitted_at), not a dataset-
relative proxy — this schema stores real timezone-aware UTC timestamps at
ingestion, so a genuine wall-clock window is meaningful here, unlike the
seed CSV's raw TransactionDT.

Threshold caveat (unchanged from earlier discussion, now checkable for
real): with your seeded population's low median transaction count per
customer, expect the velocity rule to fire rarely. That's expected, not a
bug — but pull actual per-customer transaction-count/time-gap distributions
from your seeded DB before treating these numbers as final.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from db.models import RuleViolation, Transaction

# ---- Config (move to a proper config file once thresholds are validated against real data) ----

VELOCITY_WINDOW = timedelta(hours=1)
VELOCITY_MAX_TXNS = 5

AMOUNT_MULTIPLIER_THRESHOLD = 3.0        # flag if > 3x customer's own historical mean
AMOUNT_MIN_HISTORY_FOR_MULTIPLIER = 3    # need >= 3 prior txns to trust a customer-specific mean
# else fall back to a global percentile — arbitrary starting point, not tuned

SEVERITY_BY_RULE = {
    "velocity": "medium",
    "amount_own_history": "high",     # customer-specific deviation is a stronger signal
    "amount_global_fallback": "medium",  # weaker signal — thin-history customer, less confidence
}


@dataclass
class RuleComplianceResult:
    transaction_id: int
    violations: list = field(default_factory=list)  # list of (rule_name, detail) tuples

    @property
    def flagged(self) -> bool:
        return len(self.violations) > 0


# ---- Pure signal checks (unit-testable with no DB) ----

def check_velocity(
    current_dt: datetime,
    prior_dts: list[datetime],
    window: timedelta = VELOCITY_WINDOW,
    max_txns: int = VELOCITY_MAX_TXNS,
) -> tuple[bool, Optional[str]]:
    if not prior_dts:
        return False, None  # no history -> insufficient data, not an auto-pass disguised as a rule result

    window_start = current_dt - window
    in_window = [dt for dt in prior_dts if window_start <= dt <= current_dt]
    count_including_current = len(in_window) + 1

    if count_including_current > max_txns:
        return True, f"{count_including_current} txns within {window} (limit {max_txns})"
    return False, None


def check_amount(
    current_amt: float,
    prior_amts: list[float],
    global_p99: Optional[float],
) -> tuple[bool, Optional[str], Optional[str]]:
    """Returns (fired, detail, rule_name) — rule_name distinguishes which tier fired, for severity mapping."""
    if len(prior_amts) >= AMOUNT_MIN_HISTORY_FOR_MULTIPLIER:
        mean_amt = sum(prior_amts) / len(prior_amts)
        if mean_amt > 0 and current_amt > AMOUNT_MULTIPLIER_THRESHOLD * mean_amt:
            detail = (f"amount {current_amt:.2f} > {AMOUNT_MULTIPLIER_THRESHOLD}x "
                       f"customer's own mean {mean_amt:.2f} (n={len(prior_amts)})")
            return True, detail, "amount_own_history"
        return False, None, None

    if global_p99 is not None and current_amt > global_p99:
        detail = f"amount {current_amt:.2f} > global p99 {global_p99:.2f} (thin history, n={len(prior_amts)})"
        return True, detail, "amount_global_fallback"
    return False, None, None


def evaluate_transaction(
    transaction_id: int,
    current_dt: datetime,
    current_amt: float,
    prior_dts: list[datetime],
    prior_amts: list[float],
    global_amt_p99: Optional[float],
) -> RuleComplianceResult:
    result = RuleComplianceResult(transaction_id=transaction_id)

    fired, detail = check_velocity(current_dt, prior_dts)
    if fired:
        result.violations.append(("velocity", detail))

    fired, detail, rule_name = check_amount(current_amt, prior_amts, global_amt_p99)
    if fired:
        result.violations.append((rule_name, detail))

    return result


# ---- DB-touching functions (real, against the actual schema) ----

def _get_prior_transactions(session: Session, transaction: Transaction) -> list[Transaction]:
    """
    Prior transactions for the SAME account (== same customer, per Week 1's
    one-account-per-customer simplification documented in ingestion.py).
    """
    return (
        session.query(Transaction)
        .filter(
            Transaction.account_id == transaction.account_id,
            Transaction.transaction_id != transaction.transaction_id,
            Transaction.submitted_at < transaction.submitted_at,
        )
        .order_by(Transaction.submitted_at)
        .all()
    )


def compute_global_amount_p99(session: Session) -> Optional[float]:
    """
    Global 99th percentile of Transaction.amount, recomputed on every call.
    Fine at Week 2 / ~31K-row seeded-DB scale. Revisit caching (compute
    once at startup, or in scripts/seed_db.py and store somewhere) before
    Week 7's dashboard puts this on a hot path.
    """
    amounts = [row[0] for row in session.query(Transaction.amount).all()]
    if len(amounts) < 2:
        return None
    try:
        return statistics.quantiles(amounts, n=100)[98]
    except statistics.StatisticsError:
        return max(amounts)


def run_rule_compliance(session: Session, transaction: Transaction) -> RuleComplianceResult:
    """
    Evaluates the given (already-persisted, flushed) Transaction and writes
    RuleViolation rows for anything that fires. Follows ingestion.py's
    convention: flush, don't commit — the caller (route/orchestrator) owns
    the transaction boundary.
    """
    prior = _get_prior_transactions(session, transaction)
    prior_dts = [t.submitted_at for t in prior]
    prior_amts = [t.amount for t in prior]
    global_p99 = compute_global_amount_p99(session)

    result = evaluate_transaction(
        transaction_id=transaction.transaction_id,
        current_dt=transaction.submitted_at,
        current_amt=transaction.amount,
        prior_dts=prior_dts,
        prior_amts=prior_amts,
        global_amt_p99=global_p99,
    )

    for rule_name, detail in result.violations:
        violation = RuleViolation(
            transaction_id=transaction.transaction_id,
            rule_name=rule_name,
            rule_description=detail,
            severity=SEVERITY_BY_RULE.get(rule_name, "medium"),
        )
        session.add(violation)

    if result.violations:
        session.flush()

    return result
