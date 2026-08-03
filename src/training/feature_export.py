"""Feature export for T6b (conditional A* -- trade_sample-subject packs).

Scope: historical_import trade_samples via indicator_packs.trade_sample_id
(subject_type='trade_sample', current_status='succeeded'), per
docs/schema-discovery.md's conditional A* decision (parity=anchor_policy).
Does not touch signal_scores or any order/signal path -- those remain
gated on signal_scores having real rows (still 0 as of that decision).

Feature extraction mirrors NestJS's buildFeaturesRecord
(score-request-builder.util.ts) exactly: only
pack_json["timeframes"]["primary"]["features"] + pack_json["globalFeatures"]
feed the numeric feature dict (higherTimeframe1/2's own features arrays are
not used online either, and non-numeric-string values -- e.g. categorical
{"name": "side", "value": "long"} -- are silently excluded, same as the
online path, not an error).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from training.label_export import assert_read_only_sql

_SELECT_TRADE_SAMPLE_PACKS = """
    SELECT
        ip.trade_sample_id AS sample_id,
        ip.current_pack_json AS pack_json
    FROM public.indicator_packs ip
    JOIN public.trade_samples ts ON ts.id = ip.trade_sample_id
    WHERE ip.subject_type = 'trade_sample'
      AND ip.current_status = 'succeeded'
      AND ip.current_pack_json IS NOT NULL
      AND ts.sample_quality = 'complete'
      AND ts.result_label IN ('win', 'loss')
      AND ts.exit_at IS NOT NULL
      AND ts.exit_at <= :as_of
      AND ts.entry_at >= :window_start
      AND ts.entry_at < :window_end
    ORDER BY ts.entry_at, ip.trade_sample_id
"""


class FeatureExportError(Exception):
    """Raised when pack features cannot be exported safely."""


@dataclass(frozen=True)
class PackFeatures:
    sample_id: str
    features_version: str
    features: dict[str, float]


def export_pack_features(
    engine: Engine,
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> Iterator[PackFeatures]:
    """Export numeric feature vectors from succeeded trade_sample packs.

    Same window/as_of contract as label_export.export_labeled_samples --
    window_start/window_end bound ts.entry_at, as_of is the lookahead
    cutoff. Only current_status='succeeded' packs with a non-null
    current_pack_json are read; anything else is skipped by the query, not
    silently substituted.
    """
    if window_start is None or window_end is None or as_of is None:
        raise FeatureExportError("window_start, window_end and as_of are all mandatory")
    if window_start >= window_end:
        raise FeatureExportError("window_start must be before window_end")
    if as_of < window_end:
        raise FeatureExportError("as_of must not be before window_end")

    assert_read_only_sql(_SELECT_TRADE_SAMPLE_PACKS)
    query = text(_SELECT_TRADE_SAMPLE_PACKS)
    params = {"window_start": window_start, "window_end": window_end, "as_of": as_of}

    with engine.connect() as conn:
        result = conn.execute(query, params)
        for row in result:
            yield _to_pack_features(row.sample_id, row.pack_json)


def _to_pack_features(sample_id: str, pack_json: Any) -> PackFeatures:
    if not isinstance(pack_json, dict):
        raise FeatureExportError(f"sample '{sample_id}': pack_json is not an object")

    if pack_json.get("packSchemaVersion") != 2:
        raise FeatureExportError(f"sample '{sample_id}': unexpected packSchemaVersion")
    if pack_json.get("leakageCheckStatus") != "passed":
        raise FeatureExportError(f"sample '{sample_id}': leakageCheckStatus is not 'passed'")

    features_version = pack_json.get("featureDictionaryVersion")
    if not isinstance(features_version, int):
        raise FeatureExportError(f"sample '{sample_id}': missing featureDictionaryVersion")

    try:
        primary_features = pack_json["timeframes"]["primary"]["features"]
    except (KeyError, TypeError) as exc:
        raise FeatureExportError(
            f"sample '{sample_id}': missing timeframes.primary.features"
        ) from exc
    if not isinstance(primary_features, list):
        raise FeatureExportError(f"sample '{sample_id}': timeframes.primary.features is not a list")

    global_features = pack_json.get("globalFeatures") or []
    if not isinstance(global_features, list):
        raise FeatureExportError(f"sample '{sample_id}': globalFeatures is not a list")

    features = _build_features_record(sample_id, [*primary_features, *global_features])

    return PackFeatures(
        sample_id=sample_id,
        features_version=str(features_version),
        features=features,
    )


def _build_features_record(sample_id: str, items: list[Any]) -> dict[str, float]:
    """Mirror NestJS's buildFeaturesRecord (score-request-builder.util.ts).

    Only items with a string `name` and a string `value` that parses as a
    finite number are included -- non-numeric values (e.g. categorical
    {"name": "side", "value": "long"}) are silently skipped, same as
    online, not an error. A duplicate numeric feature name is a hard error,
    same as NestJS's feature_name_collision.
    """
    features: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            raise FeatureExportError(f"sample '{sample_id}': feature item is not an object")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        try:
            numeric_value = float(value)
        except ValueError:
            continue
        if not math.isfinite(numeric_value):
            continue
        if name in features:
            raise FeatureExportError(f"sample '{sample_id}': duplicate feature name '{name}'")
        features[name] = numeric_value

    return features
