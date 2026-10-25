"""GET /customers/me — the logged-in customer's profile for the website (ADR-027)."""

from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import AuthUser, require_customer
from api.identity import parse_uid
from api.schemas import CustomerMe
from db.models import Account, Customer, Transaction
from db.session import get_session

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/me", response_model=CustomerMe)
def my_profile(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(require_customer),
) -> CustomerMe:
    customer = session.get(Customer, user.user_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        card1 = int(parse_uid(customer.synthetic_uid)[0])
    except ValueError:
        card1 = None

    amounts = [
        row[0]
        for row in session.query(Transaction.amount)
        .join(Account, Transaction.account_id == Account.account_id)
        .filter(Account.customer_id == customer.customer_id)
    ]
    return CustomerMe(
        customer_id=customer.customer_id,
        name=customer.name,
        email=customer.email,
        card1=card1,
        billing_region=customer.billing_region,
        typical_amount=round(statistics.median(amounts), 2) if amounts else None,
        transaction_count=len(amounts),
    )
