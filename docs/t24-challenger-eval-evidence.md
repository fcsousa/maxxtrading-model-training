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

### Preflight (sanitized)

| Check | Result |
| --- | --- |
| Source URL | `TRAINING_DATABASE_URL` only |
| Score Engine `DATABASE_URL` | **not used** (db `maxxtrading-scoreengine`, user `postgres`) |
| Username contains `readonly` | yes (`scoreengine_readonly`) |
| DB name | `maxxtrading` |
| URL ≠ `DATABASE_URL` | yes |
| Host / port | `192.168.3.10:5432` |
| Dialect | `postgresql+psycopg` |
| `SELECT 1` | OK (`1`) |
| Write probe `CREATE TEMP TABLE` | **REJECTED** — `psycopg.errors.ReadOnlySqlTransaction` / SQLAlchemy `InternalError` |

### Export smoke inputs

T8 window preserved; `n_max` raised so holdout can reach `MIN_HOLDOUT_SAMPLES`
(200). Partition boundaries unchanged from T8 (temporal split already yields
holdout ≥ 200 at `n_max=2000`).

| Param | Value |
| --- | --- |
| `window_start` | `2025-07-29T00:00:00+00:00` |
| `window_end` / `as_of` / `holdout_end` | `2026-07-02T00:00:00+00:00` |
| `train_end` | `2025-11-01T00:00:00+00:00` |
| `validation_end` | `2026-03-01T00:00:00+00:00` |
| `n_max` | `2000` (T8 used 100; first successful Heavy attempt) |
| `label_policy_ref` | `docs/label-policy.md` |
| `seed` | `42` |
| FD | `/workspace/app/artifacts/feature_dictionary_v1.json` (read-only) |

Tried: `n_max=2000` with T8 boundaries — sufficient (`holdout_n=307`). No need
for wider calendar window.

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
| `business_proxy_delta` (B1) | `None` — `LabeledTradeSample` has no `result_r`; no Score Engine grades in this path |
| `max_grade_share_delta_pp` (G1) | `None` — deferred pending T26 shadow orchestrator |

### Observed metrics (signed holdout)

| Metric | Observed |
| --- | --- |
| `auc_roc` | `0.5127041742286751` |
| `brier_score` | `0.3719825391593575` |
| `ece` | `0.3337181837595723` |
| `holdout_n` | `307` |
| `p95_latency_ratio_vs_baseline` | `1.0676743153767` (probe N=307) |
| `rss_delta_mib` | `0.0` |
| baseline / challenger p95 ms | `~1.004` / `~1.072` |

### Gate results (`shadow-acceptance-v1`)

| ID | Verdict | Notes |
| --- | --- | --- |
| Q1 | FAIL | auc < 0.55 |
| Q2 | FAIL | brier > 0.25 |
| Q3 | FAIL | ece > 0.10 |
| B1 | FAIL | fail-closed (`None`); no grade-A R without Score Engine grading |
| G1 | FAIL | fail-closed (`None`); grade shares need T26 |
| L1 | PASS | ratio ≤ 2.0 |
| M1 | PASS | rss delta ≤ 256 MiB |

**overall_verdict**: `FAIL`

### Bundle

Skipped — `export_challenger_bundle` refuses non-PASS evaluations. No
`model_sha256` recorded.

### Library versions (Heavy/real host)

| Library | Version |
| --- | --- |
| lightgbm | 4.7.0 |
| scikit-learn | 1.9.0 |
| numpy | 2.4.6 |

### Blockers remaining

- Quality gates Q1–Q3 failed on this real holdout (small train N=128 under T8
  temporal cut with `n_max=2000` may contribute; retuning / larger train share
  needs a new signed run — do not waive thresholds).
- B1/G1 remain fail-closed until T26 (or honest `result_r` + grade computation
  from Score Engine thresholds).
- T25 MLflow registry / alias moves still out of scope.
- Production `baseline_v1` / `baseline_heuristic` serving-image probe not used
  here (peer LGBM only for L1/M1 fairness).

### Commands run (sanitized)

```bash
cd /home/app/maxxtrading-model-training
# preflight: SELECT 1 + CREATE TEMP TABLE via TRAINING_DATABASE_URL (postgresql+psycopg)
uv run python  # run_export_smoke(... n_max=2000, seed=42, FD read-only)
uv run python  # peer LGBM seed=0; evaluate_challenger(... B1/G1=None)
uv run pytest tests/test_challenger_eval.py -q
```

Secrets, full DSNs, and passwords were never printed.
