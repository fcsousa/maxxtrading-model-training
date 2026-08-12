# Challenger Quality V1 Validation

**Date**: 2026-08-12  
**Spec**: `.specs/features/challenger-quality-v1/spec.md`  
**Diff range**: `e8a0732^..HEAD` (`feature/mlflow-p4-challenger-shadow`, 10 commits through `6012849`)  
**Verifier**: independent sub-agent (author ≠ verifier)  
**Mode**: READ-ONLY on real tree; discrimination mutants only in `/tmp` scratch (discarded)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 Quota batch | ✅ Done | `quota_batch.py` + `tests/test_quota_batch.py` |
| T2 Quality export | ✅ Done | `quality_export.py` + tests; smoke path preserved |
| T3 `result_r` export | ✅ Done | `label_export` + tests |
| T4 Categorical encode | ✅ Done | fit train-only; missing → skip |
| T5 Cats in quality + bundle | ✅ Done | deferred empty; encoder bundle validates |
| T6 Offline B1/G1 | ✅ Done | thresholds + fail-closed empty grade-A / missing R |
| T7 Full Q1–M1 gate | ✅ Done | `evaluate_challenger_quality`; overall PASS iff all seven |
| T8 Docs + SE pointer | ✅ Done | `docs/challenger-quality-v1.md`; SE `docs/mlflow/challenger-quality-v1-pointer.md` |
| T9 Heavy/real | ⚠️ Pending AUTH | Not run; CQ-12 heavy evidence not updated — do **not** treat as sole feature FAIL |

---

## Spec-Anchored Acceptance Criteria

### P1: Partition-quota dataset + revised temporal window

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| ------------------------- | -------------------- | ----------------------- | ------ |
| WHEN export/smoke builds batch THEN enforce configurable min full-vector counts; holdout ≥ 200 | `QuotaSpec` rejects `holdout_min < 200`; selection meets mins | `tests/test_quota_batch.py:60-62` — `pytest.raises(ValueError, match="holdout_min")` with `holdout_min=199`; `tests/test_quota_batch.py:80-82` — `holdout_count >= 200` | ⚠️ PASS with weak assert (see sensor M1) |
| WHEN quotas unmet THEN fail closed with explicit stop reason | `QuotaBatchError` + sanitized counts; no silent underfill | `tests/test_quota_batch.py:95-111` — raises `QuotaBatchError`; `counts["train"]==1` etc.; no `password`/`DATABASE_URL` in message | ✅ PASS |
| WHEN temporal window / `train_end` changes THEN new `dataset_id` with manifest fields | Manifest folds window/split/seed/feature_order/deferred/checksums into `dataset_id` | `tests/test_quality_export.py:114-126` — `dataset_id`/`quotas`/`included_categoricals`; `tests/test_dataset_builder.py:129-144` + `163-169` — manifest + deterministic id; `src/training/dataset_builder.py:166-181` — `train_end` in hash payload | ✅ PASS |
| WHEN selecting packs THEN not solely global top-N; respect partition quotas | `select_quota_batch` fills per-partition mins before `n_max` | `tests/test_quota_batch.py:66-84` — per-partition counts; `src/training/quota_batch.py:152-158` — mins first | ✅ PASS |
| WHEN using DB THEN only `TRAINING_DATABASE_URL`; never SE `DATABASE_URL` | Refuse SE DB name | `tests/test_quality_export.py:249-258` — `QualityExportError` / `match="TRAINING_DATABASE_URL"`; `src/training/quality_export.py:118-140` | ✅ PASS (best-effort name guard) |

### P1: Categorical features in train + bundle

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --------- | -------------------- | ----------------------- | ------ |
| WHEN vectorizing CQ runs THEN include encoded `trend_regime` / `volatility_regime` + numerical | Vectors longer than numerical-only; cats listed | `tests/test_quality_export.py:117` — `included_categoricals == ("trend_regime", "volatility_regime")`; `:177` — `len(feature_vectors[id]) > 2` | ✅ PASS |
| WHEN required cat missing THEN sample partial/skipped (no invent) | Missing → skip; underfill fail-closed | `tests/test_categorical_encode.py:40-61` — `skipped == ("miss_key", "miss_null")`; `tests/test_quality_export.py:179-202` — holdout count 0 → `QuotaBatchError` | ✅ PASS |
| WHEN exporting bundle THEN encoder + checksum satisfy SE contract | `validate_artifact_bundle` with encoder sha | `tests/test_quality_export.py:204-245` — `encoder_sha256 is not None`; `validate_artifact_bundle(...)` | ✅ PASS |
| WHEN manifest written THEN cats **included** (not deferred) | `deferred_categoricals == ()` | `tests/test_quality_export.py:170-172` — report + manifest deferred empty | ✅ PASS |

### P1: Complete T24 gate evaluation (Q1–M1)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --------- | -------------------- | ----------------------- | ------ |
| WHEN evaluating on signed holdout THEN Q1/Q2/Q3 computed; holdout not used for fit | Metrics present; train-only fit | `tests/test_challenger_eval.py:123-132` — holdout absent from train map; `:170-172` — `auc_roc`/`brier_score`/`ece`; `src/training/challenger_eval.py:416-417` | ✅ PASS |
| WHEN computing B1/G1 THEN grades from SE `thresholds.json` RO + `result_r` (no fabricate R) | Offline grades + delta; missing R fail-closed | `tests/test_offline_scoring.py:69-80` — `grade == "A"`; `:127-131` — missing R raises; `tests/test_label_export.py:206-209` — null stays None; `tests/test_challenger_eval.py:283-310` — B1 FAIL | ✅ PASS |
| WHEN `result_r` / fallback unavailable for grade-A THEN B1 FAIL/BLOCKED | Fail closed, not skipped | `tests/test_challenger_eval.py:308-310` — `by_id["B1"].verdict == "FAIL"`; `overall_verdict == "FAIL"` | ✅ PASS |
| WHEN probing L1/M1 THEN emit p95 ratio + RSS delta; strict compare (no round toward PASS) | Keys present; compare strict | `tests/test_challenger_eval.py:174-175` — probe keys; `:102-105` — `compare(..., 0.549999999, ...) is False`; `:146-154` — Q1 not rounded away | ✅ PASS |
| WHEN any Q1–M1 FAIL/BLOCKED THEN overall FAIL/BLOCKED and refuse bundle | Overall FAIL; export refused | `tests/test_challenger_eval.py:142-144` — overall FAIL; `:213-215` — `refusing to export`; `src/training/challenger_eval.py:287-292`, `:505-507` | ✅ PASS |
| WHEN all seven PASS THEN allow export + sanitized evidence path | Synthetic all-PASS; export OK on PASS | `tests/test_challenger_eval.py:278-281` — all PASS + `len(SIGNED_CRITERIA)==7`; `:178-201` — export on PASS | ✅ PASS (unit); Heavy/real sanitized table → T9 pending |

**Independent-test note**: Spec asks isolation FAIL per criterion. Evidence exists for Q1 (`:231-251`), B1 (`:283-310`), missing B1/G1 (`:136-144`). No dedicated isolation tests forcing Q2/Q3/G1/L1/M1 alone → coverage gap (not AC WHEN/THEN zero-evidence).

### P2: Score Engine pointer

| Criterion | Spec-defined outcome | Evidence | Result |
| --------- | -------------------- | -------- | ------ |
| Short pointer under `docs/mlflow/` with path/branch/CQ-IDs; no full spec copy | File exists; CQ-01..13; no AC tables | `/workspace/docs/mlflow/challenger-quality-v1-pointer.md:1-31` | ✅ PASS |
| Pointer states limiares = `shadow-acceptance-v1`; T26 still required | Explicit invariants | same file `:23-24` | ✅ PASS |

### P3: Serving-image baseline_heuristic (CQ-14)

| Criterion | Outcome | Evidence | Result |
| --------- | ------- | -------- | ------ |
| Optional probe vs `baseline_heuristic` | Deferred optional | tasks.md CQ-14 Deferred | ⏭️ Out of scope / optional |

**Status**: ❌ Gaps present (sensor survival + T9 pending + isolation incompleteness) — code ACs T1–T8 largely ✅

---

## Discrimination Sensor

Scratch: `/tmp/cq-v1-sensor.*` (temp copy of `src/training`); real tree restored/unmodified. Import forced via `sys.path.insert(0, scratch/src)` + module cache clear.

| Mutation | File:line | Description | Killed? |
| -------- | --------- | ----------- | ------- |
| M1 | `quota_batch.py:37` | `holdout_min < 200` → `< 100` | ❌ Survived — `test_holdout_min_below_200_raises` still passes because `match="holdout_min"` matches `n_max must be >= ... holdout_min` (`QuotaSpec(..., holdout_min=199, n_max=50)`) |
| M2 | `quota_batch.py:143` | Underfill gate disabled (`available < mins` → never true) | ✅ Killed — `test_underfill_raises_with_sanitized_counts` DID NOT RAISE |
| M3 | `offline_scoring.py:139-140` | Empty grade-A returns `0.0` instead of raise | ✅ Killed — `test_empty_grade_a_fail_closed` |
| M4 (extra) | `challenger_eval.py:287-292` | `overall_verdict` always `"PASS"` | ✅ Killed — GateFailClosed + Q1 isolation |

**Sensor depth**: lightweight (3 primary + 1 extra)  
**Result**: 3/4 killed, **1 survived** — FAIL ❌ for discrimination

---

## Interactive UAT Results

N/A — backend/offline training feature; automated checks only.

---

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum code | ✅ |
| Surgical changes | ✅ |
| No scope creep | ✅ (CQ-14 deferred; no threshold edits; `shadow-acceptance.md` untouched in diff) |
| Matches patterns | ✅ |
| Spec-anchored outcome check | ⚠️ M1 weak assert on holdout floor |
| Per-layer Coverage Expectation | ⚠️ Isolation not 1:1 for every Q2/Q3/G1/L1/M1 |
| Every test maps to a spec requirement | ✅ (feature tests map to CQ / edges) |
| Documented guidelines | ✅ `CLAUDE.md`, `docs/agent-repo-policy.md`, tasks matrix |

---

## Edge Cases

- [x] RO underfill → actionable sanitized counts (`QuotaBatchError.counts`)
- [x] Holdout below 200 → BLOCKED eval (`test_holdout_below_minimum_is_blocked`) + `QuotaSpec` floor (weak assert)
- [x] Leakage features — existing `feature_export` leakageCheckStatus guards (pre-feature)
- [x] SE `DATABASE_URL` / scoreengine DB name — `_reject_score_engine_database`
- [ ] WRITE_PROBE abort — **no code path** in this feature; ops protocol / T9 evidence only
- [ ] Non-readonly username refuse — **not automated** beyond DB name guard
- [x] Missing `thresholds.json` → fail closed (`test_missing_file_raises`; CQ path returns None→FAIL)

---

## Gate Check

- **Gate command**: `uv run pytest tests/ -q --tb=line`
- **Result**: **174 passed**, 0 failed, 0 skipped
- **Test defs before feature** (`e8a0732^`): 139  
- **Test defs after** (`HEAD`): 171  
- **Delta**: +32 test functions  
- **Skipped**: none  
- **Failures**: none  
- **Note**: Integration requiring `TRAINING_DATABASE_URL` not present as failing/unmarked skips in this run

---

## Fix Plans

### Fix 1: Strengthen holdout_min floor assertion (sensor M1)

- **Root cause**: `pytest.raises(..., match="holdout_min")` matches a different `ValueError` from the `n_max >= sum(mins)` check when the floor guard is removed/weakened.
- **Fix task**: Change test to `match="holdout_min must be >= 200"` **and/or** use `n_max` large enough that only the floor check can fire; add assertion that `QuotaSpec(..., holdout_min=199, n_max=500)` raises the floor error.
- **Where**: `tests/test_quota_batch.py` (`TestQuotaSpec.test_holdout_min_below_200_raises`)
- **Verify**: Re-run discrimination mutant M1 → must FAIL the test.
- **Priority**: Major (surviving mutant)

### Fix 2: Isolation FAIL for remaining criteria (Independent Test)

- **Root cause**: Only Q1 and B1 have dedicated isolation paths; Independent Test asks each of seven.
- **Fix task**: Unit tests forcing Q2, Q3, G1, L1, M1 FAIL in isolation via `gate_challenger_metrics` / injected probe metrics while others PASS; assert `overall_verdict == "FAIL"`.
- **Where**: `tests/test_challenger_eval.py`
- **Priority**: Minor/Major (Independent Test completeness)

### Fix 3: T9 Heavy/real + CQ-12 evidence (pending AUTH)

- **Root cause**: AUTH not granted this session.
- **Fix task**: Authorized RO run; WRITE_PROBE rejected; update `docs/t24-challenger-eval-evidence.md` with full Q1–M1 table; no fabricated PASS.
- **Priority**: Blocker for promotion evidence; **not** sole code-AC FAIL per orchestrator instruction

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| ----------- | --------------- | ---------- |
| CQ-01 | Implementing | ⚠️ Verified w/ weak floor assert |
| CQ-02 | Implementing | ✅ Verified |
| CQ-03 | Implementing | ✅ Verified |
| CQ-04 | Implementing | ✅ Verified (best-effort) |
| CQ-05 | Implementing | ✅ Verified |
| CQ-06 | Implementing | ✅ Verified |
| CQ-07 | Implementing | ✅ Verified |
| CQ-08 | Implementing | ✅ Verified |
| CQ-09 | Implementing | ✅ Verified |
| CQ-10 | Implementing | ✅ Verified |
| CQ-11 | Implementing | ✅ Verified (unit) |
| CQ-12 | Implementing | ⚠️ Pending AUTH (T9) |
| CQ-13 | Implementing | ✅ Verified |
| CQ-14 | Pending optional | ⏭️ Deferred |

---

## Summary

**Overall**: ❌ Not Ready (surviving mutant + T9 pending)

**Spec-anchored check**: 14/15 code ACs matched (P1–P2); 1 weak assert on holdout floor; CQ-12 heavy pending; CQ-14 deferred  
**Sensor**: 3/4 killed, 1 survived (M1)  
**Gate**: 174 passed, 0 failed  

**What works**: Quota fail-closed, quality export + cats + encoder bundle, offline B1/G1, full seven-PASS synthetic path, export refuse on FAIL, SE pointer, build gate green.

**Issues found**: Surviving mutant on holdout floor test; incomplete per-criterion isolation; WRITE_PROBE/non-readonly edge cases not coded; T9/CQ-12 pending AUTH.

**Next steps**: Fix 1 (strengthen floor test) before re-verify; optionally Fix 2; run T9 only with explicit AUTH.
