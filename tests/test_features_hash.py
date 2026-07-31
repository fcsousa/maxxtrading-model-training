import re

from training.features_hash import compute_features_hash

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TestComputeFeaturesHash:
    def test_deterministic_across_calls(self):
        features = {"ema_9": 61180.2, "trend_regime": "bullish"}

        assert compute_features_hash(features) == compute_features_hash(features)

    def test_independent_of_key_order(self):
        ordered = {"ema_9": 61180.2, "rsi_14": 58.4, "trend_regime": "bullish"}
        reordered = {"trend_regime": "bullish", "ema_9": 61180.2, "rsi_14": 58.4}

        assert compute_features_hash(ordered) == compute_features_hash(reordered)

    def test_produces_valid_sha256_hex_digest(self):
        assert SHA256_HEX_PATTERN.match(compute_features_hash({"ema_9": 61180.2}))

    def test_matches_hand_computed_canonical_json_digest(self):
        # Canonical form for {"a": 1, "b": 2.5} is '{"a":1,"b":2.5}' (sorted
        # keys, no whitespace) -- this is the exact byte sequence NestJS's
        # stableStringify would also produce for the same logical values
        # (docs/schema-discovery.md A* parity study).
        canonical = '{"a":1,"b":2.5}'
        expected = hashlib_sha256_hex(canonical)

        assert compute_features_hash({"b": 2.5, "a": 1}) == expected

    def test_whole_number_value_renders_without_decimal_point(self):
        # This is the specific cross-language risk called out in the A*
        # parity study: Python floats render integer values with a
        # trailing ".0", but JS numbers never do. A whole-number feature
        # value must therefore arrive/stay as a Python int (never coerced
        # to float) for the hash to match NestJS's computeFeaturesHash.
        canonical_if_int = '{"trend_strength":1}'
        canonical_if_float = '{"trend_strength":1.0}'

        result = compute_features_hash({"trend_strength": 1})

        assert result == hashlib_sha256_hex(canonical_if_int)
        assert result != hashlib_sha256_hex(canonical_if_float)


def hashlib_sha256_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
