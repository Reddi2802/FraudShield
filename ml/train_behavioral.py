"""
Train the Behavioral Analysis model (ADR-019).

    uv run python -m ml.train_behavioral                  # train + save + register
    uv run python -m ml.train_behavioral --register-only  # re-register the latest
                                                          # artifact (e.g. after
                                                          # deleting + re-seeding the DB)

What it does:
  1. Reads data/raw/train_transaction.csv (the FULL, unfiltered CSV — ADR-013
     is seeding policy only) and builds the eight time-gated features with the
     SAME function the live agent uses (agents/behavioral_features.py).
  2. Splits CHRONOLOGICALLY by TransactionDT: train earliest 55%, validation
     next 15% (early stopping + threshold selection), test the last 30%. This
     is stricter than ADR-012's UID split and is recorded as an amendment.
  3. Fits XGBoost with scale_pos_weight (no SMOTE: synthetic rows would break
     the time-gating).
  4. Fits the probability -> risk-score map on VALIDATION only, then reports
     metrics on the untouched TEST period.
  5. Saves ml/artifacts/<name>.json + <name>.meta.json (gitignored) and inserts
     a ModelVersion row in the operational DB.

isFraud is read straight from the CSV here and never stored in the DB.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score, roc_auc_score

from agents.behavioral_analysis import MODEL_TYPE
from agents.behavioral_features import FEATURE_COLUMNS, build_training_frame
from agents.risk_synthesis import ALLOW_BELOW, BLOCK_AT

CSV = Path("data/raw/train_transaction.csv")
ARTIFACT_DIR = Path("ml/artifacts")
RAW_COLUMNS = [
    "TransactionID", "isFraud", "TransactionDT", "TransactionAmt",
    "ProductCD", "card1", "card6", "addr1", "D1",
]
TRAIN_END_Q, VAL_END_Q = 0.55, 0.70

DEFAULT_PARAMS = dict(
    n_estimators=500,
    learning_rate=0.05,
    max_depth=6,
    min_child_weight=5,
    subsample=0.8,
    colsample_bytree=0.8,
    tree_method="hist",
    eval_metric="aucpr",
    early_stopping_rounds=30,
    random_state=0,
    n_jobs=-1,
)


# ---- pure helpers (unit-tested) ----

def chronological_split(df: pd.DataFrame, train_end_q=TRAIN_END_Q, val_end_q=VAL_END_Q):
    t_train = df["TransactionDT"].quantile(train_end_q)
    t_val = df["TransactionDT"].quantile(val_end_q)
    train = df[df["TransactionDT"] <= t_train]
    val = df[(df["TransactionDT"] > t_train) & (df["TransactionDT"] <= t_val)]
    test = df[df["TransactionDT"] > t_val]
    return train, val, test, float(t_val)


def calibration_from_validation(p_val: np.ndarray) -> dict:
    """Piecewise-linear map anchors (probability -> risk score), fitted on validation."""
    q = np.quantile(p_val, [0.50, 0.95, 0.99, 0.999])
    xp = np.maximum.accumulate(q)
    for i in range(1, len(xp)):  # np.interp needs strictly increasing anchors
        if xp[i] <= xp[i - 1]:
            xp[i] = xp[i - 1] + 1e-9
    return {"p": [float(x) for x in xp], "score": [0.0, ALLOW_BELOW, BLOCK_AT, 1.0]}


def evaluate(y: np.ndarray, p: np.ndarray, flag_p: float, block_p: float) -> dict:
    base = float(y.mean())
    ap = float(average_precision_score(y, p))
    metrics = {
        "n": int(len(y)),
        "base_rate": base,
        "pr_auc": ap,
        "pr_auc_lift": ap / base if base else None,
        "roc_auc": float(roc_auc_score(y, p)),
        "coverage": 1.0,
    }
    for name, thr in (("flag", flag_p), ("block", block_p)):
        hit = p >= thr
        metrics[f"{name}_share"] = float(hit.mean())
        metrics[f"{name}_precision"] = float(y[hit].mean()) if hit.any() else None
        metrics[f"{name}_recall"] = float(y[hit].sum() / max(y.sum(), 1))
    return metrics


def fit(train: pd.DataFrame, val: pd.DataFrame, params: dict | None = None) -> xgb.XGBClassifier:
    merged = {**DEFAULT_PARAMS, **(params or {})}
    pos = max(int(train["isFraud"].sum()), 1)
    neg = max(int((train["isFraud"] == 0).sum()), 1)
    merged["scale_pos_weight"] = neg / pos
    model = xgb.XGBClassifier(**merged)
    model.fit(
        train[FEATURE_COLUMNS], train["isFraud"],
        eval_set=[(val[FEATURE_COLUMNS], val["isFraud"])],
        verbose=False,
    )
    return model


def train_from_frame(
    frame: pd.DataFrame, out_dir: Path, name: str, params: dict | None = None
) -> Path:
    """Split, fit, calibrate, evaluate, save. frame needs FEATURE_COLUMNS,
    isFraud and TransactionDT. Returns the meta.json path."""
    train, val, test, test_start_dt = chronological_split(frame)
    model = fit(train, val, params)

    p_val = model.predict_proba(val[FEATURE_COLUMNS])[:, 1]
    p_test = model.predict_proba(test[FEATURE_COLUMNS])[:, 1]
    calibration = calibration_from_validation(p_val)
    flag_p, block_p = calibration["p"][1], calibration["p"][2]
    metrics = evaluate(test["isFraud"].to_numpy(), p_test, flag_p, block_p)
    metrics.update(
        n_train=int(len(train)), n_val=int(len(val)),
        best_iteration=int(getattr(model, "best_iteration", model.n_estimators)),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"{name}.json"
    model.save_model(str(artifact))
    meta = {
        "name": name,
        "model_type": MODEL_TYPE,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": FEATURE_COLUMNS,
        "calibration": calibration,
        "test_start_dt": test_start_dt,
        "split": {"train_end_q": TRAIN_END_Q, "val_end_q": VAL_END_Q},
        "hyperparameters": {
            k: v for k, v in model.get_params().items()
            if isinstance(v, (int, float, str, bool)) or v is None
        },
        "metrics": metrics,
        "artifact_path": artifact.as_posix(),
    }
    meta_path = out_dir / f"{name}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta_path


# ---- DB registration ----

def register_model_version(session, meta_path: Path):
    """Insert a ModelVersion row for the artifact described by meta_path
    (idempotent per artifact_path). Flushes; caller commits."""
    from db.models import ModelVersion

    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    existing = (
        session.query(ModelVersion).filter_by(artifact_path=meta["artifact_path"]).first()
    )
    if existing is not None:
        return existing
    version = ModelVersion(
        model_type=meta["model_type"],
        trained_at=datetime.fromisoformat(meta["trained_at"]),
        hyperparameters={**meta["hyperparameters"], "features": meta["feature_columns"]},
        metrics=meta["metrics"],
        artifact_path=meta["artifact_path"],
    )
    session.add(version)
    session.flush()
    return version


def latest_meta_path(out_dir: Path = ARTIFACT_DIR) -> Path | None:
    metas = sorted(Path(out_dir).glob("*.meta.json"), key=lambda p: p.stat().st_mtime)
    return metas[-1] if metas else None


# ---- CLI ----

def _print_metrics(m: dict) -> None:
    print(f"\nTEST period ({m['n']:,} rows, base fraud rate {m['base_rate']:.2%}):")
    print(f"  PR-AUC {m['pr_auc']:.3f}  (lift {m['pr_auc_lift']:.1f}x)   ROC-AUC {m['roc_auc']:.3f}   "
          f"coverage {m['coverage']:.0%}")
    for name in ("flag", "block"):
        prec = m[f"{name}_precision"]
        print(f"  {name:<5} (validation-chosen threshold): {m[f'{name}_share']:.1%} of transactions, "
              f"precision {prec:.1%}" if prec is not None else f"  {name}: no hits",
              f"recall {m[f'{name}_recall']:.1%}" if prec is not None else "")


def main() -> None:
    from db.session import SessionLocal, init_db

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="behavioral_v1")
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()

    init_db()
    if args.register_only:
        meta_path = ARTIFACT_DIR / f"{args.name}.meta.json"
        if not meta_path.exists():
            meta_path = latest_meta_path()
        if meta_path is None:
            raise SystemExit("No artifact found in ml/artifacts/ — train first.")
    else:
        print("Loading train_transaction.csv and building time-gated features...")
        raw = pd.read_csv(CSV, usecols=RAW_COLUMNS)
        frame = build_training_frame(raw)
        print(f"Training on {len(frame):,} rows (chronological split)...")
        meta_path = train_from_frame(frame, ARTIFACT_DIR, args.name)
        _print_metrics(json.loads(meta_path.read_text(encoding="utf-8"))["metrics"])

    with SessionLocal() as session:
        version = register_model_version(session, meta_path)
        session.commit()
        print(f"\nRegistered ModelVersion {version.model_version_id} -> {version.artifact_path}")


if __name__ == "__main__":
    main()
