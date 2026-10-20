"""
Pydantic models for the API layer.

TransactionResponse gained `decision`, `risk_score` and `explanation` in
Week 4, once Risk Synthesis existed — populated for real from the
pipeline's RiskAssessment, never stubbed earlier (a placeholder field would
have changed the response contract twice). The fields are additive, so a
client built against the Week 1 contract keeps working.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TransactionRequest(BaseModel):
    # IEEE-CIS-shaped fields used to derive the synthetic UID (ADR-011).
    # Raw and unmasked in the sense that a real client would send these
    # straight from a card-processing context, not from the Kaggle CSV.
    card1: float
    addr1: float | None = None
    d1: float | None = Field(default=None, description="Days since card first used (IEEE-CIS D1)")
    card6: str | None = Field(default=None, description="'credit' or 'debit', if known")
    # Week 3 (ADR-011 amendment): simulated TransactionDT, seconds, same
    # units as IEEE-CIS. Drives both the UID's D1n component and
    # submitted_at, so a CSV-replay demo produces real inter-transaction
    # time gaps instead of everything collapsing to ~now(). Omit for a
    # genuinely live transaction — see agents/ingestion.py's docstring for
    # what that means for UID matching against seeded customers.
    transaction_dt: float | None = None

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
    # Week 4: from the Risk Synthesis Agent (RiskAssessment row).
    decision: Literal["allow", "flag", "block"]
    risk_score: float
    explanation: str
    # Week 5 (ADR-020): set only when the decision is flag or block.
    case_id: int | None = None

    model_config = {"from_attributes": True}


# ---- Authentication (ADR-021) ----

class LoginRequest(BaseModel):
    email: str
    password: str
    role: Literal["customer", "investigator"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: Literal["customer", "investigator"]
    user_id: int


class MyTransaction(BaseModel):
    """One row of GET /transactions/me. decision / risk_score / explanation are
    null for transactions that never went through the pipeline (the seeded
    history was loaded directly into the database and has no RiskAssessment)."""

    transaction_id: int
    amount: float
    currency: str
    submitted_at: datetime
    decision: Literal["allow", "flag", "block"] | None = None
    risk_score: float | None = None
    explanation: str | None = None
    case_id: int | None = None


# ---- Investigator cases (ADR-021) ----

CaseStatus = Literal["open", "in_review", "resolved"]


class CaseSummary(BaseModel):
    case_id: int
    transaction_id: int
    status: CaseStatus
    opened_at: datetime
    decision: Literal["allow", "flag", "block"] | None = None
    risk_score: float | None = None


class CaseTransaction(BaseModel):
    amount: float
    currency: str
    submitted_at: datetime
    customer_id: int


class FeedbackInfo(BaseModel):
    label: Literal["fraud", "not_fraud"]
    notes: str | None = None
    investigator_id: int
    submitted_at: datetime


class CaseDetail(BaseModel):
    case_id: int
    transaction_id: int
    status: CaseStatus
    opened_at: datetime
    resolved_at: datetime | None = None
    transaction: CaseTransaction
    decision: Literal["allow", "flag", "block"] | None = None
    risk_score: float | None = None
    explanation: str | None = None
    feedback: FeedbackInfo | None = None


class FeedbackRequest(BaseModel):
    label: Literal["fraud", "not_fraud"]
    notes: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    feedback_id: int
    case_id: int
    label: Literal["fraud", "not_fraud"]
    notes: str | None = None
    status: CaseStatus
