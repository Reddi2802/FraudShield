"""Read the per-agent Signals persisted by agents/agent_log.py (ADR-027)."""

from __future__ import annotations

from api.schemas import SignalOut
from db.models import Transaction

AGENT_ORDER = ["rules", "device", "behavioral", "network"]


def signals_for_transaction(transaction: Transaction) -> list[SignalOut] | None:
    """The latest logged Signal per agent, in a fixed display order. None when the
    transaction never went through the pipeline (seeded history has no AgentLog)."""
    latest = {}
    for log in sorted(transaction.agent_logs, key=lambda l: l.agent_log_id):
        latest[log.agent_name] = log
    if not latest:
        return None
    ordered = sorted(latest, key=lambda a: AGENT_ORDER.index(a) if a in AGENT_ORDER else len(AGENT_ORDER))
    return [
        SignalOut(
            agent=name,
            score=latest[name].raw_output.get("score"),
            reason=latest[name].raw_output.get("reason", ""),
            weight=latest[name].raw_output.get("weight", 1.0),
        )
        for name in ordered
    ]
