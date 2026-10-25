"""
Persist every agent's Signal for a transaction (ADR-027).

Risk Synthesis already builds one Signal per agent (rules, device, behavioral,
network), but only the flattened explanation string was stored, so nothing
downstream could show "rules 0.60, device 0.30, behavioral abstained" without
parsing text (which ADR-020 rejects). The AgentLog table has existed since
Week 1 as the planned per-agent audit trail; this fills it, one row per Signal.

raw_output = {"score": float | None, "reason": str, "weight": float}
score None means the agent abstained. The weight is the fusion weight in force
when the decision was made (agents/risk_synthesis.AGENT_WEIGHTS), stored so a
later weight change cannot rewrite history.

Follows the repo convention: flush, never commit.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from agents.risk_synthesis import AGENT_WEIGHTS, RiskDecision
from db.models import AgentLog, Transaction


def log_signals(session: Session, transaction: Transaction, decision: RiskDecision) -> list[AgentLog]:
    rows = []
    for signal in decision.signals:
        row = AgentLog(
            transaction_id=transaction.transaction_id,
            agent_name=signal.agent,
            raw_output={
                "score": signal.score,
                "reason": signal.reason,
                "weight": AGENT_WEIGHTS.get(signal.agent, 1.0),
            },
            logged_at=transaction.submitted_at,  # transaction-driven time (ADR-016)
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return rows
