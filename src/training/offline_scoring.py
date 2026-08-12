"""Offline SE-aligned score/grade proxies for shadow B1/G1 (CQ-09).

Pure functions only — no Score Engine Python imports. Formulas mirror
``app/domain/services/scoring_policy.py`` (AD-006) + ``thresholds.json``.

When ``risk_reward_ratio`` is omitted, ``expected_r`` is taken from the
explicit ``expected_r`` argument, defaulting to ``0.0`` (documented default;
never invent RR).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class OfflineScoringError(Exception):
    """Raised when offline grades or B1/G1 proxies cannot be computed safely."""


def load_thresholds(path: Path) -> dict[str, Any]:
    """Load SE ``thresholds.json``. Fail closed if the path is missing/unreadable."""
    if not path.is_file():
        raise OfflineScoringError(f"thresholds file missing or not a file: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise OfflineScoringError(f"failed to load thresholds from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise OfflineScoringError("thresholds root must be a JSON object")
    for key in ("weights", "grades", "decisionHintMap"):
        if key not in data:
            raise OfflineScoringError(f"thresholds missing required key: {key}")
    return data


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _derive_expected_r(
    probability_win: float,
    *,
    risk_reward_ratio: float | None,
    expected_r: float | None,
) -> float:
    if risk_reward_ratio is not None:
        return float(probability_win * risk_reward_ratio - (1.0 - probability_win) * 1.0)
    if expected_r is not None:
        return float(expected_r)
    return 0.0


def compute_score(
    probability_win: float,
    thresholds: Mapping[str, Any],
    *,
    confidence: float = 0.5,
    expected_r: float,
) -> int:
    """Weighted score 0–100 aligned with SE ScoringPolicy.compute_score."""
    weights = thresholds["weights"]
    w_p = float(weights["probabilityWin"])
    w_r = float(weights["expectedR"])
    w_c = float(weights["confidence"])
    norm_expected_r = _clamp01((expected_r + 1.0) / 3.0)
    raw = w_p * probability_win + w_r * norm_expected_r + w_c * confidence
    return int(round(100 * raw))


def grade_from_prediction(
    probability_win: float,
    thresholds: Mapping[str, Any],
    *,
    confidence: float = 0.5,
    risk_reward_ratio: float | None = None,
    expected_r: float | None = None,
) -> str:
    """Return ``A``/``B``/``C`` using SE grade boundaries (C = not A and not B).

    Grade A uses strict ``expected_r > minExpectedR`` (SE AD-006). Grade B also
    requires ``minScore <= score <= maxScore``.
    """
    er = _derive_expected_r(
        probability_win,
        risk_reward_ratio=risk_reward_ratio,
        expected_r=expected_r,
    )
    score = compute_score(
        probability_win,
        thresholds,
        confidence=confidence,
        expected_r=er,
    )
    grade_a = thresholds["grades"]["A"]
    grade_b = thresholds["grades"]["B"]

    if (
        score >= int(grade_a["minScore"])
        and er > float(grade_a["minExpectedR"])
        and confidence >= float(grade_a["minConfidence"])
    ):
        return "A"
    if (
        int(grade_b["minScore"]) <= score <= int(grade_b["maxScore"])
        and er >= float(grade_b["minExpectedR"])
        and confidence >= float(grade_b["minConfidence"])
    ):
        return "B"
    return "C"


def _grade_a_result_rs(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        if row.get("grade") != "A":
            continue
        result_r = row.get("result_r")
        if result_r is None:
            continue
        values.append(float(result_r))
    return values


def mean_result_r_at_grade_a_delta(
    challenger_rows: Sequence[Mapping[str, Any]],
    baseline_rows: Sequence[Mapping[str, Any]],
) -> float:
    """B1 proxy: mean(result_r | grade=A, challenger) − mean(... baseline).

    Fail closed (raise) when either side has an empty grade-A set or all
    grade-A ``result_r`` values are None — never invent R for B1.
    """
    challenger_a = [row for row in challenger_rows if row.get("grade") == "A"]
    baseline_a = [row for row in baseline_rows if row.get("grade") == "A"]
    if not challenger_a or not baseline_a:
        raise OfflineScoringError("grade-A set empty on challenger or baseline — B1 fail-closed")

    challenger_rs = _grade_a_result_rs(challenger_rows)
    baseline_rs = _grade_a_result_rs(baseline_rows)
    if not challenger_rs or not baseline_rs:
        raise OfflineScoringError("result_r missing for all grade-A rows — B1 fail-closed")

    challenger_mean = sum(challenger_rs) / len(challenger_rs)
    baseline_mean = sum(baseline_rs) / len(baseline_rs)
    return float(challenger_mean - baseline_mean)


def _share_pp(grades: Sequence[str], label: str) -> float:
    if not grades:
        return 0.0
    count = sum(1 for grade in grades if grade == label)
    return 100.0 * count / len(grades)


def max_grade_share_delta_pp(
    challenger_grades: Sequence[str],
    baseline_grades: Sequence[str],
) -> float:
    """G1 proxy: max absolute grade-share delta across A/B/C in percentage points."""
    if not challenger_grades or not baseline_grades:
        raise OfflineScoringError("grade lists must be non-empty for G1")
    deltas = [
        abs(_share_pp(challenger_grades, label) - _share_pp(baseline_grades, label))
        for label in ("A", "B", "C")
    ]
    return float(max(deltas))
