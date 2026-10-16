"""
Per-customer history helpers, shared by the orchestrator, Risk Synthesis and
(Week 3) Behavioral Analysis.

MIN_PRIOR_FOR_BEHAVIORAL encodes the cold-start rule (ADR-017): Behavioral
Analysis abstains — returns no score — for a customer with fewer than this
many earlier transactions. Measured on the raw IEEE-CIS CSV (D1n UIDs),
transactions with >= 3 prior UID transactions are 37.8% of traffic and
46.1% of all fraud, so the rule leaves the agent roughly half the fraud to
look at while never scoring a customer on one or two data points. The value
also matches Rule Compliance's AMOUNT_MIN_HISTORY_FOR_MULTIPLIER.
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
