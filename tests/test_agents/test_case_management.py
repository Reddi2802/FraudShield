"""Case Management Agent: a case only for flag/block, one per transaction."""

from __future__ import annotations

from datetime import timedelta


from agents.case_management import run_case_management
from agents.orchestrator import run_pipeline
from agents.uid import REFERENCE_START
from db.models import CaseStatusEnum, DecisionEnum, FraudCase

DAY = 86400


def _txn(session, dt, amount=10.0):
    return run_pipeline(
        session, card1=1000, addr1=300.0, d1=5.0 + dt / DAY, card6="credit",
        amount=amount, currency="USD", product_cd="W", transaction_dt=dt,
    )


def _flagged(session):
    for i in range(3):
        _txn(session, 10 * DAY + i * 7200)
    return _txn(session, 10 * DAY + 3 * 7200, amount=100.0)


def test_allowed_transaction_opens_no_case(db_session):
    out = _txn(db_session, 10 * DAY)
    assert out["assessment"].decision == DecisionEnum.ALLOW
    assert out["case"] is None
    assert db_session.query(FraudCase).count() == 0


def test_flagged_transaction_opens_an_open_unassigned_case(db_session):
    out = _flagged(db_session)
    assert out["assessment"].decision == DecisionEnum.FLAG
    case = out["case"]
    assert case.status == CaseStatusEnum.OPEN
    assert case.investigator_id is None and case.resolved_at is None
    assert case.transaction_id == out["transaction"].transaction_id


def test_case_is_stamped_with_the_transaction_time_not_the_wall_clock(db_session):
    out = _flagged(db_session)
    expected = REFERENCE_START + timedelta(seconds=10 * DAY + 3 * 7200)
    assert out["case"].opened_at == expected


def test_blocked_transaction_opens_a_case(db_session):
    for i in range(5):
        _txn(db_session, 10 * DAY + i * 60)
    out = _txn(db_session, 10 * DAY + 5 * 60, amount=100.0)
    assert out["assessment"].decision == DecisionEnum.BLOCK
    assert out["case"] is not None


def test_agent_is_idempotent(db_session):
    out = _flagged(db_session)
    again = run_case_management(db_session, out["transaction"], out["assessment"])
    assert again.fraud_case_id == out["case"].fraud_case_id
    assert db_session.query(FraudCase).count() == 1


def test_pipeline_explanation_is_plain_language_first(db_session):
    out = _flagged(db_session)
    text = out["assessment"].explanation_text
    assert text.startswith("Flagged for review: the amount is much higher")
    assert "Evidence: FLAG (risk" in text
