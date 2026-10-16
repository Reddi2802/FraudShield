"""Risk Synthesis Agent (Week 4) — fusion, thresholds, abstain handling."""

from __future__ import annotations

import pytest

from agents.device_trust import DeviceTrustResult
from agents.risk_synthesis import (
    ALLOW_BELOW,
    BLOCK_AT,
    Signal,
    decide,
    device_signal,
    explain,
    fuse,
    noisy_or,
    rule_signal,
    synthesize,
)
from agents.rule_compliance import RuleComplianceResult
from db.models import DecisionEnum


def _device(**kw) -> DeviceTrustResult:
    base = dict(
        transaction_id=1,
        device_id=1,
        reuse_count=1,
        is_first_seen_globally=False,
        is_new_device_for_customer=False,
        device_age=None,
    )
    base.update(kw)
    return DeviceTrustResult(**base)


# ---- rule signal ----

def test_rule_signal_clean_is_zero_not_abstained():
    s = rule_signal(RuleComplianceResult(transaction_id=1))
    assert s.score == 0.0 and not s.abstained


def test_rule_signal_single_high_severity():
    r = RuleComplianceResult(1, violations=[("amount_own_history", "x")])
    assert rule_signal(r).score == pytest.approx(0.6)


def test_rule_signal_combines_violations():
    r = RuleComplianceResult(1, violations=[("amount_own_history", "x"), ("velocity", "y")])
    assert rule_signal(r).score == pytest.approx(1 - 0.4 * 0.6)  # 0.76


# ---- device signal ----

def test_device_signal_abstains_without_a_device():
    s = device_signal(_device(device_id=None), customer_prior_txn_count=10)
    assert s.abstained


def test_device_signal_familiar_device_is_zero():
    assert device_signal(_device(), 10).score == 0.0


def test_device_signal_shared_device():
    assert device_signal(_device(reuse_count=3), 0).score == pytest.approx(0.45)


def test_device_signal_reuse_is_capped():
    assert device_signal(_device(reuse_count=50), 0).score == pytest.approx(0.75)


def test_new_device_only_counts_for_customers_with_history():
    new = _device(is_new_device_for_customer=True)
    assert device_signal(new, customer_prior_txn_count=0).score == 0.0
    assert device_signal(new, customer_prior_txn_count=4).score == pytest.approx(0.15)


# ---- fusion ----

def test_noisy_or_basics():
    assert noisy_or([]) == 0.0
    assert noisy_or([0.5, 0.5]) == pytest.approx(0.75)


def test_abstained_agent_contributes_nothing():
    only_rules = fuse([Signal("rules", 0.6, "r")])
    with_abstain = fuse([Signal("rules", 0.6, "r"), Signal("device", None, "n/a")])
    assert only_rules == with_abstain == pytest.approx(0.6)


def test_clean_device_cannot_mask_a_rule_hit():
    assert fuse([Signal("rules", 0.6, "r"), Signal("device", 0.0, "ok")]) == pytest.approx(0.6)


def test_weak_signals_accumulate():
    s = fuse([Signal("rules", 0.4, "a"), Signal("device", 0.75, "b")])
    assert s == pytest.approx(1 - (1 - 0.4) * (1 - 0.8 * 0.75))


@pytest.mark.parametrize("a", [0.0, 0.3, 1.0])
@pytest.mark.parametrize("b", [0.0, 0.5, 1.0])
def test_fused_score_always_in_unit_range(a, b):
    assert 0.0 <= fuse([Signal("rules", a, ""), Signal("device", b, ""),
                        Signal("behavioral", None, "")]) <= 1.0


# ---- decision thresholds ----

def test_threshold_boundaries():
    assert decide(ALLOW_BELOW - 0.001) == DecisionEnum.ALLOW
    assert decide(ALLOW_BELOW) == DecisionEnum.FLAG
    assert decide(BLOCK_AT - 0.001) == DecisionEnum.FLAG
    assert decide(BLOCK_AT) == DecisionEnum.BLOCK


# ---- explanation ----

def test_explanation_names_every_agent_including_abstainers():
    result = synthesize([
        Signal("rules", 0.6, "amount_own_history (3x mean)"),
        Signal("device", None, "no device information on this transaction"),
        Signal("behavioral", None, "insufficient history"),
    ])
    text = result.explanation
    assert text.startswith("FLAG (risk 0.60)")
    assert "rules 0.60: amount_own_history" in text
    assert "device abstained" in text and "behavioral abstained (insufficient history)" in text


def test_explanation_fits_the_column():
    long_signals = [Signal("rules", 0.5, "x" * 3000)]
    assert len(explain(DecisionEnum.FLAG, 0.5, long_signals)) <= 2000
