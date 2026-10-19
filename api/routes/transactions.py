from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.ingestion import IngestionError
from agents.orchestrator import run_pipeline
from api.schemas import TransactionRequest, TransactionResponse
from db.session import get_session

router = APIRouter(prefix="/transaction", tags=["transactions"])


@router.post("", response_model=TransactionResponse, status_code=201)
def submit_transaction(
    payload: TransactionRequest,
    session: Session = Depends(get_session),
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
        session.commit()
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
