"""Unit tests for immutable registry registration and alias moves (T25)."""

from __future__ import annotations

import pytest

from training.registry_promotion import (
    ALLOWED_ALIASES,
    REQUIRED_MODEL_VERSION_TAGS,
    AliasMoveRequest,
    InMemoryRegistryClient,
    RegistrationRequest,
    RegistryPromotionError,
    move_alias,
    promote_candidate_then_staging,
    register_immutable_challenger,
)

_SHA = "a" * 64


def _tags(**overrides: str) -> dict[str, str]:
    payload = {
        "algorithm": "lightgbm",
        "features_version": "feature_dictionary_v1",
        "dataset_id": "ds-" + ("b" * 60),
        "label_rule_id": "docs/label-policy.md",
        "training_commit": "c" * 40,
        "training_run_id": "t24-synthetic-recorded-1",
        "bundle_sha256": _SHA,
        "approval_ref": "docs/t24-challenger-eval-evidence.md",
    }
    payload.update(overrides)
    return payload


class TestRequiredTags:
    def test_required_tag_set_matches_mlf11(self) -> None:
        assert REQUIRED_MODEL_VERSION_TAGS == {
            "algorithm",
            "features_version",
            "dataset_id",
            "label_rule_id",
            "training_commit",
            "training_run_id",
            "bundle_sha256",
            "approval_ref",
        }

    def test_registration_rejects_missing_tag(self) -> None:
        client = InMemoryRegistryClient()
        tags = _tags()
        del tags["dataset_id"]
        with pytest.raises(RegistryPromotionError, match="missing required"):
            register_immutable_challenger(
                client,
                RegistrationRequest(
                    model_name="score_model",
                    source_uri="file:///tmp/bundle-v1",
                    tags=tags,
                ),
            )

    def test_registration_rejects_non_hex_checksum(self) -> None:
        client = InMemoryRegistryClient()
        with pytest.raises(RegistryPromotionError, match="bundle_sha256"):
            register_immutable_challenger(
                client,
                RegistrationRequest(
                    model_name="score_model",
                    source_uri="file:///tmp/bundle-v1",
                    tags=_tags(bundle_sha256="not-a-digest"),
                ),
            )


class TestImmutability:
    def test_same_source_uri_cannot_overwrite(self) -> None:
        client = InMemoryRegistryClient()
        request = RegistrationRequest(
            model_name="score_model",
            source_uri="file:///tmp/bundle-immutable",
            tags=_tags(),
            run_id="run-1",
        )
        first = register_immutable_challenger(client, request)
        assert first.version == "1"

        with pytest.raises(RegistryPromotionError, match="overwrite"):
            register_immutable_challenger(client, request)

    def test_new_source_creates_new_version(self) -> None:
        client = InMemoryRegistryClient()
        v1 = register_immutable_challenger(
            client,
            RegistrationRequest(
                model_name="score_model",
                source_uri="file:///tmp/bundle-a",
                tags=_tags(training_run_id="run-a"),
            ),
        )
        v2 = register_immutable_challenger(
            client,
            RegistrationRequest(
                model_name="score_model",
                source_uri="file:///tmp/bundle-b",
                tags=_tags(training_run_id="run-b", bundle_sha256="b" * 64),
            ),
        )
        assert v1.version == "1"
        assert v2.version == "2"
        assert (
            client.get_model_version("score_model", "1").source
            != client.get_model_version("score_model", "2").source
        )


class TestAliasMoves:
    def test_production_alias_is_rejected(self) -> None:
        assert "production" not in ALLOWED_ALIASES
        client = InMemoryRegistryClient()
        version = register_immutable_challenger(
            client,
            RegistrationRequest(
                model_name="score_model",
                source_uri="file:///tmp/bundle-x",
                tags=_tags(),
            ),
        )
        with pytest.raises(RegistryPromotionError, match="not allowed"):
            move_alias(
                client,
                AliasMoveRequest(
                    model_name="score_model",
                    alias="production",
                    expected_current_version=None,
                    target_version=version.version,
                    approval_ref=_tags()["approval_ref"],
                ),
            )

    def test_alias_requires_exact_current_version_and_approval(self) -> None:
        client = InMemoryRegistryClient()
        version = register_immutable_challenger(
            client,
            RegistrationRequest(
                model_name="score_model",
                source_uri="file:///tmp/bundle-y",
                tags=_tags(),
            ),
        )
        with pytest.raises(RegistryPromotionError, match="approval_ref is mandatory"):
            move_alias(
                client,
                AliasMoveRequest(
                    model_name="score_model",
                    alias="candidate",
                    expected_current_version=None,
                    target_version=version.version,
                    approval_ref="   ",
                ),
            )
        with pytest.raises(RegistryPromotionError, match="current version mismatch"):
            move_alias(
                client,
                AliasMoveRequest(
                    model_name="score_model",
                    alias="candidate",
                    expected_current_version="99",
                    target_version=version.version,
                    approval_ref=_tags()["approval_ref"],
                ),
            )

    def test_candidate_then_staging_promotion(self) -> None:
        client = InMemoryRegistryClient()
        approval = "docs/t24-challenger-eval-evidence.md"
        version = register_immutable_challenger(
            client,
            RegistrationRequest(
                model_name="score_model",
                source_uri="file:///tmp/bundle-z",
                tags=_tags(approval_ref=approval),
            ),
        )
        candidate, staging = promote_candidate_then_staging(
            client,
            model_name="score_model",
            version=version.version,
            candidate_approval_ref=approval,
            staging_approval_ref=approval,
        )
        assert candidate == staging == version.version
        assert client.get_alias_version("score_model", "candidate") == version.version
        assert client.get_alias_version("score_model", "staging") == version.version
