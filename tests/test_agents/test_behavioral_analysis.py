"""Behavioral Analysis Agent (ADR-019): scoring, graceful abstention, pipeline wiring."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.behavioral_analysis import (
    behavioral_signal,
    map_probability,
    run_behavioral_analysis,
)
from agents.behavioral_features import FEATURE_COLUMNS
from agents.ingestion import process_transaction
from agents.orchestrator import run_pipeline
from ml.train_behavioral import register_model_version, train_from_frame

DAY = 86400


def make_frame(n=1500, seed=0) -> pd.DataFrame:
    # Duplicated from test_behavioral_training.py on purpose: tests/ may not be a
    # package in your repo, so test files must not import each other.
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({c: rng.random(n) for c in FEATURE_COLUMNS})
    df["amount"] = rng.lognormal(3.5, 1, n)
    df["TransactionDT"] = np.sort(rng.integers(0, 10_000_000, n)).astype(float)
    df["isFraud"] = (rng.random(n) < 0.02 + 0.25 * (df["amount"] > 150)).astype(int)
    df.loc[rng.random(n) < 0.3, "amt_z"] = np.nan
    return df


def _txn(session, dt=10 * DAY, amount=25.0, card1=1000):
    return process_transaction(
        session, card1=card1, addr1=300.0, d1=5.0 + dt / DAY, card6="credit",
        amount=amount, currency="USD", product_cd="W", transaction_dt=dt,
    )


@pytest.fixture()
def registered(tmp_path, db_session):
    meta = train_from_frame(
        make_frame(), tmp_path, "t", params=dict(n_estimators=25, early_stopping_rounds=5)
    )
    version = register_model_version(db_session, meta)
    db_session.flush()
    return version, tmp_path


# ---- probability -> risk map ----

CAL = {"p": [0.1, 0.3, 0.6, 0.9], "score": [0.0, 0.35, 0.70, 1.0]}


def test_map_hits_anchor_points_and_clips():
    assert map_probability(0.1, CAL) == 0.0
    assert map_probability(0.3, CAL) == pytest.approx(0.35)
    assert map_probability(0.6, CAL) == pytest.approx(0.70)
    assert map_probability(0.0, CAL) == 0.0 and map_probability(5.0, CAL) == 1.0


def test_map_is_monotone():
    scores = [map_probability(p / 100, CAL) for p in range(0, 101)]
    assert scores == sorted(scores)


# ---- abstention is graceful, never a crash ----

def test_abstains_when_no_model_is_registered(db_session):
    result = run_behavioral_analysis(db_session, _txn(db_session))
    assert result.abstained and "no trained model" in result.reason
    assert behavioral_signal(result).abstained


def test_abstains_when_artifact_file_is_missing(db_session, registered):
    version, tmp_path = registered
    (tmp_path / "t.json").unlink()
    result = run_behavioral_analysis(db_session, _txn(db_session))
    assert result.abstained and "artifact not found" in result.reason
    assert result.model_version_id == version.model_version_id


# ---- scoring ----

def test_scores_a_transaction_with_no_history(db_session, registered):
    version, _ = registered
    result = run_behavioral_analysis(db_session, _txn(db_session))  # first txn: history features missing
    assert not result.abstained  # ADR-019: scores everything, no cold-start abstention
    assert 0.0 <= result.risk_score <= 1.0 and 0.0 <= result.probability <= 1.0
    assert result.model_version_id == version.model_version_id
    assert behavioral_signal(result).score == result.risk_score


def test_scores_a_transaction_with_history(db_session, registered):
    for i in range(4):
        _txn(db_session, dt=10 * DAY + i * 7200)
    result = run_behavioral_analysis(db_session, _txn(db_session, dt=10 * DAY + 4 * 7200, amount=900.0))
    assert not result.abstained and 0.0 <= result.risk_score <= 1.0
    assert result.reason.startswith("model score")


# ---- wired into the pipeline ----

def test_pipeline_records_the_model_version_and_explains_it(db_session, registered):
    version, _ = registered
    out = run_pipeline(
        db_session, card1=1000, addr1=300.0, d1=5.0 + 10, card6="credit", amount=25.0,
        currency="USD", product_cd="W", transaction_dt=10 * DAY,
    )
    assessment = out["assessment"]
    assert assessment.model_version_id == version.model_version_id
    assert "behavioral" in assessment.explanation_text
    assert "abstained (no trained model" not in assessment.explanation_text
    assert 0.0 <= assessment.risk_score <= 1.0


def test_pipeline_still_works_with_no_model(db_session):
    out = run_pipeline(
        db_session, card1=1000, addr1=300.0, d1=5.0 + 10, card6="credit", amount=25.0,
        currency="USD", product_cd="W", transaction_dt=10 * DAY,
    )
    assert out["assessment"].model_version_id is None
    assert "behavioral abstained (no trained model registered)" in out["assessment"].explanation_text
