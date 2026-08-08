"""T8 dual-run helper: two identical train() calls on a smoke-rebuilt dataset.

Callers must supply the same dataset_id / seed / model_params for both runs.
This module does not re-export or alter feature_order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from training.dataset_builder import DatasetPartitions
from training.smoke_export import ExportSmokeReport
from training.trainer import TrainingError, TrainingResult, runs_are_reproducible, train


class DualRunError(Exception):
    """Raised when dual-run preconditions fail (id mismatch, labels, etc.)."""


@dataclass(frozen=True)
class DualRunResult:
    dataset_id: str
    seed: int
    tolerance: float
    reproducible: bool
    run1: TrainingResult
    run2: TrainingResult
    model_params: dict[str, Any]
    train_label_counts: dict[str, int]


def assert_expected_dataset_id(report: ExportSmokeReport, expected_dataset_id: str) -> str:
    """Fail closed if smoke did not yield the pinned Passo 1 dataset_id."""
    if report.stop_reason is not None or report.dataset_id is None:
        raise DualRunError(
            f"smoke did not produce dataset_id: stop_reason={report.stop_reason!r}"
        )
    if report.dataset_id != expected_dataset_id:
        raise DualRunError(
            "dataset_id mismatch: "
            f"got {report.dataset_id}, expected {expected_dataset_id}"
        )
    return report.dataset_id


def _train_label_counts(partitions: DatasetPartitions) -> dict[str, int]:
    counts = {"win": 0, "loss": 0}
    for sample in partitions.train:
        if sample.label == 1:
            counts["win"] += 1
        elif sample.label == 0:
            counts["loss"] += 1
    return counts


def run_dual_train(
    *,
    partitions: DatasetPartitions,
    features_by_sample_id: Mapping[str, Sequence[float]],
    dataset_id: str,
    seed: int,
    model_params: Mapping[str, Any] | None = None,
    tolerance: float = 1e-9,
) -> DualRunResult:
    """Train twice with identical args; return reproducibility verdict."""
    if not partitions.train:
        raise DualRunError("train partition is empty")

    label_counts = _train_label_counts(partitions)
    if label_counts["win"] == 0 or label_counts["loss"] == 0:
        raise DualRunError(
            "train partition lacks both win/loss labels: "
            f"win={label_counts['win']}, loss={label_counts['loss']}"
        )

    params = dict(model_params or {})
    try:
        run1 = train(
            partitions,
            features_by_sample_id,
            dataset_id=dataset_id,
            seed=seed,
            model_params=params,
        )
        run2 = train(
            partitions,
            features_by_sample_id,
            dataset_id=dataset_id,
            seed=seed,
            model_params=params,
        )
    except TrainingError as exc:
        raise DualRunError(str(exc)) from exc

    return DualRunResult(
        dataset_id=dataset_id,
        seed=seed,
        tolerance=tolerance,
        reproducible=runs_are_reproducible(run1, run2, tolerance=tolerance),
        run1=run1,
        run2=run2,
        model_params=params,
        train_label_counts=label_counts,
    )


def dual_train_from_smoke(
    report: ExportSmokeReport,
    *,
    expected_dataset_id: str,
    seed: int,
    model_params: Mapping[str, Any] | None = None,
    tolerance: float = 1e-9,
) -> DualRunResult:
    """Assert pinned dataset_id, then dual-train on smoke partitions+vectors."""
    dataset_id = assert_expected_dataset_id(report, expected_dataset_id)
    if report.partitions is None:
        raise DualRunError("smoke report has no partitions attached")
    if not report.coverage.vectors:
        raise DualRunError("smoke report has no feature vectors")
    return run_dual_train(
        partitions=report.partitions,
        features_by_sample_id=report.coverage.vectors,
        dataset_id=dataset_id,
        seed=seed,
        model_params=model_params,
        tolerance=tolerance,
    )
