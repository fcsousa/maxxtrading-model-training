# T24 challenger evaluation evidence

**Repo**: `maxxtrading-model-training`  
**Branch**: `feature/mlflow-p4-challenger-shadow`  
**Acceptance**: `docs/shadow-acceptance.md` (`shadow-acceptance-v1`, signed
2026-08-11 by fcsousa as ML+Produto)

---

## Synthetic offline run (historical)

**Date**: 2026-08-11  
**AUTH**: offline synthetic fixtures only — **no** real DB, **no** production
MLflow registry write, **no** `DATABASE_URL` do Score Engine.

### Verdict

**PASS** — `evaluate_challenger(...).overall_verdict == "PASS"` and
`validate_artifact_bundle` succeeded for the exported bundle.

This records the approved **synthetic** run required by T24's "one recorded
approved run" Done-when. Superseded for Heavy/real status by the section
below; kept for audit of the offline path.

### Fixed inputs

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

### Observed metrics

| Metric | Observed |
| --- | --- |
| `auc_roc` | `1.0` |
| `brier_score` | `1.056925805761123e-05` |
| `ece` | `0.003251039534918525` |
| `p95_latency_ratio_vs_baseline` | `~1.01` (probe N=220; warm-up applied) |
| `rss_delta_mib` | `0.0` |

### Gate results (`shadow-acceptance-v1`)

| ID | Verdict |
| --- | --- |
| Q1 | PASS |
| Q2 | PASS |
| Q3 | PASS |
| B1 | PASS |
| G1 | PASS |
| L1 | PASS |
| M1 | PASS |

### Bundle

- `model_version`: `challenger_synth_v1`
- `algorithm`: `lightgbm`
- `training_run_id`: `t24-synthetic-recorded-1`
- Contract: `validate_artifact_bundle` green after `export_challenger_bundle`

### Library versions (run host)

| Library | Version |
| --- | --- |
| lightgbm | 4.7.0 |
| scikit-learn | 1.9.0 |
| numpy | 2.4.6 |

---

## AUTH / connectivity (earlier attempt, 2026-08-11)

Operator authorized real training. First agent host could not reach
`192.168.3.10:5432` (`ECONNREFUSED` / connection closed). No SELECT of trading
rows; Heavy/real deferred until LAN path available. DSN/password not recorded.

---

## Heavy/real run (2026-08-12)

**AUTH**: user explicitly authorized Heavy/real T24 with `TRAINING_DATABASE_URL`
RO (session claim). Executed on a host with LAN access to the RO Postgres.
**Verdict**: **FAIL** — holdout N ≥ 200 achieved; Q1–Q3 and B1/G1 failed;
L1/M1 passed. Bundle export skipped (`overall_verdict != PASS`). No MLflow
registry writes (T25 out of scope). Not a fabricated PASS.

This section refreshes the authorized Heavy/real evaluation with the run
recorded below (same T8 window / `n_max=2000`; deterministic quality metrics
match prior Heavy attempt; probe latency re-measured on this host).

### Preflight (sanitized)

| Check | Result |
| --- | --- |
| Source URL | `TRAINING_DATABASE_URL` only |
| Score Engine `DATABASE_URL` | **not used** |
| Username contains `readonly` | yes (`scoreengine_readonly`) |
| DB name | `maxxtrading` |
| URL ≠ `DATABASE_URL` | yes |
| Host / port | `192.168.3.10:5432` |
| Dialect | `postgresql+psycopg` |
| `SELECT 1` | OK (`1`) |
| Write probe `CREATE TEMP TABLE` | **REJECTED** — `psycopg.errors.ReadOnlySqlTransaction` / SQLAlchemy `InternalError` |

### Export smoke inputs

T8 window preserved; `n_max` raised so holdout can reach `MIN_HOLDOUT_SAMPLES`
(200). Partition boundaries unchanged from T8.

| Param | Value |
| --- | --- |
| `window_start` | `2025-07-29T00:00:00+00:00` |
| `window_end` / `as_of` / `holdout_end` | `2026-07-02T00:00:00+00:00` |
| `train_end` | `2025-11-01T00:00:00+00:00` |
| `validation_end` | `2026-03-01T00:00:00+00:00` |
| `n_max` | `2000` |
| `label_policy_ref` | `docs/label-policy.md` |
| `seed` | `42` |
| FD | `/workspace/app/artifacts/feature_dictionary_v1.json` (read-only) |

### Smoke coverage / partitions

| Item | Value |
| --- | --- |
| `labels_eligible` | 4997 |
| `packs_succeeded` | 4582 |
| `batch_size` / vectorized | 2000 / 2000 (partial 0, skipped 0) |
| `dataset_id` | `5813bf7570916a351ca1feaca64b82adeb5193ae0cdd57bd2a6e275beeb20a9d` |
| train / validation / holdout | 128 / 1565 / 307 |
| train win/loss | 73 / 55 |
| holdout win/loss | 174 / 133 |

### Challenger eval config

| Input | Value |
| --- | --- |
| `ChallengerConfig.seed` | `42` |
| algorithm / params | LightGBM V1 defaults (`challenger_config.py`) |
| `baseline_predict` | peer LightGBM **same defaults**, `random_state=0` (L1 fairness; not production `baseline_heuristic`) |
| `business_proxy_delta` (B1) | `None` — fail-closed until T26; no honest grade-A `result_r` without inventing Score Engine grades |
| `max_grade_share_delta_pp` (G1) | `None` — fail-closed until T26 |

### Observed metrics (signed holdout)

| Metric | Observed |
| --- | --- |
| `auc_roc` | `0.5127041742286751` |
| `brier_score` | `0.3719825391593575` |
| `ece` | `0.3337181837595723` |
| `holdout_n` | `307` |
| `p95_latency_ratio_vs_baseline` | `1.2425715487536781` (probe N=307) |
| `rss_delta_mib` | `0.0` |
| baseline / challenger p95 ms | `1.4447028021095312` / `1.7951465983060189` |

### Gate results (`shadow-acceptance-v1`)

| ID | Verdict | Observed | Threshold |
| --- | --- | --- | --- |
| Q1 | FAIL | `0.5127041742286751` | auc_roc ≥ 0.55 |
| Q2 | FAIL | `0.3719825391593575` | brier_score ≤ 0.25 |
| Q3 | FAIL | `0.3337181837595723` | ece ≤ 0.10 |
| B1 | FAIL | `None` (fail-closed) | mean_result_r_at_grade_A_delta ≥ 0.0 |
| G1 | FAIL | `None` (fail-closed) | max_abs_grade_share_delta_pp ≤ 15.0 |
| L1 | PASS | `1.2425715487536781` | p95_latency_ratio_vs_baseline ≤ 2.0 |
| M1 | PASS | `0.0` | rss_delta_mib ≤ 256.0 |

**overall_verdict**: `FAIL`

### Bundle

Skipped — `export_challenger_bundle` refuses non-PASS evaluations. No
`validate_artifact_bundle` for this run. No MLflow registry write.

### Library versions (Heavy/real host)

| Library | Version |
| --- | --- |
| lightgbm | 4.7.0 |
| scikit-learn | 1.9.0 |
| numpy | 2.4.6 |

### Blockers remaining

- Quality gates Q1–Q3 failed on this real holdout (train N=128 under T8
  temporal cut with `n_max=2000` may contribute; retuning / larger train share
  needs a new signed run — do not waive thresholds).
- B1/G1 remain fail-closed until T26 (or honest `result_r` + grade computation
  from Score Engine thresholds without inventing grades).
- T25 MLflow registry / alias moves still out of scope.
- Production `baseline_v1` / `baseline_heuristic` serving-image probe not used
  here (peer LGBM only for L1/M1 fairness).

### Commands run (sanitized)

```bash
cd /home/app/maxxtrading-model-training
# preflight: SELECT 1 + CREATE TEMP TABLE via TRAINING_DATABASE_URL (postgresql+psycopg)
# WRITE_PROBE REJECTED (ReadOnlySqlTransaction)
uv run python  # run_export_smoke(... n_max=2000, seed=42, FD read-only)
uv run python  # peer LGBM seed=0; evaluate_challenger(... B1/G1=None)
# export_challenger_bundle / validate_artifact_bundle: skipped (FAIL)
```

Secrets, full DSNs, and passwords were never printed.

---

## CQ-v1 Heavy/real (AUTH T9, 2026-08-12)

**AUTH**: user explicitly authorized Heavy/real T9 with subagent; `TRAINING_DATABASE_URL`
RO only (never Score Engine `DATABASE_URL`); no MLflow registry writes; no invented PASS.
**Entrypoint**: `run_quality_export` + `evaluate_challenger_quality` (full Q1–M1, offline B1/G1).
**Verdict**: **FAIL** — quotas filled; holdout ≥ 200; Q1–Q3 failed quality thresholds;
B1/G1/L1/M1 passed. Bundle export skipped. Not a fabricated PASS.

Synthetic PASS and prior T8 smoke Heavy/real FAIL sections above remain for audit history.

### Preflight (sanitized)

| Check | Result |
| --- | --- |
| Source URL | `TRAINING_DATABASE_URL` only |
| Score Engine `DATABASE_URL` | **not used** |
| Username contains `readonly` | yes |
| DB name | `maxxtrading` |
| URL ≠ `DATABASE_URL` | yes |
| Dialect | `postgresql+psycopg` (scheme rewrite from `postgresql://`) |
| `SELECT 1` | OK (`1`) |
| Write probe `CREATE TEMP TABLE` | **REJECTED** — `psycopg.errors.ReadOnlySqlTransaction` / SQLAlchemy `InternalError` |

### Enabling fix (session)

Postgres `NUMERIC` `result_r` arrives as `Decimal` via psycopg. `label_export` now
coerces `Decimal|int|float` → `float` (null stays `None`, no imputation) so CQ-09
offline B1 can run against real rows.

### Quality export inputs (attempt 1 — quotas filled; no alternate needed)

| Param | Value |
| --- | --- |
| `window_start` | `2025-07-29T00:00:00+00:00` |
| `window_end` / `as_of` / `holdout_end` | `2026-07-02T00:00:00+00:00` |
| `train_end` | `2026-01-15T00:00:00+00:00` (later than T8 `2025-11-01`) |
| `validation_end` | `2026-04-01T00:00:00+00:00` |
| Quotas | `train_min=800`, `validation_min=200`, `holdout_min=200`, `n_max=5000` |
| `include_categoricals` | `True` (`trend_regime`, `volatility_regime`) |
| `seed` | `42` |
| `label_policy_ref` | `docs/label-policy.md` |
| FD | `/workspace/app/artifacts/feature_dictionary_v1.json` (read-only) |
| Thresholds | `/workspace/app/artifacts/thresholds.json` (read-only) |

### Coverage / partitions

| Item | Value |
| --- | --- |
| `labels_eligible` | 4997 |
| `packs_succeeded` | 4582 |
| `batch_size` / vectorized | 4551 / 4551 (partial 0, skipped 0) |
| `feature_dim` | 18 (12 numerical + encoded cats) |
| `dataset_id` | `95764ac113dd7158193792aabb31c094b4a305247059cb90a8f42cc0049e11de` |
| train / validation / holdout | 890 / 1361 / 2300 |
| train win/loss | 502 / 388 |
| holdout win/loss | 1248 / 1052 |
| holdout `result_r` non-null | 2300 |

### Challenger eval config

| Input | Value |
| --- | --- |
| Path | `evaluate_challenger_quality` |
| `ChallengerConfig.seed` | `42` |
| algorithm / params | LightGBM V1 defaults (`challenger_config.py`) |
| `baseline_predict` | peer LightGBM same defaults, `seed=0` (L1 fairness) |
| `thresholds_path` | SE `thresholds.json` RO |
| `result_r_by_sample_id` | from holdout labels |
| `grade_confidence` | `0.8` |
| `risk_reward_ratio` | `2.0` |

### Observed metrics (signed holdout)

| Metric | Observed |
| --- | --- |
| `auc_roc` | `0.4932812652334991` |
| `brier_score` | `0.26717657302828496` |
| `ece` | `0.10750721869139082` |
| `holdout_n` | `2300` |
| `mean_result_r_at_grade_A_delta` (B1) | `0.0` |
| `max_abs_grade_share_delta_pp` (G1) | `0.0` |
| `p95_latency_ratio_vs_baseline` | `0.9945174516879862` (probe N=2300) |
| `rss_delta_mib` | `0.0` |
| baseline / challenger p95 ms | `1.0967615504341661` / `1.0907485022471517` |

### Gate results (`shadow-acceptance-v1`)

| ID | Verdict | Observed | Threshold |
| --- | --- | --- | --- |
| Q1 | FAIL | `0.4932812652334991` | auc_roc ≥ 0.55 |
| Q2 | FAIL | `0.26717657302828496` | brier_score ≤ 0.25 |
| Q3 | FAIL | `0.10750721869139082` | ece ≤ 0.10 |
| B1 | PASS | `0.0` | mean_result_r_at_grade_A_delta ≥ 0.0 |
| G1 | PASS | `0.0` | max_abs_grade_share_delta_pp ≤ 15.0 |
| L1 | PASS | `0.9945174516879862` | p95_latency_ratio_vs_baseline ≤ 2.0 |
| M1 | PASS | `0.0` | rss_delta_mib ≤ 256.0 |

**overall_verdict**: `FAIL`

### Bundle

Skipped — `export_challenger_bundle` refuses non-PASS. No `validate_artifact_bundle`.
No MLflow registry write.

### Library versions (Heavy/real host)

| Library | Version |
| --- | --- |
| lightgbm | 4.7.0 |
| scikit-learn | 1.9.0 |
| numpy | 2.4.6 |

### Blockers remaining

- Q1–Q3 still fail on this real holdout despite larger train (890 vs T8 smoke 128)
  and cats + offline B1/G1. Do **not** waive `shadow-acceptance-v1` thresholds.
- Model/feature work needed for quality; T26 online shadow orchestration remains
  separate. T25 MLflow registry still out of scope.

### Commands run (sanitized)

```bash
cd /home/app/maxxtrading-model-training
# preflight: SELECT 1 + CREATE TEMP TABLE via TRAINING_DATABASE_URL (postgresql+psycopg)
# WRITE_PROBE REJECTED (ReadOnlySqlTransaction)
uv run python  # run_quality_export(... train_end=2026-01-15, validation_end=2026-04-01,
               # quotas DEFAULT 800/200/200/n_max=5000, include_categoricals=True, seed=42)
uv run python  # peer LGBM seed=0; evaluate_challenger_quality(... thresholds RO, result_r)
# export_challenger_bundle / validate_artifact_bundle: skipped (FAIL)
```

Secrets, full DSNs, and passwords were never printed.
