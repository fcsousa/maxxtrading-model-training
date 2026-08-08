"""Unit tests for T8 dual-run helper (synthetic fixtures only)."""

from datetime import datetime

import pytest

from training.dataset_builder import DatasetPartitions
from training.dual_run import DualRunError, dual_train_from_smoke, run_dual_train
from training.label_export import LabeledTradeSample
from training.smoke_export import ExportSmokeReport
from training.vectorize import VectorizeCoverage


def _sample(sample_id: str, label: int) -> LabeledTradeSample:
    return LabeledTradeSample(
        id=sample_id,
        source_type="live_order",
        entry_at=datetime(2026, 1, 1),
        exit_at=datetime(2026, 1, 1),
        symbol="BTCUSDT",
        timeframe="15m",
        side="long",
        label=label,
        entry_indicator_pack_id=None,
    )


def _partitions(n_per_class: int = 6) -> DatasetPartitions:
    train = []
    for i in range(n_per_class):
        train.append(_sample(f"win-{i}", 1))
        train.append(_sample(f"loss-{i}", 0))
    return DatasetPartitions(train=tuple(train), validation=(), holdout=())


def _features(partitions: DatasetPartitions) -> dict[str, list[float]]:
    features: dict[str, list[float]] = {}
    for sample in partitions.train:
        base = 1.0 if sample.label == 1 else -1.0
        offset = hash(sample.id) % 5 * 0.01
        features[sample.id] = [base + offset, base * 2 + offset]
    return features


class TestRunDualTrain:
    def test_two_identical_runs_are_reproducible(self):
        partitions = _partitions()
        result = run_dual_train(
            partitions=partitions,
            features_by_sample_id=_features(partitions),
            dataset_id="ds1",
            seed=42,
            tolerance=1e-9,
        )
        assert result.reproducible is True
        assert result.run1.metrics == result.run2.metrics
        assert result.train_label_counts["win"] > 0
        assert result.train_label_counts["loss"] > 0

    def test_single_class_stops(self):
        partitions = DatasetPartitions(
            train=(_sample("a", 1), _sample("b", 1)), validation=(), holdout=()
        )
        with pytest.raises(DualRunError, match="win/loss"):
            run_dual_train(
                partitions=partitions,
                features_by_sample_id=_features(partitions),
                dataset_id="ds1",
                seed=42,
            )


class TestDualTrainFromSmoke:
    def test_dataset_id_mismatch_stops(self):
        partitions = _partitions()
        features = _features(partitions)
        report = ExportSmokeReport(
            window_start="2026-01-01",
            window_end="2026-04-01",
            as_of="2026-04-01",
            n_max=100,
            labels_eligible=12,
            packs_succeeded=12,
            batch_size=12,
            coverage=VectorizeCoverage(
                eligible=12,
                vectorized=12,
                partial=0,
                skipped=0,
                missing_counts={},
                vectors=features,
            ),
            feature_order=("f1", "f2"),
            feature_order_source="numerical",
            deferred_categoricals=(),
            dataset_id="wrong-id",
            manifest=None,
            stop_reason=None,
            partitions=partitions,
        )
        with pytest.raises(DualRunError, match="dataset_id mismatch"):
            dual_train_from_smoke(report, expected_dataset_id="expected-id", seed=42)
