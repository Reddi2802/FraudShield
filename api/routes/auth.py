"""POST /auth/login — email + password + role in, a Bearer JWT out (ADR-021)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import ROLE_CUSTOMER, create_access_token, verify_password
from api.schemas import LoginRequest, TokenResponse
from db.models import Customer, Investigator
from db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for "no such email" AND "wrong password", so the response never
# reveals which emails exist.
_INVALID = "Invalid credentials"


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    model = Customer if payload.role == ROLE_CUSTOMER else Investigator
    user = session.query(model).filter(model.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail=_INVALID)

    user_id = user.customer_id if payload.role == ROLE_CUSTOMER else user.investigator_id
    return TokenResponse(
        access_token=create_access_token(user_id, payload.role),
        token_type="bearer",
        role=payload.role,
        user_id=user_id,
    )
