"""Train and evaluate the Phase 4 shadow challenger on a leakage-safe holdout (T24).

Fits only on ``partitions.train``. Holdout metrics never influence fitting.
Resource probes (p95-equivalent latency, RSS delta) are measured offline against
a baseline predict callable supplied by the caller.
"""

from __future__ import annotations

import importlib.metadata
import math
import resource
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb

from training.artifact_bundle import (
    BundleExportRequest,
    BundleProvenance,
    ExportedBundle,
    FeatureSchemaSpec,
    export_artifact_bundle,
)
from training.challenger_config import ChallengerConfig
from training.dataset_builder import DatasetPartitions
from training.shadow_acceptance import (
    MIN_HOLDOUT_SAMPLES,
    MIN_PROBE_REQUESTS,
    SIGNED_CRITERIA,
    compare,
    criterion_by_id,
)

PredictFn = Callable[[Sequence[Sequence[float]]], Sequence[float]]

_TRACKED_LIBRARIES = ("lightgbm", "scikit-learn", "numpy")


class ChallengerEvalError(Exception):
    """Raised when challenger training or evaluation cannot proceed safely."""


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    metric: str
    observed: float | None
    threshold: float
    operator: str
    verdict: str  # PASS | FAIL | BLOCKED


@dataclass(frozen=True)
class ChallengerEvaluation:
    config: ChallengerConfig
    dataset_id: str
    model: Any = field(repr=False)
    holdout_metrics: dict[str, float]
    probe_metrics: dict[str, float]
    criterion_results: tuple[CriterionResult, ...]
    overall_verdict: str
    library_versions: dict[str, str]


def _library_versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in _TRACKED_LIBRARIES}


def _matrix(
    sample_ids: Sequence[str],
    features_by_sample_id: Mapping[str, Sequence[float]],
) -> list[list[float]]:
    missing = [sample_id for sample_id in sample_ids if sample_id not in features_by_sample_id]
    if missing:
        raise ChallengerEvalError(
            f"missing feature vectors for {len(missing)} sample(s), e.g. {missing[:5]}"
        )
    return [list(features_by_sample_id[sample_id]) for sample_id in sample_ids]


def train_challenger(
    partitions: DatasetPartitions,
    features_by_sample_id: Mapping[str, Sequence[float]],
    *,
    dataset_id: str,
    config: ChallengerConfig | None = None,
) -> Any:
    """Fit the challenger exclusively on the train partition."""
    cfg = config or ChallengerConfig()
    if not dataset_id:
        raise ChallengerEvalError("dataset_id is mandatory")
    if not partitions.train:
        raise ChallengerEvalError("train partition is empty")

    labels = {sample.label for sample in partitions.train}
    if len(labels) < 2:
        raise ChallengerEvalError("train partition must contain both win and loss labels")

    train_ids = [sample.id for sample in partitions.train]
    x = _matrix(train_ids, features_by_sample_id)
    y = [sample.label for sample in partitions.train]

    params = dict(cfg.model_params)
    model = lgb.LGBMClassifier(random_state=cfg.seed, **params)
    model.fit(x, y)
    return model


def predict_proba_win(model: Any, rows: Sequence[Sequence[float]]) -> list[float]:
    probabilities = model.predict_proba(rows)
    classes = list(model.classes_)
    win_index = classes.index(1)
    return [float(row[win_index]) for row in probabilities]


def _auc_roc(y_true: Sequence[int], scores: Sequence[float]) -> float:
    pairs = sorted(zip(scores, y_true, strict=True), key=lambda item: item[0])
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ChallengerEvalError("holdout must contain both classes for auc_roc")
    rank_sum = 0.0
    for rank, (_score, label) in enumerate(pairs, start=1):
        if label == 1:
            rank_sum += rank
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _brier(y_true: Sequence[int], scores: Sequence[float]) -> float:
    return float(sum((p - y) ** 2 for p, y in zip(scores, y_true, strict=True)) / len(y_true))


def _ece(y_true: Sequence[int], scores: Sequence[float], *, n_bins: int = 10) -> float:
    totals = [0] * n_bins
    conf_sums = [0.0] * n_bins
    acc_sums = [0.0] * n_bins
    for prob, label in zip(scores, y_true, strict=True):
        clipped = min(max(prob, 0.0), 1.0 - 1e-12)
        index = min(n_bins - 1, int(clipped * n_bins))
        totals[index] += 1
        conf_sums[index] += clipped
        acc_sums[index] += label
    n = len(y_true)
    ece = 0.0
    for total, conf_sum, acc_sum in zip(totals, conf_sums, acc_sums, strict=True):
        if total == 0:
            continue
        ece += (total / n) * abs((acc_sum / total) - (conf_sum / total))
    return float(ece)


def evaluate_holdout_quality(
    model: Any,
    partitions: DatasetPartitions,
    features_by_sample_id: Mapping[str, Sequence[float]],
) -> dict[str, float]:
    if len(partitions.holdout) < MIN_HOLDOUT_SAMPLES:
        raise ChallengerEvalError(
            f"holdout N={len(partitions.holdout)} < {MIN_HOLDOUT_SAMPLES} (BLOCKED)"
        )
    holdout_ids = [sample.id for sample in partitions.holdout]
    x = _matrix(holdout_ids, features_by_sample_id)
    y = [sample.label for sample in partitions.holdout]
    scores = predict_proba_win(model, x)
    return {
        "auc_roc": _auc_roc(y, scores),
        "brier_score": _brier(y, scores),
        "ece": _ece(y, scores),
        "holdout_n": float(len(y)),
    }


def _rss_mib() -> float:
    # ru_maxrss is KiB on Linux.
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        raise ChallengerEvalError("percentile requires at least one value")
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def probe_latency_and_rss(
    challenger_predict: PredictFn,
    baseline_predict: PredictFn,
    rows: Sequence[Sequence[float]],
    *,
    repeats: int = 1,
) -> dict[str, float]:
    if not rows:
        raise ChallengerEvalError("probe rows must not be empty")
    payloads = list(rows) * max(1, repeats)
    while len(payloads) < MIN_PROBE_REQUESTS:
        payloads.extend(rows)
    payloads = payloads[: max(MIN_PROBE_REQUESTS, len(rows) * repeats)]

    def _latencies(predict: PredictFn) -> list[float]:
        # Warm-up avoids first-call import/JIT noise dominating the ratio.
        for row in payloads[:20]:
            predict([row])
        samples: list[float] = []
        for row in payloads:
            started = time.perf_counter()
            predict([row])
            samples.append((time.perf_counter() - started) * 1000.0)
        return samples

    baseline_rss_before = _rss_mib()
    baseline_latencies = _latencies(baseline_predict)
    baseline_rss = max(_rss_mib(), baseline_rss_before)

    challenger_rss_before = _rss_mib()
    challenger_latencies = _latencies(challenger_predict)
    challenger_rss = max(_rss_mib(), challenger_rss_before)

    baseline_p95 = _percentile(baseline_latencies, 95)
    challenger_p95 = _percentile(challenger_latencies, 95)
    if baseline_p95 <= 0.0:
        raise ChallengerEvalError("baseline p95_latency_ms must be > 0")

    return {
        "baseline_p95_latency_ms": baseline_p95,
        "challenger_p95_latency_ms": challenger_p95,
        "p95_latency_ratio_vs_baseline": challenger_p95 / baseline_p95,
        "baseline_rss_mib": baseline_rss,
        "challenger_rss_mib": challenger_rss,
        "rss_delta_mib": challenger_rss - baseline_rss,
        "probe_n": float(len(payloads)),
    }


def _verdict_for(criterion_id: str, observed: float | None) -> CriterionResult:
    criterion = criterion_by_id(criterion_id)
    if observed is None or not math.isfinite(observed):
        return CriterionResult(
            criterion_id=criterion_id,
            metric=criterion.metric,
            observed=observed,
            threshold=criterion.value,
            operator=criterion.operator,
            verdict="FAIL",
        )
    passed = compare(criterion.operator, observed, criterion.value)
    return CriterionResult(
        criterion_id=criterion_id,
        metric=criterion.metric,
        observed=observed,
        threshold=criterion.value,
        operator=criterion.operator,
        verdict="PASS" if passed else "FAIL",
    )


def gate_challenger_metrics(
    holdout_metrics: Mapping[str, float],
    probe_metrics: Mapping[str, float],
    *,
    business_proxy_delta: float | None = None,
    max_grade_share_delta_pp: float | None = None,
) -> tuple[CriterionResult, ...]:
    """Apply signed criteria. Missing B1/G1 values fail closed unless provided."""
    results = [
        _verdict_for("Q1", holdout_metrics.get("auc_roc")),
        _verdict_for("Q2", holdout_metrics.get("brier_score")),
        _verdict_for("Q3", holdout_metrics.get("ece")),
        _verdict_for("B1", business_proxy_delta),
        _verdict_for("G1", max_grade_share_delta_pp),
        _verdict_for("L1", probe_metrics.get("p95_latency_ratio_vs_baseline")),
        _verdict_for("M1", probe_metrics.get("rss_delta_mib")),
    ]
    return tuple(results)


def overall_verdict(results: Sequence[CriterionResult]) -> str:
    if any(result.verdict == "BLOCKED" for result in results):
        return "BLOCKED"
    if any(result.verdict != "PASS" for result in results):
        return "FAIL"
    return "PASS"


def evaluate_challenger(
    partitions: DatasetPartitions,
    features_by_sample_id: Mapping[str, Sequence[float]],
    *,
    dataset_id: str,
    baseline_predict: PredictFn,
    config: ChallengerConfig | None = None,
    business_proxy_delta: float | None = None,
    max_grade_share_delta_pp: float | None = None,
) -> ChallengerEvaluation:
    """Train on train-only, score holdout, probe resources, gate against T23."""
    cfg = config or ChallengerConfig()
    if len(partitions.holdout) < MIN_HOLDOUT_SAMPLES:
        raise ChallengerEvalError(
            f"holdout N={len(partitions.holdout)} < {MIN_HOLDOUT_SAMPLES} (BLOCKED)"
        )

    model = train_challenger(partitions, features_by_sample_id, dataset_id=dataset_id, config=cfg)
    holdout_metrics = evaluate_holdout_quality(model, partitions, features_by_sample_id)

    holdout_ids = [sample.id for sample in partitions.holdout]
    probe_rows = _matrix(holdout_ids, features_by_sample_id)

    def challenger_predict(rows: Sequence[Sequence[float]]) -> Sequence[float]:
        return predict_proba_win(model, rows)

    probe_metrics = probe_latency_and_rss(
        challenger_predict,
        baseline_predict,
        probe_rows,
        repeats=cfg.probe_repeats,
    )
    results = gate_challenger_metrics(
        holdout_metrics,
        probe_metrics,
        business_proxy_delta=business_proxy_delta,
        max_grade_share_delta_pp=max_grade_share_delta_pp,
    )
    return ChallengerEvaluation(
        config=cfg,
        dataset_id=dataset_id,
        model=model,
        holdout_metrics=holdout_metrics,
        probe_metrics=probe_metrics,
        criterion_results=results,
        overall_verdict=overall_verdict(results),
        library_versions=_library_versions(),
    )


def export_challenger_bundle(
    evaluation: ChallengerEvaluation,
    *,
    output_dir: str,
    feature_schema: FeatureSchemaSpec,
    model_version: str,
    training_commit: str,
    training_run_id: str | None = None,
) -> ExportedBundle:
    """Export a Score Engine-compatible bundle including evaluation metrics."""
    if evaluation.overall_verdict != "PASS":
        raise ChallengerEvalError(
            f"refusing to export bundle for overall_verdict={evaluation.overall_verdict}"
        )
    evaluation_metrics = {
        **evaluation.holdout_metrics,
        **{
            key: value
            for key, value in evaluation.probe_metrics.items()
            if key
            in {
                "p95_latency_ratio_vs_baseline",
                "rss_delta_mib",
                "challenger_p95_latency_ms",
                "baseline_p95_latency_ms",
            }
        },
    }
    for result in evaluation.criterion_results:
        if result.observed is not None:
            evaluation_metrics[f"gate_{result.criterion_id}_{result.metric}"] = result.observed

    provenance = BundleProvenance(
        dataset_id=evaluation.dataset_id,
        training_commit=training_commit,
        label_policy_ref=evaluation.config.label_policy_ref,
        seed=evaluation.config.seed,
        library_versions=evaluation.library_versions,
        training_run_id=training_run_id,
    )
    request = BundleExportRequest(
        model=evaluation.model,
        feature_schema=feature_schema,
        model_version=model_version,
        model_name=evaluation.config.model_name,
        algorithm=evaluation.config.algorithm,
        provenance=provenance,
        evaluation_metrics=evaluation_metrics,
    )
    return export_artifact_bundle(request, output_dir)


def signed_criterion_ids() -> tuple[str, ...]:
    return tuple(criterion.criterion_id for criterion in SIGNED_CRITERIA)
