"""
Offline fusion check: do the rules and device signals help or hurt?

    uv run python -m scripts.replay_eval     # once (saves data/processed/replay_results.csv)
    uv run python -m scripts.fusion_check    # seconds, as many times as you like

Re-fuses the SAVED per-signal scores under a handful of principled weight
variants (same noisy-OR formula and the same allow/flag/block thresholds as
Risk Synthesis) and prints flag volume, precision, recall and PR-AUC for the
HELD-OUT period and for all rows. No model, database or agent is touched.

Read it with care: the held-out replay sample is small (a few hundred fraud
cases), so differences of a few points are noise. Choose between variants on
principle (does a signal with ~no measured lift deserve weight?) and record
the choice in an ADR; do NOT hunt for the single best-looking number.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from agents.risk_synthesis import AGENT_WEIGHTS, ALLOW_BELOW, BLOCK_AT
from ml.train_behavioral import latest_meta_path

RESULTS_CSV = Path("data/processed/replay_results.csv")

_SCORE_COLUMNS = (("rule_score", "rules"), ("device_score", "device"), ("behavioral_score", "behavioral"))

VARIANTS = {
    "current (rules 1.0, device 0.8)": dict(AGENT_WEIGHTS),
    "rules halved (0.5)": {**AGENT_WEIGHTS, "rules": 0.5},
    "device off": {**AGENT_WEIGHTS, "device": 0.0},
    "rules off": {**AGENT_WEIGHTS, "rules": 0.0},
    "behavioral only": {**AGENT_WEIGHTS, "rules": 0.0, "device": 0.0},
}


def fuse_with_weights(df: pd.DataFrame, weights: dict) -> np.ndarray:
    """Weighted noisy-OR over the saved per-signal scores; NaN = abstained = skipped.
    Mirrors agents.risk_synthesis.fuse exactly (tested)."""
    remaining = np.ones(len(df))
    for column, agent in _SCORE_COLUMNS:
        scores = df[column].to_numpy(dtype=float)
        remaining *= 1.0 - weights.get(agent, 1.0) * np.where(np.isnan(scores), 0.0, scores)
    return 1.0 - remaining


def summarize(y: np.ndarray, fused: np.ndarray) -> dict:
    flag = fused >= ALLOW_BELOW
    block = fused >= BLOCK_AT
    n_fraud = max(int(y.sum()), 1)
    base = y.mean()
    ap = average_precision_score(y, fused) if 0 < y.sum() < len(y) else float("nan")
    return {
        "flag+block %": 100 * flag.mean(),
        "precision %": 100 * (y[flag].mean() if flag.any() else float("nan")),
        "recall %": 100 * y[flag].sum() / n_fraud,
        "block %": 100 * block.mean(),
        "block prec %": 100 * (y[block].mean() if block.any() else float("nan")),
        "PR-AUC": ap,
        "lift": ap / base if base else float("nan"),
    }


def table(df: pd.DataFrame, title: str) -> None:
    y = df["isFraud"].to_numpy()
    print(f"\n=== {title}: {len(df):,} transactions, {int(y.sum()):,} fraud ({y.mean():.2%} base rate) ===")
    rows = {name: summarize(y, fuse_with_weights(df, w)) for name, w in VARIANTS.items()}
    print(pd.DataFrame(rows).T.round(2).to_string())


def main() -> None:
    df = pd.read_csv(RESULTS_CSV)
    stored = df["score"].to_numpy()
    rebuilt = fuse_with_weights(df, VARIANTS["current (rules 1.0, device 0.8)"])
    drift = float(np.nanmax(np.abs(stored - rebuilt)))
    print(f"Sanity: re-fused 'current' matches the stored scores (max abs diff {drift:.2e}).")
    if drift > 1e-6:
        print("WARNING: weights/thresholds in agents/risk_synthesis.py changed since the replay; rerun it.")

    meta_path = latest_meta_path()
    if meta_path is not None:
        cutoff = json.loads(meta_path.read_text(encoding="utf-8"))["test_start_dt"]
        table(df[df["dt"] > cutoff], "HELD-OUT test period (the honest number)")
    table(df, "ALL replayed rows (includes data the model trained on)")


if __name__ == "__main__":
    main()
