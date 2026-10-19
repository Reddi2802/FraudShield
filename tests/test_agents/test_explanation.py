"""Explanation Agent (template version): plain sentence first, evidence after."""

from __future__ import annotations

from agents.behavioral_analysis import BehavioralResult
from agents.behavioral_features import PRODUCT_CODES
from agents.explanation import (
    BEHAVIORAL_MENTION_MIN,
    collect_reasons,
    compose_explanation,
    driver_phrase,
    plain_sentence,
)
from agents.risk_synthesis import EXPLANATION_MAX_CHARS, Signal, synthesize
from agents.rule_compliance import RuleComplianceResult
from db.models import DecisionEnum

NO_RULES = RuleComplianceResult(transaction_id=1)
AMOUNT_RULE = RuleComplianceResult(1, violations=[("amount_own_history", "amount 500 > 3x mean 10")])


def _behavioral(score, drivers=(), abstained=False):
    return BehavioralResult(
        transaction_id=1, abstained=abstained, reason="r",
        probability=0.5, risk_score=score, drivers=list(drivers),
    )


def test_allowed_sentence_names_no_reasons():
    assert plain_sentence(DecisionEnum.ALLOW, ["ignored"]) == "Allowed: no signal raised enough risk."


def test_flagged_by_a_rule_uses_plain_language_not_rule_codes():
    sentence, full = compose_explanation(
        synthesize([Signal("rules", 0.6, "amount_own_history (...)")]), AMOUNT_RULE, None
    )
    assert sentence == (
        "Flagged for review: the amount is much higher than this customer's usual spend."
    )
    assert "amount_own_history" not in sentence
    assert full.startswith(sentence + " Evidence: FLAG (risk 0.60).")


def test_blocked_prefix():
    assert plain_sentence(DecisionEnum.BLOCK, ["x"]).startswith("Blocked: x")


def test_behavioral_drivers_are_translated():
    behavioral = _behavioral(0.5, [("product_cd", float(PRODUCT_CODES["C"]), 0.8), ("amt_ratio", 21.0, 0.3)])
    reasons = collect_reasons(NO_RULES, [], behavioral)
    assert reasons == [
        "product category C carries elevated risk",
        "the amount is 21.0x this customer's usual spend",
    ]


def test_low_behavioral_risk_and_abstentions_are_not_mentioned():
    drivers = [("product_cd", 0.0, 0.8)]
    assert collect_reasons(NO_RULES, [], _behavioral(BEHAVIORAL_MENTION_MIN - 0.01, drivers)) == []
    assert collect_reasons(NO_RULES, [], _behavioral(None, drivers, abstained=True)) == []


def test_behavioral_without_drivers_gets_a_generic_reason():
    assert collect_reasons(NO_RULES, [], _behavioral(0.6)) == [
        "the behavioral model rates this transaction riskier than most"
    ]


def test_device_reasons_come_from_the_device_signal():
    signals = [Signal("device", 0.45, "device shared by 3 customers; first use of this device by a customer with history")]
    assert collect_reasons(NO_RULES, signals, None) == [
        "device shared by 3 customers",
        "first use of this device by a customer with history",
    ]


def test_reasons_are_capped_for_readability():
    rules = RuleComplianceResult(1, violations=[("velocity", "a"), ("amount_own_history", "b"), ("amount_global_fallback", "c")])
    behavioral = _behavioral(0.7, [("amount", 500.0, 0.5), ("hour", 7.0, 0.4)])
    assert len(collect_reasons(rules, [], behavioral)) == 4


def test_flag_with_no_attributable_reason_still_reads_sensibly():
    assert plain_sentence(DecisionEnum.FLAG, []) == (
        "Flagged for review: the combined risk score crossed the review threshold."
    )


def test_driver_phrases_cover_every_feature():
    from agents.behavioral_features import FEATURE_COLUMNS

    for name in FEATURE_COLUMNS:
        assert driver_phrase(name, 1.0) and "_" not in driver_phrase(name, 1.0)


def test_full_text_fits_the_column():
    decision = synthesize([Signal("rules", 0.6, "x" * 3000)])
    _, full = compose_explanation(decision, AMOUNT_RULE, None)
    assert len(full) <= EXPLANATION_MAX_CHARS
