"""
Run the Network Intelligence batch job (ADR-024) — manually; scheduling is a
stretch item.

    uv run python -m scripts.run_network_batch

Builds the shared-device customer graph, scores every customer who shares a
device with someone, and appends NetworkRiskScore rows (latest row per customer
wins). Risk Synthesis reads those rows on every transaction, so run this after
seeding (and again whenever new device links appear).
"""

from __future__ import annotations

from sqlalchemy import func

from agents.network_intelligence import build_customer_graph, run_network_batch
from db.models import Customer
from db.session import SessionLocal, init_db


def main() -> None:
    init_db()
    with SessionLocal() as session:
        graph = build_customer_graph(session)
        n_customers = session.query(func.count(Customer.customer_id)).scalar() or 0
        written = run_network_batch(session)
        session.commit()
    print(
        f"Network graph: {graph.number_of_nodes()} of {n_customers} customers share a device "
        f"({graph.number_of_edges()} links). Wrote {written} NetworkRiskScore rows."
    )
    if written == 0:
        print("No customer shares a device, so nobody gets a network score (that is a valid result).")


if __name__ == "__main__":
    main()
