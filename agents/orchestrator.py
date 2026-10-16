"""
Orchestrator — LangGraph state graph (Week 4).

    ingestion -> rule_compliance -> device_trust -> risk_synthesis

State is passed between nodes as a typed dict; each node returns only the
keys it adds. Adding an agent later (Behavioral Analysis, Network
Intelligence) is one new node + one edge + one extra Signal handed to Risk
Synthesis — ADR-001's point.

WHY THE EDGES ARE SEQUENTIAL, NOT A FAN-OUT: every DB-touching node shares
ONE SQLAlchemy Session, and Sessions are not thread-safe. LangGraph runs the
branches of a fan-out in separate worker threads (verified: parallel sync
nodes land on ThreadPoolExecutor threads), so a fan-out here would have
Rule Compliance and Device Trust using the same Session concurrently. Both
agents are fast indexed queries, so the lost parallelism is negligible. A
future node that touches NO session (Behavioral Analysis scoring from an
already-loaded model) is the one place a fan-out is safe.

Follows the repo convention: nodes flush, never commit — the caller (the API
route) owns the transaction boundary, and an IngestionError raised by the
ingestion node propagates unchanged so the route can map it to a 4xx.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from agents.device_trust import DeviceTrustResult, run_device_trust
from agents.history import count_prior_transactions
from agents.ingestion import process_transaction
from agents.risk_synthesis import run_risk_synthesis
from agents.rule_compliance import RuleComplianceResult, run_rule_compliance
from db.models import RiskAssessment, Transaction


class PipelineState(TypedDict, total=False):
    payload: dict[str, Any]          # raw transaction fields (input)
    transaction: Transaction
    prior_txn_count: int
    rule_result: RuleComplianceResult
    device_result: DeviceTrustResult
    assessment: RiskAssessment       # final output


def build_graph(session: Session):
    """Compile the graph with `session` captured by the node closures."""

    def ingestion_node(state: PipelineState) -> PipelineState:
        transaction = process_transaction(session, **state["payload"])
        return {
            "transaction": transaction,
            "prior_txn_count": count_prior_transactions(session, transaction),
        }

    def rule_compliance_node(state: PipelineState) -> PipelineState:
        return {"rule_result": run_rule_compliance(session, state["transaction"])}

    def device_trust_node(state: PipelineState) -> PipelineState:
        return {"device_result": run_device_trust(session, state["transaction"])}

    def risk_synthesis_node(state: PipelineState) -> PipelineState:
        return {
            "assessment": run_risk_synthesis(
                session,
                state["transaction"],
                state["rule_result"],
                state["device_result"],
                state["prior_txn_count"],
            )
        }

    graph = StateGraph(PipelineState)
    graph.add_node("ingestion", ingestion_node)
    graph.add_node("rule_compliance", rule_compliance_node)
    graph.add_node("device_trust", device_trust_node)
    graph.add_node("risk_synthesis", risk_synthesis_node)

    graph.add_edge(START, "ingestion")
    graph.add_edge("ingestion", "rule_compliance")
    graph.add_edge("rule_compliance", "device_trust")
    graph.add_edge("device_trust", "risk_synthesis")
    graph.add_edge("risk_synthesis", END)
    return graph.compile()


def run_pipeline(session: Session, **payload: Any) -> PipelineState:
    """Run one transaction end to end. Accepts the same keyword fields as
    agents.ingestion.process_transaction. Caller commits / rolls back."""
    return build_graph(session).invoke({"payload": payload})
