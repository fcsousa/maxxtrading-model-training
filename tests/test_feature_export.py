from datetime import datetime

import pytest

from training.feature_export import (
    FeatureExportError,
    PackFeatures,
    _to_pack_features,
    export_pack_features,
)

VALID_PACK = {
    "packSchemaVersion": 2,
    "leakageCheckStatus": "passed",
    "featureDictionaryVersion": 4,
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
    def __init__(self, sample_id, pack_json):
        self.sample_id = sample_id
        self.pack_json = pack_json


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
    def test_query_restricted_to_trade_sample_subject_succeeded_packs(self):
        from training.feature_export import _SELECT_TRADE_SAMPLE_PACKS

        assert "subject_type = 'trade_sample'" in _SELECT_TRADE_SAMPLE_PACKS
        assert "current_status = 'succeeded'" in _SELECT_TRADE_SAMPLE_PACKS
        assert "current_pack_json IS NOT NULL" in _SELECT_TRADE_SAMPLE_PACKS

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

        assert result == PackFeatures(
            sample_id="sample-123",
            features_version="4",
            features={"rsi_14": 58.4, "trend_score": 1.0, "risk_reward_ratio": 2.0},
        )


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
