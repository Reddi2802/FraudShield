from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.ingestion import IngestionError
from agents.orchestrator import run_pipeline
from api.auth import AuthUser, require_customer
from api.schemas import MyTransaction, TransactionRequest, TransactionResponse
from db.models import Account, Transaction
from db.session import get_session

router = APIRouter(prefix="/transaction", tags=["transactions"])
# Same prefix would make /transactions/me a sibling resource, so it gets its own router.
me_router = APIRouter(prefix="/transactions", tags=["transactions"])

MY_TRANSACTIONS_LIMIT = 50


@router.post("", response_model=TransactionResponse, status_code=201)
def submit_transaction(
    payload: TransactionRequest,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_customer),
) -> TransactionResponse:
    try:
        result = run_pipeline(
            session,
            card1=payload.card1,
            addr1=payload.addr1,
            d1=payload.d1,
            card6=payload.card6,
            amount=payload.amount,
            currency=payload.currency,
            product_cd=payload.product_cd,
            device_type=payload.device_type,
            device_info=payload.device_info,
            browser=payload.browser,
            transaction_dt=payload.transaction_dt,
        )

        # Scope rule (ADR-021): a customer may only submit transactions that
        # resolve to THEMSELVES. Checked after the pipeline but BEFORE commit, so
        # nothing is persisted on a mismatch. A UID with no existing customer
        # creates one inside the pipeline; the ids differ and it is rolled back,
        # so a customer cannot create new customers either.
        resolved_customer_id = result["transaction"].account.customer.customer_id
        if resolved_customer_id != user.user_id:
            session.rollback()
            raise HTTPException(
                status_code=403,
                detail="Transaction does not belong to the logged-in customer",
            )
        session.commit()
    except HTTPException:
        raise
    except IngestionError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise

    transaction = result["transaction"]
    assessment = result["assessment"]
    case = result.get("case")
    customer = transaction.account.customer

    return TransactionResponse(
        transaction_id=transaction.transaction_id,
        synthetic_uid=customer.synthetic_uid,
        customer_id=customer.customer_id,
        account_id=transaction.account_id,
        merchant_id=transaction.merchant_id,
        device_id=transaction.device_id,
        amount=transaction.amount,
        currency=transaction.currency,
        submitted_at=transaction.submitted_at,
        decision=assessment.decision.value,
        risk_score=assessment.risk_score,
        explanation=assessment.explanation_text,
        case_id=case.fraud_case_id if case is not None else None,
    )


@me_router.get("/me", response_model=list[MyTransaction])
def my_transactions(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_customer),
) -> list[MyTransaction]:
    """The logged-in customer's last 50 transactions, newest first. Seeded
    history has no RiskAssessment, so decision / risk_score / explanation are
    null there."""
    transactions = (
        session.query(Transaction)
        .join(Account, Transaction.account_id == Account.account_id)
        .filter(Account.customer_id == user.user_id)
        .order_by(Transaction.submitted_at.desc(), Transaction.transaction_id.desc())
        .limit(MY_TRANSACTIONS_LIMIT)
        .all()
    )
    items = []
    for t in transactions:
        assessment = (
            max(t.risk_assessments, key=lambda a: a.risk_assessment_id) if t.risk_assessments else None
        )
        items.append(
            MyTransaction(
                transaction_id=t.transaction_id,
                amount=t.amount,
                currency=t.currency,
                submitted_at=t.submitted_at,
                decision=assessment.decision.value if assessment else None,
                risk_score=assessment.risk_score if assessment else None,
                explanation=assessment.explanation_text if assessment else None,
                case_id=t.fraud_case.fraud_case_id if t.fraud_case else None,
            )
        )
    return items
