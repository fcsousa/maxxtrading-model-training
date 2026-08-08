"""Unit + contract tests for the Score Engine artifact bundle exporter (T10)."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from training.artifact_bundle import (
    ArtifactBundleError,
    BundleExportRequest,
    BundleProvenance,
    FeatureSchemaSpec,
    export_artifact_bundle,
    required_bundle_filenames,
    sha256_file,
    validate_artifact_bundle,
)

_TRAIN_X = [[20.0, 0.5], [80.0, 1.5], [25.0, 0.6], [78.0, 1.4]]
_TRAIN_Y = [0, 1, 0, 1]


def _fit_model() -> LogisticRegression:
    return LogisticRegression(random_state=42).fit(_TRAIN_X, _TRAIN_Y)


def _provenance(**overrides: object) -> BundleProvenance:
    payload: dict[str, object] = {
        "dataset_id": "ds-" + ("a" * 60),
        "training_commit": "7ca5cbe0123456789abcdef0123456789abcdef0",
        "label_policy_ref": "docs/label-policy.md#v1",
        "seed": 42,
        "library_versions": {"scikit-learn": "1.5.0", "numpy": "1.26.0"},
        "training_run_id": "run-fixture-1",
    }
    payload.update(overrides)
    return BundleProvenance(**payload)  # type: ignore[arg-type]


def _schema() -> FeatureSchemaSpec:
    return FeatureSchemaSpec(
        features_version="feature_dictionary_v1",
        numeric_features=("rsi_14", "volume_ratio"),
        categorical_features=(),
    )


def _request(**overrides: object) -> BundleExportRequest:
    payload: dict[str, object] = {
        "model": _fit_model(),
        "feature_schema": _schema(),
        "model_version": "score_model_v1.0.0",
        "model_name": "score_model",
        "algorithm": "logistic_regression",
        "provenance": _provenance(),
        "evaluation_metrics": {"train_log_loss": 0.12},
    }
    payload.update(overrides)
    return BundleExportRequest(**payload)  # type: ignore[arg-type]


class TestExportRequiredLayout:
    def test_writes_required_files_and_fields(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")

        for name in required_bundle_filenames():
            assert (exported.output_dir / name).is_file()

        schema = json.loads(
            (exported.output_dir / "feature_schema.json").read_text(encoding="utf-8")
        )
        assert schema["features_version"] == "feature_dictionary_v1"
        assert schema["numeric_features"] == ["rsi_14", "volume_ratio"]
        assert schema["categorical_features"] == []

        metrics = json.loads((exported.output_dir / "metrics.json").read_text(encoding="utf-8"))
        assert metrics["model_version"] == "score_model_v1.0.0"
        assert metrics["model_name"] == "score_model"
        assert metrics["algorithm"] == "logistic_regression"
        assert metrics["model_sha256"] == exported.model_sha256
        assert metrics["model_sha256"] == sha256_file(exported.output_dir / "model.pkl")

    def test_checksums_are_lowercase_hex(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")
        digest = exported.model_sha256

        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(ch in "0123456789abcdef" for ch in digest)

    def test_provenance_is_included_in_metrics(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")
        metrics = dict(exported.metrics)

        assert metrics["dataset_id"].startswith("ds-")
        assert metrics["training_commit"].startswith("7ca5cbe")
        assert metrics["label_policy_ref"] == "docs/label-policy.md#v1"
        assert metrics["label_rule_id"] == metrics["label_policy_ref"]
        assert metrics["seed"] == 42
        assert metrics["library_versions"]["scikit-learn"]
        assert metrics["training_run_id"] == "run-fixture-1"
        assert metrics["evaluation"] == {"train_log_loss": 0.12}


class TestOptionalArtifacts:
    def test_scaler_requires_checksum_when_present(self, tmp_path: Path) -> None:
        scaler = StandardScaler().fit(_TRAIN_X)
        exported = export_artifact_bundle(
            _request(scaler=scaler, model=_fit_model()),
            tmp_path / "bundle",
        )

        assert (exported.output_dir / "scaler.pkl").is_file()
        assert exported.scaler_sha256 is not None
        assert exported.metrics["scaler_sha256"] == exported.scaler_sha256
        assert exported.scaler_sha256 == sha256_file(exported.output_dir / "scaler.pkl")
        assert "encoder_sha256" not in exported.metrics

    def test_encoder_requires_checksum_when_present(self, tmp_path: Path) -> None:
        encoder = OneHotEncoder(sparse_output=False).fit([["buy"], ["sell"]])
        schema = FeatureSchemaSpec(
            features_version="feature_dictionary_v1",
            numeric_features=("rsi_14",),
            categorical_features=("side",),
        )
        exported = export_artifact_bundle(
            _request(encoder=encoder, feature_schema=schema),
            tmp_path / "bundle",
        )

        assert (exported.output_dir / "encoder.pkl").is_file()
        assert exported.encoder_sha256 is not None
        assert exported.metrics["encoder_sha256"] == exported.encoder_sha256
        assert "scaler_sha256" not in exported.metrics


class TestExportGuards:
    def test_missing_model_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ArtifactBundleError, match="model_version"):
            export_artifact_bundle(_request(model_version=""), tmp_path / "bundle")

    def test_missing_dataset_id_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ArtifactBundleError, match="dataset_id"):
            export_artifact_bundle(
                _request(provenance=_provenance(dataset_id="")),
                tmp_path / "bundle",
            )


class TestExternalContractFailures:
    def test_missing_required_file_fails_validation(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")
        (exported.output_dir / "metrics.json").unlink()

        with pytest.raises(ArtifactBundleError, match="missing required artifact"):
            validate_artifact_bundle(exported.output_dir)

    def test_tampered_model_fails_checksum_validation(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")
        model_path = exported.output_dir / "model.pkl"
        model_path.write_bytes(model_path.read_bytes() + b"\x00tamper")

        with pytest.raises(ArtifactBundleError, match="checksum mismatch"):
            validate_artifact_bundle(exported.output_dir)

    def test_optional_scaler_without_checksum_fails_validation(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")
        scaler = StandardScaler().fit(_TRAIN_X)
        joblib.dump(scaler, exported.output_dir / "scaler.pkl")

        with pytest.raises(ArtifactBundleError, match="missing checksum"):
            validate_artifact_bundle(exported.output_dir)

    def test_uppercase_checksum_fails_validation(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(_request(), tmp_path / "bundle")
        metrics_path = exported.output_dir / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["model_sha256"] = metrics["model_sha256"].upper()
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

        with pytest.raises(ArtifactBundleError, match="lowercase hex SHA-256"):
            validate_artifact_bundle(exported.output_dir)

    def test_valid_exported_bundle_passes_contract(self, tmp_path: Path) -> None:
        exported = export_artifact_bundle(
            _request(scaler=StandardScaler().fit(_TRAIN_X)),
            tmp_path / "bundle",
        )
        # Must not raise — post-export contract is the external gate for T10.
        validate_artifact_bundle(exported.output_dir)
