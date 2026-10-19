"""The offline fusion tool must reproduce Risk Synthesis's own fusion exactly."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.risk_synthesis import AGENT_WEIGHTS, Signal, fuse
from scripts.fusion_check import VARIANTS, fuse_with_weights, summarize

NAN = float("nan")


def _frame():
    return pd.DataFrame(
        {
            "rule_score": [0.0, 0.6, 0.76, NAN, 0.4],
            "device_score": [NAN, 0.45, 0.0, 0.15, NAN],
            "behavioral_score": [0.1, 0.35, NAN, 0.7, 1.0],
            "isFraud": [0, 0, 1, 1, 0],
        }
    )


def test_matches_risk_synthesis_fuse_row_for_row():
    df = _frame()
    expected = []
    for row in df.itertuples():
        signals = [
            Signal("rules", None if np.isnan(row.rule_score) else row.rule_score, ""),
            Signal("device", None if np.isnan(row.device_score) else row.device_score, ""),
            Signal("behavioral", None if np.isnan(row.behavioral_score) else row.behavioral_score, ""),
        ]
        expected.append(fuse(signals))
    np.testing.assert_allclose(fuse_with_weights(df, AGENT_WEIGHTS), expected)


def test_behavioral_only_ignores_rules_and_device():
    df = _frame()
    fused = fuse_with_weights(df, VARIANTS["behavioral only"])
    np.testing.assert_allclose(fused, df["behavioral_score"].fillna(0.0).to_numpy())


def test_scores_stay_in_unit_range_for_every_variant():
    for weights in VARIANTS.values():
        fused = fuse_with_weights(_frame(), weights)
        assert (fused >= 0).all() and (fused <= 1).all()


def test_summarize_reports_flag_and_block_shares():
    y = np.array([0, 0, 1, 1])
    out = summarize(y, np.array([0.0, 0.4, 0.8, 0.9]))
    assert out["flag+block %"] == pytest.approx(75.0)
    assert out["block %"] == pytest.approx(50.0)
    assert out["recall %"] == pytest.approx(100.0)
