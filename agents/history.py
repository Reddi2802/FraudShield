"""
Per-customer history helpers, shared by the orchestrator, Risk Synthesis and
(Week 3) Behavioral Analysis.

MIN_PRIOR_FOR_BEHAVIORAL is the minimum number of earlier transactions before
the per-customer z-score feature (amt_z) is computed. ADR-017 first used it
as an ABSTAIN cutoff for Behavioral Analysis; ADR-019 supersedes that: the
supervised model scores every transaction and simply sees amt_z as missing
below this many priors. Measured on the raw IEEE-CIS CSV (D1n UIDs),
transactions with >= 3 prior UID transactions are 37.8% of traffic and 46.1%
of all fraud. The value matches Rule Compliance's own
AMOUNT_MIN_HISTORY_FOR_MULTIPLIER.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from db.models import Transaction

MIN_PRIOR_FOR_BEHAVIORAL = 3


def count_prior_transactions(session: Session, transaction: Transaction) -> int:
    """Earlier transactions on the SAME account (== same customer, one
    account per customer). Strictly earlier submitted_at, never the
    transaction itself — time-gated, per ADR-012."""
    return (
        session.query(Transaction)
        .filter(
            Transaction.account_id == transaction.account_id,
            Transaction.transaction_id != transaction.transaction_id,
            Transaction.submitted_at < transaction.submitted_at,
        )
        .count()
    )


def has_enough_history(prior_count: int, minimum: int = MIN_PRIOR_FOR_BEHAVIORAL) -> bool:
    return prior_count >= minimum
