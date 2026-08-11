# T24 challenger evaluation evidence (synthetic offline run)

**Date**: 2026-08-11  
**Repo**: `maxxtrading-model-training`  
**Branch**: `feature/mlflow-p4-challenger-shadow`  
**Acceptance**: `docs/shadow-acceptance.md` (`shadow-acceptance-v1`, signed
2026-08-11 by fcsousa as ML+Produto)  
**AUTH**: offline synthetic fixtures only — **no** real DB, **no** production
MLflow registry write, **no** `DATABASE_URL` do Score Engine.

## Verdict

**PASS** — `evaluate_challenger(...).overall_verdict == "PASS"` and
`validate_artifact_bundle` succeeded for the exported bundle.

This records the approved **synthetic** run required by T24's "one recorded
approved run" Done-when. A real holdout against `TRAINING_DATABASE_URL` (RO
dedicada) permanece **pendente** até autorização explícita de recurso.

## Fixed inputs

| Input | Value |
| --- | --- |
| `dataset_id` | `ds-synth-t24-recorded` (synthetic) |
| holdout N | 220 (≥ 200) |
| train N | 80 (40 win / 40 loss) |
| `ChallengerConfig.seed` | `7` |
| algorithm | `lightgbm` (V1 defaults in `challenger_config.py`) |
| B1 (injected for offline gate) | `+0.05` R (grade-A proxy delta) |
| G1 (injected for offline gate) | `5.0` pp |
| baseline probe peer | LightGBM same defaults, `seed=0` (latency-fair peer; not production `baseline_heuristic`) |

## Observed metrics

| Metric | Observed |
| --- | --- |
| `auc_roc` | `1.0` |
| `brier_score` | `1.056925805761123e-05` |
| `ece` | `0.003251039534918525` |
| `p95_latency_ratio_vs_baseline` | `~1.01` (probe N=220; warm-up applied) |
| `rss_delta_mib` | `0.0` |

## Gate results (`shadow-acceptance-v1`)

| ID | Verdict |
| --- | --- |
| Q1 | PASS |
| Q2 | PASS |
| Q3 | PASS |
| B1 | PASS |
| G1 | PASS |
| L1 | PASS |
| M1 | PASS |

## Bundle

- `model_version`: `challenger_synth_v1`
- `algorithm`: `lightgbm`
- `training_run_id`: `t24-synthetic-recorded-1`
- Contract: `validate_artifact_bundle` green after `export_challenger_bundle`

## Library versions (run host)

| Library | Version |
| --- | --- |
| lightgbm | 4.7.0 |
| scikit-learn | 1.9.0 |
| numpy | 2.4.6 |

## Out of scope / blockers for Heavy/real

- Real dataset reconstruction via `TRAINING_DATABASE_URL` (RO dedicada)
- Probe against production `baseline_v1` / `baseline_heuristic` on the serving image
- MLflow registry registration (T25; requires separate auth)
- Score Engine T26 shadow orchestrator outputs for true B1/G1 population metrics
