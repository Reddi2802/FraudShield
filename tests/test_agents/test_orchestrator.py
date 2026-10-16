"""End-to-end: LangGraph pipeline — ingestion -> rules -> device -> synthesis."""

from __future__ import annotations

import pytest

from agents.ingestion import IngestionError
from agents.orchestrator import run_pipeline
from db.models import DecisionEnum, RiskAssessment, RuleViolation, Transaction

DAY = 86400
DEVICE = dict(device_type="mobile", device_info="SM-G960F Build/R16NW", browser="chrome 63.0")


def _txn(session, *, dt, amount=10.0, card1=1000, device=False):
    payload = dict(
        card1=card1,
        addr1=300.0,
        d1=5.0 + dt / DAY,  # keeps D1n constant -> same customer for the same card1
        card6="credit",
        amount=amount,
        currency="USD",
        product_cd="W",
        transaction_dt=dt,
    )
    if device:
        payload.update(DEVICE)
    return run_pipeline(session, **payload)


def test_clean_first_transaction_is_allowed(db_session):
    out = _txn(db_session, dt=10 * DAY)
    a = out["assessment"]
    assert a.decision == DecisionEnum.ALLOW
    assert a.risk_score == 0.0
    assert a.transaction_id == out["transaction"].transaction_id
    assert a.model_version_id is None  # no trained model contributes yet


def test_one_assessment_row_per_run(db_session):
    _txn(db_session, dt=10 * DAY)
    _txn(db_session, dt=11 * DAY)
    assert db_session.query(RiskAssessment).count() == 2


def test_amount_spike_on_established_customer_is_flagged(db_session):
    for i in range(3):
        _txn(db_session, dt=10 * DAY + i * 7200)  # spaced 2h: no velocity hit
    out = _txn(db_session, dt=10 * DAY + 3 * 7200, amount=100.0)
    assert out["assessment"].decision == DecisionEnum.FLAG
    assert "amount_own_history" in out["assessment"].explanation_text
    assert out["prior_txn_count"] == 3


def test_velocity_plus_amount_spike_is_blocked(db_session):
    for i in range(5):
        _txn(db_session, dt=10 * DAY + i * 60)
    out = _txn(db_session, dt=10 * DAY + 5 * 60, amount=100.0)
    assert out["assessment"].decision == DecisionEnum.BLOCK
    assert out["assessment"].risk_score >= 0.70
    names = {v.rule_name for v in db_session.query(RuleViolation).all()}
    assert {"velocity", "amount_own_history"} <= names


def test_device_shared_by_three_customers_is_flagged(db_session):
    _txn(db_session, dt=10 * DAY, card1=1000, device=True)
    _txn(db_session, dt=11 * DAY, card1=2000, device=True)
    out = _txn(db_session, dt=12 * DAY, card1=3000, device=True)
    assert out["device_result"].reuse_count == 3
    assert out["assessment"].decision == DecisionEnum.FLAG
    assert "device shared by 3 customers" in out["assessment"].explanation_text


def test_missing_device_shows_up_as_an_abstention(db_session):
    out = _txn(db_session, dt=10 * DAY, device=False)
    assert "device abstained" in out["assessment"].explanation_text


def test_invalid_payload_raises_and_writes_nothing(db_session):
    with pytest.raises(IngestionError):
        _txn(db_session, dt=10 * DAY, amount=-5.0)
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(RiskAssessment).count() == 0
