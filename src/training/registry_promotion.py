"""Immutable challenger registration and candidate→staging alias moves (T25).

Follows Score Engine ``docs/mlflow/evidence/phase-3/registry-runbook.md``
(MLF-11 tags + alias rules). Real MLflow writes require explicit authorization
and run from the VPS (OF-4) — this module never embeds credentials.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Final, Protocol

ALLOWED_ALIASES: Final[frozenset[str]] = frozenset({"candidate", "staging"})
# production is intentionally excluded from this Phase 4 helper (Fase 5 only).

REQUIRED_MODEL_VERSION_TAGS: Final[frozenset[str]] = frozenset(
    {
        "algorithm",
        "features_version",
        "dataset_id",
        "label_rule_id",
        "training_commit",
        "training_run_id",
        "bundle_sha256",
        "approval_ref",
    }
)


class RegistryPromotionError(Exception):
    """Raised when registration or alias promotion is rejected."""


@dataclass(frozen=True)
class ModelVersionInfo:
    name: str
    version: str
    tags: Mapping[str, str]
    source: str
    run_id: str | None = None


@dataclass(frozen=True)
class RegistrationRequest:
    model_name: str
    source_uri: str
    tags: Mapping[str, str]
    run_id: str | None = None


@dataclass(frozen=True)
class AliasMoveRequest:
    model_name: str
    alias: str
    expected_current_version: str | None
    target_version: str
    approval_ref: str


class RegistryClient(Protocol):
    def create_registered_model(self, name: str) -> None: ...

    def create_model_version(
        self,
        name: str,
        source: str,
        *,
        run_id: str | None,
        tags: Mapping[str, str],
    ) -> ModelVersionInfo: ...

    def get_model_version(self, name: str, version: str) -> ModelVersionInfo: ...

    def set_model_version_tag(self, name: str, version: str, key: str, value: str) -> None: ...

    def get_alias_version(self, name: str, alias: str) -> str | None: ...

    def set_registered_model_alias(self, name: str, alias: str, version: str) -> None: ...

    def version_source_exists(self, name: str, source: str) -> bool: ...


def _require_tags(tags: Mapping[str, str]) -> None:
    missing = sorted(REQUIRED_MODEL_VERSION_TAGS - set(tags))
    if missing:
        raise RegistryPromotionError(f"missing required provenance/tags: {missing}")
    for key in REQUIRED_MODEL_VERSION_TAGS:
        value = tags.get(key)
        if value is None or not str(value).strip():
            raise RegistryPromotionError(f"tag {key!r} must be a non-empty string")
    bundle = tags["bundle_sha256"].strip().lower()
    if len(bundle) != 64 or any(ch not in "0123456789abcdef" for ch in bundle):
        raise RegistryPromotionError("bundle_sha256 must be lowercase hex sha256")
    if bundle != tags["bundle_sha256"]:
        raise RegistryPromotionError("bundle_sha256 must be lowercase")


def register_immutable_challenger(
    client: RegistryClient,
    request: RegistrationRequest,
) -> ModelVersionInfo:
    """Register a new immutable model version; never overwrite an existing source."""
    if not request.model_name.strip():
        raise RegistryPromotionError("model_name is mandatory")
    if not request.source_uri.strip():
        raise RegistryPromotionError("source_uri is mandatory")
    _require_tags(request.tags)

    if client.version_source_exists(request.model_name, request.source_uri):
        raise RegistryPromotionError(
            "refusing to overwrite existing version contents for source_uri"
        )

    try:
        client.create_registered_model(request.model_name)
    except RegistryPromotionError:
        raise
    except Exception:
        # Model may already exist — creation is best-effort.
        pass

    version = client.create_model_version(
        request.model_name,
        request.source_uri,
        run_id=request.run_id,
        tags=dict(request.tags),
    )
    # Re-read and enforce tag completeness before any alias is allowed.
    loaded = client.get_model_version(request.model_name, version.version)
    _require_tags(loaded.tags)
    return loaded


def move_alias(
    client: RegistryClient,
    request: AliasMoveRequest,
) -> str:
    """Move candidate/staging only when source/target versions and approval match."""
    if request.alias not in ALLOWED_ALIASES:
        raise RegistryPromotionError(
            f"alias {request.alias!r} not allowed here; use candidate|staging only"
        )
    if not request.approval_ref.strip():
        raise RegistryPromotionError("approval_ref is mandatory for alias moves")
    if not request.target_version.strip():
        raise RegistryPromotionError("target_version is mandatory")

    current = client.get_alias_version(request.model_name, request.alias)
    if current != request.expected_current_version:
        raise RegistryPromotionError(
            "alias current version mismatch: "
            f"expected {request.expected_current_version!r}, found {current!r}"
        )

    target = client.get_model_version(request.model_name, request.target_version)
    _require_tags(target.tags)
    if target.tags.get("approval_ref", "").strip() != request.approval_ref.strip():
        raise RegistryPromotionError(
            "approval_ref on model version must equal AliasMoveRequest.approval_ref"
        )

    client.set_registered_model_alias(request.model_name, request.alias, request.target_version)
    return request.target_version


def promote_candidate_then_staging(
    client: RegistryClient,
    *,
    model_name: str,
    version: str,
    candidate_approval_ref: str,
    staging_approval_ref: str,
    expected_candidate_version: str | None = None,
    expected_staging_version: str | None = None,
) -> tuple[str, str]:
    """Move ``candidate`` then ``staging`` to the same immutable version."""
    candidate = move_alias(
        client,
        AliasMoveRequest(
            model_name=model_name,
            alias="candidate",
            expected_current_version=expected_candidate_version,
            target_version=version,
            approval_ref=candidate_approval_ref,
        ),
    )
    staging = move_alias(
        client,
        AliasMoveRequest(
            model_name=model_name,
            alias="staging",
            expected_current_version=expected_staging_version,
            target_version=version,
            approval_ref=staging_approval_ref,
        ),
    )
    return candidate, staging


@dataclass
class InMemoryRegistryClient:
    """Deterministic fake for unit tests — no network, no credentials."""

    models: MutableMapping[str, dict[str, ModelVersionInfo]] = field(default_factory=dict)
    aliases: MutableMapping[str, dict[str, str]] = field(default_factory=dict)
    _next_version: MutableMapping[str, int] = field(default_factory=dict)

    def create_registered_model(self, name: str) -> None:
        self.models.setdefault(name, {})
        self.aliases.setdefault(name, {})
        self._next_version.setdefault(name, 1)

    def create_model_version(
        self,
        name: str,
        source: str,
        *,
        run_id: str | None,
        tags: Mapping[str, str],
    ) -> ModelVersionInfo:
        self.create_registered_model(name)
        if self.version_source_exists(name, source):
            raise RegistryPromotionError(
                "refusing to overwrite existing version contents for source_uri"
            )
        version = str(self._next_version[name])
        self._next_version[name] += 1
        info = ModelVersionInfo(
            name=name,
            version=version,
            tags=dict(tags),
            source=source,
            run_id=run_id,
        )
        self.models[name][version] = info
        return info

    def get_model_version(self, name: str, version: str) -> ModelVersionInfo:
        try:
            return self.models[name][version]
        except KeyError as exc:
            raise RegistryPromotionError(f"model version not found: {name}/{version}") from exc

    def set_model_version_tag(self, name: str, version: str, key: str, value: str) -> None:
        current = self.get_model_version(name, version)
        updated = ModelVersionInfo(
            name=current.name,
            version=current.version,
            tags={**dict(current.tags), key: value},
            source=current.source,
            run_id=current.run_id,
        )
        self.models[name][version] = updated

    def get_alias_version(self, name: str, alias: str) -> str | None:
        return self.aliases.get(name, {}).get(alias)

    def set_registered_model_alias(self, name: str, alias: str, version: str) -> None:
        self.get_model_version(name, version)
        self.aliases.setdefault(name, {})[alias] = version

    def version_source_exists(self, name: str, source: str) -> bool:
        return any(info.source == source for info in self.models.get(name, {}).values())
