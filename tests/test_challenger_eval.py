"""Tests for Phase 4 challenger train/eval gates (T24 / MLF-15)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from training.artifact_bundle import FeatureSchemaSpec, validate_artifact_bundle
from training.challenger_config import ChallengerConfig
from training.challenger_eval import (
    ChallengerEvalError,
    evaluate_challenger,
    evaluate_challenger_quality,
    export_challenger_bundle,
    gate_challenger_metrics,
    overall_verdict,
    predict_proba_win,
    train_challenger,
)
from training.dataset_builder import DatasetPartitions
from training.label_export import LabeledTradeSample
from training.shadow_acceptance import (
    DOCUMENT_PATH,
    MIN_HOLDOUT_SAMPLES,
    SIGNED_CRITERIA,
    compare,
    criterion_by_id,
)


def _sample(sample_id: str, label: int) -> LabeledTradeSample:
    return LabeledTradeSample(
        id=sample_id,
        source_type="live_order",
        entry_at=datetime(2026, 1, 1),
        exit_at=datetime(2026, 1, 2),
        symbol="BTCUSDT",
        timeframe="15m",
        side="long",
        label=label,
        entry_indicator_pack_id=None,
    )


def _separable_partitions(
    *,
    train_per_class: int = 40,
    holdout_per_class: int = 110,
) -> tuple[DatasetPartitions, dict[str, list[float]]]:
    train: list[LabeledTradeSample] = []
    holdout: list[LabeledTradeSample] = []
    features: dict[str, list[float]] = {}

    def _add(bucket: list[LabeledTradeSample], prefix: str, count: int, label: int) -> None:
        for index in range(count):
            sample_id = f"{prefix}-{label}-{index}"
            bucket.append(_sample(sample_id, label))
            noise = (hash(sample_id) % 7) * 0.01
            base = 1.5 if label == 1 else -1.5
            features[sample_id] = [base + noise, base * 0.5 + noise, float(label)]

    _add(train, "tr", train_per_class, 1)
    _add(train, "tr", train_per_class, 0)
    _add(holdout, "ho", holdout_per_class, 1)
    _add(holdout, "ho", holdout_per_class, 0)

    partitions = DatasetPartitions(train=tuple(train), validation=(), holdout=tuple(holdout))
    return partitions, features


def _fit_baseline_predict(partitions: DatasetPartitions, features: dict[str, list[float]]):
    """Peer-cost baseline: LightGBM with the same V1 defaults (latency-fair probe)."""
    model = train_challenger(
        partitions,
        features,
        dataset_id="baseline-peer",
        config=ChallengerConfig(seed=0),
    )

    def _predict(rows):
        return predict_proba_win(model, rows)

    return _predict


class TestShadowAcceptanceParity:
    def test_signed_constants_match_document(self) -> None:
        text = Path(DOCUMENT_PATH).read_text(encoding="utf-8")
        for criterion in SIGNED_CRITERIA:
            assert criterion.criterion_id in text
            renderings = {
                str(criterion.value),
                f"{criterion.value:g}",
                f"{criterion.value:.2f}",
                f"{criterion.value:.1f}",
                str(int(criterion.value)) if criterion.value.is_integer() else "",
            }
            assert any(token and token in text for token in renderings), criterion

    def test_compare_does_not_round_toward_pass(self) -> None:
        q1 = criterion_by_id("Q1")
        assert compare(q1.operator, 0.55, q1.value) is True
        assert compare(q1.operator, 0.549999999, q1.value) is False


class TestLeakageGuards:
    def test_holdout_below_minimum_is_blocked(self) -> None:
        partitions, features = _separable_partitions(holdout_per_class=50)
        assert len(partitions.holdout) < MIN_HOLDOUT_SAMPLES

        with pytest.raises(ChallengerEvalError, match="BLOCKED"):
            evaluate_challenger(
                partitions,
                features,
                dataset_id="ds-synth-1",
                baseline_predict=_fit_baseline_predict(partitions, features),
                business_proxy_delta=0.0,
                max_grade_share_delta_pp=0.0,
            )

    def test_train_does_not_require_holdout_features(self) -> None:
        partitions, features = _separable_partitions()
        holdout_only = {sample.id: features[sample.id] for sample in partitions.holdout}
        train_only = {sample.id: features[sample.id] for sample in partitions.train}

        model = train_challenger(partitions, train_only, dataset_id="ds-1")
        # Holdout vectors unused during fit — proving holdout map can be absent.
        assert model is not None
        assert partitions.holdout[0].id not in train_only
        assert partitions.holdout[0].id in holdout_only


class TestGateFailClosed:
    def test_missing_business_and_grade_metrics_fail(self) -> None:
        results = gate_challenger_metrics(
            {"auc_roc": 0.9, "brier_score": 0.1, "ece": 0.05},
            {"p95_latency_ratio_vs_baseline": 1.1, "rss_delta_mib": 10.0},
        )
        by_id = {result.criterion_id: result for result in results}
        assert by_id["B1"].verdict == "FAIL"
        assert by_id["G1"].verdict == "FAIL"
        assert overall_verdict(results) == "FAIL"

    def test_threshold_failure_is_not_rounded_away(self) -> None:
        results = gate_challenger_metrics(
            {"auc_roc": 0.549999999, "brier_score": 0.1, "ece": 0.05},
            {"p95_latency_ratio_vs_baseline": 1.0, "rss_delta_mib": 1.0},
            business_proxy_delta=0.0,
            max_grade_share_delta_pp=0.0,
        )
        assert overall_verdict(results) == "FAIL"
        assert next(result for result in results if result.criterion_id == "Q1").verdict == "FAIL"


class TestEndToEndSynthetic:
    def test_separable_challenger_emits_quality_and_probe_metrics(self) -> None:
        partitions, features = _separable_partitions()
        evaluation = evaluate_challenger(
            partitions,
            features,
            dataset_id="ds-synth-pass",
            baseline_predict=_fit_baseline_predict(partitions, features),
            config=ChallengerConfig(seed=7),
            business_proxy_delta=0.05,
            max_grade_share_delta_pp=5.0,
        )

        assert evaluation.holdout_metrics["auc_roc"] >= 0.55
        assert "brier_score" in evaluation.holdout_metrics
        assert "ece" in evaluation.holdout_metrics
        assert evaluation.probe_metrics["probe_n"] >= 200
        assert "p95_latency_ratio_vs_baseline" in evaluation.probe_metrics
        assert "rss_delta_mib" in evaluation.probe_metrics
        assert evaluation.overall_verdict == "PASS"

    def test_export_bundle_stays_green_on_pass(self, tmp_path: Path) -> None:
        partitions, features = _separable_partitions()
        evaluation = evaluate_challenger(
            partitions,
            features,
            dataset_id="ds-synth-bundle",
            baseline_predict=_fit_baseline_predict(partitions, features),
            business_proxy_delta=0.0,
            max_grade_share_delta_pp=0.0,
        )
        schema = FeatureSchemaSpec(
            features_version="feature_dictionary_v1",
            numeric_features=("f0", "f1", "f2"),
        )
        exported = export_challenger_bundle(
            evaluation,
            output_dir=str(tmp_path / "bundle"),
            feature_schema=schema,
            model_version="challenger_synth_v1",
            training_commit="a" * 40,
            training_run_id="t24-synthetic-1",
        )
        validate_artifact_bundle(exported.output_dir)
        assert exported.metrics["algorithm"] == "lightgbm"
        assert "evaluation" in exported.metrics

    def test_export_refuses_failed_evaluation(self, tmp_path: Path) -> None:
        partitions, features = _separable_partitions()
        evaluation = evaluate_challenger(
            partitions,
            features,
            dataset_id="ds-synth-fail-export",
            baseline_predict=_fit_baseline_predict(partitions, features),
            # Force FAIL via missing B1/G1 (None → fail closed).
        )
        assert evaluation.overall_verdict == "FAIL"
        with pytest.raises(ChallengerEvalError, match="refusing to export"):
            export_challenger_bundle(
                evaluation,
                output_dir=str(tmp_path / "bundle"),
                feature_schema=FeatureSchemaSpec(
                    features_version="feature_dictionary_v1",
                    numeric_features=("f0", "f1", "f2"),
                ),
                model_version="should_not_write",
                training_commit="b" * 40,
            )


_THRESHOLDS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "thresholds.json"


class TestChallengerQualityGate:
    def test_q1_fail_still_fails_overall_with_passing_b1_g1(self) -> None:
        """Isolation: Q1 FAIL keeps overall FAIL even when B1/G1 pass."""
        partitions, features = _separable_partitions()
        # Scramble holdout features so AUC collapses while B1/G1 are injected PASS.
        scrambled = dict(features)
        for index, sample in enumerate(partitions.holdout):
            scrambled[sample.id] = [0.01 * (index % 3), 0.0, 0.0]

        evaluation = evaluate_challenger(
            partitions,
            scrambled,
            dataset_id="ds-q1-isolation",
            baseline_predict=_fit_baseline_predict(partitions, features),
            business_proxy_delta=0.0,
            max_grade_share_delta_pp=0.0,
        )
        by_id = {result.criterion_id: result for result in evaluation.criterion_results}
        assert by_id["Q1"].verdict == "FAIL"
        assert by_id["B1"].verdict == "PASS"
        assert by_id["G1"].verdict == "PASS"
        assert evaluation.overall_verdict == "FAIL"

    def test_quality_path_can_pass_all_seven(self) -> None:
        partitions, features = _separable_partitions()
        # Peer baseline with same seed → near-identical grades (G1≈0); constant R → B1≈0.
        baseline_same_seed = train_challenger(
            partitions,
            features,
            dataset_id="baseline-peer-seed7",
            config=ChallengerConfig(seed=7),
        )

        def baseline_predict(rows):
            return predict_proba_win(baseline_same_seed, rows)

        result_r = {sample.id: 1.0 for sample in partitions.holdout}
        evaluation = evaluate_challenger_quality(
            partitions,
            features,
            dataset_id="ds-cq-pass-seven",
            baseline_predict=baseline_predict,
            thresholds_path=_THRESHOLDS_FIXTURE,
            result_r_by_sample_id=result_r,
            config=ChallengerConfig(seed=7),
            grade_confidence=0.8,
            risk_reward_ratio=2.0,
        )
        by_id = {result.criterion_id: result for result in evaluation.criterion_results}
        assert all(result.verdict == "PASS" for result in evaluation.criterion_results), by_id
        assert evaluation.overall_verdict == "PASS"
        assert len(SIGNED_CRITERIA) == 7

    def test_missing_result_r_on_grade_a_fails_b1(self) -> None:
        partitions, features = _separable_partitions()
        baseline_model = train_challenger(
            partitions,
            features,
            dataset_id="baseline-peer-seed7",
            config=ChallengerConfig(seed=7),
        )

        def baseline_predict(rows):
            return predict_proba_win(baseline_model, rows)

        # All result_r None → grade-A sets empty of R → B1 fail-closed.
        result_r = {sample.id: None for sample in partitions.holdout}
        evaluation = evaluate_challenger_quality(
            partitions,
            features,
            dataset_id="ds-cq-b1-fail",
            baseline_predict=baseline_predict,
            thresholds_path=_THRESHOLDS_FIXTURE,
            result_r_by_sample_id=result_r,
            config=ChallengerConfig(seed=7),
            grade_confidence=0.8,
            risk_reward_ratio=2.0,
        )
        by_id = {result.criterion_id: result for result in evaluation.criterion_results}
        assert by_id["B1"].verdict == "FAIL"
        assert evaluation.overall_verdict == "FAIL"
