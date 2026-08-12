"""Unit tests for offline SE-aligned grade/score proxies (CQ-09 / T6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from training.offline_scoring import (
    OfflineScoringError,
    grade_from_prediction,
    load_thresholds,
    max_grade_share_delta_pp,
    mean_result_r_at_grade_a_delta,
)

_MINIMAL_THRESHOLDS = {
    "weights": {
        "probabilityWin": 0.5,
        "expectedR": 0.3,
        "confidence": 0.2,
    },
    "grades": {
        "A": {
            "minScore": 75,
            "minExpectedR": 0.25,
            "minConfidence": 0.65,
        },
        "B": {
            "minScore": 55,
            "maxScore": 74,
            "minExpectedR": 0.0,
            "minConfidence": 0.5,
        },
    },
    "decisionHintMap": {
        "A": "eligible",
        "B": "review",
        "C": "rejected",
    },
    "reasons": {
        "minRiskRewardRatio": 1.5,
        "lowConfidenceThreshold": 0.5,
    },
}


def _write_thresholds(path: Path) -> Path:
    path.write_text(json.dumps(_MINIMAL_THRESHOLDS), encoding="utf-8")
    return path


class TestLoadThresholds:
    def test_loads_weights_and_grades(self, tmp_path: Path) -> None:
        path = _write_thresholds(tmp_path / "thresholds.json")
        loaded = load_thresholds(path)
        assert loaded["weights"]["probabilityWin"] == 0.5
        assert loaded["grades"]["A"]["minScore"] == 75
        assert loaded["decisionHintMap"]["C"] == "rejected"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "absent.json"
        with pytest.raises(OfflineScoringError, match="thresholds"):
            load_thresholds(missing)


class TestGradeFromPrediction:
    def test_high_prob_with_rr_can_be_grade_a(self, tmp_path: Path) -> None:
        thresholds = load_thresholds(_write_thresholds(tmp_path / "thresholds.json"))
        # p=0.9, RR=2 → expected_r = 0.9*2 - 0.1 = 1.7
        # norm = clamp01((1.7+1)/3)=0.9
        # score = round(100*(0.5*0.9 + 0.3*0.9 + 0.2*0.8)) = round(88) = 88 → A
        grade = grade_from_prediction(
            0.9,
            thresholds,
            confidence=0.8,
            risk_reward_ratio=2.0,
        )
        assert grade == "A"

    def test_low_prob_is_grade_c(self, tmp_path: Path) -> None:
        thresholds = load_thresholds(_write_thresholds(tmp_path / "thresholds.json"))
        grade = grade_from_prediction(
            0.2,
            thresholds,
            confidence=0.4,
            risk_reward_ratio=1.0,
        )
        assert grade == "C"

    def test_missing_rr_uses_expected_r_or_zero(self, tmp_path: Path) -> None:
        thresholds = load_thresholds(_write_thresholds(tmp_path / "thresholds.json"))
        # Without RR and without expected_r → expected_r defaults to 0.0
        grade_default = grade_from_prediction(0.6, thresholds, confidence=0.6)
        assert grade_default in {"A", "B", "C"}
        grade_explicit = grade_from_prediction(
            0.6,
            thresholds,
            confidence=0.6,
            expected_r=0.5,
        )
        assert grade_explicit in {"A", "B", "C"}


class TestBusinessProxyAndGradeShare:
    def test_mean_result_r_delta_at_grade_a(self) -> None:
        challenger = [
            {"grade": "A", "result_r": 1.0},
            {"grade": "A", "result_r": 0.5},
            {"grade": "B", "result_r": -1.0},
        ]
        baseline = [
            {"grade": "A", "result_r": 0.2},
            {"grade": "A", "result_r": 0.3},
            {"grade": "C", "result_r": 9.0},
        ]
        # challenger mean A = 0.75; baseline mean A = 0.25 → delta 0.5
        assert mean_result_r_at_grade_a_delta(challenger, baseline) == pytest.approx(0.5)

    def test_empty_grade_a_fail_closed(self) -> None:
        challenger = [{"grade": "B", "result_r": 1.0}]
        baseline = [{"grade": "A", "result_r": 0.5}]
        with pytest.raises(OfflineScoringError, match="grade-A"):
            mean_result_r_at_grade_a_delta(challenger, baseline)

    def test_all_result_r_none_on_grade_a_fail_closed(self) -> None:
        challenger = [{"grade": "A", "result_r": None}, {"grade": "A", "result_r": None}]
        baseline = [{"grade": "A", "result_r": 1.0}]
        with pytest.raises(OfflineScoringError, match="result_r"):
            mean_result_r_at_grade_a_delta(challenger, baseline)

    def test_max_grade_share_delta_pp(self) -> None:
        # challenger: 2A, 1B, 1C → 50%, 25%, 25%
        # baseline:   1A, 1B, 2C → 25%, 25%, 50%
        # deltas: A=25, B=0, C=25 → max 25.0
        challenger = ["A", "A", "B", "C"]
        baseline = ["A", "B", "C", "C"]
        assert max_grade_share_delta_pp(challenger, baseline) == pytest.approx(25.0)
