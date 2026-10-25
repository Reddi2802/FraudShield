"""
Orchestrator — LangGraph state graph (Week 4).

    ingestion -> rule_compliance -> device_trust -> behavioral_analysis -> risk_synthesis
        -> explanation -> case_management

State is passed between nodes as a typed dict; each node returns only the
keys it adds. Adding an agent later (Behavioral Analysis, Network
Intelligence) is one new node + one edge + one extra Signal handed to Risk
Synthesis — ADR-001's point. Behavioral Analysis (ADR-019) is exactly that.

WHY THE EDGES ARE SEQUENTIAL, NOT A FAN-OUT: every DB-touching node shares
ONE SQLAlchemy Session, and Sessions are not thread-safe. LangGraph runs the
branches of a fan-out in separate worker threads (verified: parallel sync
nodes land on ThreadPoolExecutor threads), so a fan-out here would have
Rule Compliance and Device Trust using the same Session concurrently. Both
agents are fast indexed queries, so the lost parallelism is negligible. A
node that touches NO session would be the one place a fan-out is safe
(Behavioral Analysis is not one: it reads the customer's history from the
DB to build its features).

Follows the repo convention: nodes flush, never commit — the caller (the API
route) owns the transaction boundary, and an IngestionError raised by the
ingestion node propagates unchanged so the route can map it to a 4xx.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from agents.behavioral_analysis import (
    BehavioralResult,
    behavioral_signal,
    run_behavioral_analysis,
)
from agents.device_trust import DeviceTrustResult, run_device_trust
from agents.history import count_prior_transactions
from agents.ingestion import process_transaction
from agents.network_intelligence import network_signal
from agents.agent_log import log_signals
from agents.case_management import run_case_management
from agents.explanation import run_explanation
from agents.risk_synthesis import RiskDecision, run_risk_synthesis_detailed
from agents.rule_compliance import RuleComplianceResult, run_rule_compliance
from db.models import FraudCase, RiskAssessment, Transaction


class PipelineState(TypedDict, total=False):
    payload: dict[str, Any]          # raw transaction fields (input)
    transaction: Transaction
    prior_txn_count: int
    rule_result: RuleComplianceResult
    device_result: DeviceTrustResult
    behavioral_result: BehavioralResult
    risk_decision: RiskDecision      # fused score, decision and every Signal
    assessment: RiskAssessment       # the persisted RiskAssessment row
    case: FraudCase | None           # opened only for flag / block


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

    def behavioral_analysis_node(state: PipelineState) -> PipelineState:
        return {"behavioral_result": run_behavioral_analysis(session, state["transaction"])}

    def risk_synthesis_node(state: PipelineState) -> PipelineState:
        behavioral = state["behavioral_result"]
        assessment, decision = run_risk_synthesis_detailed(
            session,
            state["transaction"],
            state["rule_result"],
            state["device_result"],
            state["prior_txn_count"],
            extra_signals=[
                behavioral_signal(behavioral),
                network_signal(session, state["transaction"].account.customer_id),
            ],
            model_version_id=behavioral.model_version_id,
        )
        log_signals(session, state["transaction"], decision)  # ADR-027: per-agent audit trail
        return {"assessment": assessment, "risk_decision": decision}

    def explanation_node(state: PipelineState) -> PipelineState:
        run_explanation(
            session,
            state["assessment"],
            state["risk_decision"],
            state["rule_result"],
            state["behavioral_result"],
        )
        return {}

    def case_management_node(state: PipelineState) -> PipelineState:
        return {"case": run_case_management(session, state["transaction"], state["assessment"])}

    graph = StateGraph(PipelineState)
    graph.add_node("ingestion", ingestion_node)
    graph.add_node("rule_compliance", rule_compliance_node)
    graph.add_node("device_trust", device_trust_node)
    graph.add_node("behavioral_analysis", behavioral_analysis_node)
    graph.add_node("risk_synthesis", risk_synthesis_node)
    graph.add_node("explanation", explanation_node)
    graph.add_node("case_management", case_management_node)

    graph.add_edge(START, "ingestion")
    graph.add_edge("ingestion", "rule_compliance")
    graph.add_edge("rule_compliance", "device_trust")
    graph.add_edge("device_trust", "behavioral_analysis")
    graph.add_edge("behavioral_analysis", "risk_synthesis")
    graph.add_edge("risk_synthesis", "explanation")
    graph.add_edge("explanation", "case_management")
    graph.add_edge("case_management", END)
    return graph.compile()


def run_pipeline(session: Session, **payload: Any) -> PipelineState:
    """Run one transaction end to end. Accepts the same keyword fields as
    agents.ingestion.process_transaction. Caller commits / rolls back."""
    return build_graph(session).invoke({"payload": payload})
