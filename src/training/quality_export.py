"""Challenger-quality export with partition quotas (CQ-01, CQ-03, CQ-04).

Separate from ``smoke_export.run_export_smoke`` so T8 smoke evidence stays
reproducible. Uses ``select_quota_batch`` instead of global top-``n_max``.

Revised CQ window defaults (for real/authorized runs; unit tests pass
synthetic dates explicitly):

- Prefer keeping T8 ``window_start`` / ``window_end`` / ``holdout_end`` calendar.
- Prefer moving ``train_end`` **later** than T8's ``2025-11-01`` (e.g. toward
  mid-validation such as ``2026-01-15``) so train captures more full-vector
  packs without starving holdout ≥ 200.
- Default quotas (caller may override): train_min=800, validation_min=200,
  holdout_min=200, n_max=5000.

Never use the Score Engine ``DATABASE_URL`` — only ``TRAINING_DATABASE_URL``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from training.categorical_encode import (
    DEFAULT_CATEGORICAL_NAMES,
    fit_transform_categoricals,
    transform_categoricals,
)
from training.dataset_builder import DatasetManifest, DatasetPartitions, build_dataset
from training.feature_export import PackFeatures, export_pack_features
from training.label_export import LabeledTradeSample, export_labeled_samples
from training.quota_batch import QuotaBatchError, QuotaSpec, select_quota_batch
from training.vectorize import (
    FeatureOrder,
    VectorizeCoverage,
    load_feature_order,
    vectorize_all_soft,
)

DEFAULT_QUALITY_QUOTAS = QuotaSpec(
    train_min=800,
    validation_min=200,
    holdout_min=200,
    n_max=5000,
)

_INCLUDED_CATS = DEFAULT_CATEGORICAL_NAMES


class QualityExportError(Exception):
    """Raised when quality export cannot proceed safely."""


@dataclass(frozen=True)
class QualityExportReport:
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
    quotas: QuotaSpec
    included_categoricals: tuple[str, ...]
    partitions: DatasetPartitions | None = None
    encoder: object | None = None
    feature_vectors: dict[str, list[float]] | None = None

    def to_sanitized_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
            "quotas": {
                "train_min": self.quotas.train_min,
                "validation_min": self.quotas.validation_min,
                "holdout_min": self.quotas.holdout_min,
                "n_max": self.quotas.n_max,
            },
            "included_categoricals": list(self.included_categoricals),
        }
        if self.manifest is not None:
            payload["manifest"] = {
                key: (list(value) if isinstance(value, tuple) else value)
                for key, value in asdict(self.manifest).items()
            }
        return payload


def _reject_score_engine_database(engine: Engine) -> None:
    """Best-effort CQ-04 guard: refuse Score Engine app DB name."""
    url = getattr(engine, "url", None)
    if url is None:
        return
    database = getattr(url, "database", None)
    if database is not None and "maxxtrading-scoreengine" in str(database):
        raise QualityExportError(
            "refusing Score Engine database name; use TRAINING_DATABASE_URL only"
        )
    rendered = ""
    render = getattr(url, "render_as_string", None)
    if callable(render):
        try:
            rendered = str(render(hide_password=True))
        except TypeError:
            rendered = str(render())
    else:
        rendered = str(url)
    # Hide credentials if present in fallback string form.
    if "maxxtrading-scoreengine" in rendered.split("@")[-1]:
        raise QualityExportError(
            "refusing Score Engine database name; use TRAINING_DATABASE_URL only"
        )


def run_quality_export(
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
    quotas: QuotaSpec,
    seed: int = 42,
    include_categoricals: bool = True,
) -> QualityExportReport:
    """Export labels+packs, select by partition quotas, build dataset."""
    _reject_score_engine_database(engine)
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
    return _assemble_quality(
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
        quotas=quotas,
        include_categoricals=include_categoricals,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _partition_name(
    entry_at: datetime,
    *,
    train_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
) -> str | None:
    entry = _ensure_utc(entry_at)
    if entry >= _ensure_utc(holdout_end):
        return None
    if entry < _ensure_utc(train_end):
        return "train"
    if entry < _ensure_utc(validation_end):
        return "validation"
    return "holdout"


def _cat_row_complete(cats: dict[str, str], cat_names: Sequence[str]) -> bool:
    return all(name in cats and cats[name] for name in cat_names)


def _assemble_quality(
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
    quotas: QuotaSpec,
    include_categoricals: bool,
) -> QualityExportReport:
    included = _INCLUDED_CATS if include_categoricals else ()
    deferred: tuple[str, ...] = () if include_categoricals else feature_order.deferred_categoricals

    batch = select_quota_batch(
        labels=labels,
        packs=packs,
        feature_order=feature_order.names,
        train_end=train_end,
        validation_end=validation_end,
        holdout_end=holdout_end,
        quotas=quotas,
    )

    labels_by_id = {sample.id: sample for sample in labels}
    packs_by_id = {pack.sample_id: pack for pack in packs}
    features_by_id = {
        sample_id: packs_by_id[sample_id].features
        for sample_id in batch.selected_sample_ids
        if sample_id in packs_by_id
    }
    coverage = vectorize_all_soft(features_by_id, feature_order.names)

    dataset_id: str | None = None
    manifest: DatasetManifest | None = None
    partitions: DatasetPartitions | None = None
    stop_reason: str | None = None
    encoder: object | None = None
    feature_vectors: dict[str, list[float]] | None = None
    batch_size = len(batch.selected_sample_ids)

    if coverage.vectorized == 0:
        stop_reason = (
            "no samples with full numerical feature_order "
            f"({len(feature_order.names)} fields) after quota selection"
        )
    else:
        eligible_ids = [
            sample_id
            for sample_id in sorted(
                coverage.vectors,
                key=lambda sid: (labels_by_id[sid].entry_at, sid),
            )
            if sample_id in labels_by_id
        ]

        if include_categoricals:
            eligible_ids = [
                sample_id
                for sample_id in eligible_ids
                if sample_id in packs_by_id
                and _cat_row_complete(packs_by_id[sample_id].categoricals, included)
            ]
            counts = {"train": 0, "validation": 0, "holdout": 0}
            for sample_id in eligible_ids:
                part = _partition_name(
                    labels_by_id[sample_id].entry_at,
                    train_end=train_end,
                    validation_end=validation_end,
                    holdout_end=holdout_end,
                )
                if part is not None:
                    counts[part] += 1
            mins = {
                "train": quotas.train_min,
                "validation": quotas.validation_min,
                "holdout": quotas.holdout_min,
            }
            if any(counts[name] < mins[name] for name in mins):
                raise QuotaBatchError(
                    "partition quotas unmet after categorical filter: "
                    f"train={counts['train']}/{mins['train']}, "
                    f"validation={counts['validation']}/{mins['validation']}, "
                    f"holdout={counts['holdout']}/{mins['holdout']}",
                    counts=counts,
                )

            train_ids = [
                sample_id
                for sample_id in eligible_ids
                if _partition_name(
                    labels_by_id[sample_id].entry_at,
                    train_end=train_end,
                    validation_end=validation_end,
                    holdout_end=holdout_end,
                )
                == "train"
            ]
            train_rows = [dict(packs_by_id[sid].categoricals) for sid in train_ids]
            encoder, _, kept_train = fit_transform_categoricals(
                train_rows,
                sample_ids=tuple(train_ids),
                cat_names=included,
            )
            kept_train_set = set(kept_train)
            eligible_ids = [
                sample_id
                for sample_id in eligible_ids
                if sample_id not in train_ids or sample_id in kept_train_set
            ]

            all_rows = [dict(packs_by_id[sid].categoricals) for sid in eligible_ids]
            cat_matrix, skipped = transform_categoricals(
                encoder,
                all_rows,
                sample_ids=tuple(eligible_ids),
                cat_names=included,
            )
            if skipped:
                skip_set = set(skipped)
                eligible_ids = [sid for sid in eligible_ids if sid not in skip_set]
                # Re-transform aligned rows after skip (should be rare if pre-filtered).
                all_rows = [dict(packs_by_id[sid].categoricals) for sid in eligible_ids]
                cat_matrix, skipped = transform_categoricals(
                    encoder,
                    all_rows,
                    sample_ids=tuple(eligible_ids),
                    cat_names=included,
                )
                if skipped:
                    raise QualityExportError(
                        f"categorical transform skipped unexpected ids: {len(skipped)}"
                    )

            feature_vectors = {}
            for index, sample_id in enumerate(eligible_ids):
                numerical = coverage.vectors[sample_id]
                encoded = cat_matrix[index].tolist()
                feature_vectors[sample_id] = list(numerical) + encoded

            batch_size = len(eligible_ids)
        else:
            feature_vectors = {
                sample_id: list(coverage.vectors[sample_id]) for sample_id in eligible_ids
            }

        vectorized_labels = [labels_by_id[sample_id] for sample_id in eligible_ids]
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
            deferred_categoricals=deferred,
        )
        dataset_id = manifest.dataset_id

    return QualityExportReport(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        as_of=as_of.isoformat(),
        n_max=quotas.n_max,
        labels_eligible=len(labels),
        packs_succeeded=len(packs),
        batch_size=batch_size,
        coverage=coverage,
        feature_order=feature_order.names,
        feature_order_source=feature_order.source,
        deferred_categoricals=deferred,
        dataset_id=dataset_id,
        manifest=manifest,
        stop_reason=stop_reason,
        quotas=quotas,
        included_categoricals=included,
        partitions=partitions,
        encoder=encoder,
        feature_vectors=feature_vectors,
    )
