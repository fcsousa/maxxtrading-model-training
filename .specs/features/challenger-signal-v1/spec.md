# Challenger Signal V1 Specification

**Status**: Draft — awaiting gray-area answers  
**Repo**: `maxxtrading-model-training`  
**Branch alvo**: `feature/mlflow-p4-challenger-shadow`  
**Related**: CQ-v1 Heavy/real T9 FAIL; `docs/shadow-acceptance.md` (`shadow-acceptance-v1`);
`docs/label-policy.md`; `docs/schema-discovery.md` (A*); decisão CQ-v1 3A (grid/calib deferred)  
**Context**: `.specs/features/challenger-signal-v1/context.md`  
**Scope tier**: Complex (label + feature contract + external RO DB)

## Problem Statement

O Heavy/real CQ-v1 T9 falhou em Q1–Q3 com train=890, holdout=2300,
`feature_dim=18`, AUC≈0.493, Brier≈0.267, ECE≈0.108 — enquanto B1/G1/L1/M1
PASS. A causa raiz **não** é starvation de train: é fit
predictor/features/label. O produto serve `probabilityWin` com hipótese
“bater target antes do stop”, mas o rótulo atual segue Nest PnL/R
(`docs/label-policy.md`). Sem diagnóstico + sign-off de label e alinhamento
de features (A* ainda aberto), grid/calibração seria otimização cega.

## Goals

- [ ] Diagnosticar por que o challenger está ~aleatório (label mismatch vs
      features vs ambos), com evidência sanitizada e decisão de label
      assinada **nesta mesma feature** (P0).
- [ ] Fechar ou condicionar A*/feature parity e entregar sinal mensurável no
      **train** (não só holdout) via features/contrato (P1).
- [ ] Só então (se desbloqueado) explorar grid LightGBM + calibração pós-hoc
      (P2), sem afrouxar `shadow-acceptance-v1`.
- [ ] Re-avaliar Q1–Q3 (e gate completo Q1–M1 quando aplicável) contra os
      limiares **imutáveis** de `shadow-acceptance-v1`.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Alterar limiares `shadow-acceptance-v1` / inventar shadow thresholds | Política MLF-15; doc imutável nesta feature |
| Promoção MLflow alias / T25 registry | OF-4; task/feature separada |
| Orquestrador shadow online no Score Engine (T26) / T27 / T28 | Repo/task diferentes |
| Escrever em `trading.*` ou usar `DATABASE_URL` do Score Engine | Isolamento RO; só `TRAINING_DATABASE_URL` |
| Treino/código de scoring dentro do Score Engine | AD-013 |
| Aceitar `overall_verdict=PASS` com Q1–Q3 FAIL | Gate estrito; sem waive |
| Redefinir produto Nest de persistência de outcomes (código Nest) | Fora deste repo; só política de label de treino + evidência |

---

## Assumptions & Open Questions

Provisórias até gray-area answers. **Nenhuma decisão final inventada.**

| Assumption / decision | Chosen default (provisional) | Rationale | Confirmed? |
| --------------------- | ---------------------------- | --------- | ---------- |
| Root cause CQ-v1 T9 | Fit predictor/features/label — não train starvation | Train=890; B1/G1/L1/M1 PASS; Q1–Q3 ~chance | y (contexto) |
| Limiares shadow | Permanecem `shadow-acceptance-v1` (Q1 AUC≥0.55, Q2 Brier≤0.25, Q3 ECE≤0.10) | Doc imutável | y |
| Label strategy | **Open — gray area 1** | Serving hyp ≠ PnL/R armazenado | n |
| A* / feature parity gate | **Open — gray area 2** | `schema-discovery.md` A* ainda PENDING/conditional | n |
| Unlock grid/calibração | **Open — gray area 3** | CQ-v1 3A deferred; só após sinal | n |
| Spec location | **Open — gray area 4** | CQ-v1 usou training + ponteiro SE | n |
| DB access | Somente `TRAINING_DATABASE_URL` RO; nunca SE `DATABASE_URL` | AD-T01 / agent policy | y |
| Holdout mínimo | N ≥ 200 labeled; senão BLOCKED | `shadow-acceptance-v1` | y |
| Leakage | Features derivadas de exit/PnL pós-entrada proibidas | Lookahead / label-policy | y |
| Auth / rate limits | N/A — jobs offline batch, credencial RO dedicada | Medium sweep | N/A |
| Payments | N/A | Fora do domínio | N/A |
| Concurrency / ordering | N/A — eval offline single-run; sem fan-out sem limite se Design introduzir I/O | Medium sweep | N/A (até Design) |

**Open questions:** gray areas 1–4 em `context.md` — **aguardando resposta do usuário**. Spec **não** Confirmed.

---

## User Stories

### P0: Diagnostic + label sign-off ⭐ MVP-gate

**User Story**: As ML owner, I want a documented diagnosis of label↔serving
hypothesis fit and an explicit label-policy decision so that subsequent feature
and model work optimizes the right target.

**Why P0**: User exigiu diagnostic + decisão de label como P0 **da mesma
feature** (não spike separado). Sem isso, P1/P2 otimizam o alvo errado.

**Acceptance Criteria**:

1. WHEN the diagnostic runs on the authorized RO dataset THEN the system SHALL
   produce sanitized evidence comparing at least: (a) current Nest PnL/R binary
   label vs model scores, and (b) a clearly defined proxy or analysis for
   “target-before-stop” feasibility (or an explicit BLOCKED reason if fields
   cannot support it).
2. WHEN the diagnostic completes THEN docs SHALL record train/holdout sizes,
   feature_dim, and Q1–Q3-style metrics under the **current** label without
   claiming PASS by rounding or waiving `shadow-acceptance-v1`.
3. WHEN Product/ML signs off THEN `docs/label-policy.md` (or an addendum linked
   from it) SHALL state the chosen training target for challenger-signal-v1
   (keep PnL/R, redefine target-before-stop, or hybrid) with owner + date —
   **no numeric shadow threshold invention**.
4. WHEN label policy changes THEN a **new** `dataset_id` / manifest SHALL be
   required before any promotion-oriented Heavy/real re-run.
5. WHEN RO credentials or required columns are missing THEN the diagnostic
   SHALL fail closed with an actionable stop reason (no silent skip).

**Independent Test**: Evidence doc exists with methods + limitations; label
decision recorded as signed table row; can demo “current label metrics” without
running grid search.

---

### P1: A* / feature contract + measurable train signal

**User Story**: As ML owner, I want feature parity (A*) resolved or explicitly
gated, and a feature set that shows **non-chance signal on train**, so that
holdout Q1–Q3 failure is not driven by broken feature↔label alignment.

**Why P1**: A* parity com Nest ainda aberto; CQ-v1 já mostrou que só volume +
cats V1 defaults não bastam.

**Acceptance Criteria**:

1. WHEN A* work is in scope (per gray-area 2) THEN evidence SHALL update
   `docs/schema-discovery.md` (or linked evidence) to PASS, FAIL, or
   conditional PASS with concrete criteria — never silent PENDING.
2. WHEN building the challenger feature vector THEN the system SHALL document
   feature_order / encoder / FD alignment and SHALL reject exit-derived leakage
   features.
3. WHEN evaluating signal after label sign-off THEN the system SHALL report
   **train** AUC (and holdout AUC) under the signed label; “signal unlocked”
   for P2 SHALL mean an **operational** train-AUC criterion agreed in Design
   after gray-area 3 — **not** a change to shadow Q1 threshold.
4. WHEN feature export cannot meet full-vector / join integrity THEN the run
   SHALL fail closed (no imputed invention of missing required features).
5. WHEN using the database THEN the system SHALL use only
   `TRAINING_DATABASE_URL` (readonly).

**Independent Test**: Unit/contract tests for feature vector + leakage guard;
sanitized train AUC table before any hyperparameter grid.

---

### P2: Model grid + calibration (gated)

**User Story**: As ML owner, I want LightGBM grid / early-stop and optional
post-hoc calibration **only after** train shows signal, so that compute is not
spent fitting noise.

**Why P2**: CQ-v1 decision 3A deferred grid/calib; unlock depends on gray-area 3.

**Acceptance Criteria**:

1. WHEN the P2 unlock condition (gray-area 3) is not met THEN the pipeline
   SHALL refuse grid/calibration runs for promotion evidence (or mark them
   exploratory-only with no promotion claim).
2. WHEN unlocked THEN grid/early-stop SHALL fit **without** using holdout for
   model selection; holdout remains for final Q1–Q3 only.
3. WHEN calibration (isotonic/Platt or equivalent) is applied THEN it SHALL be
   fit on validation (or nested scheme documented), never on holdout.
4. WHEN re-running Heavy/real THEN Q1–Q3 SHALL be compared to unchanged
   `shadow-acceptance-v1` thresholds; B1/G1/L1/M1 remain part of overall gate
   when evaluated.
5. WHEN any of Q1–Q3 is FAIL THEN `overall_verdict` SHALL NOT be PASS and
   promotion artifacts SHALL be refused.

**Independent Test**: Gate test blocks P2 without unlock flag/evidence; one
synthetic path shows calib does not touch holdout.

---

## Edge Cases

- WHEN Nest fields cannot reconstruct target-before-stop THEN system SHALL
  document BLOCKED for that proxy and force an explicit label decision (keep
  PnL/R vs hybrid vs defer) — not invent labels.
- WHEN A* is FAIL THEN system SHALL follow gray-area 2 (stop vs parallel
  offline reconstruction) without inventing SE FD changes in this repo.
- WHEN train AUC remains ~0.5 after label+features THEN P2 SHALL stay locked
  (unless gray-area 3 chooses otherwise) and evidence SHALL recommend stop or
  new feature — not threshold waive.
- WHEN holdout N < 200 THEN evaluation SHALL be BLOCKED.
- WHEN `TRAINING_DATABASE_URL` is missing, not RO, or equals SE `DATABASE_URL`
  THEN Heavy/real and diagnostic RO paths SHALL refuse to run.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| CSIG-01 | P0: Diagnostic evidence (PnL/R vs target-before-stop proxy) | Specify | Pending |
| CSIG-02 | P0: Sanitized metrics under current label | Specify | Pending |
| CSIG-03 | P0: Label policy sign-off documented | Specify | Pending |
| CSIG-04 | P0: New dataset_id after label change | Specify | Pending |
| CSIG-05 | P0: Fail-closed diagnostic / RO | Specify | Pending |
| CSIG-06 | P1: A* status closed (PASS/FAIL/conditional) | Specify | Pending |
| CSIG-07 | P1: Feature contract + leakage reject | Specify | Pending |
| CSIG-08 | P1: Train (+ holdout) AUC signal report | Specify | Pending |
| CSIG-09 | P1: Full-vector / join fail-closed | Specify | Pending |
| CSIG-10 | P1: RO-only DB boundary | Specify | Pending |
| CSIG-11 | P2: Unlock gate before grid/calib | Specify | Pending |
| CSIG-12 | P2: Holdout unused for selection | Specify | Pending |
| CSIG-13 | P2: Calibration off-holdout | Specify | Pending |
| CSIG-14 | P2: Q1–Q3 vs immutable shadow-acceptance-v1 | Specify | Pending |
| CSIG-15 | P2: No PASS if Q1–Q3 FAIL | Specify | Pending |

**Coverage:** 15 total, 0 mapped to tasks, 15 unmapped ⚠️ (expected pre-Design/Tasks)  
**ID prefix:** `CSIG-`

---

## Success Criteria

Tied to **`shadow-acceptance-v1`** (doc imutável — **não** alterar números):

- [ ] P0 diagnostic + label sign-off published; open questions 1–4 answered.
- [ ] P1 delivers documented A*/feature disposition and **train** signal report
      under the signed label.
- [ ] Heavy/real (when re-run for promotion claim) evaluates Q1 (`auc_roc` ≥
      0.55), Q2 (`brier_score` ≤ 0.25), Q3 (`ece` ≤ 0.10) honestly on signed
      holdout N ≥ 200 — same thresholds as `docs/shadow-acceptance.md`.
- [ ] `overall_verdict=PASS` only if applicable gate criteria PASS; else FAIL /
      BLOCKED — no waive.
- [ ] Limiares `shadow-acceptance-v1` **inalterados**.
- [ ] Sem uso de `DATABASE_URL` do Score Engine; evidência sem secrets.

---

## Implicit-requirement dimensions (Medium/Complex sweep)

| Dimension | Resolution |
| --- | --- |
| Input validation & bounds | Holdout ≥ 200; RO URL checks; label disposition enum win/loss/excluded |
| Failure / partial-failure | Fail-closed diagnostic, missing columns, A* FAIL paths |
| Idempotency / retry | New `dataset_id` on label/feature policy change; re-run safe manifests |
| Auth boundaries & rate limits | TRAINING_DATABASE_URL RO only; N/A rate limits (offline) |
| Concurrency / ordering | N/A — offline batch (Design may add bounded workers later) |
| Data lifecycle / expiry | Manifests + evidence in git; no prod mutation / no alias moves here |
| Observability | Sanitized diagnostic + Heavy/real evidence tables |
| External-dependency failure | DB unreachable / pg_hba → abort with stop reason |
| State-transition integrity | Label unsigned → no promotion re-run; P2 locked until unlock; FAIL ⇒ no promote |

Remaining dimensions N/A for this offline training-repo scope (payments, end-user auth UI).
