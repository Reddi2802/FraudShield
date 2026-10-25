"""
GET /admin/overview — read-only system overview for the website (ADR-027).

Deliberately UNAUTHENTICATED, exactly like the Streamlit Admin flag (ADR-010):
Admin has no login in this project and the app runs locally. Do not expose this
server on a public network without putting auth in front of this route.
It replaces dashboard/data.admin_overview's direct database read, which a
browser cannot do.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.schemas import AdminOverview, ModelInfo, RetrainingStatus
from db.models import Customer, Feedback, FraudCase, ModelVersion, RiskAssessment, Transaction
from db.session import get_session
from scripts.feedback_status import feedback_since_last_model

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverview)
def overview(session: Session = Depends(get_session)) -> AdminOverview:
    decisions = {
        d.value: n for d, n in session.query(RiskAssessment.decision, func.count()).group_by(RiskAssessment.decision)
    }
    cases = {s.value: n for s, n in session.query(FraudCase.status, func.count()).group_by(FraudCase.status)}
    feedback = {l.value: n for l, n in session.query(Feedback.label, func.count()).group_by(Feedback.label)}
    model = (
        session.query(ModelVersion)
        .order_by(ModelVersion.trained_at.desc(), ModelVersion.model_version_id.desc())
        .first()
    )
    status = feedback_since_last_model(session)
    return AdminOverview(
        customers=session.query(func.count(Customer.customer_id)).scalar() or 0,
        transactions=session.query(func.count(Transaction.transaction_id)).scalar() or 0,
        assessments=session.query(func.count(RiskAssessment.risk_assessment_id)).scalar() or 0,
        decisions=decisions,
        cases=cases,
        feedback=feedback,
        model=None
        if model is None
        else ModelInfo(
            type=model.model_type,
            trained_at=model.trained_at,
            artifact_path=model.artifact_path,
            metrics=model.metrics or {},
        ),
        retraining=RetrainingStatus(
            labels_since_model=status["total"], threshold=status["threshold"], reached=status["reached"]
        ),
    )
