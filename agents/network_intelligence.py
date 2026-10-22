"""
Network Intelligence Agent — thin version (ADR-003, ADR-024).

Finds customers who SHARE DEVICES — the classic fraud-ring precursor — with
classical graph metrics (no GNN) and turns them into a 0-1 score.

  graph   nodes = customers; two customers are connected when the
          DeviceCustomerLink table links both of them to the same device.
          (Only device-intrinsic fingerprints can ever link two customers:
          agents/device_identity.py gives generic / missing devices a
          customer-scoped fingerprint on purpose, ADR-014.)
  metrics per customer: degree (how many OTHER customers), clustering
          coefficient (how tightly that group is interlinked), component size.
  score   min(1.0, 0.25 * degree + 0.25 * clustering). Starting-point
          constants, not tuned values; a customer with no shared device has no
          row at all, which means "no signal", never a fake 0.5.

It is a BATCH job (scripts/run_network_batch.py, run manually): each run
appends NetworkRiskScore rows and the latest row per customer wins, so history
is kept. Per-transaction scoring only READS the latest row (network_signal), so
the pipeline never waits on graph work. Scheduling it (APScheduler) is a
stretch item.

Honest expectation: in the seeded data only ~112 of 1,359 devices are shared,
so most customers will have no score. That is a property of the dataset.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

import networkx as nx
from sqlalchemy.orm import Session

from agents.risk_synthesis import Signal
from db.models import DeviceCustomerLink, NetworkRiskScore

DEGREE_WEIGHT = 0.25
CLUSTERING_WEIGHT = 0.25


def build_customer_graph(session: Session) -> nx.Graph:
    """Customers connected by shared devices. Customers who share nothing are
    not in the graph."""
    customers_by_device: dict[int, set[int]] = defaultdict(set)
    for device_id, customer_id in session.query(DeviceCustomerLink.device_id, DeviceCustomerLink.customer_id):
        customers_by_device[device_id].add(customer_id)

    graph = nx.Graph()
    for customers in customers_by_device.values():
        for a, b in combinations(sorted(customers), 2):
            graph.add_edge(a, b)
    return graph


def network_score(degree: int, clustering: float) -> float:
    return min(1.0, DEGREE_WEIGHT * degree + CLUSTERING_WEIGHT * clustering)


def compute_scores(graph: nx.Graph) -> dict[int, dict]:
    """{customer_id: {score, degree, clustering, component_size}} for every
    customer in the graph (each has degree >= 1 by construction)."""
    clustering = nx.clustering(graph)
    component_size: dict[int, int] = {}
    for component in nx.connected_components(graph):
        for node in component:
            component_size[node] = len(component)

    return {
        node: {
            "score": network_score(graph.degree(node), clustering[node]),
            "degree": graph.degree(node),
            "clustering": round(clustering[node], 4),
            "component_size": component_size[node],
        }
        for node in graph.nodes
    }


def run_network_batch(session: Session) -> int:
    """Compute scores for the whole graph and append NetworkRiskScore rows.
    Flushes, never commits (the caller owns the transaction). Returns rows written."""
    scores = compute_scores(build_customer_graph(session))
    computed_at = datetime.now(timezone.utc)
    for customer_id, metrics in scores.items():
        session.add(
            NetworkRiskScore(
                customer_id=customer_id,
                score=metrics["score"],
                graph_metrics={k: v for k, v in metrics.items() if k != "score"},
                computed_at=computed_at,
            )
        )
    session.flush()
    return len(scores)


def network_signal(session: Session, customer_id: int) -> Signal:
    """The customer's latest network score as a Signal, or an abstention when the
    batch has never scored them (no shared devices, or it has not run yet)."""
    latest = (
        session.query(NetworkRiskScore)
        .filter(NetworkRiskScore.customer_id == customer_id)
        .order_by(NetworkRiskScore.computed_at.desc(), NetworkRiskScore.network_risk_score_id.desc())
        .first()
    )
    if latest is None:
        return Signal("network", None, "no network score computed")
    degree = (latest.graph_metrics or {}).get("degree", 0)
    return Signal("network", latest.score, f"linked to {degree} other customers via shared devices")
