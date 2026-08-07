from datetime import datetime

import pytest

from training.feature_export import (
    FeatureExportError,
    _to_pack_features,
    export_pack_features,
)

VALID_PACK = {
    "packSchemaVersion": 2,
    "leakageCheckStatus": "passed",
    "featureDictionaryVersion": 4,
    "metadata": {
        "anchorTime": "2026-06-15T14:30:00.000Z",
    },
    "timeframes": {
        "primary": {
            "features": [
                {"name": "rsi_14", "value": "58.40000000"},
                {"name": "trend_score", "value": "1.00000000"},
            ]
        }
    },
    "globalFeatures": [
        {"name": "risk_reward_ratio", "value": "2.00000000"},
        {"name": "side", "value": "long"},
    ],
}


class FakeConnection:
    def __init__(self, rows):
        self._rows = rows
        self.executed_params = None

    def execute(self, _query, params):
        self.executed_params = params
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


class FakeEngine:
    def __init__(self, rows):
        self._connection = FakeConnection(rows)

    def connect(self):
        return self._connection


class Row:
    def __init__(
        self,
        sample_id,
        pack_json,
        pack_run_id="run-1",
        ht_entry_price=None,
        ht_stop_price=None,
        ht_target_price=None,
    ):
        self.sample_id = sample_id
        self.pack_json = pack_json
        self.pack_run_id = pack_run_id
        self.ht_entry_price = ht_entry_price
        self.ht_stop_price = ht_stop_price
        self.ht_target_price = ht_target_price


class TestWindowBoundsAreMandatory:
    def test_missing_window_start_raises(self):
        with pytest.raises(FeatureExportError):
            list(
                export_pack_features(
                    FakeEngine([]),
                    window_start=None,
                    window_end=datetime(2026, 1, 2),
                    as_of=datetime(2026, 1, 2),
                )
            )

    def test_window_start_after_window_end_raises(self):
        with pytest.raises(FeatureExportError):
            list(
                export_pack_features(
                    FakeEngine([]),
                    window_start=datetime(2026, 1, 2),
                    window_end=datetime(2026, 1, 1),
                    as_of=datetime(2026, 1, 2),
                )
            )

    def test_as_of_before_window_end_raises(self):
        with pytest.raises(FeatureExportError):
            list(
                export_pack_features(
                    FakeEngine([]),
                    window_start=datetime(2026, 1, 1),
                    window_end=datetime(2026, 1, 2),
                    as_of=datetime(2026, 1, 1),
                )
            )

    def test_valid_bounds_are_passed_as_query_params(self):
        engine = FakeEngine([])
        window_start = datetime(2026, 1, 1)
        window_end = datetime(2026, 1, 8)
        as_of = datetime(2026, 1, 10)

        list(
            export_pack_features(
                engine, window_start=window_start, window_end=window_end, as_of=as_of
            )
        )

        assert engine._connection.executed_params == {
            "window_start": window_start,
            "window_end": window_end,
            "as_of": as_of,
        }


class TestQueryEncodesTheConditionalAStarPath:
    def test_query_restricted_to_trade_sample_succeeded_pack_runs(self):
        from training.feature_export import _SELECT_TRADE_SAMPLE_PACKS

        assert "subject_type = 'trade_sample'" in _SELECT_TRADE_SAMPLE_PACKS
        assert "indicator_pack_runs" in _SELECT_TRADE_SAMPLE_PACKS
        assert "status = 'succeeded'" in _SELECT_TRADE_SAMPLE_PACKS
        assert "pack_json IS NOT NULL" in _SELECT_TRADE_SAMPLE_PACKS
        assert "DISTINCT ON (ipr.trade_sample_id)" in _SELECT_TRADE_SAMPLE_PACKS
        # Run-pin: must not rely on mutable current/lastSuccessful alone.
        assert "current_pack_json" not in _SELECT_TRADE_SAMPLE_PACKS
        assert "last_successful_pack_json" not in _SELECT_TRADE_SAMPLE_PACKS

    def test_query_does_not_touch_signal_scores(self):
        from training.feature_export import _SELECT_TRADE_SAMPLE_PACKS

        assert "signal_scores" not in _SELECT_TRADE_SAMPLE_PACKS


class TestPackValidation:
    def test_wrong_schema_version_raises(self):
        pack = {**VALID_PACK, "packSchemaVersion": 1}
        with pytest.raises(FeatureExportError, match="packSchemaVersion"):
            _to_pack_features("s1", pack)

    def test_missing_leakage_check_passed_raises(self):
        pack = {**VALID_PACK, "leakageCheckStatus": "pending"}
        with pytest.raises(FeatureExportError, match="leakageCheckStatus"):
            _to_pack_features("s1", pack)

    def test_missing_features_dictionary_version_raises(self):
        pack = {k: v for k, v in VALID_PACK.items() if k != "featureDictionaryVersion"}
        with pytest.raises(FeatureExportError, match="featureDictionaryVersion"):
            _to_pack_features("s1", pack)

    def test_missing_primary_features_raises(self):
        pack = {**VALID_PACK, "timeframes": {"primary": {}}}
        with pytest.raises(FeatureExportError, match="timeframes.primary.features"):
            _to_pack_features("s1", pack)

    def test_non_list_global_features_raises(self):
        pack = {**VALID_PACK, "globalFeatures": "not-a-list"}
        with pytest.raises(FeatureExportError, match="globalFeatures"):
            _to_pack_features("s1", pack)

    def test_pack_json_not_an_object_raises(self):
        with pytest.raises(FeatureExportError, match="not an object"):
            _to_pack_features("s1", "not-a-dict")


class TestFeatureExtractionMirrorsNestJs:
    def test_numeric_primary_and_global_features_are_extracted(self):
        result = _to_pack_features("s1", VALID_PACK)

        assert result.features["rsi_14"] == pytest.approx(58.4)
        assert result.features["trend_score"] == pytest.approx(1.0)
        assert result.features["risk_reward_ratio"] == pytest.approx(2.0)
        # B2 from metadata.anchorTime (2026-06-15 = Monday UTC 14:30)
        assert result.features["hour_of_day"] == pytest.approx(14.0)
        assert result.features["day_of_week"] == pytest.approx(1.0)  # Monday

    def test_categorical_value_is_silently_skipped_not_an_error(self):
        result = _to_pack_features("s1", VALID_PACK)

        assert "side" not in result.features

    def test_duplicate_feature_name_raises(self):
        pack = {
            **VALID_PACK,
            "timeframes": {"primary": {"features": [{"name": "rsi_14", "value": "1.0"}]}},
            "globalFeatures": [{"name": "rsi_14", "value": "2.0"}],
        }
        with pytest.raises(FeatureExportError, match="duplicate feature name"):
            _to_pack_features("s1", pack)

    def test_non_dict_feature_item_raises(self):
        pack = {**VALID_PACK, "timeframes": {"primary": {"features": ["not-a-dict"]}}}
        with pytest.raises(FeatureExportError, match="not an object"):
            _to_pack_features("s1", pack)

    def test_non_numeric_string_value_is_skipped(self):
        pack = {
            **VALID_PACK,
            "timeframes": {"primary": {"features": [{"name": "weird", "value": "not-a-number"}]}},
            "globalFeatures": [],
        }
        result = _to_pack_features("s1", pack)

        assert "weird" not in result.features

    def test_features_version_is_stringified(self):
        result = _to_pack_features("s1", VALID_PACK)

        assert result.features_version == "4"

    def test_full_result_shape(self):
        result = _to_pack_features("sample-123", VALID_PACK)

        assert result.sample_id == "sample-123"
        assert result.features_version == "4"
        assert result.features["rsi_14"] == pytest.approx(58.4)
        assert result.features["trend_score"] == pytest.approx(1.0)
        assert result.features["risk_reward_ratio"] == pytest.approx(2.0)
        assert result.features["hour_of_day"] == pytest.approx(14.0)
        assert result.features["day_of_week"] == pytest.approx(1.0)


class TestBridgeEnrichment:
    def test_rrr_derived_from_historical_trade_prices_when_absent(self):
        pack = {
            **VALID_PACK,
            "globalFeatures": [],  # no RRR in pack
        }
        result = _to_pack_features(
            "s1",
            pack,
            ht_entry_price=100,
            ht_stop_price=90,
            ht_target_price=120,
        )

        assert result.features["risk_reward_ratio"] == pytest.approx(2.0)

    def test_pack_rrr_not_overwritten_by_ht_derivation(self):
        result = _to_pack_features(
            "s1",
            VALID_PACK,
            ht_entry_price=100,
            ht_stop_price=90,
            ht_target_price=150,  # would be 5.0 if used
        )

        assert result.features["risk_reward_ratio"] == pytest.approx(2.0)

    def test_zero_stop_risk_does_not_inject_rrr(self):
        pack = {**VALID_PACK, "globalFeatures": []}
        result = _to_pack_features(
            "s1",
            pack,
            ht_entry_price=100,
            ht_stop_price=100,
            ht_target_price=120,
        )

        assert "risk_reward_ratio" not in result.features

    def test_sunday_anchor_maps_to_day_of_week_zero(self):
        pack = {
            **VALID_PACK,
            "metadata": {"anchorTime": "2026-06-14T00:00:00.000Z"},  # Sunday
            "globalFeatures": [],
        }
        result = _to_pack_features("s1", pack)

        assert result.features["day_of_week"] == pytest.approx(0.0)
        assert result.features["hour_of_day"] == pytest.approx(0.0)


class TestExportPackFeaturesEndToEnd:
    def test_yields_pack_features_per_row(self):
        engine = FakeEngine([Row("s1", VALID_PACK)])

        results = list(
            export_pack_features(
                engine,
                window_start=datetime(2026, 1, 1),
                window_end=datetime(2026, 1, 8),
                as_of=datetime(2026, 1, 10),
            )
        )

        assert len(results) == 1
        assert results[0].sample_id == "s1"
        assert results[0].features["rsi_14"] == pytest.approx(58.4)
