"""
Explanation Agent — template version (ADR-004, ADR-020).

Turns the structured evidence behind a decision into ONE plain-language
sentence a customer or investigator can read, and keeps the technical
evidence right after it in the same field:

    Flagged for review: the amount is much higher than this customer's usual
    spend. Evidence: FLAG (risk 0.60). rules 0.60: amount_own_history (...)

It is deterministic and instant (no model call), so it never blocks a
decision. The slower natural-language enrichment via a local LLM (ADR-004's
async half) is a stretch item and would append to this, not replace it.

It explains from structured results (rule violations, the device signal, the
Behavioral model's top drivers), never by parsing the technical string, and
it only states what the evidence supports: a driver is named only when the
model's contribution for it is positive, and behavioral reasons appear only
when the behavioral risk is at least BEHAVIORAL_MENTION_MIN.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from agents.behavioral_analysis import BehavioralResult
from agents.behavioral_features import decode_card6, decode_product
from agents.risk_synthesis import EXPLANATION_MAX_CHARS, RiskDecision, Signal
from agents.rule_compliance import RuleComplianceResult
from db.models import DecisionEnum, RiskAssessment

BEHAVIORAL_MENTION_MIN = 0.20
MAX_REASONS = 4

RULE_PHRASES = {
    "velocity": "an unusually high number of transactions in a short time",
    "amount_own_history": "the amount is much higher than this customer's usual spend",
    "amount_global_fallback": "the amount is unusually high compared with all customers",
}

_PREFIX = {
    DecisionEnum.ALLOW: "Allowed",
    DecisionEnum.FLAG: "Flagged for review",
    DecisionEnum.BLOCK: "Blocked",
}


def driver_phrase(name: str, value: float) -> str:
    """One model driver (feature name + its value) as a readable clause."""
    if name == "amount":
        return f"the amount ({value:.2f}) is unusual"
    if name == "product_cd":
        return f"product category {decode_product(value)} carries elevated risk"
    if name == "card6":
        return f"the card type ({decode_card6(value)}) carries elevated risk"
    if name == "hour":
        return f"the time of day (hour {int(value)}) carries elevated risk"
    if name == "prior_count":
        return f"the customer has little history ({int(value)} earlier transactions)"
    if name == "amt_ratio":
        return f"the amount is {value:.1f}x this customer's usual spend"
    if name == "amt_z":
        return f"the amount is {value:.1f} standard deviations above this customer's norm"
    if name == "secs_since_last":
        return f"only {value / 60:.0f} minutes since this customer's previous transaction"
    return name.replace("_", " ")


def collect_reasons(
    rule_result: RuleComplianceResult,
    signals: list[Signal],
    behavioral: Optional[BehavioralResult],
) -> list[str]:
    reasons: list[str] = []
    for rule_name, _detail in rule_result.violations:
        reasons.append(RULE_PHRASES.get(rule_name, rule_name.replace("_", " ")))

    for signal in signals:
        if signal.agent == "device" and signal.score:
            reasons.extend(part.strip() for part in signal.reason.split(";") if part.strip())

    if (
        behavioral is not None
        and not behavioral.abstained
        and (behavioral.risk_score or 0.0) >= BEHAVIORAL_MENTION_MIN
    ):
        if behavioral.drivers:
            reasons.extend(driver_phrase(n, v) for n, v, _c in behavioral.drivers)
        else:
            reasons.append("the behavioral model rates this transaction riskier than most")
    return reasons[:MAX_REASONS]


def plain_sentence(decision: DecisionEnum, reasons: list[str]) -> str:
    prefix = _PREFIX[decision]
    if decision == DecisionEnum.ALLOW:
        return f"{prefix}: no signal raised enough risk."
    if not reasons:
        return f"{prefix}: the combined risk score crossed the review threshold."
    return f"{prefix}: {'; '.join(reasons)}."


def compose_explanation(
    risk_decision: RiskDecision,
    rule_result: RuleComplianceResult,
    behavioral: Optional[BehavioralResult],
) -> tuple[str, str]:
    """Returns (plain sentence, full text = sentence + technical evidence)."""
    reasons = collect_reasons(rule_result, risk_decision.signals, behavioral)
    sentence = plain_sentence(risk_decision.decision, reasons)
    full = f"{sentence} Evidence: {risk_decision.explanation}"
    return sentence, full[:EXPLANATION_MAX_CHARS]


def run_explanation(
    session: Session,
    assessment: RiskAssessment,
    risk_decision: RiskDecision,
    rule_result: RuleComplianceResult,
    behavioral: Optional[BehavioralResult],
) -> str:
    """Rewrite assessment.explanation_text (flush, don't commit). Returns the
    plain-language sentence."""
    sentence, full = compose_explanation(risk_decision, rule_result, behavioral)
    assessment.explanation_text = full
    session.flush()
    return sentence
