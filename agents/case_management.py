"""
Case Management Agent — minimal version (ADR-020).

Opens a FraudCase when, and only when, the decision is flag or block. One
case per transaction (the table's UNIQUE constraint on transaction_id
enforces it, and the agent is idempotent). Cases start OPEN and unassigned:
investigators pick them up from the dashboard (Week 7), and their Feedback
labels are stored against the case. Retraining on that feedback is a manual
script (Week 8) with its own threshold decision — not here.

opened_at is the TRANSACTION's timestamp, not the wall clock, for the same
reason as ADR-016: a CSV replay must produce a consistent timeline (a 2017
transaction with a 2026 case would make every case look nine years late).
For live traffic submitted_at is "now", so nothing changes.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from db.models import CaseStatusEnum, DecisionEnum, FraudCase, RiskAssessment, Transaction

CASE_DECISIONS = (DecisionEnum.FLAG, DecisionEnum.BLOCK)


def run_case_management(
    session: Session, transaction: Transaction, assessment: RiskAssessment
) -> Optional[FraudCase]:
    if assessment.decision not in CASE_DECISIONS:
        return None

    existing = (
        session.query(FraudCase)
        .filter(FraudCase.transaction_id == transaction.transaction_id)
        .one_or_none()
    )
    if existing is not None:
        return existing

    case = FraudCase(
        transaction_id=transaction.transaction_id,
        status=CaseStatusEnum.OPEN,
        opened_at=transaction.submitted_at,
    )
    session.add(case)
    session.flush()
    return case
