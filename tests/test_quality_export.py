"""Unit tests for challenger-quality export (CQ-01, CQ-03, CQ-04, CQ-05, CQ-07)."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sklearn.linear_model import LogisticRegression

from training.artifact_bundle import (
    BundleExportRequest,
    BundleProvenance,
    FeatureSchemaSpec,
    export_artifact_bundle,
    validate_artifact_bundle,
)
from training.feature_export import PackFeatures
from training.label_export import LabeledTradeSample
from training.quality_export import (
    QualityExportError,
    _assemble_quality,
    _reject_score_engine_database,
    run_quality_export,
)
from training.quota_batch import QuotaBatchError, QuotaSpec
from training.smoke_export import _assemble_smoke
from training.vectorize import FeatureOrder


def _sample(sample_id: str, entry_at: datetime, label: int = 1) -> LabeledTradeSample:
    return LabeledTradeSample(
        id=sample_id,
        source_type="historical_import",
        entry_at=entry_at,
        exit_at=entry_at,
        symbol="BTCUSDT",
        timeframe="1h",
        side="long",
        label=label,
        entry_indicator_pack_id=None,
    )


def _pack(
    sample_id: str,
    features: dict[str, float] | None = None,
    *,
    categoricals: dict[str, str] | None = None,
) -> PackFeatures:
    return PackFeatures(
        sample_id=sample_id,
        features_version="4",
        features=features if features is not None else {"ema_9": 1.0, "rsi_14": 50.0},
        categoricals=categoricals
        if categoricals is not None
        else {"trend_regime": "up", "volatility_regime": "low"},
    )


FEATURE_ORDER = FeatureOrder(
    names=("ema_9", "rsi_14"),
    source="numerical",
    deferred_categoricals=("trend_regime", "volatility_regime"),
)

WINDOW = dict(
    window_start=datetime(2026, 1, 1),
    window_end=datetime(2026, 4, 1),
    as_of=datetime(2026, 4, 1),
    train_end=datetime(2026, 2, 1),
    validation_end=datetime(2026, 3, 1),
    holdout_end=datetime(2026, 4, 1),
    label_policy_ref="docs/label-policy.md",
    seed=42,
)


def _make_partitioned(
    *, n_train: int, n_validation: int, n_holdout: int
) -> tuple[list[LabeledTradeSample], list[PackFeatures]]:
    labels = [
        *[_sample(f"t{i}", datetime(2026, 1, 1 + (i % 28))) for i in range(n_train)],
        *[_sample(f"v{i}", datetime(2026, 2, 1 + (i % 25))) for i in range(n_validation)],
        *[_sample(f"h{i}", datetime(2026, 3, 1 + (i % 28))) for i in range(n_holdout)],
    ]
    packs = [
        _pack(
            sample.id,
            categoricals={
                "trend_regime": "up" if i % 2 == 0 else "down",
                "volatility_regime": "low" if i % 3 == 0 else "high",
            },
        )
        for i, sample in enumerate(labels)
    ]
    return labels, packs


class TestAssembleQuality:
    def test_happy_path_records_quotas_and_dataset_id(self) -> None:
        labels, packs = _make_partitioned(n_train=10, n_validation=5, n_holdout=210)
        quotas = QuotaSpec(train_min=3, validation_min=2, holdout_min=200, n_max=5000)

        report = _assemble_quality(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            quotas=quotas,
            include_categoricals=True,
            **WINDOW,
        )

        assert report.dataset_id is not None
        assert report.manifest is not None
        assert report.quotas == quotas
        assert report.included_categoricals == ("trend_regime", "volatility_regime")
        assert report.partitions is not None
        assert len(report.partitions.train) >= 3
        assert len(report.partitions.holdout) >= 200
        sanitized = report.to_sanitized_dict()
        assert sanitized["quotas"]["holdout_min"] == 200
        assert sanitized["included_categoricals"] == [
            "trend_regime",
            "volatility_regime",
        ]

    def test_underfill_raises_quota_batch_error(self) -> None:
        labels, packs = _make_partitioned(n_train=1, n_validation=1, n_holdout=1)
        quotas = QuotaSpec(train_min=5, validation_min=5, holdout_min=200, n_max=500)

        with pytest.raises(QuotaBatchError):
            _assemble_quality(
                labels=labels,
                packs=packs,
                feature_order=FEATURE_ORDER,
                quotas=quotas,
                include_categoricals=False,
                **WINDOW,
            )

    def test_smoke_assemble_still_works_without_quotas(self) -> None:
        labels = [_sample("full", datetime(2026, 1, 15))]
        packs = [_pack("full")]
        report = _assemble_smoke(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            n_max=100,
            **WINDOW,
        )
        assert report.dataset_id is not None
        assert report.stop_reason is None


class TestCategoricalsInQualityExport:
    def test_deferred_empty_and_vectors_concatenated(self) -> None:
        labels, packs = _make_partitioned(n_train=10, n_validation=5, n_holdout=210)
        quotas = QuotaSpec(train_min=3, validation_min=2, holdout_min=200, n_max=5000)

        report = _assemble_quality(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            quotas=quotas,
            include_categoricals=True,
            **WINDOW,
        )

        assert report.deferred_categoricals == ()
        assert report.manifest is not None
        assert report.manifest.deferred_categoricals == ()
        assert report.encoder is not None
        assert report.feature_vectors is not None
        sample_id = next(iter(report.feature_vectors))
        # numerical-2 + one-hot cats (>2)
        assert len(report.feature_vectors[sample_id]) > 2

    def test_missing_cat_underfill_fail_closed(self) -> None:
        labels, packs = _make_partitioned(n_train=10, n_validation=5, n_holdout=210)
        # Strip cats from most holdout packs so quota fails after filter.
        packs = [
            PackFeatures(
                sample_id=pack.sample_id,
                features_version=pack.features_version,
                features=pack.features,
                categoricals={} if pack.sample_id.startswith("h") else pack.categoricals,
            )
            for pack in packs
        ]
        quotas = QuotaSpec(train_min=3, validation_min=2, holdout_min=200, n_max=5000)

        with pytest.raises(QuotaBatchError) as exc_info:
            _assemble_quality(
                labels=labels,
                packs=packs,
                feature_order=FEATURE_ORDER,
                quotas=quotas,
                include_categoricals=True,
                **WINDOW,
            )
        assert exc_info.value.counts["holdout"] == 0

    def test_encoder_bundle_validates(self, tmp_path: Path) -> None:
        labels, packs = _make_partitioned(n_train=10, n_validation=5, n_holdout=210)
        quotas = QuotaSpec(train_min=3, validation_min=2, holdout_min=200, n_max=5000)
        report = _assemble_quality(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            quotas=quotas,
            include_categoricals=True,
            **WINDOW,
        )
        assert report.encoder is not None
        assert report.feature_vectors is not None
        assert report.dataset_id is not None

        x_rows = list(report.feature_vectors.values())[:4]
        y_rows = [0, 1, 0, 1]
        model = LogisticRegression(random_state=42).fit(x_rows, y_rows)
        exported = export_artifact_bundle(
            BundleExportRequest(
                model=model,
                feature_schema=FeatureSchemaSpec(
                    features_version="feature_dictionary_v1",
                    numeric_features=("ema_9", "rsi_14"),
                    categorical_features=("trend_regime", "volatility_regime"),
                ),
                model_version="score_model_v1.0.0",
                model_name="score_model",
                algorithm="logistic_regression",
                provenance=BundleProvenance(
                    dataset_id=report.dataset_id,
                    training_commit="abc123",
                    label_policy_ref="docs/label-policy.md",
                    seed=42,
                    library_versions={"scikit-learn": "1.5.0"},
                ),
                encoder=report.encoder,
            ),
            tmp_path / "bundle",
        )
        validate_artifact_bundle(exported.output_dir)
        assert exported.encoder_sha256 is not None


class TestScoreEngineDbGuard:
    def test_rejects_score_engine_database_name(self) -> None:
        engine = MagicMock()
        engine.url = SimpleNamespace(
            database="maxxtrading-scoreengine",
            render_as_string=lambda hide_password=True: (
                "postgresql://u:***@h/maxxtrading-scoreengine"
            ),
        )
        with pytest.raises(QualityExportError, match="TRAINING_DATABASE_URL"):
            _reject_score_engine_database(engine)

    def test_run_quality_export_invokes_guard(self, tmp_path) -> None:
        fd = tmp_path / "fd.json"
        fd.write_text(
            '{"numerical": ["ema_9"], "required": ["ema_9"]}',
            encoding="utf-8",
        )
        engine = MagicMock()
        engine.url = SimpleNamespace(
            database="maxxtrading-scoreengine",
            render_as_string=lambda hide_password=True: "x/maxxtrading-scoreengine",
        )
        quotas = QuotaSpec(train_min=1, validation_min=1, holdout_min=200, n_max=500)
        with pytest.raises(QualityExportError):
            run_quality_export(
                engine,
                window_start=datetime(2026, 1, 1),
                window_end=datetime(2026, 4, 1),
                as_of=datetime(2026, 4, 1),
                train_end=datetime(2026, 2, 1),
                validation_end=datetime(2026, 3, 1),
                holdout_end=datetime(2026, 4, 1),
                feature_dictionary_path=fd,
                label_policy_ref="docs/label-policy.md",
                quotas=quotas,
            )
