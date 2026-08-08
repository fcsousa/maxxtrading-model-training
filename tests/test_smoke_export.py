"""Unit tests for Phase 1 smoke assembly (no live DB)."""

from datetime import datetime

from training.feature_export import PackFeatures
from training.label_export import LabeledTradeSample
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


def _pack(sample_id: str, features: dict[str, float]) -> PackFeatures:
    return PackFeatures(sample_id=sample_id, features_version="4", features=features)


FEATURE_ORDER = FeatureOrder(
    names=("ema_9", "rsi_14"),
    source="numerical",
    deferred_categoricals=("trend_regime",),
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
    n_max=100,
)


class TestAssembleSmoke:
    def test_stop_when_no_full_vectors(self):
        labels = [_sample("s1", datetime(2026, 1, 10))]
        packs = [_pack("s1", {"ema_9": 1.0})]  # missing rsi_14

        report = _assemble_smoke(
            labels=labels, packs=packs, feature_order=FEATURE_ORDER, **WINDOW
        )

        assert report.dataset_id is None
        assert report.stop_reason is not None
        assert report.coverage.vectorized == 0
        assert report.coverage.partial == 1
        assert report.coverage.missing_counts["rsi_14"] == 1

    def test_prefers_full_packs_and_writes_dataset_id(self):
        labels = [
            _sample("partial", datetime(2026, 1, 5)),
            _sample("full", datetime(2026, 1, 15)),
        ]
        packs = [
            _pack("partial", {"ema_9": 1.0}),
            _pack("full", {"ema_9": 2.0, "rsi_14": 55.0}),
        ]

        report = _assemble_smoke(
            labels=labels, packs=packs, feature_order=FEATURE_ORDER, **WINDOW
        )

        assert report.dataset_id is not None
        assert report.manifest is not None
        assert report.partitions is not None
        assert len(report.partitions.train) == 1
        assert "full" in report.coverage.vectors
        assert report.coverage.vectorized == 1
        assert report.manifest.feature_order_source == "numerical"
        assert report.manifest.deferred_categoricals == ("trend_regime",)
        assert report.stop_reason is None

    def test_same_inputs_yield_same_dataset_id(self):
        labels = [_sample("full", datetime(2026, 1, 15))]
        packs = [_pack("full", {"ema_9": 2.0, "rsi_14": 55.0})]

        first = _assemble_smoke(
            labels=labels, packs=packs, feature_order=FEATURE_ORDER, **WINDOW
        )
        second = _assemble_smoke(
            labels=labels, packs=packs, feature_order=FEATURE_ORDER, **WINDOW
        )

        assert first.dataset_id == second.dataset_id

    def test_n_max_caps_batch(self):
        labels = [_sample(f"s{i}", datetime(2026, 1, 1 + i)) for i in range(5)]
        packs = [_pack(f"s{i}", {"ema_9": 1.0, "rsi_14": 50.0}) for i in range(5)]

        report = _assemble_smoke(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            **{**WINDOW, "n_max": 2},
        )

        assert report.batch_size == 2
        assert report.coverage.eligible == 2
        assert report.coverage.vectorized == 2
