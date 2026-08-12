"""Signed shadow-acceptance-v1 thresholds (T23) for programmatic gates.

Source of truth for humans: ``docs/shadow-acceptance.md``.
Numeric values here MUST stay identical to that document; tests assert parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DOCUMENT_VERSION: Final = "shadow-acceptance-v1"
DOCUMENT_PATH: Final = "docs/shadow-acceptance.md"
MIN_HOLDOUT_SAMPLES: Final = 200
MIN_PROBE_REQUESTS: Final = 200


@dataclass(frozen=True)
class NumericCriterion:
    criterion_id: str
    family: str
    metric: str
    operator: str
    value: float
    unit: str


# Binding rows from docs/shadow-acceptance.md §2 (APPROVED 2026-08-11).
SIGNED_CRITERIA: Final[tuple[NumericCriterion, ...]] = (
    NumericCriterion("Q1", "quality_calibration", "auc_roc", ">=", 0.55, "dimensionless"),
    NumericCriterion("Q2", "quality_calibration", "brier_score", "<=", 0.25, "dimensionless"),
    NumericCriterion("Q3", "quality_calibration", "ece", "<=", 0.10, "dimensionless"),
    NumericCriterion(
        "B1",
        "business_proxy",
        "mean_result_r_at_grade_A_delta",
        ">=",
        0.0,
        "R-multiple",
    ),
    NumericCriterion(
        "G1",
        "grade_distribution",
        "max_abs_grade_share_delta_pp",
        "<=",
        15.0,
        "percentage_points",
    ),
    NumericCriterion("L1", "latency_p95", "p95_latency_ratio_vs_baseline", "<=", 2.0, "ratio"),
    NumericCriterion("M1", "memory_rss", "rss_delta_mib", "<=", 256.0, "MiB"),
)


def criterion_by_id(criterion_id: str) -> NumericCriterion:
    for criterion in SIGNED_CRITERIA:
        if criterion.criterion_id == criterion_id:
            return criterion
    raise KeyError(f"unknown criterion_id: {criterion_id}")


def compare(operator: str, observed: float, threshold: float) -> bool:
    """Strict comparison — no rounding toward the threshold."""
    if operator == ">=":
        return observed >= threshold
    if operator == "<=":
        return observed <= threshold
    raise ValueError(f"unsupported operator: {operator}")
