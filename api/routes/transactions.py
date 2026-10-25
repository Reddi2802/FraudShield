from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from agents.ingestion import IngestionError
from agents.orchestrator import run_pipeline
from api.auth import AuthUser, require_customer
from api.identity import d1_for, next_transaction_dt, parse_uid
from api.schemas import (
    CUSTOMER_MESSAGES,
    CUSTOMER_STATUS_BY_DECISION,
    CustomerTransactionResult,
    MyTransaction,
    MyTransactionRequest,
    TransactionRequest,
    TransactionResponse,
)
from api.signals import signals_for_transaction
from db.models import Account, Customer, Transaction
from db.session import get_session

router = APIRouter(prefix="/transaction", tags=["transactions"])
# Same prefix would make /transactions/me a sibling resource, so it gets its own router.
me_router = APIRouter(prefix="/transactions", tags=["transactions"])

MY_TRANSACTIONS_LIMIT = 50


def _score_and_commit(session: Session, user: AuthUser, payload: dict[str, Any]) -> TransactionResponse:
    """Run the pipeline for one transaction and shape the response. Shared by
    POST /transaction (raw payload) and POST /transactions/me (server-built payload)."""
    try:
        result = run_pipeline(session, **payload)

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
        signals=signals_for_transaction(transaction),
    )


@router.post("", response_model=TransactionResponse, status_code=201)
def submit_transaction(
    payload: TransactionRequest,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_customer),
) -> TransactionResponse:
    return _score_and_commit(
        session,
        user,
        dict(
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
        ),
    )


@me_router.post("/me", response_model=CustomerTransactionResult, status_code=201)
def submit_my_transaction(
    payload: MyTransactionRequest,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_customer),
) -> CustomerTransactionResult:
    """Website endpoint (ADR-027): the customer supplies only what a customer would
    know. Card, region, D1 and the simulated time come from their stored identity,
    so the transaction always resolves to them. The response is customer-safe
    (ADR-028): a status and a message, never the score, explanation or signals."""
    customer = session.get(Customer, user.user_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        card1, addr1, d1n = parse_uid(customer.synthetic_uid)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    latest = (
        session.query(func.max(Transaction.submitted_at))
        .join(Account, Transaction.account_id == Account.account_id)
        .filter(Account.customer_id == customer.customer_id)
        .scalar()
    )
    dt = next_transaction_dt(latest)
    full = _score_and_commit(
        session,
        user,
        dict(
            card1=card1,
            addr1=addr1,
            d1=d1_for(dt, d1n),
            card6=payload.card6,
            amount=payload.amount,
            currency="USD",
            product_cd=payload.product_cd,
            device_type=payload.device_type,
            device_info=payload.device_info,
            browser=payload.browser,
            transaction_dt=dt,
        ),
    )
    status = CUSTOMER_STATUS_BY_DECISION[full.decision]
    return CustomerTransactionResult(
        transaction_id=full.transaction_id,
        amount=full.amount,
        currency=full.currency,
        submitted_at=full.submitted_at,
        status=status,
        message=CUSTOMER_MESSAGES[status],
    )


@me_router.get("/me", response_model=list[MyTransaction])
def my_transactions(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_customer),
) -> list[MyTransaction]:
    """The logged-in customer's last 50 transactions, newest first, with a
    customer-safe status only (ADR-028). Seeded history has no RiskAssessment,
    so its status is null."""
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
                status=CUSTOMER_STATUS_BY_DECISION[assessment.decision.value] if assessment else None,
            )
        )
    return items
