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
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

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

_INCLUDED_CATS_PLACEHOLDER = ("trend_regime", "volatility_regime")


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
    included = _INCLUDED_CATS_PLACEHOLDER if include_categoricals else ()

    try:
        batch = select_quota_batch(
            labels=labels,
            packs=packs,
            feature_order=feature_order.names,
            train_end=train_end,
            validation_end=validation_end,
            holdout_end=holdout_end,
            quotas=quotas,
        )
    except QuotaBatchError:
        raise

    selected_ids = set(batch.selected_sample_ids)
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

    if coverage.vectorized == 0:
        stop_reason = (
            "no samples with full numerical feature_order "
            f"({len(feature_order.names)} fields) after quota selection"
        )
    else:
        vectorized_labels = [
            labels_by_id[sample_id]
            for sample_id in sorted(
                coverage.vectors,
                key=lambda sid: (labels_by_id[sid].entry_at, sid),
            )
            if sample_id in selected_ids and sample_id in labels_by_id
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

    return QualityExportReport(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        as_of=as_of.isoformat(),
        n_max=quotas.n_max,
        labels_eligible=len(labels),
        packs_succeeded=len(packs),
        batch_size=len(batch.selected_sample_ids),
        coverage=coverage,
        feature_order=feature_order.names,
        feature_order_source=feature_order.source,
        deferred_categoricals=feature_order.deferred_categoricals,
        dataset_id=dataset_id,
        manifest=manifest,
        stop_reason=stop_reason,
        quotas=quotas,
        included_categoricals=included,
        partitions=partitions,
    )
