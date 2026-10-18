"""
Behavioral Analysis features — ONE definition shared by training and serving.

The eight features (ADR-019) are all computable at serving time from the
`Transaction` row, the customer's earlier transactions, and the payload:

    amount, product_cd, card6, hour,
    prior_count, amt_ratio, amt_z, secs_since_last

WHY ONE CODE PATH: training/serving skew is the classic way a fraud model
looks great offline and does nothing live. So serving does not re-implement
the history math — it builds a tiny frame (the customer's earlier
transactions plus the current one) and runs the SAME vectorized function
(`add_history_features`) the training script runs over the whole CSV, then
takes the last row. tests/test_agents/test_behavioral_features.py checks the
two paths agree row for row.

TIME-GATING (ADR-012): every history feature for a row uses only EARLIER rows
(sums are "cumulative minus self"), so nothing from the future leaks in.

Known, accepted differences:
  - Rows with an identical timestamp inside one customer are ordered by
    transaction id, so the earlier id counts as "prior" (rare).
  - `hour` is derived from seconds since REFERENCE_START, exactly as in
    training, so replay matches; for genuinely live traffic it is the real
    UTC hour (REFERENCE_START is midnight UTC).
  - card6 at serving comes from Account.account_type (the first card6 seen
    for that customer), training uses the per-row card6.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from agents.history import MIN_PRIOR_FOR_BEHAVIORAL
from agents.uid import REFERENCE_START
from db.models import Merchant, Transaction

FEATURE_COLUMNS = [
    "amount",
    "product_cd",
    "card6",
    "hour",
    "prior_count",
    "amt_ratio",
    "amt_z",
    "secs_since_last",
]

# Fixed encodings (never derived from the data, so serving can't drift).
PRODUCT_CODES = {"C": 0, "H": 1, "R": 2, "S": 3, "W": 4}
CARD6_CODES = {"credit": 0, "debit": 1}
_CARD6_OTHER = 2  # e.g. "debit or credit", "charge card"
_CARD6_MISSING = {"", "nan", "none", "unknown"}


def encode_product(value: object) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    return float(PRODUCT_CODES.get(str(value).strip().upper(), np.nan))


def encode_card6(value: object) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value).strip().lower()
    if text in _CARD6_MISSING:
        return np.nan
    return float(CARD6_CODES.get(text, _CARD6_OTHER))


def decode_product(code: float) -> str:
    for name, c in PRODUCT_CODES.items():
        if c == code:
            return name
    return "unknown"


def decode_card6(code: float) -> str:
    return {0: "credit", 1: "debit", 2: "other"}.get(int(code), "unknown")


# ---- the shared, vectorized history math ----

def add_history_features(frame: pd.DataFrame) -> pd.DataFrame:
    """
    frame needs columns: uid, time (seconds), amount, order (tiebreak id).
    Returns a copy sorted by (time, order) with prior_count, amt_ratio,
    amt_z, secs_since_last added. Every value uses only earlier rows.
    """
    df = frame.sort_values(["time", "order"], kind="stable").reset_index(drop=True)
    amt = df["amount"].astype(float)
    g = df.groupby("uid", sort=False)

    df["prior_count"] = g.cumcount().astype(float)
    n = df["prior_count"].replace(0, np.nan)
    csum = amt.groupby(df["uid"]).cumsum() - amt          # earlier rows only
    csq = (amt ** 2).groupby(df["uid"]).cumsum() - amt ** 2
    prior_mean = csum / n
    prior_std = np.sqrt((csq / n - prior_mean ** 2).clip(lower=0))

    df["amt_ratio"] = amt / prior_mean
    df["amt_z"] = np.where(
        df["prior_count"] >= MIN_PRIOR_FOR_BEHAVIORAL,
        (amt - prior_mean) / prior_std.replace(0, np.nan),
        np.nan,
    )
    df["secs_since_last"] = g["time"].diff()
    return df


# ---- training path: whole CSV at once ----

def _token(series: pd.Series) -> pd.Series:
    """Same cleaning as agents.uid.clean_component: NaN -> 'NA', floats -> ints."""
    return series.astype("Int64").astype("string").fillna("NA")


def build_training_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """
    raw columns: TransactionID, TransactionDT, TransactionAmt, ProductCD,
    card1, card6, addr1, D1 (+ anything else, e.g. isFraud, kept as-is).
    UID grouping is identical to agents.uid.compute_uid (D1n).
    """
    df = raw.copy()
    d1n = np.floor(df["TransactionDT"] / 86400 - df["D1"])
    df["uid"] = _token(df["card1"]) + "-" + _token(df["addr1"]) + "-" + _token(d1n)
    df["time"] = df["TransactionDT"].astype(float)
    df["amount"] = df["TransactionAmt"].astype(float)
    df["order"] = df["TransactionID"]

    df = add_history_features(df)
    df["product_cd"] = df["ProductCD"].map(encode_product).astype(float)
    df["card6"] = df["card6"].map(encode_card6).astype(float)
    df["hour"] = ((df["time"] // 3600) % 24).astype(float)
    return df


# ---- serving path: one transaction, from the database ----

def features_for_transaction(session: Session, transaction: Transaction) -> dict[str, float]:
    """The eight features for an already-persisted (flushed) transaction."""
    account = transaction.account
    t_cur = transaction.submitted_at

    rows = (
        session.query(Transaction.transaction_id, Transaction.submitted_at, Transaction.amount)
        .filter(
            Transaction.account_id == transaction.account_id,
            or_(
                Transaction.submitted_at < t_cur,
                and_(
                    Transaction.submitted_at == t_cur,
                    Transaction.transaction_id <= transaction.transaction_id,
                ),
            ),
        )
        .all()
    )
    frame = pd.DataFrame(
        {
            "uid": "customer",
            "time": [(r.submitted_at - REFERENCE_START).total_seconds() for r in rows],
            "amount": [float(r.amount) for r in rows],
            "order": [r.transaction_id for r in rows],
        }
    )
    featured = add_history_features(frame)
    last = featured.iloc[-1]
    assert int(last["order"]) == transaction.transaction_id  # current row is last

    merchant = session.get(Merchant, transaction.merchant_id)
    return {
        "amount": float(transaction.amount),
        "product_cd": encode_product(merchant.category if merchant else None),
        "card6": encode_card6(account.account_type),
        "hour": float((last["time"] // 3600) % 24),
        "prior_count": float(last["prior_count"]),
        "amt_ratio": float(last["amt_ratio"]),
        "amt_z": float(last["amt_z"]),
        "secs_since_last": float(last["secs_since_last"]),
    }
