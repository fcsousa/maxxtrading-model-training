from datetime import datetime

import pytest

from training.dataset_builder import DatasetBuildError, build_dataset
from training.label_export import LabeledTradeSample

WINDOW_START = datetime(2026, 1, 1)
TRAIN_END = datetime(2026, 1, 8)
VALIDATION_END = datetime(2026, 1, 15)
HOLDOUT_END = datetime(2026, 1, 22)
WINDOW_END = datetime(2026, 1, 22)
AS_OF = datetime(2026, 1, 25)


def _sample(sample_id: str, entry_at: datetime, label: int = 1) -> LabeledTradeSample:
    return LabeledTradeSample(
        id=sample_id,
        source_type="live_order",
        entry_at=entry_at,
        exit_at=entry_at,
        symbol="BTCUSDT",
        timeframe="15m",
        side="long",
        label=label,
        entry_indicator_pack_id=None,
    )


def _build(samples, **overrides):
    params = dict(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        as_of=AS_OF,
        train_end=TRAIN_END,
        validation_end=VALIDATION_END,
        holdout_end=HOLDOUT_END,
        label_policy_ref="maxxtrading-model-training@c557216",
        seed=42,
    )
    params.update(overrides)
    return build_dataset(samples, **params)


class TestPartitionsAreMonotonicAndNonOverlapping:
    def test_samples_land_in_expected_partitions(self):
        samples = [
            _sample("a", datetime(2026, 1, 2)),
            _sample("b", datetime(2026, 1, 10)),
            _sample("c", datetime(2026, 1, 20)),
        ]

        partitions, _ = _build(samples)

        assert [s.id for s in partitions.train] == ["a"]
        assert [s.id for s in partitions.validation] == ["b"]
        assert [s.id for s in partitions.holdout] == ["c"]

    def test_partition_time_ranges_do_not_overlap(self):
        samples = [
            _sample("a", datetime(2026, 1, 2)),
            _sample("b", datetime(2026, 1, 5)),
            _sample("c", datetime(2026, 1, 10)),
            _sample("d", datetime(2026, 1, 14)),
            _sample("e", datetime(2026, 1, 20)),
        ]

        partitions, _ = _build(samples)

        assert max(s.entry_at for s in partitions.train) < min(
            s.entry_at for s in partitions.validation
        )
        assert max(s.entry_at for s in partitions.validation) < min(
            s.entry_at for s in partitions.holdout
        )


class TestBoundaryConditions:
    def test_sample_exactly_at_train_end_goes_to_validation(self):
        samples = [_sample("a", TRAIN_END)]

        partitions, _ = _build(samples)

        assert [s.id for s in partitions.validation] == ["a"]
        assert partitions.train == ()

    def test_sample_exactly_at_validation_end_goes_to_holdout(self):
        samples = [_sample("a", VALIDATION_END)]

        partitions, _ = _build(samples)

        assert [s.id for s in partitions.holdout] == ["a"]
        assert partitions.validation == ()

    def test_sample_before_window_start_raises(self):
        samples = [_sample("a", datetime(2025, 12, 31))]

        with pytest.raises(DatasetBuildError, match="outside the dataset window"):
            _build(samples)

    def test_sample_at_or_after_holdout_end_raises(self):
        samples = [_sample("a", HOLDOUT_END)]

        with pytest.raises(DatasetBuildError, match="outside the dataset window"):
            _build(samples)


class TestSplitBoundaryValidation:
    def test_non_increasing_boundaries_raise(self):
        with pytest.raises(DatasetBuildError, match="strictly increasing"):
            _build([], train_end=VALIDATION_END, validation_end=TRAIN_END)

    def test_holdout_end_beyond_window_end_raises(self):
        with pytest.raises(DatasetBuildError, match="holdout_end must not exceed"):
            _build([], holdout_end=datetime(2026, 2, 1), window_end=WINDOW_END)

    def test_as_of_before_holdout_end_raises(self):
        with pytest.raises(DatasetBuildError, match="lookahead guard"):
            _build([], as_of=datetime(2026, 1, 20))


class TestManifestContents:
    def test_manifest_records_window_label_rule_split_seed_and_checksums(self):
        samples = [_sample("a", datetime(2026, 1, 2))]

        _, manifest = _build(samples)

        assert manifest.source_window_start == WINDOW_START.isoformat()
        assert manifest.source_window_end == WINDOW_END.isoformat()
        assert manifest.as_of == AS_OF.isoformat()
        assert manifest.label_policy_ref == "maxxtrading-model-training@c557216"
        assert manifest.train_end == TRAIN_END.isoformat()
        assert manifest.validation_end == VALIDATION_END.isoformat()
        assert manifest.holdout_end == HOLDOUT_END.isoformat()
        assert manifest.seed == 42
        assert manifest.train_count == 1
        assert manifest.validation_count == 0
        assert manifest.holdout_count == 0
        assert len(manifest.train_checksum) == 64
        assert len(manifest.validation_checksum) == 64
        assert len(manifest.holdout_checksum) == 64

    def test_empty_samples_produce_empty_partitions_and_valid_manifest(self):
        partitions, manifest = _build([])

        assert partitions.train == ()
        assert partitions.validation == ()
        assert partitions.holdout == ()
        assert manifest.train_count == 0
        assert manifest.dataset_id


class TestDeterminism:
    def test_same_input_and_config_yield_same_dataset_id(self):
        samples = [_sample("a", datetime(2026, 1, 2)), _sample("b", datetime(2026, 1, 10))]

        _, manifest_1 = _build(samples)
        _, manifest_2 = _build(samples)

        assert manifest_1.dataset_id == manifest_2.dataset_id
        assert manifest_1.train_checksum == manifest_2.train_checksum

    def test_different_seed_yields_different_dataset_id(self):
        samples = [_sample("a", datetime(2026, 1, 2))]

        _, manifest_1 = _build(samples, seed=42)
        _, manifest_2 = _build(samples, seed=7)

        assert manifest_1.dataset_id != manifest_2.dataset_id

    def test_different_samples_yield_different_checksum_and_dataset_id(self):
        samples_1 = [_sample("a", datetime(2026, 1, 2), label=1)]
        samples_2 = [_sample("a", datetime(2026, 1, 2), label=0)]

        _, manifest_1 = _build(samples_1)
        _, manifest_2 = _build(samples_2)

        assert manifest_1.train_checksum != manifest_2.train_checksum
        assert manifest_1.dataset_id != manifest_2.dataset_id

    def test_input_order_does_not_affect_dataset_id(self):
        samples = [_sample("a", datetime(2026, 1, 2)), _sample("b", datetime(2026, 1, 3))]

        _, manifest_forward = _build(samples)
        _, manifest_reversed = _build(list(reversed(samples)))

        assert manifest_forward.dataset_id == manifest_reversed.dataset_id
