# Challenger Quality V1 — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and
follow its Execute flow and Critical Rules.** Do not search for skill files by
filesystem path.

**If the skill cannot be activated, STOP and tell the user — do not proceed.**

---

**Design**: `.specs/features/challenger-quality-v1/design.md`  
**Status**: Approved for Execute (user: pode seguir)

---

## Test Coverage Matrix

> Generated from codebase + `CLAUDE.md` / `docs/agent-repo-policy.md` / `pyproject.toml`.
> Guidelines found: `CLAUDE.md`, `docs/agent-repo-policy.md`, `pyproject.toml` (pytest/ruff).

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| quota_batch / categorical_encode / offline_scoring / quality_export | unit | All branches; 1:1 to CQ ACs; listed edge cases | `tests/test_*.py` | `uv run pytest tests/test_quota_batch.py tests/test_categorical_encode.py tests/test_offline_scoring.py tests/test_quality_export.py -q` |
| label_export / challenger_eval extensions | unit | AC + fail-closed edges | `tests/test_label_export.py` `tests/test_challenger_eval.py` | `uv run pytest tests/test_label_export.py tests/test_challenger_eval.py -q` |
| Docs / SE pointer | none | Headings, no secrets, no threshold edits | `docs/` `.specs/` | `git diff --check` |
| Heavy/real RO | integration (opt-in) | Sanitized evidence; WRITE_PROBE rejected | `docs/t24-challenger-eval-evidence.md` | Explicit AUTH + `TRAINING_DATABASE_URL` |

## Gate Check Commands

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | Unit-only tasks | `uv run pytest <task-tests> -q` && `uv run ruff check <touched>` && `uv run ruff format --check <touched>` |
| Full | After label/challenger wiring | `uv run pytest tests/test_label_export.py tests/test_challenger_eval.py tests/test_offline_scoring.py tests/test_quota_batch.py tests/test_categorical_encode.py tests/test_quality_export.py -q` |
| Build | End of code phases | Full + `uv run pytest tests/ -q` (exclude needing DB) |
| Heavy/real | T9 only | Authorized RO run; never invent PASS |

---

## Execution Plan

### Phase 1 — Data foundation

```
T1 → T2 → T3
```

### Phase 2 — Features

```
T4 → T5
```

### Phase 3 — Complete gate

```
T6 → T7 → T8
```

### Phase 4 — Heavy/real

```
T9
```

---

## Task Breakdown

### T1: Quota batch selector

**What**: Add `QuotaSpec` + `select_quota_batch` with fail-closed underfill.  
**Where**: `src/training/quota_batch.py`, `tests/test_quota_batch.py`  
**Depends on**: None  
**Reuses**: full-vector check idea from `smoke_export`  
**Requirement**: CQ-01, CQ-02  

**Tools**: Skill `tlc-spec-driven`; filesystem  

**Done when**:

- [x] `holdout_min < 200` rejected at construction
- [x] Quotas enforced per temporal partition
- [x] Underfill raises with sanitized counts
- [x] ≥4 unit tests; quick gate green

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(train): add partition quota batch selector`

---

### T2: Quality export entrypoint

**What**: New `run_quality_export` using quotas + revised window defaults → new dataset_id.  
**Where**: `src/training/quality_export.py`, `tests/test_quality_export.py`  
**Depends on**: T1  
**Reuses**: smoke assemble patterns; `dataset_builder`  
**Requirement**: CQ-01, CQ-03, CQ-04  

**Tools**: Skill `tlc-spec-driven`  

**Done when**:

- [x] Does not break existing `run_export_smoke` behavior/tests
- [x] Manifest records quotas + included cats flag placeholders
- [x] Refuses if engine URL looks like app DATABASE_URL (best-effort guard)
- [x] ≥3 unit tests; quick gate green

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(train): add quality export with quotas`

---

### T3: Export `result_r` on labels

**What**: Extend `LabeledTradeSample` + SELECT to include nullable `result_r`.  
**Where**: `src/training/label_export.py`, `tests/test_label_export.py`  
**Depends on**: None (parallel-safe after T1; ordered here for phase cohesion)  
**Reuses**: existing RO guards  
**Requirement**: CQ-09  

**Tools**: Skill `tlc-spec-driven`  

**Done when**:

- [x] `result_r` present when DB column non-null
- [x] Null stays None (no imputation)
- [x] Existing label tests updated; ≥2 new assertions
- [x] Quick gate green

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(train): include result_r in label export`

---

### T4: Categorical encode (train-fit)

**What**: Fit/transform `trend_regime`/`volatility_regime`; missing → skip sample.  
**Where**: `src/training/categorical_encode.py`, `tests/test_categorical_encode.py`  
**Depends on**: T2 (consumes quality vectors) — implementable with synthetic rows standalone; depends on T2 for integration defaults  
**Reuses**: sklearn OneHotEncoder pattern from artifact tests  
**Requirement**: CQ-05, CQ-06  

**Tools**: Skill `tlc-spec-driven`  

**Done when**:

- [x] Fit on train only; transform val/holdout
- [x] Missing cat excludes sample
- [x] Deterministic columns order
- [x] ≥4 unit tests; quick gate green

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(train): encode challenger categorical features`

---

### T5: Wire cats into quality vectors + bundle metadata

**What**: Quality pipeline concatenates numerical + encoded cats; manifest marks cats included; bundle can carry encoder.  
**Where**: `src/training/quality_export.py` and/or small helper; tests  
**Depends on**: T2, T4  
**Reuses**: `artifact_bundle.export_artifact_bundle` encoder field  
**Requirement**: CQ-05, CQ-07  

**Tools**: Skill `tlc-spec-driven`  

**Done when**:

- [x] Manifest `deferred_categoricals=()` and records included cats for CQ datasets
- [x] Bundle validate passes with encoder when exported
- [x] ≥3 unit tests; quick gate green

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(train): include categoricals in quality dataset and bundle`

---

### T6: Offline scoring for B1/G1

**What**: Load SE `thresholds.json`; compute grades; business proxy delta; grade-share delta.  
**Where**: `src/training/offline_scoring.py`, `tests/test_offline_scoring.py`  
**Depends on**: T3 (result_r semantics)  
**Reuses**: thresholds schema; shadow-acceptance definitions  
**Requirement**: CQ-09  

**Tools**: Skill `tlc-spec-driven`  

**Done when**:

- [ ] Grade A/B/C deterministic from thresholds
- [ ] Empty grade-A set → B1 fail-closed path documented in API
- [ ] Missing thresholds path → error/FAIL
- [ ] ≥5 unit tests; quick gate green

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(train): add offline grade and shadow proxy metrics`

---

### T7: Wire complete Q1–M1 into challenger_eval

**What**: Evaluate path computes B1/G1 when possible; overall PASS iff all seven pass; no rounding.  
**Where**: `src/training/challenger_eval.py`, `tests/test_challenger_eval.py`  
**Depends on**: T4, T6  
**Reuses**: `gate_challenger_metrics`, `shadow_acceptance.compare`  
**Requirement**: CQ-08, CQ-09, CQ-10, CQ-11  

**Tools**: Skill `tlc-spec-driven`  

**Done when**:

- [ ] B1/G1 no longer must be injected as None for CQ path
- [ ] Isolation tests: each criterion can force FAIL
- [ ] Synthetic path can PASS all seven
- [ ] Full gate green; no weakened tests

**Tests**: unit  
**Gate**: full  
**Commit**: `feat(model): gate challenger on full shadow-acceptance set`

---

### T8: Evidence + Score Engine pointer

**What**: Docs for CQ feature + SE pointer markdown (no full spec copy).  
**Where**: `docs/challenger-quality-v1.md` (or section in t24 evidence); SE `docs/mlflow/challenger-quality-v1-pointer.md`  
**Depends on**: T7  
**Reuses**: agent-repo-policy handoff style  
**Requirement**: CQ-12, CQ-13  

**Tools**: Skill `tlc-spec-driven`; SE edit only for pointer  

**Done when**:

- [ ] Training docs describe quotas/window/cats/gate rules
- [ ] SE pointer lists path, CQ-IDs, shadow-acceptance-v1 immutability, T26 still separate
- [ ] No secrets; `git diff --check` clean on touched docs

**Tests**: none  
**Gate**: build (docs check)  
**Commit**: `docs(model): add challenger quality v1 pointer and runbook`  
(SE pointer may be second commit on SE claim: `docs(mlflow): point to challenger-quality-v1`)

---

### T9: Authorized Heavy/real re-run

**What**: RO eval with quality_export + full gates; update `docs/t24-challenger-eval-evidence.md`.  
**Where**: evidence doc only (+ temp artifacts unsaved)  
**Depends on**: T7, T8  
**Reuses**: prior Heavy/real protocol  
**Requirement**: CQ-11, CQ-12  

**Tools**: AUTH required; subagent OK  

**Done when**:

- [ ] WRITE_PROBE rejected
- [ ] Holdout ≥ 200; all seven criteria recorded
- [ ] PASS only if truly all PASS — else FAIL documented (no fabricate)
- [ ] Pushed evidence commit if AUTH allows

**Tests**: none (ops evidence)  
**Gate**: Heavy/real  
**Commit**: `docs(model): record CQ-v1 heavy/real challenger evaluation`

---

## Phase Execution Map

```
Phase 1 → Phase 2 → Phase 3 → Phase 4

Phase 1:  T1 ──→ T2 ──→ T3
Phase 2:  T4 ──→ T5
Phase 3:  T6 ──→ T7 ──→ T8
Phase 4:  T9
```

**Batch packing (~7 tasks):**

| Batch | Phases | Tasks |
| --- | --- | --- |
| Batch A | 1+2 | T1–T5 (5) |
| Batch B | 3 | T6–T8 (3) |
| Batch C | 4 | T9 (1, AUTH) |

> 9 tasks → offer sub-agents for Batch A then B; T9 only with explicit Heavy/real AUTH.

---

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1 | 1 module + tests | ✅ |
| T2 | 1 entrypoint + tests | ✅ |
| T3 | 1 export extension | ✅ |
| T4 | 1 encode module | ✅ |
| T5 | wire + tests | ✅ |
| T6 | 1 scoring module | ✅ |
| T7 | eval wire + tests | ✅ |
| T8 | docs | ✅ |
| T9 | ops evidence | ✅ |

## Diagram-Definition Cross-Check

| Task | Depends On (body) | Diagram | Status |
| --- | --- | --- | --- |
| T1 | None | — | ✅ |
| T2 | T1 | T1→T2 | ✅ |
| T3 | None | parallel in P1 after T1 start; listed T1→T2→T3 for cohesion | ✅ ordered |
| T4 | T2 | T2→T4 | ✅ |
| T5 | T2,T4 | T4→T5 | ✅ |
| T6 | T3 | T3→T6 (cross-phase) | ✅ |
| T7 | T4,T6 | T5/T6→T7 | ✅ |
| T8 | T7 | T7→T8 | ✅ |
| T9 | T7,T8 | T8→T9 | ✅ |

## Test Co-location Validation

| Task | Layer | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | quota_batch | unit | unit | ✅ |
| T2 | quality_export | unit | unit | ✅ |
| T3 | label_export | unit | unit | ✅ |
| T4 | categorical_encode | unit | unit | ✅ |
| T5 | quality_export/bundle | unit | unit | ✅ |
| T6 | offline_scoring | unit | unit | ✅ |
| T7 | challenger_eval | unit | unit | ✅ |
| T8 | docs | none | none | ✅ |
| T9 | evidence | ops | none | ✅ |

---

## Requirement mapping (post-Tasks)

| ID | Task |
| --- | --- |
| CQ-01..04 | T1, T2 |
| CQ-05..07 | T4, T5 |
| CQ-08..11 | T6, T7 |
| CQ-12..13 | T8, T9 |
| CQ-14 | Deferred (P3) |
