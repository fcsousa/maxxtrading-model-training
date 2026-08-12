"""Partition-quota batch selection for challenger-quality datasets (CQ-01, CQ-02).

Selects full-vector packs into temporal partitions (train / validation /
holdout) meeting configurable minima, then fills up to ``n_max`` without
violating temporal membership. Fail-closed on underfill.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from training.feature_export import PackFeatures
from training.label_export import LabeledTradeSample

PartitionName = Literal["train", "validation", "holdout"]


class QuotaBatchError(Exception):
    """Raised when partition quotas cannot be met (fail-closed underfill)."""

    def __init__(self, message: str, *, counts: Mapping[str, int]) -> None:
        super().__init__(message)
        self.counts = dict(counts)


@dataclass(frozen=True)
class QuotaSpec:
    train_min: int
    validation_min: int
    holdout_min: int
    n_max: int

    def __post_init__(self) -> None:
        if self.holdout_min < 200:
            raise ValueError("holdout_min must be >= 200 (shadow-acceptance holdout floor)")
        if self.train_min < 0 or self.validation_min < 0 or self.n_max < 0:
            raise ValueError("quota mins and n_max must be non-negative")
        if self.n_max < self.train_min + self.validation_min + self.holdout_min:
            raise ValueError("n_max must be >= train_min + validation_min + holdout_min")


@dataclass(frozen=True)
class QuotaBatchResult:
    selected_sample_ids: tuple[str, ...]
    train_count: int
    validation_count: int
    holdout_count: int


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_full_vector(pack: PackFeatures, feature_order: Sequence[str]) -> bool:
    return all(name in pack.features for name in feature_order)


def _partition_for(
    entry_at: datetime,
    *,
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
) -> PartitionName | None:
    entry = _ensure_utc(entry_at)
    train_end_u = _ensure_utc(train_end)
    validation_end_u = _ensure_utc(validation_end)
    holdout_end_u = _ensure_utc(holdout_end)
    if entry >= holdout_end_u:
        return None
    if entry < train_end_u:
        return "train"
    if entry < validation_end_u:
        return "validation"
    return "holdout"


def select_quota_batch(
    *,
    labels: Sequence[LabeledTradeSample],
    packs: Sequence[PackFeatures],
    feature_order: Sequence[str],
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    quotas: QuotaSpec,
) -> QuotaBatchResult:
    """Select full-vector samples meeting per-partition mins, then fill to n_max."""
    if not feature_order:
        raise QuotaBatchError(
            "feature_order must not be empty",
            counts={"train": 0, "validation": 0, "holdout": 0},
        )

    labels_by_id = {sample.id: sample for sample in labels}
    buckets: dict[PartitionName, list[str]] = {
        "train": [],
        "validation": [],
        "holdout": [],
    }

    ordered_packs = sorted(
        packs,
        key=lambda pack: (
            _ensure_utc(labels_by_id[pack.sample_id].entry_at)
            if pack.sample_id in labels_by_id
            else datetime.min.replace(tzinfo=UTC),
            pack.sample_id,
        ),
    )

    for pack in ordered_packs:
        sample = labels_by_id.get(pack.sample_id)
        if sample is None:
            continue
        if not _is_full_vector(pack, feature_order):
            continue
        partition = _partition_for(
            sample.entry_at,
            train_end=train_end,
            validation_end=validation_end,
            holdout_end=holdout_end,
        )
        if partition is None:
            continue
        buckets[partition].append(pack.sample_id)

    available = {
        "train": len(buckets["train"]),
        "validation": len(buckets["validation"]),
        "holdout": len(buckets["holdout"]),
    }
    mins = {
        "train": quotas.train_min,
        "validation": quotas.validation_min,
        "holdout": quotas.holdout_min,
    }
    if any(available[name] < mins[name] for name in mins):
        raise QuotaBatchError(
            "partition quotas unmet: "
            f"train={available['train']}/{mins['train']}, "
            f"validation={available['validation']}/{mins['validation']}, "
            f"holdout={available['holdout']}/{mins['holdout']}",
            counts=available,
        )

    selected: list[str] = []
    selected_set: set[str] = set()
    for name in ("train", "validation", "holdout"):
        take = mins[name]
        for sample_id in buckets[name][:take]:
            selected.append(sample_id)
            selected_set.add(sample_id)

    remaining_slots = quotas.n_max - len(selected)
    if remaining_slots > 0:
        leftovers: list[str] = []
        for name in ("train", "validation", "holdout"):
            for sample_id in buckets[name][mins[name] :]:
                leftovers.append(sample_id)
        for sample_id in leftovers[:remaining_slots]:
            if sample_id not in selected_set:
                selected.append(sample_id)
                selected_set.add(sample_id)

    train_ids = set(buckets["train"])
    validation_ids = set(buckets["validation"])
    holdout_ids = set(buckets["holdout"])
    train_count = sum(1 for sid in selected if sid in train_ids)
    validation_count = sum(1 for sid in selected if sid in validation_ids)
    holdout_count = sum(1 for sid in selected if sid in holdout_ids)

    return QuotaBatchResult(
        selected_sample_ids=tuple(selected),
        train_count=train_count,
        validation_count=validation_count,
        holdout_count=holdout_count,
    )
