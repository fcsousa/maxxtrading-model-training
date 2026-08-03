import json

import pytest

from training.vectorize import (
    FeatureOrder,
    VectorizeError,
    load_feature_order,
    vectorize,
    vectorize_all,
)

REAL_SHAPED_DICTIONARY = {
    "required": [
        "ema_9",
        "rsi_14",
        "risk_reward_ratio",
        "trend_regime",
        "volatility_regime",
    ],
    "numerical": ["ema_9", "rsi_14", "risk_reward_ratio"],
    "categorical": ["asset", "trend_regime", "volatility_regime"],
}


class TestLoadFeatureOrder:
    def test_defaults_to_numerical_list(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps(REAL_SHAPED_DICTIONARY))

        loaded = load_feature_order(path)

        assert loaded.names == ("ema_9", "rsi_14", "risk_reward_ratio")
        assert loaded.source == "numerical"

    def test_deferred_categoricals_are_required_minus_numerical(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps(REAL_SHAPED_DICTIONARY))

        loaded = load_feature_order(path)

        assert loaded.deferred_categoricals == ("trend_regime", "volatility_regime")

    def test_loads_alternate_list_when_keys_specified(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps({"required": ["rsi_14"], "optional": ["macd", "ema_9"]}))

        loaded = load_feature_order(path, keys="optional")

        assert loaded.names == ("macd", "ema_9")
        assert loaded.source == "optional"

    def test_required_list_has_no_deferred_categoricals_against_itself(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps(REAL_SHAPED_DICTIONARY))

        loaded = load_feature_order(path, keys="required")

        assert loaded.deferred_categoricals == ()

    def test_missing_keys_list_raises(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps({"required": ["rsi_14"]}))

        with pytest.raises(VectorizeError, match="no 'categorical' list"):
            load_feature_order(path, keys="categorical")

    def test_malformed_list_raises(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps({"numerical": ["rsi_14", 42]}))

        with pytest.raises(VectorizeError, match="malformed"):
            load_feature_order(path)

    def test_empty_list_raises(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps({"numerical": []}))

        with pytest.raises(VectorizeError, match="empty"):
            load_feature_order(path)

    def test_order_matches_json_order_not_sorted(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps({"numerical": ["atr_14", "rsi_14", "ema_9"]}))

        assert load_feature_order(path).names == ("atr_14", "rsi_14", "ema_9")

    def test_missing_required_list_yields_empty_deferred_categoricals(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps({"numerical": ["ema_9"]}))

        loaded = load_feature_order(path)

        assert loaded.deferred_categoricals == ()

    def test_returns_feature_order_dataclass(self, tmp_path):
        path = tmp_path / "feature_dictionary.json"
        path.write_text(json.dumps(REAL_SHAPED_DICTIONARY))

        assert isinstance(load_feature_order(path), FeatureOrder)


class TestVectorize:
    def test_returns_values_in_feature_order(self):
        features = {"ema_9": 1.5, "rsi_14": 58.4, "atr_14": 0.02}

        result = vectorize(features, ["rsi_14", "ema_9", "atr_14"])

        assert result == [58.4, 1.5, 0.02]

    def test_missing_required_feature_raises(self):
        features = {"ema_9": 1.5}

        with pytest.raises(VectorizeError, match="rsi_14"):
            vectorize(features, ["ema_9", "rsi_14"])

    def test_empty_feature_order_raises(self):
        with pytest.raises(VectorizeError, match="empty"):
            vectorize({"ema_9": 1.5}, [])

    def test_ignores_extra_features_not_in_order(self):
        features = {"ema_9": 1.5, "unused_feature": 999.0}

        result = vectorize(features, ["ema_9"])

        assert result == [1.5]


class TestVectorizeAll:
    def test_vectorizes_multiple_samples(self):
        features_by_sample_id = {
            "s1": {"ema_9": 1.0, "rsi_14": 50.0},
            "s2": {"ema_9": 2.0, "rsi_14": 60.0},
        }

        result = vectorize_all(features_by_sample_id, ["ema_9", "rsi_14"])

        assert result == {"s1": [1.0, 50.0], "s2": [2.0, 60.0]}

    def test_missing_feature_error_includes_sample_id(self):
        features_by_sample_id = {"s1": {"ema_9": 1.0}}

        with pytest.raises(VectorizeError, match="sample 's1'"):
            vectorize_all(features_by_sample_id, ["ema_9", "rsi_14"])
