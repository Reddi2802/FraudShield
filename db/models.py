"""
ORM models, mapped 1:1 against the Lab5 ERD / class diagram.

Entity list: Customer, Account, Device, Merchant, Transaction,
RiskAssessment, ModelVersion, RuleViolation, NetworkRiskScore, FraudCase,
Investigator, Feedback, AgentLog, DeviceCustomerLink.

Cardinality notes carried over verbatim from the Lab5 doc, because these
are the things you'll be asked to defend:
- RiskAssessment is ONE-TO-MANY from Transaction (not 1:1) — a transaction
  can be re-scored after retraining or manual review.
- ModelVersion is ONE-TO-MANY into RiskAssessment — traceability of which
  trained model produced which score (see chat: this is the thing that
  makes "explainable by construction" actually auditable over time).
- FraudCase is ONE-TO-ONE with Transaction — only flagged/blocked
  transactions get a case, and a transaction gets at most one.
- NetworkRiskScore is ONE-TO-MANY from Customer (not Transaction) —
  it's a periodic, customer-level output of the async batch job, not
  something computed per transaction.
- AgentLog is ONE-TO-MANY from Transaction — independent audit trail of
  every agent's raw output, separate from RiskAssessment's final result.
- Device is now MANY-TO-MANY with Customer via DeviceCustomerLink (see
  chat, week 2: the original single Device.customer_id FK made
  cross-customer device reuse — the actual signal Device Trust needs —
  structurally impossible to detect. One physical device can now link to
  many customers, and Device Trust's reuse_count is a query over this
  link table, not a stored counter.)

Identity note (ADR-011 / ADR-012):
- Customer.synthetic_uid is the join key between IEEE-CIS-derived identity
  (card1+addr1+D1n, see agents/uid.py) and this ORM's Customer row. It is a
  probabilistic proxy, not a verified identity key — see ADR-011 for
  documented limitations. Customer.name / email / hashed_password are
  FABRICATED at seed time (scripts/seed_db.py) for demo-login purposes
  only; IEEE-CIS provides no real name, email, or credential for anyone.
- Customer.billing_region persists the raw addr1 value used in the UID
  computation (previously computed into the UID and discarded — see
  chat, week 2). Profile/explanation context ONLY — not a rule trigger.
  A billing-mismatch rule is structurally unreachable because addr1 is
  part of synthetic_uid (see ADR-015).
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────
# Using real Python enums (not free-text strings) so a typo like "flagg"
# fails at insert time instead of silently corrupting a report later.

class DecisionEnum(str, enum.Enum):
    ALLOW = "allow"
    FLAG = "flag"
    BLOCK = "block"


class CaseStatusEnum(str, enum.Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class FeedbackLabelEnum(str, enum.Enum):
    FRAUD = "fraud"
    NOT_FRAUD = "not_fraud"


# ── Core entity classes (Customer, Account, Device, Merchant) ──────────────

class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(primary_key=True)
    # ADR-011 join key: card1+addr1+D1n -> string, computed by agents/uid.py.
    # unique+indexed because both ingestion.py and seed_db.py look up
    # "does a Customer with this UID already exist" on every transaction.
    synthetic_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Raw addr1 value, cleaned via agents.uid.clean_component (same "NA"
    # sentinel convention as the UID itself). Customer-level, not
    # per-transaction — matches how the UID already treats addr1 as a
    # customer-identifying anchor, not a transaction attribute.
    billing_region: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))  # passlib bcrypt hash
    created_at: Mapped[datetime] = mapped_column(default=_now_utc)

    accounts: Mapped[list["Account"]] = relationship(back_populates="customer")
    device_links: Mapped[list["DeviceCustomerLink"]] = relationship(
        back_populates="customer"
    )
    network_risk_scores: Mapped[list["NetworkRiskScore"]] = relationship(
        back_populates="customer"
    )


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"))
    account_number: Mapped[str] = mapped_column(String(34), unique=True)
    account_type: Mapped[str] = mapped_column(String(50))  # e.g. "checking", "credit"
    created_at: Mapped[datetime] = mapped_column(default=_now_utc)

    customer: Mapped["Customer"] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[int] = mapped_column(primary_key=True)
    # NOTE: no customer_id FK anymore (see chat, week 2). A Device is no
    # longer owned by exactly one Customer — see DeviceCustomerLink below.
    # device_fingerprint is now built from device-intrinsic signals
    # (DeviceInfo + id_31) where possible, NOT customer identity — see
    # agents/device_identity.py for the exact rule,
    # including the generic-OS-bucket exclusion fallback.
    device_fingerprint: Mapped[str] = mapped_column(String(255), unique=True)
    device_type: Mapped[str] = mapped_column(String(50))  # e.g. "mobile", "desktop"
    first_seen_at: Mapped[datetime] = mapped_column(default=_now_utc)  # first ever seen, any customer
    last_seen_at: Mapped[datetime] = mapped_column(default=_now_utc)   # most recent use, any customer

    customer_links: Mapped[list["DeviceCustomerLink"]] = relationship(
        back_populates="device"
    )
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="device")


class DeviceCustomerLink(Base):
    """
    Association table enabling many-to-many Device <-> Customer.

    Replaces the original Device.customer_id single FK (see chat, week 2:
    that FK made cross-customer device reuse — the core Device Trust
    signal — structurally undetectable, since one device could only ever
    belong to one customer).

    first_seen_at here is scoped to THIS customer+device pair ("when did
    this customer first use this device"), distinct from
    Device.first_seen_at ("when was this device first seen at all, by
    any customer"). Device Trust needs both: per-customer first-seen for
    "is this a new device for this customer" (existing signal), and the
    device-level view for reuse_count ("how many distinct customers has
    this device been linked to" — a simple COUNT over this table, not a
    stored counter, so it's always correct without a sync step).
    """

    __tablename__ = "device_customer_links"
    __table_args__ = (UniqueConstraint("device_id", "customer_id"),)

    device_customer_link_id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.device_id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"))
    first_seen_at: Mapped[datetime] = mapped_column(default=_now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(default=_now_utc)

    device: Mapped["Device"] = relationship(back_populates="customer_links")
    customer: Mapped["Customer"] = relationship(back_populates="device_links")


class Merchant(Base):
    __tablename__ = "merchants"

    merchant_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))  # MCC-style category

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="merchant")


# ── Central fact class ──────────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[int] = mapped_column(primary_key=True)
    # index=True on account_id/device_id: Rule Compliance, Device Trust and the
    # history helper all filter Transaction by these on every request; SQLite
    # does not index foreign keys automatically, so each lookup was a full scan
    # that got slower as the table grew (visible in scripts/replay_eval.py).
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.merchant_id"))
    # Nullable: not every transaction has an identifiable device (e.g. card-present).
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.device_id"), nullable=True, index=True
    )
    amount: Mapped[float]
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    submitted_at: Mapped[datetime] = mapped_column(default=_now_utc)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    merchant: Mapped["Merchant"] = relationship(back_populates="transactions")
    device: Mapped["Device | None"] = relationship(back_populates="transactions")

    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="transaction"
    )
    rule_violations: Mapped[list["RuleViolation"]] = relationship(
        back_populates="transaction"
    )
    agent_logs: Mapped[list["AgentLog"]] = relationship(back_populates="transaction")
    # uselist=False enforces the 1:1 with FraudCase at the ORM level.
    fraud_case: Mapped["FraudCase | None"] = relationship(
        back_populates="transaction", uselist=False
    )


# ── Detection & scoring classes ─────────────────────────────────────────

class ModelVersion(Base):
    __tablename__ = "model_versions"

    model_version_id: Mapped[int] = mapped_column(primary_key=True)
    model_type: Mapped[str] = mapped_column(String(100))  # e.g. "isolation_forest_behavioral"
    trained_at: Mapped[datetime] = mapped_column(default=_now_utc)
    hyperparameters: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # precision/recall/F1/FPR at training time
    artifact_path: Mapped[str] = mapped_column(String(500))  # points into ml/artifacts/ (gitignored)

    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="model_version"
    )


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    risk_assessment_id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.transaction_id"))
    # Nullable: a rule-only rejection (instant block) may not involve a trained model at all.
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.model_version_id"), nullable=True
    )
    risk_score: Mapped[float]  # 0.0–1.0, fused across agents
    decision: Mapped[DecisionEnum]
    explanation_text: Mapped[str] = mapped_column(String(2000))
    assessed_at: Mapped[datetime] = mapped_column(default=_now_utc)

    transaction: Mapped["Transaction"] = relationship(back_populates="risk_assessments")
    model_version: Mapped["ModelVersion | None"] = relationship(
        back_populates="risk_assessments"
    )


class RuleViolation(Base):
    __tablename__ = "rule_violations"

    rule_violation_id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.transaction_id"))
    rule_name: Mapped[str] = mapped_column(String(100))  # e.g. "velocity_limit"
    rule_description: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(20))  # "low" | "medium" | "high"

    transaction: Mapped["Transaction"] = relationship(back_populates="rule_violations")


class NetworkRiskScore(Base):
    __tablename__ = "network_risk_scores"

    network_risk_score_id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"))
    score: Mapped[float]
    graph_metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # degree, clustering_coeff, etc.
    computed_at: Mapped[datetime] = mapped_column(default=_now_utc)

    customer: Mapped["Customer"] = relationship(back_populates="network_risk_scores")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    agent_log_id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.transaction_id"))
    agent_name: Mapped[str] = mapped_column(String(100))  # e.g. "device_trust"
    raw_output: Mapped[dict] = mapped_column(JSON, default=dict)
    logged_at: Mapped[datetime] = mapped_column(default=_now_utc)

    transaction: Mapped["Transaction"] = relationship(back_populates="agent_logs")


# ── Case management & audit classes ─────────────────────────────────────

class Investigator(Base):
    __tablename__ = "investigators"

    investigator_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    fraud_cases: Mapped[list["FraudCase"]] = relationship(back_populates="investigator")
    feedback_entries: Mapped[list["Feedback"]] = relationship(back_populates="investigator")


class FraudCase(Base):
    __tablename__ = "fraud_cases"
    __table_args__ = (UniqueConstraint("transaction_id"),)  # enforces the 1:1 with Transaction

    fraud_case_id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.transaction_id"))
    # Nullable: a case can exist before it's been assigned to an investigator.
    investigator_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigators.investigator_id"), nullable=True
    )
    status: Mapped[CaseStatusEnum] = mapped_column(default=CaseStatusEnum.OPEN)
    opened_at: Mapped[datetime] = mapped_column(default=_now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    transaction: Mapped["Transaction"] = relationship(back_populates="fraud_case")
    investigator: Mapped["Investigator | None"] = relationship(back_populates="fraud_cases")
    feedback_entries: Mapped[list["Feedback"]] = relationship(back_populates="fraud_case")


class Feedback(Base):
    __tablename__ = "feedback"

    feedback_id: Mapped[int] = mapped_column(primary_key=True)
    fraud_case_id: Mapped[int] = mapped_column(ForeignKey("fraud_cases.fraud_case_id"))
    investigator_id: Mapped[int] = mapped_column(ForeignKey("investigators.investigator_id"))
    label: Mapped[FeedbackLabelEnum]
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(default=_now_utc)

    fraud_case: Mapped["FraudCase"] = relationship(back_populates="feedback_entries")
    investigator: Mapped["Investigator"] = relationship(back_populates="feedback_entries")

