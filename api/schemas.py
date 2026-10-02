"""
Pydantic models for the API layer.

TransactionResponse deliberately has NO `decision` / `risk_score` field.
Risk Synthesis doesn't exist until week 4 — adding a stub field now
(null, "pending", whatever) means changing the response contract twice:
once now to fake it, once in week 4 to populate it for real. Clients
built against this week-1 contract won't need to change when the field
is added later; they simply weren't relying on something that didn't
exist yet.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TransactionRequest(BaseModel):
    # IEEE-CIS-shaped fields used to derive the synthetic UID (ADR-011).
    # Raw and unmasked in the sense that a real client would send these
    # straight from a card-processing context, not from the Kaggle CSV.
    card1: float
    addr1: float | None = None
    d1: float | None = Field(default=None, description="Days since card first used (IEEE-CIS D1)")
    card6: str | None = Field(default=None, description="'credit' or 'debit', if known")

    amount: float
    currency: str = "USD"
    product_cd: str = Field(..., description="Merchant category proxy, e.g. IEEE-CIS ProductCD")

    device_type: str | None = None
    device_info: str | None = None
    # Browser+version string (IEEE-CIS id_31 equivalent, e.g. "chrome 63.0").
    # Week 2: needed alongside device_info for device-intrinsic
    # fingerprinting (agents/device_identity.py) — without it, this
    # transaction's device falls back to customer-scoped fingerprinting
    # and can never be linked to a second customer, even if it should be.
    browser: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency_must_be_three_letters(cls, value: str) -> str:
        if len(value) != 3:
            raise ValueError("currency must be a 3-letter code, e.g. 'USD'")
        return value.upper()


class TransactionResponse(BaseModel):
    transaction_id: int
    synthetic_uid: str
    customer_id: int
    account_id: int
    merchant_id: int
    device_id: int | None
    amount: float
    currency: str
    submitted_at: datetime

    model_config = {"from_attributes": True}
