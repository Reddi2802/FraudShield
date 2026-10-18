"""Shared feature builder: hand-checked math, time-gating, and train/serve parity."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.behavioral_features import (
    FEATURE_COLUMNS,
    add_history_features,
    build_training_frame,
    encode_card6,
    encode_product,
    features_for_transaction,
)
from agents.ingestion import process_transaction

DAY = 86400


def test_product_encoding_is_fixed_and_tolerant():
    assert encode_product("W") == 4 and encode_product("c") == 0
    assert np.isnan(encode_product(None)) and np.isnan(encode_product("Z"))
    assert np.isnan(encode_product(float("nan")))


def test_card6_encoding():
    assert encode_card6("credit") == 0 and encode_card6("DEBIT") == 1
    assert encode_card6("charge card") == 2
    assert np.isnan(encode_card6("unknown")) and np.isnan(encode_card6(None))


def _frame(times, amounts, uid="a", order0=1):
    return pd.DataFrame(
        {"uid": uid, "time": times, "amount": amounts,
         "order": range(order0, order0 + len(times))}
    )


def test_history_features_hand_checked():
    out = add_history_features(_frame([0, 100, 200, 300], [10, 20, 30, 60]))
    assert out["prior_count"].tolist() == [0, 1, 2, 3]
    assert out["secs_since_last"].isna().tolist() == [True, False, False, False]
    assert out["secs_since_last"].iloc[3] == 100
    last = out.iloc[3]
    assert last["amt_ratio"] == pytest.approx(60 / 20)  # prior mean of 10,20,30 = 20
    assert last["amt_z"] == pytest.approx((60 - 20) / np.sqrt(200 / 3))
    assert out["amt_z"].iloc[:3].isna().all()  # z-score needs >= 3 priors


def test_customers_do_not_leak_into_each_other():
    both = pd.concat([_frame([0, 100], [10, 10], "a"), _frame([50, 150], [999, 999], "b", 10)])
    out = add_history_features(both).set_index(["uid", "order"])
    assert out.loc[("a", 2), "amt_ratio"] == pytest.approx(1.0)
    assert out.loc[("b", 11), "amt_ratio"] == pytest.approx(1.0)


def test_features_never_use_future_rows():
    base = add_history_features(_frame([0, 100, 200, 300], [10, 20, 30, 40]))
    changed = add_history_features(_frame([0, 100, 200, 300], [10, 20, 30, 40_000]))
    cols = ["prior_count", "amt_ratio", "amt_z", "secs_since_last"]
    pd.testing.assert_frame_equal(base.iloc[:3][cols], changed.iloc[:3][cols])


def test_serving_features_match_training_features_row_for_row(db_session):
    """The point of the shared builder: DB-derived serving features must equal
    the vectorized training features for the same transactions."""
    spec = [  # (card1, dt, amount, product)
        (1000, 10 * DAY, 10.0, "W"), (2000, 10 * DAY + 500, 55.0, "C"),
        (1000, 10 * DAY + 7200, 20.0, "W"), (1000, 11 * DAY, 30.0, "W"),
        (2000, 11 * DAY + 60, 5.0, "C"), (1000, 12 * DAY, 60.0, "W"),
        (1000, 12 * DAY + 90, 15.0, "H"), (2000, 13 * DAY, 80.0, "C"),
    ]
    serving, raw = {}, []
    for card1, dt, amount, product in spec:
        t = process_transaction(
            db_session, card1=card1, addr1=300.0, d1=5.0 + dt / DAY, card6="credit",
            amount=amount, currency="USD", product_cd=product, transaction_dt=dt,
        )
        serving[t.transaction_id] = features_for_transaction(db_session, t)
        raw.append(dict(
            TransactionID=t.transaction_id, TransactionDT=float(dt), TransactionAmt=amount,
            ProductCD=product, card1=card1, card6="credit", addr1=300.0, D1=5.0 + dt / DAY,
            isFraud=0,
        ))
    training = build_training_frame(pd.DataFrame(raw)).set_index("TransactionID")

    for tid, feats in serving.items():
        for col in FEATURE_COLUMNS:
            np.testing.assert_allclose(
                feats[col], training.loc[tid, col], equal_nan=True,
                err_msg=f"transaction {tid}, feature {col}",
            )
