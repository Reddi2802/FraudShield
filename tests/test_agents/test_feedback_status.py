"""scripts/feedback_status.py: counts investigator labels since the current model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from passlib.hash import bcrypt

from db.models import (
    Account,
    CaseStatusEnum,
    Customer,
    Feedback,
    FeedbackLabelEnum,
    FraudCase,
    Investigator,
    Merchant,
    ModelVersion,
    Transaction,
)
from scripts.feedback_status import RETRAIN_AFTER_LABELS, feedback_since_last_model

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
_FAST_HASH = bcrypt.using(rounds=4).hash("pw")


def _base(session):
    customer = Customer(synthetic_uid="1-1-1", name="c", email="c@example.invalid", hashed_password=_FAST_HASH)
    investigator = Investigator(name="i", email="i@example.invalid", hashed_password=_FAST_HASH)
    merchant = Merchant(name="m", category="W")
    session.add_all([customer, investigator, merchant])
    session.flush()
    account = Account(customer_id=customer.customer_id, account_number="A1", account_type="credit")
    session.add(account)
    session.flush()
    return account, investigator, merchant


def _label(session, base, label, submitted_at):
    account, investigator, merchant = base
    txn = Transaction(account_id=account.account_id, merchant_id=merchant.merchant_id, amount=10.0, currency="USD")
    session.add(txn)
    session.flush()
    case = FraudCase(transaction_id=txn.transaction_id, status=CaseStatusEnum.RESOLVED, opened_at=submitted_at)
    session.add(case)
    session.flush()
    session.add(
        Feedback(
            fraud_case_id=case.fraud_case_id, investigator_id=investigator.investigator_id,
            label=label, submitted_at=submitted_at,
        )
    )
    session.flush()


def _model(session, trained_at):
    session.add(
        ModelVersion(model_type="xgboost_behavioral", trained_at=trained_at, hyperparameters={}, metrics={}, artifact_path="x")
    )
    session.flush()


def test_no_feedback_no_model(db_session):
    status = feedback_since_last_model(db_session)
    assert status["total"] == 0 and status["since"] is None and not status["reached"]


def test_without_a_model_every_label_counts(db_session):
    base = _base(db_session)
    _label(db_session, base, FeedbackLabelEnum.FRAUD, T0)
    _label(db_session, base, FeedbackLabelEnum.NOT_FRAUD, T0)
    status = feedback_since_last_model(db_session)
    assert (status["total"], status["fraud"], status["not_fraud"]) == (2, 1, 1)


def test_only_labels_after_the_latest_model_count(db_session):
    base = _base(db_session)
    _label(db_session, base, FeedbackLabelEnum.FRAUD, T0)  # before the model
    _model(db_session, T0 + timedelta(days=1))
    _label(db_session, base, FeedbackLabelEnum.NOT_FRAUD, T0 + timedelta(days=2))
    status = feedback_since_last_model(db_session)
    assert status["total"] == 1 and status["not_fraud"] == 1 and status["fraud"] == 0
    assert status["since"] == T0 + timedelta(days=1)


def test_threshold_is_reached_exactly_at_the_limit(db_session):
    base = _base(db_session)
    for _ in range(RETRAIN_AFTER_LABELS - 1):
        _label(db_session, base, FeedbackLabelEnum.FRAUD, T0)
    assert not feedback_since_last_model(db_session)["reached"]
    _label(db_session, base, FeedbackLabelEnum.NOT_FRAUD, T0)
    assert feedback_since_last_model(db_session)["reached"]
