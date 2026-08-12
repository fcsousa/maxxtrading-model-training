"""Feature export for T6b (conditional A* -- trade_sample-subject packs).

Scope: historical_import trade_samples via immutable
``indicator_pack_runs.pack_json`` (subject_type='trade_sample',
status='succeeded'), per docs/schema-discovery.md's conditional A*
decision and AUTH run-pin policy (do not use mutable
IndicatorPack.current/lastSuccessful as the sole snapshot).

Feature extraction mirrors NestJS's buildFeaturesRecord
(score-request-builder.util.ts): only
pack_json["timeframes"]["primary"]["features"] + pack_json["globalFeatures"]
feed the numeric feature dict. Bridge-side (B2) fields
``hour_of_day`` / ``day_of_week`` are then derived from
``metadata.anchorTime`` (UTC), matching the Nest ponte. When
``risk_reward_ratio`` is still absent from the flattened pack (legacy
packs without globalFeatures), it is derived from
historical_trades entry/stop/target using
abs(target-entry)/abs(entry-stop), fail-closed if ingredients are
missing or the stop risk is zero.

Does not touch signal_scores or any order/signal path.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from training.categorical_encode import DEFAULT_CATEGORICAL_NAMES
from training.label_export import assert_read_only_sql

_SELECT_TRADE_SAMPLE_PACKS = """
    SELECT
        pinned.sample_id,
        pinned.pack_run_id,
        pinned.pack_json,
        pinned.ht_entry_price,
        pinned.ht_stop_price,
        pinned.ht_target_price
    FROM (
        SELECT DISTINCT ON (ipr.trade_sample_id)
            ipr.trade_sample_id AS sample_id,
            ipr.id AS pack_run_id,
            ipr.pack_json AS pack_json,
            ht.entry_price AS ht_entry_price,
            ht.stop_price AS ht_stop_price,
            ht.target_price AS ht_target_price,
            ts.entry_at AS entry_at
        FROM public.indicator_pack_runs ipr
        JOIN public.trade_samples ts ON ts.id = ipr.trade_sample_id
        LEFT JOIN public.historical_trades ht ON ht.id = ts.historical_trade_id
        WHERE ipr.subject_type = 'trade_sample'
          AND ipr.status = 'succeeded'
          AND ipr.pack_json IS NOT NULL
          AND ts.sample_quality = 'complete'
          AND ts.result_label IN ('win', 'loss')
          AND ts.exit_at IS NOT NULL
          AND ts.exit_at <= :as_of
          AND ts.entry_at >= :window_start
          AND ts.entry_at < :window_end
        ORDER BY ipr.trade_sample_id, ipr.finished_at DESC NULLS LAST, ipr.id DESC
    ) pinned
    ORDER BY pinned.entry_at, pinned.sample_id
"""


class FeatureExportError(Exception):
    """Raised when pack features cannot be exported safely."""


@dataclass(frozen=True)
class PackFeatures:
    sample_id: str
    features_version: str
    features: dict[str, float]
    pack_run_id: str | None = None
    categoricals: dict[str, str] = field(default_factory=dict)


def export_pack_features(
    engine: Engine,
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> Iterator[PackFeatures]:
    """Export numeric feature vectors from succeeded trade_sample pack runs.

    Same window/as_of contract as label_export.export_labeled_samples --
    window_start/window_end bound ts.entry_at, as_of is the lookahead
    cutoff. Reads immutable ``indicator_pack_runs.pack_json`` for the
    latest succeeded run per sample (run-pin), not mutable current/last
    Successful snapshot columns on ``indicator_packs``.
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
            yield _to_pack_features(
                row.sample_id,
                row.pack_json,
                pack_run_id=row.pack_run_id,
                ht_entry_price=row.ht_entry_price,
                ht_stop_price=row.ht_stop_price,
                ht_target_price=row.ht_target_price,
            )


def _to_pack_features(
    sample_id: str,
    pack_json: Any,
    *,
    pack_run_id: str | None = None,
    ht_entry_price: Any = None,
    ht_stop_price: Any = None,
    ht_target_price: Any = None,
) -> PackFeatures:
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

    features, categoricals = _build_features_record(
        sample_id, [*primary_features, *global_features]
    )
    _apply_bridge_enrichment(
        sample_id,
        pack_json,
        features,
        ht_entry_price=ht_entry_price,
        ht_stop_price=ht_stop_price,
        ht_target_price=ht_target_price,
    )

    return PackFeatures(
        sample_id=sample_id,
        features_version=str(features_version),
        features=features,
        pack_run_id=pack_run_id,
        categoricals=categoricals,
    )


def _apply_bridge_enrichment(
    sample_id: str,
    pack_json: dict[str, Any],
    features: dict[str, float],
    *,
    ht_entry_price: Any,
    ht_stop_price: Any,
    ht_target_price: Any,
) -> None:
    """Apply Nest ponte B2 (HOD/DOW) and legacy RRR fallback in-place."""
    _derive_hour_day_from_anchor(sample_id, pack_json, features)
    if "risk_reward_ratio" not in features:
        rrr = _derive_risk_reward_ratio(ht_entry_price, ht_stop_price, ht_target_price)
        if rrr is not None:
            features["risk_reward_ratio"] = rrr


def _derive_hour_day_from_anchor(
    sample_id: str, pack_json: dict[str, Any], features: dict[str, float]
) -> None:
    metadata = pack_json.get("metadata")
    if not isinstance(metadata, dict):
        return
    anchor_raw = metadata.get("anchorTime")
    if not isinstance(anchor_raw, str) or not anchor_raw:
        return
    try:
        anchor = datetime.fromisoformat(anchor_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeatureExportError(
            f"sample '{sample_id}': metadata.anchorTime is not a valid ISO datetime"
        ) from exc
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    else:
        anchor = anchor.astimezone(UTC)
    # Nest/JS Date#getUTCDay(): 0=Sunday..6=Saturday.
    # Python weekday(): 0=Monday..6=Sunday → (weekday + 1) % 7.
    # Only fill when absent -- never overwrite contracted pack/ponte values.
    features.setdefault("hour_of_day", float(anchor.hour))
    features.setdefault("day_of_week", float((anchor.weekday() + 1) % 7))


def _derive_risk_reward_ratio(entry_price: Any, stop_price: Any, target_price: Any) -> float | None:
    try:
        entry = float(entry_price)
        stop = float(stop_price)
        target = float(target_price)
    except (TypeError, ValueError):
        return None
    risk = abs(entry - stop)
    if risk == 0 or not math.isfinite(risk):
        return None
    reward = abs(target - entry)
    if not math.isfinite(reward):
        return None
    ratio = reward / risk
    if not math.isfinite(ratio):
        return None
    return ratio


def _build_features_record(
    sample_id: str, items: list[Any]
) -> tuple[dict[str, float], dict[str, str]]:
    """Mirror NestJS's buildFeaturesRecord (score-request-builder.util.ts).

    Numeric string values feed ``features``. Non-numeric string values for
    challenger categorical names (``trend_regime`` / ``volatility_regime``)
    are captured in ``categoricals`` for CQ encode (CQ-05). Other
    non-numeric names are skipped, same as online.
    """
    features: dict[str, float] = {}
    categoricals: dict[str, str] = {}
    cat_names = frozenset(DEFAULT_CATEGORICAL_NAMES)
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
            if name in cat_names:
                if name in categoricals:
                    raise FeatureExportError(
                        f"sample '{sample_id}': duplicate feature name '{name}'"
                    ) from None
                categoricals[name] = value
            continue
        if not math.isfinite(numeric_value):
            continue
        if name in features:
            raise FeatureExportError(f"sample '{sample_id}': duplicate feature name '{name}'")
        features[name] = numeric_value

    return features, categoricals
