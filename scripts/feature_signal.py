"""
How much fraud signal exists in what the pipeline can actually see?

Run from the repo root:
    uv run python -m scripts.feature_signal

Why this exists: scripts/replay_eval.py showed the rules + device pipeline has
no lift (flag+block precision ~4.2% vs a 4.43% base rate). Before building
Behavioral Analysis on the same kind of features, measure what those features
can possibly deliver.

Part 1 - single signals on the FULL dataset (time-gated per ADR-012): fraud rate
         for the things the rules look at (amount spike vs own history, rapid
         repeat, first transaction) plus ProductCD / amount / hour. lift =
         fraud_rate / base_rate; ~1.0 means the signal tells you nothing.
Part 2 - model ceiling, TIME-based split (train on the earliest 70% of
         TransactionDT, test on the latest 30% - stricter than a UID split):
           set A = features available at serving today (amount, ProductCD,
                   card6, hour, per-UID history features)
           set B = A + C1-C14, D1-D15, dist1, card4  (what an expanded API
                   payload could carry)
         A gradient-boosted model stands in for any ML agent; PR-AUC lift =
         average_precision / base_rate (1.0 == random).
Nothing here touches the database or any agent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

CSV = Path("data/raw/train_transaction.csv")
C_COLS = [f"C{i}" for i in range(1, 15)]
D_COLS = [f"D{i}" for i in range(1, 16)]
USECOLS = list(dict.fromkeys(
    ["TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "ProductCD",
     "card1", "card4", "card6", "addr1", "D1", "dist1"] + C_COLS + D_COLS
))


def _token(series: pd.Series) -> pd.Series:
    """Same cleaning as agents.uid.clean_component: NaN -> 'NA', floats -> ints."""
    return series.astype("Int64").astype("string").fillna("NA")


def load_with_history_features() -> pd.DataFrame:
    df = pd.read_csv(CSV, usecols=USECOLS)
    df = df.sort_values(["TransactionDT", "TransactionID"]).reset_index(drop=True)

    d1n = np.floor(df["TransactionDT"] / 86400 - df["D1"])
    df["uid"] = _token(df["card1"]) + "-" + _token(df["addr1"]) + "-" + _token(d1n)

    amt = df["TransactionAmt"]
    g = df.groupby("uid", sort=False)
    df["prior_count"] = g.cumcount()
    n = df["prior_count"].replace(0, np.nan)
    csum = g["TransactionAmt"].cumsum() - amt            # sums of EARLIER rows only
    csq = (amt ** 2).groupby(df["uid"]).cumsum() - amt ** 2
    df["prior_mean"] = csum / n
    prior_std = np.sqrt((csq / n - df["prior_mean"] ** 2).clip(lower=0))
    df["amt_ratio"] = amt / df["prior_mean"]
    df["amt_z"] = np.where(
        df["prior_count"] >= 3, (amt - df["prior_mean"]) / prior_std.replace(0, np.nan), np.nan
    )
    df["secs_since_last"] = g["TransactionDT"].diff()
    df["hour"] = (df["TransactionDT"] // 3600) % 24
    for col, new in [("ProductCD", "pcd"), ("card4", "card4c"), ("card6", "card6c")]:
        df[new] = df[col].astype("category").cat.codes
    return df


def lift_row(df: pd.DataFrame, mask: pd.Series, name: str, base: float) -> None:
    n = int(mask.sum())
    if n == 0:
        print(f"  {name:<46} (no rows)")
        return
    rate = df.loc[mask, "isFraud"].mean()
    print(f"  {name:<46} n={n:>7,} ({n / len(df):>5.1%})  fraud_rate={rate:>6.2%}  lift={rate / base:>4.2f}")


def part1_single_signals(df: pd.DataFrame) -> None:
    base = df["isFraud"].mean()
    print(f"\n=== Part 1: single signals (base fraud rate {base:.2%}; lift 1.0 = no information) ===")
    print(" What the rules look at:")
    lift_row(df, (df["prior_count"] >= 3) & (df["amt_ratio"] > 3), "amount > 3x own prior mean (>=3 priors)", base)
    lift_row(df, (df["prior_count"] >= 3) & (df["amt_ratio"] <= 3), "amount within 3x own prior mean (>=3 priors)", base)
    lift_row(df, df["secs_since_last"] < 3600, "repeat within 1h of previous txn", base)
    lift_row(df, df["prior_count"] == 0, "first transaction for this UID", base)
    print(" Other serving-available fields:")
    for code, grp in df.groupby("ProductCD"):
        lift_row(df, df["ProductCD"] == code, f"ProductCD = {code}", base)
    for lo, hi in [(0, 6), (6, 12), (12, 18), (18, 24)]:
        lift_row(df, (df["hour"] >= lo) & (df["hour"] < hi), f"hour of day {lo:02d}-{hi:02d}", base)
    deciles = pd.qcut(df["TransactionAmt"], 10, duplicates="drop")
    for interval in deciles.cat.categories:
        lift_row(df, deciles == interval, f"amount in {interval}", base)


def _fit_eval(df, cols, train, test, label):
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=0)
    model.fit(df.loc[train, cols], df.loc[train, "isFraud"])
    p = model.predict_proba(df.loc[test, cols])[:, 1]
    y = df.loc[test, "isFraud"].to_numpy()
    base = y.mean()
    ap = average_precision_score(y, p)
    top = np.argsort(-p)[: max(int(0.05 * len(p)), 1)]
    print(f"  {label:<34} PR-AUC={ap:.3f} (lift {ap / base:.1f}x)  ROC-AUC={roc_auc_score(y, p):.3f}  "
          f"recall in top 5% = {y[top].sum() / max(y.sum(), 1):.1%}")
    return p


def part2_model_ceiling(df: pd.DataFrame) -> None:
    cut = df["TransactionDT"].quantile(0.7)
    train, test = df["TransactionDT"] < cut, df["TransactionDT"] >= cut
    elig = test & (df["prior_count"] >= 3)
    print(f"\n=== Part 2: model ceiling, time split (train {train.sum():,} rows, test {test.sum():,}; "
          f"test base rate {df.loc[test, 'isFraud'].mean():.2%}) ===")

    set_a = ["TransactionAmt", "pcd", "card6c", "hour", "prior_count", "amt_ratio", "amt_z", "secs_since_last"]
    set_b = set_a + C_COLS + D_COLS + ["dist1", "card4c"]

    print(" All test transactions:")
    _fit_eval(df, set_a, train, test, "A: serving-available today")
    _fit_eval(df, set_b, train, test, "B: A + C/D/dist1/card4 columns")

    print(f" Only test transactions with >=3 prior UID txns ({elig.sum():,} rows, "
          f"base {df.loc[elig, 'isFraud'].mean():.2%}) - Behavioral-eligible slice:")
    for label, cols in [("A: serving-available today", set_a), ("B: A + C/D/dist1/card4 columns", set_b)]:
        model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=0)
        model.fit(df.loc[train, cols], df.loc[train, "isFraud"])
        p = model.predict_proba(df.loc[elig, cols])[:, 1]
        y = df.loc[elig, "isFraud"].to_numpy()
        ap = average_precision_score(y, p)
        print(f"  {label:<34} PR-AUC={ap:.3f} (lift {ap / y.mean():.1f}x)  ROC-AUC={roc_auc_score(y, p):.3f}")


def main() -> None:
    print("Loading train_transaction.csv and building time-gated per-UID features...")
    df = load_with_history_features()
    part1_single_signals(df)
    part2_model_ceiling(df)


if __name__ == "__main__":
    main()
