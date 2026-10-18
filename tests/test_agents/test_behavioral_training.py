"""Training helpers (ml/train_behavioral.py): split, calibration, metrics, registration."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from agents.behavioral_features import FEATURE_COLUMNS
from agents.risk_synthesis import ALLOW_BELOW, BLOCK_AT
from db.models import ModelVersion
from ml.train_behavioral import (
    calibration_from_validation,
    chronological_split,
    evaluate,
    register_model_version,
    train_from_frame,
)


def make_frame(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({c: rng.random(n) for c in FEATURE_COLUMNS})
    df["amount"] = rng.lognormal(3.5, 1, n)
    df["TransactionDT"] = np.sort(rng.integers(0, 10_000_000, n)).astype(float)
    df["isFraud"] = (rng.random(n) < 0.02 + 0.25 * (df["amount"] > 150)).astype(int)
    df.loc[rng.random(n) < 0.3, "amt_z"] = np.nan  # missing history features are normal
    return df


def test_chronological_split_is_ordered_and_disjoint():
    train, val, test, t_val = chronological_split(make_frame())
    assert train["TransactionDT"].max() <= val["TransactionDT"].min()
    assert val["TransactionDT"].max() <= test["TransactionDT"].min()
    assert len(train) + len(val) + len(test) == 1500
    assert test["TransactionDT"].min() > t_val
    assert len(train) > len(val) and len(test) > len(val)


def test_calibration_anchors_are_increasing_and_tied_to_synthesis_thresholds():
    cal = calibration_from_validation(np.random.default_rng(1).random(5000))
    assert cal["score"] == [0.0, ALLOW_BELOW, BLOCK_AT, 1.0]
    assert all(b > a for a, b in zip(cal["p"], cal["p"][1:]))


def test_calibration_survives_tied_probabilities():
    cal = calibration_from_validation(np.full(1000, 0.1))
    assert all(b > a for a, b in zip(cal["p"], cal["p"][1:]))


def test_evaluate_reports_the_expected_fields():
    y = np.array([0] * 90 + [1] * 10)
    p = np.concatenate([np.linspace(0, 0.5, 90), np.linspace(0.5, 1, 10)])
    m = evaluate(y, p, flag_p=0.9, block_p=0.97)
    assert m["base_rate"] == pytest.approx(0.1)
    assert 0.0 <= m["pr_auc"] <= 1.0 and m["coverage"] == 1.0
    assert m["flag_recall"] > 0 and m["flag_share"] > m["block_share"]


def test_train_package_and_register(tmp_path, db_session):
    meta_path = train_from_frame(
        make_frame(), tmp_path, "t", params=dict(n_estimators=25, early_stopping_rounds=5)
    )
    meta = json.loads(meta_path.read_text())
    assert (tmp_path / "t.json").exists()
    assert meta["feature_columns"] == FEATURE_COLUMNS
    assert meta["metrics"]["coverage"] == 1.0 and meta["metrics"]["n_train"] > 0

    v1 = register_model_version(db_session, meta_path)
    v2 = register_model_version(db_session, meta_path)  # idempotent
    assert v1.model_version_id == v2.model_version_id
    assert db_session.query(ModelVersion).count() == 1
    assert v1.metrics["pr_auc"] == meta["metrics"]["pr_auc"]
    assert v1.hyperparameters["features"] == FEATURE_COLUMNS
