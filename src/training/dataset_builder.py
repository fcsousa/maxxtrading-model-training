"""Temporal dataset builder and lineage manifest (T7).

Takes T6's exported LabeledTradeSample rows (label policy already applied at
export time — see label_export.py / docs/label-policy.md) and produces
train/validation/holdout partitions with monotonic, non-overlapping time
ranges plus a deterministic lineage manifest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from training.label_export import LabeledTradeSample


class DatasetBuildError(Exception):
    """Raised when the split configuration or input samples are invalid."""


@dataclass(frozen=True)
class DatasetPartitions:
    train: tuple[LabeledTradeSample, ...]
    validation: tuple[LabeledTradeSample, ...]
    holdout: tuple[LabeledTradeSample, ...]


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    source_window_start: str
    source_window_end: str
    as_of: str
    label_policy_ref: str
    train_end: str
    validation_end: str
    holdout_end: str
    seed: int
    train_count: int
    validation_count: int
    holdout_count: int
    train_checksum: str
    validation_checksum: str
    holdout_checksum: str


def _validate_split_boundaries(
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
) -> None:
    if not (window_start < train_end < validation_end < holdout_end):
        raise DatasetBuildError(
            "split boundaries must be strictly increasing: "
            "window_start < train_end < validation_end < holdout_end"
        )
    if holdout_end > window_end:
        raise DatasetBuildError("holdout_end must not exceed window_end")
    if as_of < holdout_end:
        raise DatasetBuildError("as_of must not be before holdout_end (lookahead guard)")


def _checksum(samples: Sequence[LabeledTradeSample]) -> str:
    payload = [[sample.id, sample.label] for sample in samples]
    return _sha256_json(payload)


def _sha256_json(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_dataset(
    samples: Sequence[LabeledTradeSample],
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    label_policy_ref: str,
    seed: int,
) -> tuple[DatasetPartitions, DatasetManifest]:
    """Split samples into monotonic, non-overlapping partitions by entry_at.

    Partition boundaries are exclusive on the upper edge: a sample with
    entry_at == train_end lands in validation, not train (same convention as
    label_export.py's window_end). Any sample outside
    [window_start, holdout_end) raises DatasetBuildError — this builder
    trusts label_export.py's disposition filtering but not its own caller's
    window bookkeeping.
    """
    _validate_split_boundaries(
        window_start=window_start,
        window_end=window_end,
        as_of=as_of,
        train_end=train_end,
        validation_end=validation_end,
        holdout_end=holdout_end,
    )

    ordered = sorted(samples, key=lambda sample: (sample.entry_at, sample.id))
    train: list[LabeledTradeSample] = []
    validation: list[LabeledTradeSample] = []
    holdout: list[LabeledTradeSample] = []

    for sample in ordered:
        if sample.entry_at < window_start or sample.entry_at >= holdout_end:
            raise DatasetBuildError(f"sample '{sample.id}' entry_at is outside the dataset window")
        if sample.entry_at < train_end:
            train.append(sample)
        elif sample.entry_at < validation_end:
            validation.append(sample)
        else:
            holdout.append(sample)

    train_checksum = _checksum(train)
    validation_checksum = _checksum(validation)
    holdout_checksum = _checksum(holdout)

    manifest_payload = {
        "source_window_start": window_start.isoformat(),
        "source_window_end": window_end.isoformat(),
        "as_of": as_of.isoformat(),
        "label_policy_ref": label_policy_ref,
        "train_end": train_end.isoformat(),
        "validation_end": validation_end.isoformat(),
        "holdout_end": holdout_end.isoformat(),
        "seed": seed,
        "train_checksum": train_checksum,
        "validation_checksum": validation_checksum,
        "holdout_checksum": holdout_checksum,
    }
    dataset_id = _sha256_json(manifest_payload)

    manifest = DatasetManifest(
        dataset_id=dataset_id,
        source_window_start=manifest_payload["source_window_start"],
        source_window_end=manifest_payload["source_window_end"],
        as_of=manifest_payload["as_of"],
        label_policy_ref=label_policy_ref,
        train_end=manifest_payload["train_end"],
        validation_end=manifest_payload["validation_end"],
        holdout_end=manifest_payload["holdout_end"],
        seed=seed,
        train_count=len(train),
        validation_count=len(validation),
        holdout_count=len(holdout),
        train_checksum=train_checksum,
        validation_checksum=validation_checksum,
        holdout_checksum=holdout_checksum,
    )
    partitions = DatasetPartitions(
        train=tuple(train), validation=tuple(validation), holdout=tuple(holdout)
    )
    return partitions, manifest
