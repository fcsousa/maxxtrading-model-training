"""Reproducible reference trainer skeleton (T8).

Deliberately decoupled from feature sourcing: callers supply
features_by_sample_id explicitly (synthetic fixtures today; real vectors
once docs/schema-discovery.md's A* hash-match proof passes on real data —
see that file for status). This module only owns: pinning seed/config,
fitting a deterministic classifier on the dataset builder's train partition,
and recording provenance for the reproducibility check required by MLF-06.

Full "Done" (two real reproducibility runs against real features, on
authorized training resources) is structurally blocked until A* resolves
(PASS or a written FAIL with a B/C fallback) and explicit resource
authorization is granted. Unit tests here use synthetic fixtures only.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sklearn.linear_model import LogisticRegression

from training.dataset_builder import DatasetPartitions

_TRACKED_LIBRARIES = ("scikit-learn", "numpy")


class TrainingError(Exception):
    """Raised when the trainer cannot run safely with the given inputs."""


@dataclass(frozen=True)
class TrainingProvenance:
    dataset_id: str
    seed: int
    library_versions: dict[str, str]
    model_params: dict[str, Any]


@dataclass(frozen=True)
class TrainingResult:
    provenance: TrainingProvenance
    metrics: dict[str, float]
    model: LogisticRegression = field(repr=False)


def _library_versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in _TRACKED_LIBRARIES}


def train(
    partitions: DatasetPartitions,
    features_by_sample_id: Mapping[str, Sequence[float]],
    *,
    dataset_id: str,
    seed: int,
    model_params: Mapping[str, Any] | None = None,
) -> TrainingResult:
    """Fit a deterministic reference classifier on partitions.train.

    Only the train partition is used for fitting -- validation/holdout are
    never touched here (they belong to Phase 4's shadow/quality gate, out
    of scope for T8's reproducibility requirement).
    """
    if not dataset_id:
        raise TrainingError("dataset_id is mandatory")
    if seed is None:
        raise TrainingError("seed is mandatory")
    if not partitions.train:
        raise TrainingError("train partition is empty")

    missing = [s.id for s in partitions.train if s.id not in features_by_sample_id]
    if missing:
        raise TrainingError(
            f"missing feature vectors for {len(missing)} train sample(s), e.g. {missing[:5]}"
        )

    labels = {sample.label for sample in partitions.train}
    if len(labels) < 2:
        raise TrainingError("train partition must contain both win and loss labels")

    params = dict(model_params or {})
    model = LogisticRegression(random_state=seed, **params)

    x = [list(features_by_sample_id[sample.id]) for sample in partitions.train]
    y = [sample.label for sample in partitions.train]
    model.fit(x, y)

    train_log_loss = _log_loss(model, x, y)

    provenance = TrainingProvenance(
        dataset_id=dataset_id,
        seed=seed,
        library_versions=_library_versions(),
        model_params=params,
    )
    metrics = {
        "train_log_loss": train_log_loss,
        "n_iter": float(model.n_iter_[0]),
    }
    return TrainingResult(provenance=provenance, metrics=metrics, model=model)


def _log_loss(model: LogisticRegression, x: list[list[float]], y: list[int]) -> float:
    import math

    probabilities = model.predict_proba(x)
    classes = list(model.classes_)
    win_index = classes.index(1)

    total = 0.0
    for label, proba_row in zip(y, probabilities, strict=True):
        p_win = min(max(proba_row[win_index], 1e-15), 1 - 1e-15)
        p = p_win if label == 1 else 1 - p_win
        total += -math.log(p)
    return total / len(y)


def runs_are_reproducible(
    first: TrainingResult, second: TrainingResult, *, tolerance: float
) -> bool:
    """Compare two TrainingResults per MLF-06's declared numerical tolerance.

    Same dataset_id and seed are required exactly (metadata, not numeric);
    metrics common to both runs must agree within `tolerance`.
    """
    if first.provenance.dataset_id != second.provenance.dataset_id:
        return False
    if first.provenance.seed != second.provenance.seed:
        return False

    for key, value in first.metrics.items():
        if key not in second.metrics:
            return False
        if abs(value - second.metrics[key]) > tolerance:
            return False
    return True
