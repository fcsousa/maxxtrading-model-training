# Shadow Acceptance Criteria (Phase 4)

**Status**: APPROVED — 2026-08-11 (ML + Produto: fcsousa).
**Requirement**: MLF-15, MLF-25, MLF-27 (`maxxtrading-scoreengine` spec.md).
**Related**: roadmap TDD §11 / §15 / open Q4; Phase 0 report (0 inference
samples — absolute online p95/grades unavailable; relative probe rules apply).
**Policy**: `docs/agent-repo-policy.md` — limiares numéricos exigem sign-off;
este documento é a fonte de verdade para T24–T28.

This document defines the numeric pass/fail gates for comparing a challenger
model against `baseline_v1` / `algorithm=baseline_heuristic` on a signed holdout
and the same historical shadow population. Any FAIL blocks alias moves
`candidate` → `staging` and `staging` → `production`.

## 1. Scope and population

| Item | Value |
| --- | --- |
| Baseline reference | `modelVersion=baseline_v1`, `algorithm=baseline_heuristic` |
| Challenger | Immutable registered version under evaluation (T24/T25) |
| Quality/calibration population | Signed holdout partition of the approved `dataset_id` (no refit, no leakage) |
| Shadow / grade / proxy population | Same bounded historical window and sample set for baseline and challenger |
| Latency / RSS population | Probe on the production-like serving image, N ≥ 200 scored requests, same payload set for both models |
| Minimum holdout size | N ≥ 200 labeled samples; if smaller, evaluation is **BLOCKED** (invalid metrics — do not round or waive) |
| Document version | `shadow-acceptance-v1` |

## 2. Signed numeric criteria

Every row is mandatory. Operator, value, unit and population are binding.

| ID | Family | Metric | Operator | Value | Unit | Population |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Quality / calibration | `auc_roc` | ≥ | 0.55 | dimensionless | signed holdout |
| Q2 | Quality / calibration | `brier_score` | ≤ | 0.25 | dimensionless | signed holdout |
| Q3 | Quality / calibration | `ece` (10 equal-width bins on predicted P(win)) | ≤ | 0.10 | dimensionless | signed holdout |
| B1 | Business proxy | `mean_result_r_at_grade_A` (challenger − baseline) | ≥ | 0.0 | R-multiple | same shadow population |
| G1 | Grade distribution | `max_{i∈{A,B,C}} \|share_i^{challenger} − share_i^{baseline}\|` | ≤ | 15 | percentage points | same shadow population |
| L1 | Latency p95 | `p95_latency_ms` (challenger) | ≤ | 2.0 × `p95_latency_ms` (baseline) | ms | serving-image probe N≥200 |
| M1 | Memory RSS | `rss_mib` (challenger) − `rss_mib` (baseline) | ≤ | 256 | MiB | same probe process/window as L1 |

### 2.1 Metric definitions

- **`auc_roc`**: ROC AUC of predicted `probabilityWin` vs binary label
  (`win`→1, `loss`→0) per `docs/label-policy.md`.
- **`brier_score`**: mean squared error of `probabilityWin` vs the same binary
  label on the holdout.
- **`ece`**: expected calibration error with 10 equal-width probability bins.
- **`mean_result_r_at_grade_A`**: mean `result_r` among samples that receive
  grade `A` under each model, using Score Engine grade thresholds from the
  paired serving image. Prefer NestJS `result_r` when present; if absent for a
  sample, use `realized_pnl / |entry_price − stop_price|` when stop risk is
  known; samples without a usable R are excluded from this mean (not imputed).
  If the grade-A set is empty for either model, B1 is **FAIL** (not skipped).
- **Grade shares**: fraction of the shadow population assigned grades A, B, C
  by each model; G1 is the maximum absolute difference across the three shares,
  in percentage points (e.g. 0.12 vs 0.20 share → 8 pp).
- **`p95_latency_ms`**: 95th percentile of end-to-end score latency on the
  probe. Baseline and challenger MUST use the same probe payloads and image
  family. Phase 0 had zero production samples; the baseline p95 is the value
  measured on this probe for `baseline_v1`, not an invented absolute.
- **`rss_mib`**: process resident set size in mebibytes after the probe warm-up,
  measured for each model load on the same host/image class.

## 3. Rejection behavior

| Condition | Action |
| --- | --- |
| Any of Q1–Q3, B1, G1, L1, M1 evaluates to FAIL | Block promotion; do not move `candidate`→`staging` or `staging`→`production` |
| Holdout N < 200 or shadow/probe population mismatch | **BLOCKED** — treat as gate failure; do not pass by omission |
| Missing metric value, NaN, or incomparable population | **FAIL** (fail closed) |
| Rounding to meet a threshold | Forbidden — compare with full float precision used by the report generator |

Qualitative judgments (“looks better”, “close enough”) are not acceptance
criteria.

## 4. Traceability

| Requirement | Satisfied by |
| --- | --- |
| MLF-15 (numeric signed criteria, five families) | §2 Q\*/B1/G1/L1/M1 |
| MLF-25 (reproducible gate inputs) | §1 populations + `dataset_id` / model versions bound at report time |
| MLF-27 (no secrets in evidence) | This doc contains no credentials, DSNs, or host identifiers |

## 5. Approvals

| Role | Name | Date | Decision |
| --- | --- | --- | --- |
| ML | fcsousa | 2026-08-11 | APPROVED — shadow-acceptance-v1 |
| Produto | fcsousa | 2026-08-11 | APPROVED — shadow-acceptance-v1 |

Session sign-off text (immutable reference):

```text
SIGN-OFF T23 — aprovo sugestão V1 acima
ML+Produto: fcsousa
data: 2026-08-11
```

Revisions require a new document version id and a fresh named/dated sign-off.
