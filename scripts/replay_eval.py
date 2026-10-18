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
- Includes Behavioral Analysis (ADR-019) when a model exists in ml/artifacts/
  (train with `uv run python -m ml.train_behavioral`). The model was trained on
  the EARLIEST part of the dataset, so replaying everything would partly score
  rows it trained on. The script therefore reports twice: all rows, and the
  HELD-OUT test period only (TransactionDT after the model's test cutoff) —
  the held-out table is the honest number.
- Expect roughly 10-15 minutes for ~22K transactions.
"""

from __future__ import annotations

import json
import time

import pandas as pd
from passlib.hash import bcrypt
from sklearn.metrics import average_precision_score
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agents.ingestion as ingestion
import db.models  # noqa: F401  (registers all tables on Base.metadata)
from agents.orchestrator import run_pipeline
from db.base import Base
from ml.train_behavioral import latest_meta_path, register_model_version
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

    meta_path = latest_meta_path()
    test_start_dt = None
    if meta_path is not None:
        register_model_version(session, meta_path)
        test_start_dt = json.loads(meta_path.read_text(encoding="utf-8"))["test_start_dt"]
        print(f"Using {meta_path.name}; held-out period = TransactionDT > {test_start_dt:,.0f}")
    else:
        print("WARNING: no model in ml/artifacts/ - Behavioral Analysis will abstain.")

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
            "dt": float(r.TransactionDT),
            "behavioral": not out["behavioral_result"].abstained,
        })
        if i % 2000 == 0:
            print(f"  ...{i:,}/{len(subset):,} replayed ({time.time() - started:.0f}s)")

    res = pd.DataFrame(rows)
    report(res, "ALL replayed transactions (includes rows the model trained on)")
    if test_start_dt is not None:
        report(res[res["dt"] > test_start_dt], "HELD-OUT test period only (the honest number)")


def report(res: pd.DataFrame, title: str) -> None:
    total_fraud = int(res["isFraud"].sum())
    print(f"\n=== {title} ===")
    print(f"{len(res):,} transactions, {total_fraud:,} fraud ({total_fraud / max(len(res), 1):.2%} base rate).\n")

    by = res.groupby("decision").agg(txns=("isFraud", "size"), frauds=("isFraud", "sum"))
    by["share_txns"] = by["txns"] / by["txns"].sum()
    by["fraud_rate"] = by["frauds"] / by["txns"]
    by["share_fraud"] = by["frauds"] / max(total_fraud, 1)
    print(by.reindex(["allow", "flag", "block"]).round(4))

    hit = res[res["decision"].isin(["flag", "block"])]
    precision = hit["isFraud"].mean() if len(hit) else float("nan")
    print(f"\nFlag+block: {len(hit) / max(len(res), 1):.1%} of transactions "
          f"-> recall {hit['isFraud'].sum() / max(total_fraud, 1):.1%}, precision {precision:.1%}")
    if total_fraud and total_fraud < len(res):
        ap = average_precision_score(res["isFraud"], res["score"])
        base = total_fraud / len(res)
        print(f"Fused risk score: PR-AUC {ap:.3f} (lift {ap / base:.1f}x over the {base:.2%} base rate)")
    print(f"Device present on {res['has_device'].mean():.1%} of transactions; "
          f"Behavioral scored {res['behavioral'].mean():.1%}; "
          f">=3 prior transactions on {(res['prior'] >= 3).mean():.1%}.")


if __name__ == "__main__":
    main()
