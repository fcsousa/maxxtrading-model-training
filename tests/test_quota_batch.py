"""Unit tests for partition-quota batch selection (CQ-01, CQ-02)."""

from datetime import datetime

import pytest

from training.feature_export import PackFeatures
from training.label_export import LabeledTradeSample
from training.quota_batch import (
    QuotaBatchError,
    QuotaSpec,
    select_quota_batch,
)


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


def _pack(sample_id: str, features: dict[str, float] | None = None) -> PackFeatures:
    return PackFeatures(
        sample_id=sample_id,
        features_version="4",
        features=features if features is not None else {"ema_9": 1.0, "rsi_14": 50.0},
    )


FEATURE_ORDER = ("ema_9", "rsi_14")
TRAIN_END = datetime(2026, 2, 1)
VALIDATION_END = datetime(2026, 3, 1)
HOLDOUT_END = datetime(2026, 4, 1)


def _make_partitioned(
    *,
    n_train: int,
    n_validation: int,
    n_holdout: int,
) -> tuple[list[LabeledTradeSample], list[PackFeatures]]:
    labels = [
        *[_sample(f"t{i}", datetime(2026, 1, 1 + (i % 28))) for i in range(n_train)],
        *[_sample(f"v{i}", datetime(2026, 2, 1 + (i % 25))) for i in range(n_validation)],
        *[_sample(f"h{i}", datetime(2026, 3, 1 + (i % 28))) for i in range(n_holdout)],
    ]
    packs = [_pack(sample.id) for sample in labels]
    return labels, packs


class TestQuotaSpec:
    def test_holdout_min_below_200_raises(self) -> None:
        with pytest.raises(ValueError, match="holdout_min"):
            QuotaSpec(train_min=10, validation_min=5, holdout_min=199, n_max=50)


class TestSelectQuotaBatch:
    def test_quotas_enforced_per_partition(self) -> None:
        labels, packs = _make_partitioned(n_train=10, n_validation=5, n_holdout=210)
        quotas = QuotaSpec(train_min=3, validation_min=2, holdout_min=200, n_max=5000)

        result = select_quota_batch(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            train_end=TRAIN_END,
            validation_end=VALIDATION_END,
            holdout_end=HOLDOUT_END,
            quotas=quotas,
        )

        assert result.train_count >= 3
        assert result.validation_count >= 2
        assert result.holdout_count >= 200
        total = result.train_count + result.validation_count + result.holdout_count
        assert total == len(result.selected_sample_ids)

    def test_underfill_raises_with_sanitized_counts(self) -> None:
        labels = [
            _sample("t0", datetime(2026, 1, 10)),
            _sample("v0", datetime(2026, 2, 10)),
            _sample("h0", datetime(2026, 3, 10)),
        ]
        packs = [_pack(sample.id) for sample in labels]
        quotas = QuotaSpec(train_min=5, validation_min=5, holdout_min=200, n_max=500)

        with pytest.raises(QuotaBatchError) as exc_info:
            select_quota_batch(
                labels=labels,
                packs=packs,
                feature_order=FEATURE_ORDER,
                train_end=TRAIN_END,
                validation_end=VALIDATION_END,
                holdout_end=HOLDOUT_END,
                quotas=quotas,
            )

        message = str(exc_info.value)
        assert "password" not in message.lower()
        assert "DATABASE_URL" not in message
        assert exc_info.value.counts["train"] == 1
        assert exc_info.value.counts["validation"] == 1
        assert exc_info.value.counts["holdout"] == 1

    def test_happy_path_sizes_and_n_max_fill(self) -> None:
        labels, packs = _make_partitioned(n_train=20, n_validation=15, n_holdout=210)
        packs.append(_pack("partial", {"ema_9": 1.0}))
        labels.append(_sample("partial", datetime(2026, 1, 15)))

        quotas = QuotaSpec(train_min=5, validation_min=5, holdout_min=200, n_max=230)

        result = select_quota_batch(
            labels=labels,
            packs=packs,
            feature_order=FEATURE_ORDER,
            train_end=TRAIN_END,
            validation_end=VALIDATION_END,
            holdout_end=HOLDOUT_END,
            quotas=quotas,
        )

        assert result.train_count >= 5
        assert result.validation_count >= 5
        assert result.holdout_count >= 200
        assert len(result.selected_sample_ids) == 230
        assert "partial" not in result.selected_sample_ids

    def test_partial_packs_do_not_count_toward_quota(self) -> None:
        labels = [
            _sample("t_full", datetime(2026, 1, 10)),
            _sample("t_partial", datetime(2026, 1, 11)),
            _sample("v0", datetime(2026, 2, 10)),
            *[_sample(f"h{i}", datetime(2026, 3, 1 + (i % 28))) for i in range(200)],
        ]
        packs = [
            _pack("t_full"),
            _pack("t_partial", {"ema_9": 1.0}),
            _pack("v0"),
            *[_pack(f"h{i}") for i in range(200)],
        ]
        quotas = QuotaSpec(train_min=2, validation_min=1, holdout_min=200, n_max=500)

        with pytest.raises(QuotaBatchError) as exc_info:
            select_quota_batch(
                labels=labels,
                packs=packs,
                feature_order=FEATURE_ORDER,
                train_end=TRAIN_END,
                validation_end=VALIDATION_END,
                holdout_end=HOLDOUT_END,
                quotas=quotas,
            )

        assert exc_info.value.counts["train"] == 1
