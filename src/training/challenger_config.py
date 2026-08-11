"""Challenger training configuration for Phase 4 shadow (T24).

Default algorithm is LightGBM per the MLflow adoption TDD. Real training against
production-like data requires explicit resource authorization and a dedicated
read-only ``TRAINING_DATABASE_URL`` — never the Score Engine ``DATABASE_URL``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

DEFAULT_ALGORITHM: Final = "lightgbm"
DEFAULT_MODEL_NAME: Final = "score_model"
DEFAULT_SEED: Final = 42

# Conservative defaults for a first challenger; tune only with a new signed run.
_DEFAULT_LGBM_PARAMS: Final[dict[str, Any]] = {
    "n_estimators": 50,
    "learning_rate": 0.1,
    "num_leaves": 15,
    "min_child_samples": 5,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "reg_lambda": 0.0,
    "objective": "binary",
    "verbosity": -1,
}


@dataclass(frozen=True)
class ChallengerConfig:
    """Immutable challenger training/eval configuration."""

    algorithm: str = DEFAULT_ALGORITHM
    model_name: str = DEFAULT_MODEL_NAME
    seed: int = DEFAULT_SEED
    model_params: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_LGBM_PARAMS))
    label_policy_ref: str = "docs/label-policy.md"
    shadow_acceptance_version: str = "shadow-acceptance-v1"
    probe_repeats: int = 1

    def __post_init__(self) -> None:
        if self.algorithm != DEFAULT_ALGORITHM:
            raise ValueError(
                f"unsupported algorithm {self.algorithm!r}; V1 challenger is {DEFAULT_ALGORITHM}"
            )
        if self.seed is None:
            raise ValueError("seed is mandatory")
        if self.probe_repeats < 1:
            raise ValueError("probe_repeats must be >= 1")
