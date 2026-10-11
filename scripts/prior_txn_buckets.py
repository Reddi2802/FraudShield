"""
How much fraud happens on UIDs with enough prior history for Behavioral
Analysis to see?

Run from the repo root:
    uv run python -m scripts.prior_txn_buckets

For every transaction in the raw CSV, count how many EARLIER transactions
(by TransactionDT, ties broken by TransactionID) share its UID (ADR-011 as
amended: card1 + addr1 + D1n, D1n = floor(TransactionDT/86400 - D1)).
This is the same time-gated notion of history ADR-012 requires, so the
bucket a transaction lands in is exactly how much history Behavioral
Analysis would have had when scoring it.

Columns:
  share_txns  - coverage: fraction of all transactions in this bucket
  fraud_rate  - fraud rate inside the bucket
  share_fraud - fraction of ALL fraud that falls in this bucket
                (this is the number that decides whether an
                abstain-below-3-priors rule leaves Behavioral Analysis
                anything to catch)

Operates on the full raw CSV, matching how the model will be trained
(ADR-012/ADR-013), not on the 1,500-customer seeded demo DB.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TRANSACTION_CSV = Path("data/raw/train_transaction.csv")
COLUMNS = ["TransactionID", "isFraud", "TransactionDT", "card1", "addr1", "D1"]


def _token(series: pd.Series) -> pd.Series:
    """Same cleaning as agents.uid.clean_component: NaN -> 'NA', floats -> ints."""
    return series.map(lambda v: "NA" if pd.isna(v) else str(int(v)))


def main() -> None:
    df = pd.read_csv(TRANSACTION_CSV, usecols=COLUMNS)

    d1n = np.floor(df["TransactionDT"] / 86400 - df["D1"])  # NaN stays NaN -> "NA"
    df["uid"] = _token(df["card1"]) + "-" + _token(df["addr1"]) + "-" + _token(d1n)

    df = df.sort_values(["TransactionDT", "TransactionID"])
    df["prior"] = df.groupby("uid").cumcount()
    df["bucket"] = pd.cut(
        df["prior"], [-1, 0, 2, 7, np.inf], labels=["0", "1-2", "3-7", "8+"]
    )

    table = df.groupby("bucket", observed=True).agg(
        txns=("isFraud", "size"), frauds=("isFraud", "sum")
    )
    table["share_txns"] = table["txns"] / table["txns"].sum()
    table["fraud_rate"] = table["frauds"] / table["txns"]
    table["share_fraud"] = table["frauds"] / table["frauds"].sum()
    print(table.round(4))

    covered = table.loc[table.index.isin(["3-7", "8+"])]
    print(
        f"\nWith >=3 prior transactions: {covered['share_txns'].sum():.1%} of "
        f"transactions, {covered['share_fraud'].sum():.1%} of all fraud."
    )


if __name__ == "__main__":
    main()
