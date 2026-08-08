"""Score Engine artifact bundle exporter (T10 / MLF-07, MLF-08).

Writes the canonical promoted-candidate layout consumed by
`JoblibModelLoader` in maxxtrading-scoreengine:

    <output_dir>/
      model.pkl                 required
      feature_schema.json       required
      metrics.json              required (+ checksums + provenance)
      scaler.pkl / encoder.pkl  optional; each requires its *_sha256

No live training or DB access — callers supply fitted objects and metadata.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import joblib

_MODEL_FILENAME: Final = "model.pkl"
_SCALER_FILENAME: Final = "scaler.pkl"
_ENCODER_FILENAME: Final = "encoder.pkl"
_FEATURE_SCHEMA_FILENAME: Final = "feature_schema.json"
_METRICS_FILENAME: Final = "metrics.json"

_REQUIRED_BUNDLE_FILES: Final = frozenset(
    {_MODEL_FILENAME, _FEATURE_SCHEMA_FILENAME, _METRICS_FILENAME}
)
_SHA256_HEX_LENGTH: Final = 64


class ArtifactBundleError(Exception):
    """Raised when a bundle cannot be exported or fails the external contract."""


@dataclass(frozen=True)
class FeatureSchemaSpec:
    features_version: str
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class BundleProvenance:
    """Training provenance folded into metrics.json for registry/serving audit."""

    dataset_id: str
    training_commit: str
    label_policy_ref: str
    seed: int
    library_versions: Mapping[str, str]
    training_run_id: str | None = None


@dataclass(frozen=True)
class BundleExportRequest:
    model: object
    feature_schema: FeatureSchemaSpec
    model_version: str
    model_name: str
    algorithm: str
    provenance: BundleProvenance
    evaluation_metrics: Mapping[str, float] | None = None
    scaler: object | None = None
    encoder: object | None = None


@dataclass(frozen=True)
class ExportedBundle:
    output_dir: Path
    model_sha256: str
    scaler_sha256: str | None
    encoder_sha256: str | None
    feature_schema: Mapping[str, object]
    metrics: Mapping[str, object]


def export_artifact_bundle(
    request: BundleExportRequest,
    output_dir: Path | str,
) -> ExportedBundle:
    """Serialize a promoted Score Engine candidate bundle into ``output_dir``."""
    _validate_export_request(request)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    model_path = target / _MODEL_FILENAME
    joblib.dump(request.model, model_path)
    model_sha256 = sha256_file(model_path)

    scaler_sha256: str | None = None
    if request.scaler is not None:
        scaler_path = target / _SCALER_FILENAME
        joblib.dump(request.scaler, scaler_path)
        scaler_sha256 = sha256_file(scaler_path)

    encoder_sha256: str | None = None
    if request.encoder is not None:
        encoder_path = target / _ENCODER_FILENAME
        joblib.dump(request.encoder, encoder_path)
        encoder_sha256 = sha256_file(encoder_path)

    feature_schema = {
        "features_version": request.feature_schema.features_version,
        "numeric_features": list(request.feature_schema.numeric_features),
        "categorical_features": list(request.feature_schema.categorical_features),
    }
    _write_json(target / _FEATURE_SCHEMA_FILENAME, feature_schema)

    metrics: dict[str, object] = {
        "model_version": request.model_version,
        "model_name": request.model_name,
        "algorithm": request.algorithm,
        "model_sha256": model_sha256,
        "dataset_id": request.provenance.dataset_id,
        "training_commit": request.provenance.training_commit,
        "label_policy_ref": request.provenance.label_policy_ref,
        "label_rule_id": request.provenance.label_policy_ref,
        "seed": request.provenance.seed,
        "library_versions": dict(request.provenance.library_versions),
    }
    if request.provenance.training_run_id is not None:
        metrics["training_run_id"] = request.provenance.training_run_id
    if scaler_sha256 is not None:
        metrics["scaler_sha256"] = scaler_sha256
    if encoder_sha256 is not None:
        metrics["encoder_sha256"] = encoder_sha256
    if request.evaluation_metrics:
        metrics["evaluation"] = {
            key: float(value) for key, value in request.evaluation_metrics.items()
        }

    _write_json(target / _METRICS_FILENAME, metrics)

    exported = ExportedBundle(
        output_dir=target,
        model_sha256=model_sha256,
        scaler_sha256=scaler_sha256,
        encoder_sha256=encoder_sha256,
        feature_schema=feature_schema,
        metrics=metrics,
    )
    validate_artifact_bundle(target)
    return exported


def validate_artifact_bundle(bundle_dir: Path | str) -> None:
    """Fail closed when the on-disk bundle violates the Score Engine contract.

    Used by the exporter (post-write) and by external contract tests for
    missing/tampered artifact cases (MLF-07 / MLF-08).
    """
    root = Path(bundle_dir)
    if not root.is_dir():
        raise ArtifactBundleError(f"bundle directory does not exist: {root}")

    for filename in _REQUIRED_BUNDLE_FILES:
        path = root / filename
        if not path.is_file():
            raise ArtifactBundleError(f"missing required artifact: {filename}")

    schema = _read_json(root / _FEATURE_SCHEMA_FILENAME)
    _require_string(schema, "features_version", where=_FEATURE_SCHEMA_FILENAME)
    _require_string_list(schema, "numeric_features", where=_FEATURE_SCHEMA_FILENAME)
    _require_string_list(schema, "categorical_features", where=_FEATURE_SCHEMA_FILENAME)

    metrics = _read_json(root / _METRICS_FILENAME)
    _require_string(metrics, "model_version", where=_METRICS_FILENAME)
    _require_string(metrics, "model_name", where=_METRICS_FILENAME)
    _require_string(metrics, "algorithm", where=_METRICS_FILENAME)
    _require_lowercase_sha256(metrics, "model_sha256", where=_METRICS_FILENAME)
    _require_string(metrics, "dataset_id", where=_METRICS_FILENAME)
    _require_string(metrics, "training_commit", where=_METRICS_FILENAME)
    _require_label_provenance(metrics)
    if "seed" not in metrics:
        raise ArtifactBundleError("metrics.json missing required field: seed")
    if not isinstance(metrics["seed"], int) or isinstance(metrics["seed"], bool):
        raise ArtifactBundleError("metrics.json field 'seed' must be an int")
    library_versions = metrics.get("library_versions")
    if not isinstance(library_versions, dict) or not library_versions:
        raise ArtifactBundleError("metrics.json missing required field: library_versions")
    for name, version in library_versions.items():
        if not isinstance(name, str) or not isinstance(version, str) or not version:
            raise ArtifactBundleError("library_versions entries must be non-empty strings")

    _verify_checksum(root / _MODEL_FILENAME, metrics["model_sha256"])
    _validate_optional_pickle(root, _SCALER_FILENAME, metrics.get("scaler_sha256"))
    _validate_optional_pickle(root, _ENCODER_FILENAME, metrics.get("encoder_sha256"))


def sha256_file(path: Path) -> str:
    """Return lowercase hex SHA-256 of ``path`` (streaming)."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _validate_export_request(request: BundleExportRequest) -> None:
    if request.model is None:
        raise ArtifactBundleError("model is required")
    if not request.model_version:
        raise ArtifactBundleError("model_version is required")
    if not request.model_name:
        raise ArtifactBundleError("model_name is required")
    if not request.algorithm:
        raise ArtifactBundleError("algorithm is required")
    if not request.feature_schema.features_version:
        raise ArtifactBundleError("features_version is required")
    if not request.provenance.dataset_id:
        raise ArtifactBundleError("dataset_id is required")
    if not request.provenance.training_commit:
        raise ArtifactBundleError("training_commit is required")
    if not request.provenance.label_policy_ref:
        raise ArtifactBundleError("label_policy_ref is required")
    if not request.provenance.library_versions:
        raise ArtifactBundleError("library_versions is required")


def _validate_optional_pickle(
    root: Path,
    filename: str,
    expected_sha256: object,
) -> None:
    path = root / filename
    if not path.exists():
        if expected_sha256 is not None:
            raise ArtifactBundleError(
                f"metrics.json declares {filename.replace('.pkl', '_sha256')} "
                f"but {filename} is missing"
            )
        return
    if expected_sha256 is None:
        raise ArtifactBundleError(f"missing checksum for optional artifact: {filename}")
    if not isinstance(expected_sha256, str):
        raise ArtifactBundleError(f"checksum for {filename} must be a string")
    _assert_lowercase_sha256(expected_sha256, field=filename)
    _verify_checksum(path, expected_sha256)


def _verify_checksum(path: Path, expected_sha256: str) -> None:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ArtifactBundleError(f"checksum mismatch for {path.name}")


def _require_label_provenance(metrics: Mapping[str, object]) -> None:
    label_policy_ref = metrics.get("label_policy_ref")
    label_rule_id = metrics.get("label_rule_id")
    if isinstance(label_policy_ref, str) and label_policy_ref:
        return
    if isinstance(label_rule_id, str) and label_rule_id:
        return
    raise ArtifactBundleError(
        "metrics.json missing required label provenance (label_policy_ref or label_rule_id)"
    )


def _require_string(payload: Mapping[str, object], field: str, *, where: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ArtifactBundleError(f"{where} missing required field: {field}")
    return value


def _require_string_list(
    payload: Mapping[str, object],
    field: str,
    *,
    where: str,
) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ArtifactBundleError(f"{where} missing required field: {field}")
    if not all(isinstance(item, str) for item in value):
        raise ArtifactBundleError(f"{where} field '{field}' must be a list of strings")
    return value


def _require_lowercase_sha256(
    payload: Mapping[str, object],
    field: str,
    *,
    where: str,
) -> str:
    value = _require_string(payload, field, where=where)
    _assert_lowercase_sha256(value, field=field)
    return value


def _assert_lowercase_sha256(value: str, *, field: str) -> None:
    if len(value) != _SHA256_HEX_LENGTH or any(ch in "ABCDEF" for ch in value):
        raise ArtifactBundleError(f"{field} must be lowercase hex SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ArtifactBundleError(f"{field} must be lowercase hex SHA-256") from exc


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactBundleError(f"failed to read {path.name}") from exc
    if not isinstance(raw, dict):
        raise ArtifactBundleError(f"{path.name} must be a JSON object")
    return raw


def required_bundle_filenames() -> Sequence[str]:
    """Stable list of required filenames for contract documentation/tests."""
    return sorted(_REQUIRED_BUNDLE_FILES)
