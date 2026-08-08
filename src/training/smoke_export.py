"""Phase 1 export smoke: T6 labels + T6b run-pinned packs → soft vectorize → T7.

SELECT-only. Caps at N samples. Writes DatasetManifest only when at least
one sample vectorizes against the full numerical feature_order. Coverage
stats are always returned so pre-ponte packs can fail-closed without
shrinking feature_order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from training.dataset_builder import DatasetManifest, DatasetPartitions, build_dataset
from training.feature_export import PackFeatures, export_pack_features
from training.label_export import LabeledTradeSample, export_labeled_samples
from training.vectorize import (
    FeatureOrder,
    VectorizeCoverage,
    load_feature_order,
    vectorize_all_soft,
)


@dataclass(frozen=True)
class ExportSmokeReport:
    window_start: str
    window_end: str
    as_of: str
    n_max: int
    labels_eligible: int
    packs_succeeded: int
    batch_size: int
    coverage: VectorizeCoverage
    feature_order: tuple[str, ...]
    feature_order_source: str
    deferred_categoricals: tuple[str, ...]
    dataset_id: str | None
    manifest: DatasetManifest | None
    stop_reason: str | None
    # Attached when dataset_id is green so T8 dual-run can train without
    # re-deriving partitions. Omitted from to_sanitized_dict (vectors live
    # on coverage.vectors; neither belongs in sanitized evidence dumps).
    partitions: DatasetPartitions | None = None

    def to_sanitized_dict(self) -> dict[str, Any]:
        payload = {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "as_of": self.as_of,
            "n_max": self.n_max,
            "labels_eligible": self.labels_eligible,
            "packs_succeeded": self.packs_succeeded,
            "batch_size": self.batch_size,
            "coverage": {
                "eligible": self.coverage.eligible,
                "vectorized": self.coverage.vectorized,
                "partial": self.coverage.partial,
                "skipped": self.coverage.skipped,
                "missing_counts": self.coverage.missing_counts,
            },
            "feature_order": list(self.feature_order),
            "feature_order_source": self.feature_order_source,
            "deferred_categoricals": list(self.deferred_categoricals),
            "dataset_id": self.dataset_id,
            "stop_reason": self.stop_reason,
        }
        if self.manifest is not None:
            payload["manifest"] = {
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in asdict(self.manifest).items()
            }
        return payload


def run_export_smoke(
    engine: Engine,
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    feature_dictionary_path: Path | str,
    label_policy_ref: str,
    seed: int = 42,
    n_max: int = 100,
) -> ExportSmokeReport:
    """Run T6 → T6b → soft vectorize → T7 for a bounded smoke window."""
    feature_order = load_feature_order(feature_dictionary_path, keys="numerical")
    labels = list(
        export_labeled_samples(
            engine,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
        )
    )
    packs = list(
        export_pack_features(
            engine,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
        )
    )
    return _assemble_smoke(
        labels=labels,
        packs=packs,
        feature_order=feature_order,
        window_start=window_start,
        window_end=window_end,
        as_of=as_of,
        train_end=train_end,
        validation_end=validation_end,
        holdout_end=holdout_end,
        label_policy_ref=label_policy_ref,
        seed=seed,
        n_max=n_max,
    )


def _assemble_smoke(
    *,
    labels: Sequence[LabeledTradeSample],
    packs: Sequence[PackFeatures],
    feature_order: FeatureOrder,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    label_policy_ref: str,
    seed: int,
    n_max: int,
) -> ExportSmokeReport:
    labels_by_id = {sample.id: sample for sample in labels}
    # Prefer packs that already carry every numerical key (post-ponte); else
    # keep temporal order and cap at n_max. Never shrink feature_order.
    def pack_sort_key(pack: PackFeatures) -> tuple[datetime, str]:
        sample = labels_by_id.get(pack.sample_id)
        if sample is None:
            return (window_start, pack.sample_id)
        return (sample.entry_at, pack.sample_id)

    ordered_packs = sorted(packs, key=pack_sort_key)
    joined = [pack for pack in ordered_packs if pack.sample_id in labels_by_id]

    def is_full(pack: PackFeatures) -> bool:
        return all(name in pack.features for name in feature_order.names)

    full_first = [pack for pack in joined if is_full(pack)]
    remainder = [pack for pack in joined if not is_full(pack)]
    preferred = full_first + remainder
    batch = preferred[:n_max]

    features_by_id = {pack.sample_id: pack.features for pack in batch}
    coverage = vectorize_all_soft(features_by_id, feature_order.names)

    dataset_id: str | None = None
    manifest: DatasetManifest | None = None
    partitions: DatasetPartitions | None = None
    stop_reason: str | None = None

    if coverage.vectorized == 0:
        stop_reason = (
            "no samples with full numerical feature_order "
            f"({len(feature_order.names)} fields); "
            "pre-ponte packs fail-closed — need Nest se-fd-v1 packs or backfill"
        )
    else:
        vectorized_labels = [
            labels_by_id[sample_id]
            for sample_id in sorted(
                coverage.vectors,
                key=lambda sid: (labels_by_id[sid].entry_at, sid),
            )
        ]
        partitions, manifest = build_dataset(
            vectorized_labels,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
            train_end=train_end,
            validation_end=validation_end,
            holdout_end=holdout_end,
            label_policy_ref=label_policy_ref,
            seed=seed,
            feature_order=feature_order.names,
            feature_order_source=feature_order.source,
            deferred_categoricals=feature_order.deferred_categoricals,
        )
        dataset_id = manifest.dataset_id

    return ExportSmokeReport(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        as_of=as_of.isoformat(),
        n_max=n_max,
        labels_eligible=len(labels),
        packs_succeeded=len(packs),
        batch_size=len(batch),
        coverage=coverage,
        feature_order=feature_order.names,
        feature_order_source=feature_order.source,
        deferred_categoricals=feature_order.deferred_categoricals,
        dataset_id=dataset_id,
        manifest=manifest,
        stop_reason=stop_reason,
        partitions=partitions,
    )
