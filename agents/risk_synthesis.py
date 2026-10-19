"""
Risk Synthesis Agent — Week 4

Fuses every agent's signal into one 0-1 risk score, a decision
(allow / flag / block) and a templated, human-readable explanation, and
writes a RiskAssessment row.

FUSION: weighted noisy-OR.

    risk = 1 - PRODUCT over scored agents of (1 - weight_agent * score_agent)

- An agent that ABSTAINED (score is None: no device info, too little
  history, ...) is skipped — it contributes nothing and is named as
  abstained in the explanation. No fake neutral 0.5 is ever injected.
- A clean signal (score 0.0) also contributes nothing, so a clean device can
  never mask a rule hit. A weighted average would do exactly that.
- Several independent weak signals add up; a single strong one still counts.
- The result stays in [0, 1] by construction, and every term in the
  explanation maps to one agent's reason string.

Thresholds are starting points, not tuned values — see DECISIONS.md.
Adding Behavioral Analysis or Network Intelligence later means building one
more Signal and passing it to synthesize(); nothing in here changes.

Follows the other agents' convention: flush, don't commit — the caller owns
the transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from agents.device_trust import DeviceTrustResult
from agents.rule_compliance import SEVERITY_BY_RULE, RuleComplianceResult
from db.models import DecisionEnum, RiskAssessment, Transaction

# ---- Config (starting points; revisit once real fused scores exist) ----

SEVERITY_SCORE = {"low": 0.2, "medium": 0.4, "high": 0.6}

# Per-agent trust. Behavioral / network entries are placeholders for the
# agents that land in Weeks 3 and 5; unknown agents default to 1.0.
AGENT_WEIGHTS = {"rules": 1.0, "device": 0.8, "behavioral": 1.0, "network": 0.8}

ALLOW_BELOW = 0.35   # fused score under this -> allow
BLOCK_AT = 0.70      # fused score at/over this -> block; in between -> flag

# Device sub-signals
REUSE_BASE = 0.30          # device linked to exactly 2 customers
REUSE_STEP = 0.15          # each additional linked customer
REUSE_CAP = 0.75
NEW_DEVICE_SCORE = 0.15    # new device for a customer who already has history

EXPLANATION_MAX_CHARS = 2000  # RiskAssessment.explanation_text is String(2000)


@dataclass
class Signal:
    agent: str
    score: Optional[float]  # None == abstained
    reason: str

    @property
    def abstained(self) -> bool:
        return self.score is None


@dataclass
class RiskDecision:
    risk_score: float
    decision: DecisionEnum
    explanation: str
    signals: list


# ---- Pure functions (unit-testable with no DB) ----

def noisy_or(probabilities: list[float]) -> float:
    remaining = 1.0
    for p in probabilities:
        remaining *= 1.0 - p
    return 1.0 - remaining


def rule_signal(result: RuleComplianceResult) -> Signal:
    if not result.violations:
        return Signal("rules", 0.0, "no rule violations")
    scores = [
        SEVERITY_SCORE[SEVERITY_BY_RULE.get(rule_name, "medium")]
        for rule_name, _ in result.violations
    ]
    reason = "; ".join(f"{rule_name} ({detail})" for rule_name, detail in result.violations)
    return Signal("rules", noisy_or(scores), reason)


def device_signal(result: DeviceTrustResult, customer_prior_txn_count: int) -> Signal:
    if result.no_device:
        return Signal("device", None, "no device information on this transaction")

    components: list[float] = []
    reasons: list[str] = []

    if result.reuse_count >= 2:
        components.append(
            min(REUSE_BASE + REUSE_STEP * (result.reuse_count - 2), REUSE_CAP)
        )
        reasons.append(f"device shared by {result.reuse_count} customers")

    # A first-ever transaction is trivially "a new device" — only meaningful
    # for a customer who already has history.
    if result.is_new_device_for_customer and customer_prior_txn_count > 0:
        components.append(NEW_DEVICE_SCORE)
        reasons.append("first use of this device by a customer with history")

    if not components:
        return Signal("device", 0.0, "familiar device, no sharing")
    return Signal("device", noisy_or(components), "; ".join(reasons))


def fuse(signals: list[Signal]) -> float:
    contributions = [
        AGENT_WEIGHTS.get(s.agent, 1.0) * s.score for s in signals if not s.abstained
    ]
    return min(max(noisy_or(contributions), 0.0), 1.0)


def decide(score: float) -> DecisionEnum:
    if score >= BLOCK_AT:
        return DecisionEnum.BLOCK
    if score >= ALLOW_BELOW:
        return DecisionEnum.FLAG
    return DecisionEnum.ALLOW


def explain(decision: DecisionEnum, score: float, signals: list[Signal]) -> str:
    parts = []
    for s in signals:
        if s.abstained:
            parts.append(f"{s.agent} abstained ({s.reason})")
        else:
            parts.append(f"{s.agent} {s.score:.2f}: {s.reason}")
    text = f"{decision.value.upper()} (risk {score:.2f}). " + "; ".join(parts) + "."
    return text[:EXPLANATION_MAX_CHARS]


def synthesize(signals: list[Signal]) -> RiskDecision:
    score = fuse(signals)
    decision = decide(score)
    return RiskDecision(score, decision, explain(decision, score, signals), signals)


# ---- DB-touching ----

def run_risk_synthesis_detailed(
    session: Session,
    transaction: Transaction,
    rule_result: RuleComplianceResult,
    device_result: DeviceTrustResult,
    prior_txn_count: int,
    extra_signals: Optional[list[Signal]] = None,
    model_version_id: Optional[int] = None,
) -> tuple[RiskAssessment, RiskDecision]:
    """
    Build the signals, fuse, and persist one RiskAssessment row. Returns the
    row AND the RiskDecision (with every Signal) so the Explanation Agent can
    explain from structured evidence instead of parsing text.

    extra_signals is where Behavioral Analysis (Week 3) and Network
    Intelligence (Week 5) plug in. model_version_id stays None until a
    trained model contributes (the column is nullable by design).
    """
    signals = [rule_signal(rule_result), device_signal(device_result, prior_txn_count)]
    signals.extend(extra_signals or [])

    result = synthesize(signals)

    assessment = RiskAssessment(
        transaction_id=transaction.transaction_id,
        model_version_id=model_version_id,
        risk_score=result.risk_score,
        decision=result.decision,
        explanation_text=result.explanation,
    )
    session.add(assessment)
    session.flush()
    return assessment, result


def run_risk_synthesis(
    session: Session,
    transaction: Transaction,
    rule_result: RuleComplianceResult,
    device_result: DeviceTrustResult,
    prior_txn_count: int,
    extra_signals: Optional[list[Signal]] = None,
    model_version_id: Optional[int] = None,
) -> RiskAssessment:
    """Same as run_risk_synthesis_detailed, returning only the RiskAssessment row."""
    assessment, _ = run_risk_synthesis_detailed(
        session, transaction, rule_result, device_result, prior_txn_count,
        extra_signals=extra_signals, model_version_id=model_version_id,
    )
    return assessment
