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

## AUTH attempt (2026-08-11)

Operator authorized real training in-session. Sanitized preflight:

| Check | Result |
| --- | --- |
| `TRAINING_DATABASE_URL` present | yes |
| User contains `readonly` | yes (`scoreengine_readonly`) |
| DB name | `maxxtrading` (Nest training DB) |
| Distinct from Score Engine `DATABASE_URL` | yes (`maxxtrading-scoreengine` unused) |
| TCP connect `192.168.3.10:5432` from agent host | **FAIL** — server closed connection / unreachable from this environment |

No SELECT of trading rows was executed. No write attempted beyond the failed
connect. Heavy/real holdout run remains blocked on network path to the RO host
(typically LAN/VPN from the training machine), not on missing AUTH.

## Heavy/real run (2026-08-11)

**Verdict**: **BLOCKED** — Postgres RO host unreachable on `:5432` from the agent
runtime. No smoke export, no challenger train/eval, no bundle export, no MLflow
writes. Not a PASS.

### Preflight (sanitized)

| Check | Result |
| --- | --- |
| Source URL | `TRAINING_DATABASE_URL` only (`SCOREENGINE_READONLY_DATABASE_URL` identical host/user/db; unused as alternate credential) |
| Score Engine `DATABASE_URL` | **not used** (different DB name `maxxtrading-scoreengine`, user `postgres`) |
| Username contains `readonly` | yes (`scoreengine_readonly`) |
| DB name | `maxxtrading` |
| URL ≠ `DATABASE_URL` | yes |
| Host / port | `192.168.3.10:5432` |
| Dialect planned | `postgresql+psycopg` |
| TCP `/dev/tcp` + `connect_ex` to `:5432` | **FAIL** — `ECONNREFUSED` (111); SQLAlchemy `OperationalError` (“server closed the connection unexpectedly”) |
| `SELECT 1` | **not executed** (connect failed) |
| Write probe `CREATE TEMP TABLE` | **not executed** (connect failed; prior AUTH runs on reachable path had rejection) |
| SSH reachability `:22` (diagnostic only) | open (`connect_ex=0`) — host L3 reachable; Postgres port closed/refused |
| Invented host / Score Engine DSN fallback | **not used** |

### Planned window (not executed)

Same T8 window, enlarged `n_max` for holdout ≥ 200 if data allows:

| Param | Value |
| --- | --- |
| `window_start` | `2025-07-29T00:00:00+00:00` |
| `window_end` / `as_of` / `holdout_end` | `2026-07-02T00:00:00+00:00` |
| `train_end` | `2025-11-01T00:00:00+00:00` |
| `validation_end` | `2026-03-01T00:00:00+00:00` |
| `n_max` | `2000` (intended) |
| `label_policy_ref` | `docs/label-policy.md` |
| `seed` | `42` |
| FD | `/workspace/app/artifacts/feature_dictionary_v1.json` (read-only) |

### Metrics / gates

| Item | Value |
| --- | --- |
| `dataset_id` | n/a |
| partition counts | n/a |
| `holdout_metrics` | n/a |
| `probe_metrics` | n/a |
| Q1–Q3 / B1 / G1 / L1 / M1 | n/a (no eval) |
| overall | **BLOCKED** (network) |

### Network recovery attempted

1. Confirmed `TRAINING_DATABASE_URL` host/port (`192.168.3.10:5432`).
2. TCP probes (`/dev/tcp`, Python `connect_ex` timeouts 2/5/10s) → refused.
3. WSL/Docker path check: container on `172.22.0.0/16`; gateway `172.22.0.1`; no route that opens Postgres on the LAN host.
4. Same RO URL via `SCOREENGINE_READONLY_DATABASE_URL` (identical) — same failure.
5. Did **not** retarget to Score Engine `DATABASE_URL` or any other host.

### Blockers remaining

- Operator must expose Postgres on `192.168.3.10:5432` to this runtime (service up + `listen_addresses` / firewall / `pg_hba` for the Docker/WSL client path), **or** run Heavy/real T24 from a machine already on the LAN/VPN that can complete the RO preflight (`SELECT 1` + rejected write probe).
- After connectivity: holdout N ≥ 200 (`MIN_HOLDOUT_SAMPLES`); peer LightGBM/logistic baseline for L1/M1; B1/G1 fail-closed (`None`) until T26 shadow population unless true deltas are derived.
- T25 MLflow registry writes remain out of scope.

### Exact next operator action

On a host that can reach the RO DB: verify
`psql "$TRAINING_DATABASE_URL" -c 'SELECT 1'` succeeds and
`CREATE TEMP TABLE t24_probe(id int)` is rejected; then re-run this Heavy/real
procedure (smoke `n_max≥2000` → `evaluate_challenger` → evidence section).
