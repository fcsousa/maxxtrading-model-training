"""Unit tests for challenger categorical encoding (CQ-05, CQ-06)."""

import numpy as np
import pytest
from sklearn.preprocessing import OneHotEncoder

from training.categorical_encode import (
    DEFAULT_CATEGORICAL_NAMES,
    CategoricalEncodeError,
    fit_transform_categoricals,
    transform_categoricals,
)


class TestFitTransformCategoricals:
    def test_fit_on_train_only_and_transform_other_partitions(self) -> None:
        train_rows = [
            {"trend_regime": "up", "volatility_regime": "low"},
            {"trend_regime": "down", "volatility_regime": "high"},
        ]
        encoder, train_matrix, train_kept = fit_transform_categoricals(
            train_rows,
            sample_ids=("t0", "t1"),
            cat_names=DEFAULT_CATEGORICAL_NAMES,
        )
        assert isinstance(encoder, OneHotEncoder)
        assert train_matrix.shape[0] == 2
        assert train_kept == ("t0", "t1")

        val_matrix, skipped = transform_categoricals(
            encoder,
            [{"trend_regime": "up", "volatility_regime": "low"}],
            sample_ids=("v0",),
            cat_names=DEFAULT_CATEGORICAL_NAMES,
        )
        assert skipped == ()
        assert val_matrix.shape[0] == 1
        assert val_matrix.shape[1] == train_matrix.shape[1]

    def test_missing_cat_excludes_sample(self) -> None:
        train_rows = [
            {"trend_regime": "up", "volatility_regime": "low"},
            {"trend_regime": "down", "volatility_regime": "high"},
        ]
        encoder, _, _ = fit_transform_categoricals(
            train_rows,
            sample_ids=("t0", "t1"),
            cat_names=DEFAULT_CATEGORICAL_NAMES,
        )
        matrix, skipped = transform_categoricals(
            encoder,
            [
                {"trend_regime": "up", "volatility_regime": "low"},
                {"trend_regime": "up"},  # missing volatility_regime
                {"trend_regime": None, "volatility_regime": "low"},
            ],
            sample_ids=("ok", "miss_key", "miss_null"),
            cat_names=DEFAULT_CATEGORICAL_NAMES,
        )
        assert skipped == ("miss_key", "miss_null")
        assert matrix.shape[0] == 1

    def test_deterministic_category_column_order(self) -> None:
        rows_a = [
            {"trend_regime": "down", "volatility_regime": "high"},
            {"trend_regime": "up", "volatility_regime": "low"},
        ]
        rows_b = list(reversed(rows_a))
        enc_a, mat_a, _ = fit_transform_categoricals(
            rows_a, sample_ids=("a0", "a1"), cat_names=DEFAULT_CATEGORICAL_NAMES
        )
        enc_b, mat_b, _ = fit_transform_categoricals(
            rows_b, sample_ids=("b0", "b1"), cat_names=DEFAULT_CATEGORICAL_NAMES
        )
        assert list(enc_a.get_feature_names_out(DEFAULT_CATEGORICAL_NAMES)) == list(
            enc_b.get_feature_names_out(DEFAULT_CATEGORICAL_NAMES)
        )
        # Same row content (up/low) must map to the same column pattern.
        up_low_a = mat_a[[i for i, r in enumerate(rows_a) if r["trend_regime"] == "up"][0]]
        up_low_b = mat_b[[i for i, r in enumerate(rows_b) if r["trend_regime"] == "up"][0]]
        np.testing.assert_array_equal(up_low_a, up_low_b)

    def test_fit_with_no_complete_train_rows_raises(self) -> None:
        with pytest.raises(CategoricalEncodeError):
            fit_transform_categoricals(
                [{"trend_regime": "up"}],
                sample_ids=("t0",),
                cat_names=DEFAULT_CATEGORICAL_NAMES,
            )
