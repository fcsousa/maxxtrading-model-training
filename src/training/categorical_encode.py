"""Train-fit categorical encoding for challenger-quality (CQ-05, CQ-06).

Fits sklearn ``OneHotEncoder(handle_unknown='ignore', sparse_output=False)``
on TRAIN rows only for ``trend_regime`` / ``volatility_regime``. Samples
missing a required categorical value are excluded (skip ids returned) —
never imputed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from sklearn.preprocessing import OneHotEncoder

DEFAULT_CATEGORICAL_NAMES: tuple[str, ...] = ("trend_regime", "volatility_regime")


class CategoricalEncodeError(Exception):
    """Raised when categorical encoding cannot proceed safely."""


def _row_complete(row: Mapping[str, Any], cat_names: Sequence[str]) -> bool:
    for name in cat_names:
        if name not in row:
            return False
        value = row[name]
        if value is None:
            return False
        if isinstance(value, str) and value == "":
            return False
    return True


def _as_str_matrix(rows: Sequence[Mapping[str, Any]], cat_names: Sequence[str]) -> list[list[str]]:
    return [[str(row[name]) for name in cat_names] for row in rows]


def fit_transform_categoricals(
    train_rows: Sequence[Mapping[str, Any]],
    *,
    sample_ids: Sequence[str],
    cat_names: Sequence[str] = DEFAULT_CATEGORICAL_NAMES,
) -> tuple[OneHotEncoder, np.ndarray, tuple[str, ...]]:
    """Fit OneHot on complete train rows; return encoder, matrix, kept ids."""
    if len(train_rows) != len(sample_ids):
        raise CategoricalEncodeError("train_rows and sample_ids length mismatch")
    if not cat_names:
        raise CategoricalEncodeError("cat_names must not be empty")

    kept_rows: list[Mapping[str, Any]] = []
    kept_ids: list[str] = []
    for row, sample_id in zip(train_rows, sample_ids, strict=True):
        if _row_complete(row, cat_names):
            kept_rows.append(row)
            kept_ids.append(sample_id)

    if not kept_rows:
        raise CategoricalEncodeError("no train rows with complete categorical values for fit")

    categories: list[list[str]] = []
    for name in cat_names:
        unique = sorted({str(row[name]) for row in kept_rows})
        categories.append(unique)

    encoder = OneHotEncoder(
        categories=categories,
        handle_unknown="ignore",
        sparse_output=False,
    )
    matrix = encoder.fit_transform(_as_str_matrix(kept_rows, cat_names))
    return encoder, np.asarray(matrix, dtype=float), tuple(kept_ids)


def transform_categoricals(
    encoder: OneHotEncoder,
    rows: Sequence[Mapping[str, Any]],
    *,
    sample_ids: Sequence[str],
    cat_names: Sequence[str] = DEFAULT_CATEGORICAL_NAMES,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Transform rows; return matrix for complete rows and skipped sample ids."""
    if len(rows) != len(sample_ids):
        raise CategoricalEncodeError("rows and sample_ids length mismatch")

    kept_rows: list[Mapping[str, Any]] = []
    skipped: list[str] = []
    for row, sample_id in zip(rows, sample_ids, strict=True):
        if _row_complete(row, cat_names):
            kept_rows.append(row)
        else:
            skipped.append(sample_id)

    if not kept_rows:
        n_out = sum(len(cats) for cats in encoder.categories_)
        empty = np.zeros((0, n_out), dtype=float)
        return empty, tuple(skipped)

    matrix = encoder.transform(_as_str_matrix(kept_rows, cat_names))
    return np.asarray(matrix, dtype=float), tuple(skipped)
