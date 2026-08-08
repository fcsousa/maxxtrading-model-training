from datetime import datetime

import pytest

from training.dataset_builder import DatasetPartitions
from training.label_export import LabeledTradeSample
from training.trainer import TrainingError, runs_are_reproducible, train


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


def _synthetic_partitions(n_per_class: int = 6) -> DatasetPartitions:
    train = []
    for i in range(n_per_class):
        train.append(_sample(f"win-{i}", 1))
        train.append(_sample(f"loss-{i}", 0))
    return DatasetPartitions(train=tuple(train), validation=(), holdout=())


def _synthetic_features(partitions: DatasetPartitions) -> dict[str, list[float]]:
    features: dict[str, list[float]] = {}
    for sample in partitions.train:
        base = 1.0 if sample.label == 1 else -1.0
        offset = hash(sample.id) % 5 * 0.01
        features[sample.id] = [base + offset, base * 2 + offset]
    return features


class TestMandatoryConfig:
    def test_missing_dataset_id_raises(self):
        partitions = _synthetic_partitions()
        with pytest.raises(TrainingError, match="dataset_id"):
            train(partitions, _synthetic_features(partitions), dataset_id="", seed=42)

    def test_missing_seed_raises(self):
        partitions = _synthetic_partitions()
        with pytest.raises(TrainingError, match="seed"):
            train(
                partitions,
                _synthetic_features(partitions),
                dataset_id="ds1",
                seed=None,  # type: ignore[arg-type]
            )

    def test_empty_train_partition_raises(self):
        partitions = DatasetPartitions(train=(), validation=(), holdout=())
        with pytest.raises(TrainingError, match="empty"):
            train(partitions, {}, dataset_id="ds1", seed=42)

    def test_single_class_train_partition_raises(self):
        partitions = DatasetPartitions(
            train=(_sample("a", 1), _sample("b", 1)), validation=(), holdout=()
        )
        with pytest.raises(TrainingError, match="win and loss"):
            train(partitions, _synthetic_features(partitions), dataset_id="ds1", seed=42)


class TestFeatureVectorGuard:
    def test_missing_feature_vector_raises(self):
        partitions = _synthetic_partitions()
        features = _synthetic_features(partitions)
        del features[partitions.train[0].id]

        with pytest.raises(TrainingError, match="missing feature vectors"):
            train(partitions, features, dataset_id="ds1", seed=42)


class TestProvenance:
    def test_output_records_dataset_id_seed_and_library_versions(self):
        partitions = _synthetic_partitions()

        result = train(partitions, _synthetic_features(partitions), dataset_id="ds-abc", seed=7)

        assert result.provenance.dataset_id == "ds-abc"
        assert result.provenance.seed == 7
        assert "scikit-learn" in result.provenance.library_versions
        assert "numpy" in result.provenance.library_versions

    def test_model_params_are_recorded(self):
        partitions = _synthetic_partitions()

        result = train(
            partitions,
            _synthetic_features(partitions),
            dataset_id="ds1",
            seed=1,
            model_params={"max_iter": 200},
        )

        assert result.provenance.model_params == {"max_iter": 200}

    def test_holdout_and_validation_are_never_touched(self):
        train_samples = _synthetic_partitions().train
        different_holdout_a = DatasetPartitions(
            train=train_samples, validation=(), holdout=(_sample("h1", 1),)
        )
        different_holdout_b = DatasetPartitions(
            train=train_samples, validation=(), holdout=(_sample("h2", 0),)
        )
        features = _synthetic_features(_synthetic_partitions())

        result_a = train(different_holdout_a, features, dataset_id="ds1", seed=42)
        result_b = train(different_holdout_b, features, dataset_id="ds1", seed=42)

        assert result_a.metrics == result_b.metrics


class TestReproducibility:
    def test_two_runs_same_seed_are_reproducible_within_tight_tolerance(self):
        partitions = _synthetic_partitions()
        features = _synthetic_features(partitions)

        first = train(partitions, features, dataset_id="ds1", seed=42)
        second = train(partitions, features, dataset_id="ds1", seed=42)

        assert runs_are_reproducible(first, second, tolerance=1e-9)

    def test_reproducibility_check_rejects_dataset_id_mismatch(self):
        partitions = _synthetic_partitions()
        features = _synthetic_features(partitions)

        first = train(partitions, features, dataset_id="ds1", seed=42)
        second = train(partitions, features, dataset_id="ds2", seed=42)

        assert not runs_are_reproducible(first, second, tolerance=1.0)

    def test_reproducibility_check_rejects_seed_mismatch(self):
        partitions = _synthetic_partitions()
        features = _synthetic_features(partitions)

        first = train(partitions, features, dataset_id="ds1", seed=42)
        second = train(partitions, features, dataset_id="ds1", seed=7)

        assert not runs_are_reproducible(first, second, tolerance=1.0)

    def test_reproducibility_check_rejects_diff_beyond_declared_tolerance(self):
        partitions = _synthetic_partitions()
        features = _synthetic_features(partitions)
        first = train(partitions, features, dataset_id="ds1", seed=42)
        second = train(partitions, features, dataset_id="ds1", seed=42)

        inflated_metrics = dict(second.metrics)
        inflated_metrics["train_log_loss"] += 10.0
        second_inflated = second.__class__(
            provenance=second.provenance, metrics=inflated_metrics, model=second.model
        )

        assert not runs_are_reproducible(first, second_inflated, tolerance=1e-6)
