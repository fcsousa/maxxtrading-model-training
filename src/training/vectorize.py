"""Vectorize named feature dicts (feature_export.py's PackFeatures.features)
into ordered vectors for trainer.train(), using the Score Engine's Feature
Dictionary as the canonical feature order.

Fixture/unit-tested only in this module -- no live DB access here.

Open question this does NOT resolve (flagged, not decided): the Feature
Dictionary's "required" list includes trend_regime/volatility_regime, which
the Score Engine's own baseline model (app/domain/services/baseline_heuristic.py)
treats as string category-name lookups (e.g. features.get("trend_regime")
indexes a dict keyed by category names like "bullish"), not decimal
numbers. feature_export.py's _build_features_record mirrors NestJS's
buildFeaturesRecord, which silently drops any feature value that isn't a
parseable finite number -- so if a real indicator pack encodes these two
fields as raw category strings (unconfirmed either way; not checked against
live data in this task), they would never reach PackFeatures.features at
all, and vectorize() below would then correctly fail-closed on every real
sample (missing required key) until that's resolved -- either NestJS
encodes them numerically, or the caller passes a feature_order scoped to
the dictionary's "numerical" list instead of "required" (excludes both
fields). Do not silently pick one; ask before changing the default.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


class VectorizeError(Exception):
    """Raised when a feature dict cannot be vectorized safely."""


def load_feature_order(
    feature_dictionary_path: Path | str, *, keys: str = "required"
) -> tuple[str, ...]:
    """Load the canonical feature order from a Score Engine Feature
    Dictionary JSON (e.g. app/artifacts/feature_dictionary_v1.json).

    `keys` selects which list to use ("required" by default, matching the
    Score Engine's own FEATURE_SCHEMA_INVALID contract for the online
    payload). Order is exactly the JSON list's own order -- never re-sorted
    -- since this becomes the canonical order everything downstream
    (vectorize, the dataset manifest) depends on.
    """
    with open(feature_dictionary_path) as f:
        dictionary = json.load(f)

    if keys not in dictionary:
        raise VectorizeError(f"feature dictionary has no '{keys}' list")

    names = dictionary[keys]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise VectorizeError(f"feature dictionary '{keys}' list is malformed")
    if not names:
        raise VectorizeError(f"feature dictionary '{keys}' list is empty")

    return tuple(names)


def vectorize(features: Mapping[str, float], feature_order: Sequence[str]) -> list[float]:
    """Align a named feature dict to feature_order.

    Fails closed on any missing key -- no defaulting or imputation. A
    required feature absent from a real sample's extracted features is a
    data-quality failure that must surface, not something to paper over
    with a placeholder value.
    """
    if not feature_order:
        raise VectorizeError("feature_order must not be empty")

    missing = [name for name in feature_order if name not in features]
    if missing:
        raise VectorizeError(f"missing required feature(s): {missing}")

    return [features[name] for name in feature_order]


def vectorize_all(
    features_by_sample_id: Mapping[str, Mapping[str, float]],
    feature_order: Sequence[str],
) -> dict[str, list[float]]:
    """Vectorize every sample's feature dict.

    Re-raises with the offending sample_id prefixed, so a single bad sample
    doesn't surface as an anonymous VectorizeError.
    """
    result: dict[str, list[float]] = {}
    for sample_id, features in features_by_sample_id.items():
        try:
            result[sample_id] = vectorize(features, feature_order)
        except VectorizeError as exc:
            raise VectorizeError(f"sample '{sample_id}': {exc}") from exc
    return result
