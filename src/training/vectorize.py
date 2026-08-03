"""Vectorize named feature dicts (feature_export.py's PackFeatures.features)
into ordered vectors for trainer.train(), using the Score Engine's Feature
Dictionary as the canonical feature order.

Fixture/unit-tested only in this module -- no live DB access here.

Phase 1 decision (fcsousa, 2026-08-01): default to the Feature Dictionary's
"numerical" list, not "required". "required" includes trend_regime/
volatility_regime, which the Score Engine's own baseline model
(app/domain/services/baseline_heuristic.py) treats as string category-name
lookups, not decimal numbers -- feature_export.py's numeric-only filter
(mirroring NestJS's buildFeaturesRecord) would silently drop them if a real
indicator pack encodes them as raw category strings, which would then
fail-closed here on every real sample. Rather than resolve that encoding
question now, Phase 1 excludes both fields from the float vector entirely:
load_feature_order() records which list was used (feature_order_source) and
which required-but-excluded fields were deferred (deferred_categoricals) so
the manifest carries this decision explicitly. Expanding the order to
include them is future work (either NestJS encodes them numerically, or a
Score Engine/training-side categorical pipeline is built) -- not Phase 1,
and app/artifacts/feature_dictionary_v1.json in the Score Engine repo is
not touched by this decision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class VectorizeError(Exception):
    """Raised when a feature dict cannot be vectorized safely."""


@dataclass(frozen=True)
class FeatureOrder:
    names: tuple[str, ...]
    source: str
    deferred_categoricals: tuple[str, ...]


def load_feature_order(
    feature_dictionary_path: Path | str, *, keys: str = "numerical"
) -> FeatureOrder:
    """Load the canonical feature order from a Score Engine Feature
    Dictionary JSON (e.g. app/artifacts/feature_dictionary_v1.json).

    `keys` selects which list to use ("numerical" by default for Phase 1 --
    see module docstring). Order is exactly the JSON list's own order --
    never re-sorted -- since this becomes the canonical order everything
    downstream (vectorize, the dataset manifest) depends on.

    deferred_categoricals is computed generically as every name in the
    dictionary's "required" list that is absent from the selected `keys`
    list -- for the real Feature Dictionary with keys="numerical" this is
    trend_regime/volatility_regime, but nothing here hardcodes those names.
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

    names_tuple = tuple(names)
    required = dictionary.get("required", [])
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        required = []
    deferred = tuple(name for name in required if name not in names_tuple)

    return FeatureOrder(names=names_tuple, source=keys, deferred_categoricals=deferred)


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
