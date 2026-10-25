"""
Investigator endpoints (ADR-021): list flagged cases, read one, record feedback.

Everything here requires an investigator token. The first feedback on a case
resolves it (status resolved, resolved_at now, investigator = the caller); a
second feedback on a resolved case is a 409. Only one feedback per case in this
version.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import AuthUser, require_investigator
from api.signals import signals_for_transaction
from api.schemas import (
    CaseDetail,
    CaseStatus,
    CaseSummary,
    CaseTransaction,
    FeedbackInfo,
    FeedbackRequest,
    FeedbackResponse,
)
from db.models import CaseStatusEnum, Feedback, FeedbackLabelEnum, FraudCase
from db.session import get_session

router = APIRouter(prefix="/cases", tags=["cases"])

MAX_CASES = 100


def _latest_assessment(case: FraudCase):
    assessments = case.transaction.risk_assessments
    return max(assessments, key=lambda a: a.risk_assessment_id) if assessments else None


def _get_case_or_404(session: Session, case_id: int) -> FraudCase:
    case = session.get(FraudCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("", response_model=list[CaseSummary])
def list_cases(
    status: CaseStatus = "open",
    session: Session = Depends(get_session),
    _user: AuthUser = Depends(require_investigator),
) -> list[CaseSummary]:
    cases = session.query(FraudCase).filter(FraudCase.status == CaseStatusEnum(status)).all()
    items = []
    for case in cases:
        assessment = _latest_assessment(case)
        items.append(
            CaseSummary(
                case_id=case.fraud_case_id,
                transaction_id=case.transaction_id,
                status=case.status.value,
                opened_at=case.opened_at,
                decision=assessment.decision.value if assessment else None,
                risk_score=assessment.risk_score if assessment else None,
            )
        )
    items.sort(key=lambda c: (c.risk_score if c.risk_score is not None else -1.0, c.opened_at), reverse=True)
    return items[:MAX_CASES]


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: int,
    session: Session = Depends(get_session),
    _user: AuthUser = Depends(require_investigator),
) -> CaseDetail:
    case = _get_case_or_404(session, case_id)
    transaction = case.transaction
    assessment = _latest_assessment(case)
    feedback = max(case.feedback_entries, key=lambda f: f.feedback_id) if case.feedback_entries else None
    return CaseDetail(
        case_id=case.fraud_case_id,
        transaction_id=case.transaction_id,
        status=case.status.value,
        opened_at=case.opened_at,
        resolved_at=case.resolved_at,
        transaction=CaseTransaction(
            amount=transaction.amount,
            currency=transaction.currency,
            submitted_at=transaction.submitted_at,
            customer_id=transaction.account.customer_id,
        ),
        decision=assessment.decision.value if assessment else None,
        risk_score=assessment.risk_score if assessment else None,
        explanation=assessment.explanation_text if assessment else None,
        feedback=FeedbackInfo(
            label=feedback.label.value,
            notes=feedback.notes,
            investigator_id=feedback.investigator_id,
            submitted_at=feedback.submitted_at,
        )
        if feedback
        else None,
        signals=signals_for_transaction(transaction),
    )


@router.post("/{case_id}/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(
    case_id: int,
    payload: FeedbackRequest,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_investigator),
) -> FeedbackResponse:
    case = _get_case_or_404(session, case_id)
    if case.status == CaseStatusEnum.RESOLVED or case.feedback_entries:
        raise HTTPException(status_code=409, detail="Case is already resolved")

    feedback = Feedback(
        fraud_case_id=case.fraud_case_id,
        investigator_id=user.user_id,
        label=FeedbackLabelEnum(payload.label),
        notes=payload.notes,
    )
    session.add(feedback)
    case.status = CaseStatusEnum.RESOLVED
    case.resolved_at = datetime.now(timezone.utc)
    case.investigator_id = user.user_id
    session.commit()

    return FeedbackResponse(
        feedback_id=feedback.feedback_id,
        case_id=case.fraud_case_id,
        label=payload.label,
        notes=payload.notes,
        status=case.status.value,
    )
