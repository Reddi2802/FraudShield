"""
Behavioral Analysis Agent (ADR-019).

A supervised XGBoost model over the eight features in
agents/behavioral_features.py. It scores EVERY transaction — there is no
cold-start abstention (that rule, ADR-017, was written for an unsupervised
model that needs history; this model handles missing history features
natively and still has signal from product, hour and amount).

It abstains only when it genuinely cannot score: no model registered, or the
artifact file is missing. The pipeline keeps working in that case and the
explanation says so.

The model outputs a probability trained with class weighting, so it is
RANK-calibrated, not probabilistically calibrated. A piecewise-linear map,
fitted on the VALIDATION period at training time, turns it into the 0-1 risk
signal Risk Synthesis fuses: validation median -> 0.0, 95th percentile ->
the flag threshold, 99th percentile -> the block threshold, 99.9th -> 1.0.

Explanation by construction: XGBoost's per-prediction feature contributions
(`pred_contribs`) name the top drivers of each score in the reason string.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sqlalchemy.orm import Session

from agents.behavioral_features import (
    FEATURE_COLUMNS,
    decode_card6,
    decode_product,
    features_for_transaction,
)
from agents.risk_synthesis import Signal
from db.models import ModelVersion, Transaction

MODEL_TYPE = "xgboost_behavioral"
REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_DRIVER_CONTRIBUTION = 0.05  # log-odds; ignore negligible drivers

_MODEL_CACHE: dict[str, tuple] = {}  # artifact path -> (model, meta)


@dataclass
class BehavioralResult:
    transaction_id: int
    abstained: bool
    reason: str
    probability: Optional[float] = None
    risk_score: Optional[float] = None
    model_version_id: Optional[int] = None
    drivers: list = field(default_factory=list)  # [(feature, value, contribution)]


def map_probability(p: float, calibration: dict) -> float:
    """Piecewise-linear map probability -> [0, 1] risk signal (monotone)."""
    score = float(np.interp(p, calibration["p"], calibration["score"]))
    return min(max(score, 0.0), 1.0)


def _resolve(artifact_path: str) -> Path:
    path = Path(artifact_path)
    if not path.is_absolute() and not path.exists():
        path = REPO_ROOT / artifact_path
    return path


def _load(artifact_path: str):
    path = _resolve(artifact_path)
    key = str(path)
    if key not in _MODEL_CACHE:
        model = xgb.XGBClassifier()
        model.load_model(str(path))
        meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        _MODEL_CACHE[key] = (model, meta)
    return _MODEL_CACHE[key]


def _format_driver(name: str, value: float) -> str:
    if name == "product_cd":
        return f"product_cd={decode_product(value)}"
    if name == "card6":
        return f"card6={decode_card6(value)}"
    return f"{name}={value:.2f}"


def _top_drivers(model, row: pd.DataFrame, top_n: int = 2) -> list:
    contribs = model.get_booster().predict(xgb.DMatrix(row), pred_contribs=True)[0][:-1]
    ranked = sorted(zip(FEATURE_COLUMNS, contribs), key=lambda kv: kv[1], reverse=True)
    drivers = []
    for name, contribution in ranked:
        value = float(row[name].iloc[0])
        if contribution < MIN_DRIVER_CONTRIBUTION or np.isnan(value):
            continue
        drivers.append((name, value, float(contribution)))
        if len(drivers) == top_n:
            break
    return drivers


def run_behavioral_analysis(session: Session, transaction: Transaction) -> BehavioralResult:
    tid = transaction.transaction_id

    version = (
        session.query(ModelVersion)
        .filter(ModelVersion.model_type == MODEL_TYPE)
        .order_by(ModelVersion.trained_at.desc(), ModelVersion.model_version_id.desc())
        .first()
    )
    if version is None:
        return BehavioralResult(tid, True, "no trained model registered")
    if not _resolve(version.artifact_path).exists():
        return BehavioralResult(
            tid, True, f"model artifact not found ({version.artifact_path})",
            model_version_id=version.model_version_id,
        )

    model, meta = _load(version.artifact_path)
    features = features_for_transaction(session, transaction)
    row = pd.DataFrame([features])[meta.get("feature_columns", FEATURE_COLUMNS)].astype(float)

    probability = float(model.predict_proba(row)[0, 1])
    risk_score = map_probability(probability, meta["calibration"])
    drivers = _top_drivers(model, row)

    reason = f"model score {probability:.3f}"
    if drivers:
        reason += "; top drivers " + ", ".join(
            f"{_format_driver(n, v)} (+{c:.2f})" for n, v, c in drivers
        )
    return BehavioralResult(
        tid, False, reason, probability, risk_score, version.model_version_id, drivers
    )


def behavioral_signal(result: BehavioralResult) -> Signal:
    if result.abstained:
        return Signal("behavioral", None, result.reason)
    return Signal("behavioral", result.risk_score, result.reason)
