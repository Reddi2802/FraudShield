"""
Replay the seeded customers' transactions through the full LangGraph pipeline
and compare decisions to the real isFraud labels.

Run from the repo root:
    uv run python -m scripts.replay_eval

This is the first end-to-end demo AND the honest baseline: what Rule
Compliance + Device Trust alone catch before Behavioral Analysis exists.

- Uses the SAME customer sample as scripts/seed_db.py (same seed, same
  [8,150] window), replayed in TransactionDT order with transaction_dt set,
  so time gaps, UIDs and device timestamps behave exactly as in the demo.
- Runs against a throwaway in-memory database. fraud_detection.db is never
  touched, and isFraud is only read from the CSV to score the results — it
  is never given to any agent (ADR-012 / seed_db.py).
- Replay is slow-ish: Rule Compliance recomputes the global amount p99 on
  every transaction (a known item in its docstring), so expect a few
  minutes for ~22K transactions.
"""

from __future__ import annotations

import time

import pandas as pd
from passlib.hash import bcrypt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agents.ingestion as ingestion
import db.models  # noqa: F401  (registers all tables on Base.metadata)
from agents.orchestrator import run_pipeline
from db.base import Base
from scripts.seed_db import (
    MAX_TRANSACTIONS_PER_UID,
    MIN_TRANSACTIONS_PER_UID,
    N_CUSTOMERS,
    RANDOM_SEED,
    TRANSACTION_CSV,
    load_source_data,
    sample_customers,
)

# Replay creates ~1,500 placeholder customers; full-strength bcrypt per new
# customer would dominate the runtime and adds nothing to this evaluation.
ingestion.bcrypt = bcrypt.using(rounds=4)


def _clean(value):
    return None if pd.isna(value) else value


def main() -> None:
    df = load_source_data()
    subset = sample_customers(
        df, N_CUSTOMERS, RANDOM_SEED, MIN_TRANSACTIONS_PER_UID, MAX_TRANSACTIONS_PER_UID
    )
    labels = pd.read_csv(TRANSACTION_CSV, usecols=["TransactionID", "isFraud"])
    subset = subset.merge(labels, on="TransactionID", how="left").sort_values(
        ["TransactionDT", "TransactionID"]
    )

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False)()

    rows, started = [], time.time()
    for i, r in enumerate(subset.itertuples(index=False), start=1):
        out = run_pipeline(
            session,
            card1=r.card1,
            addr1=_clean(r.addr1),
            d1=_clean(r.D1),
            card6=_clean(r.card6),
            amount=float(r.TransactionAmt),
            currency="USD",
            product_cd=r.ProductCD,
            device_type=_clean(r.DeviceType),
            device_info=_clean(r.DeviceInfo),
            browser=_clean(r.id_31),
            transaction_dt=float(r.TransactionDT),
        )
        a = out["assessment"]
        rows.append({
            "decision": a.decision.value,
            "score": a.risk_score,
            "isFraud": int(r.isFraud),
            "has_device": not out["device_result"].no_device,
            "prior": out["prior_txn_count"],
        })
        if i % 2000 == 0:
            print(f"  ...{i:,}/{len(subset):,} replayed ({time.time() - started:.0f}s)")

    res = pd.DataFrame(rows)
    total_fraud = int(res["isFraud"].sum())
    print(f"\nReplayed {len(res):,} transactions, {total_fraud:,} fraud "
          f"({total_fraud / len(res):.2%} base rate).\n")

    by = res.groupby("decision").agg(txns=("isFraud", "size"), frauds=("isFraud", "sum"))
    by["share_txns"] = by["txns"] / by["txns"].sum()
    by["fraud_rate"] = by["frauds"] / by["txns"]
    by["share_fraud"] = by["frauds"] / max(total_fraud, 1)
    print(by.reindex(["allow", "flag", "block"]).round(4))

    hit = res[res["decision"].isin(["flag", "block"])]
    print(f"\nFlag+block: {len(hit) / len(res):.1%} of transactions "
          f"-> recall {hit['isFraud'].sum() / max(total_fraud, 1):.1%}, "
          f"precision {hit['isFraud'].mean() if len(hit) else float('nan'):.1%}")
    print(f"Device present on {res['has_device'].mean():.1%} of transactions; "
          f">=3 prior transactions on {(res['prior'] >= 3).mean():.1%}.")


if __name__ == "__main__":
    main()
