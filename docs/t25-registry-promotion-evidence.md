# T25 registry promotion evidence

**Date**: 2026-08-11  
**Repo**: `maxxtrading-model-training`  
**Branch**: `feature/mlflow-p4-challenger-shadow`  
**Policy**: Score Engine `docs/mlflow/evidence/phase-3/registry-runbook.md` (MLF-11)  
**AUTH**: **real VPS MLflow registry write NOT executed** — awaiting explicit
authorization. Unit path uses `InMemoryRegistryClient` only (no credentials,
no tracking URI).

## Verdict

| Layer | Result |
| --- | --- |
| Unit / fake registration + `candidate`→`staging` | **PASS** (`tests/test_registry_promotion.py`, 8 tests) |
| Real registry on VPS (`http://mlflow:5000` via backend network) | **NOT RUN** — blocked on operator AUTH (OF-4: register from VPS) |

## Recorded fake registration (authorized for offline gate only)

| Field | Value |
| --- | --- |
| `model_name` | `score_model` |
| immutable `version` | `1` (in-memory) |
| `source_uri` | `file:///tmp/bundle-z` (fixture) |
| aliases after promote | `candidate=1`, `staging=1` |
| `approval_ref` | `docs/t24-challenger-eval-evidence.md` |
| required tags | all 8 MLF-11 tags present (`algorithm`, `features_version`, `dataset_id`, `label_rule_id`, `training_commit`, `training_run_id`, `bundle_sha256`, `approval_ref`) |

Guards verified by unit tests:

- missing tags → reject
- invalid `bundle_sha256` → reject
- same `source_uri` → reject overwrite
- `production` alias → reject in this helper
- alias move requires exact `expected_current_version` + non-empty `approval_ref`

## Secrets

none — no DSN, token, tracking URI with credentials, or host SSH material in
this evidence.

## Next AUTH (operator)

When authorized, run registration **from the VPS** against the real registry
(not from the training laptop), then append a sanitized section here with:

- registered `version` (immutable)
- alias targets before/after for `candidate` and `staging`
- tag keys present (values redacted if sensitive)
- approval references

Do **not** paste secrets.
