"""Rule Compliance Agent (Week 2) — dedicated tests (previously uncovered)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.ingestion import process_transaction
from agents.rule_compliance import (
    check_amount,
    check_velocity,
    evaluate_transaction,
    run_rule_compliance,
)
from db.models import RuleViolation

T0 = datetime(2017, 12, 10, tzinfo=timezone.utc)


# ---- pure checks (no DB) ----

def test_velocity_no_history_does_not_fire():
    assert check_velocity(T0, []) == (False, None)


def test_velocity_fires_when_over_limit_in_window():
    prior = [T0 - timedelta(minutes=i) for i in range(1, 6)]  # 5 prior + current = 6 > 5
    fired, detail = check_velocity(T0, prior)
    assert fired and "6 txns" in detail


def test_velocity_ignores_transactions_outside_window():
    prior = [T0 - timedelta(hours=2, minutes=i) for i in range(10)]
    assert check_velocity(T0, prior)[0] is False


def test_amount_own_history_fires_above_multiplier():
    fired, detail, rule = check_amount(100.0, [10.0, 10.0, 10.0], global_p99=None)
    assert fired and rule == "amount_own_history"


def test_amount_own_history_does_not_fire_within_multiplier():
    assert check_amount(25.0, [10.0, 10.0, 10.0], global_p99=None)[0] is False


def test_amount_thin_history_uses_global_fallback():
    fired, _, rule = check_amount(60.0, [10.0], global_p99=50.0)
    assert fired and rule == "amount_global_fallback"


def test_amount_thin_history_without_global_does_not_fire():
    assert check_amount(60.0, [10.0], global_p99=None)[0] is False


def test_evaluate_transaction_collects_both_rules():
    prior_dts = [T0 - timedelta(minutes=i) for i in range(1, 6)]
    prior_amts = [10.0, 10.0, 10.0, 10.0, 10.0]
    result = evaluate_transaction(1, T0, 100.0, prior_dts, prior_amts, None)
    assert result.flagged
    assert {name for name, _ in result.violations} == {"velocity", "amount_own_history"}


# ---- DB-backed ----

def _ingest(session, dt, amount):
    return process_transaction(
        session,
        card1=1000,
        addr1=300.0,
        d1=5.0 + dt / 86400,  # keeps D1n constant -> same customer
        card6="credit",
        amount=amount,
        currency="USD",
        product_cd="W",
        transaction_dt=dt,
    )


def test_run_rule_compliance_writes_amount_violation(db_session):
    base = 10 * 86400
    for i in range(3):
        _ingest(db_session, base + i * 7200, 10.0)  # spaced 2h apart: no velocity hit
    spike = _ingest(db_session, base + 3 * 7200, 100.0)

    result = run_rule_compliance(db_session, spike)

    assert result.flagged
    rows = db_session.query(RuleViolation).filter_by(transaction_id=spike.transaction_id).all()
    assert [r.rule_name for r in rows] == ["amount_own_history"]
    assert rows[0].severity == "high"


def test_run_rule_compliance_writes_velocity_violation(db_session):
    base = 10 * 86400
    last = None
    for i in range(6):
        last = _ingest(db_session, base + i * 60, 10.0)  # 6 txns in 5 minutes
    result = run_rule_compliance(db_session, last)
    assert ("velocity" in {name for name, _ in result.violations})


def test_run_rule_compliance_clean_transaction_writes_nothing(db_session):
    t = _ingest(db_session, 10 * 86400, 10.0)
    result = run_rule_compliance(db_session, t)
    assert not result.flagged
    assert db_session.query(RuleViolation).count() == 0
