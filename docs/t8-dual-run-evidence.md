# T8 dual-run evidence (Passo 2)

**Date**: 2026-08-08  
**Repo**: `maxxtrading-model-training`  
**Branch**: `feature/mlflow-p1-data-foundation`  
**AUTH**: Phase 1 T8 — two approved reference trainer runs on the pinned
Passo 1 `dataset_id`.

## Verdict

**PASS** — `runs_are_reproducible(run1, run2, tolerance=1e-9)` is `True`.

## Fixed inputs (unchanged from AUTH claim)

| Input | Value |
| --- | --- |
| `dataset_id` (pinned) | `e70956f6722d8a106d8484ebfb9483c44c85d6ede39a6bbc7837373daf02f058` |
| `feature_order_source` | `numerical` (12 fields from Score Engine FD) |
| deferred categoricals | `trend_regime`, `volatility_regime` |
| `seed` | `42` |
| `model_params` | `{}` (trainer default) |
| tolerance | `1e-9` |

### Passo 1 reconstruction params (vectors not persisted)

| Param | Value |
| --- | --- |
| `window_start` | `2025-07-29T00:00:00+00:00` |
| `window_end` | `2026-07-02T00:00:00+00:00` |
| `as_of` | `window_end` |
| `train_end` | `2025-11-01T00:00:00+00:00` |
| `validation_end` | `2026-03-01T00:00:00+00:00` |
| `holdout_end` | `window_end` |
| `n_max` | `100` |
| `label_policy_ref` | `docs/label-policy.md` |

DB: `TRAINING_DATABASE_URL` → user `scoreengine_readonly`, host
`192.168.3.10`, db `maxxtrading`, dialect `postgresql+psycopg`. SELECT-only;
write probe (`CREATE TEMP TABLE`) rejected (`InternalError`). DSN/password
not recorded.

FD path: `/workspace/app/artifacts/feature_dictionary_v1.json` (Score Engine
artifact; not modified).

## Reconstruction

Same smoke path as Passo 1 (`run_export_smoke` → soft vectorize →
`build_dataset`). Report now attaches `partitions` when `dataset_id` is
green; vectors remain on `coverage.vectors`.

| Metric | Value |
| --- | --- |
| labels_eligible | 4997 |
| packs_succeeded | 4582 |
| batch_size | 100 |
| vectorized (full numerical-12) | 100 |
| partial / skipped | 0 / 0 |
| reconstituted `dataset_id` | **exact match** to pinned id |
| train / validation / holdout | 100 / 0 / 0 |
| train labels | win=57, loss=43 |

No STOP: both classes present; `dataset_id` matched.

## Dual train

Helper: `training.dual_run.dual_train_from_smoke` → two identical
`train(...)` calls (`seed=42`, `model_params={}`).

| | run1 | run2 |
| --- | --- | --- |
| `train_log_loss` | `0.638850758331301` | `0.638850758331301` |
| `n_iter` | `100.0` | `100.0` |

| Provenance | Value |
| --- | --- |
| `dataset_id` | `e70956f6722d8a106d8484ebfb9483c44c85d6ede39a6bbc7837373daf02f058` |
| `seed` | `42` |
| `model_params` | `{}` |
| `library_versions` | scikit-learn `1.9.0`, numpy `2.4.6` |
| reproducibility | **PASS** (`tolerance=1e-9`) |

Note: both fits emit sklearn `ConvergenceWarning` (default `max_iter=100`
reached). Expected with empty `model_params`; both runs hit the same
`n_iter=100` and identical loss — does not affect the reproducibility
check.

## Code / git

- Surgical extension: `ExportSmokeReport.partitions` attached on green
  smoke; `src/training/dual_run.py` asserts pinned `dataset_id` and runs
  two trains.
- Git SHA at dual-run execution (pre-evidence commit):
  `103904016f05b8065ed7087764252c3685d3931f`
- Evidence + dual-run helper land in subsequent local commit(s) on this
  branch.

## Out of scope

- T9 / Score Engine consumption evidence — not claimed here.
- No FD-SE edit; no `feature_order` shrink; no seed/config drift between
  runs; no push to remote.
