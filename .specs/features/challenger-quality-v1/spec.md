# Challenger Quality V1 Specification

**Status**: Confirmed — 2026-08-12 (user: SPEC CONFIRMADO / pode seguir)  
**Repo**: `maxxtrading-model-training`  
**Branch alvo**: `feature/mlflow-p4-challenger-shadow` (ou branch filha dedicada)  
**Related**: T24 Heavy/real FAIL; `docs/shadow-acceptance.md` (`shadow-acceptance-v1`);
roadmap SE Phase 4 (MLF-15/25/27)  
**Context**: `.specs/features/challenger-quality-v1/context.md`  
**Scope tier**: Medium

## Problem Statement

O Heavy/real T24 contra `TRAINING_DATABASE_URL` RO produziu holdout válido
(N=307) mas qualidade ~aleatória (AUC≈0.51) com **train=128** sob seleção
top-N + corte temporal T8. Sem mais train, features categóricas e avaliação
completa de B1/G1, o challenger não pode passar `shadow-acceptance-v1`. Os
limiares assinados **não** podem ser afrouxados; o pipeline de dados/treino
precisa mudar.

## Goals

- [ ] Dataset reproduzível com cota por partição + janela/`train_end` revisados
      (novo `dataset_id`), holdout ≥ 200, train substancialmente maior que o FAIL atual.
- [ ] Treino LightGBM V1 defaults incluindo numerical-12 **e** categoricals
      `trend_regime` / `volatility_regime`, sem leakage.
- [ ] Re-run Heavy/real T24 com os **sete** critérios Q1–M1 avaliados de forma
      honesta; `overall_verdict=PASS` somente se todos PASS.
- [ ] Evidência sanitizada + ponteiro no Score Engine sem duplicar o spec.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Alterar `shadow-acceptance-v1` / inventar limiares | Política MLF-15; sign-off já fechado |
| Grid de hiperparâmetros / early-stop tuning / calibração pós-hoc | Decisão 3A — Deferred |
| Escrita MLflow registry / alias (T25) | OF-4 + task separada |
| Orquestrador shadow no Score Engine (T26) | Repo/task diferentes |
| Relatório T27 / evidência T28 | Dependem de T26 + alias real |
| Usar `DATABASE_URL` do Score Engine | Isolamento RO; só `TRAINING_DATABASE_URL` |
| Encolher `feature_order` numerical-12 | Contrato FD / serving |
| Treino dentro do Score Engine | AD-013 |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Estratégia de dados | Cota por partição **e** novo `train_end`/janela | User 1C | y |
| Features MVP | numerical-12 + cats `trend_regime`/`volatility_regime` | User 2 A+B | y |
| Modelo MVP | LightGBM V1 defaults only | User 3A | y |
| Completeness do gate | Todos Q1–M1; B1/G1 computados offline nesta feature | User 4 “mais completo possível” | y — confirm below |
| Spec location | Training `.specs/` + ponteiro curto no SE | User 5B | y |
| Cotas mínimas train/val | Agent discretion; holdout ≥ 200 fixo; train ≫ 128 e preferencialmente ≥ 1000 se dados existirem | Discretion | n — validate in Design with RO audit |
| Encoder categórico | Determinístico, versionado no manifesto, bundle-compatible | Discretion | n — Design |
| Fonte de grades B1/G1 | Offline: `thresholds.json` do SE (read-only) + `probabilityWin`/score path alinhado ao SE o suficiente para grade A/B/C; `result_r` do Nest quando disponível | Completeness sem T26 | y — confirm below |
| Peer vs baseline_heuristic em L1 | Peer LGBM OK para regressão de custo neste MVP; baseline_heuristic serving-image = Deferred | Evidência atual | y |

**Open questions:** none unmarked — defaults above await explicit user confirm of this spec.

---

## User Stories

### P1: Partition-quota dataset + revised temporal window ⭐ MVP

**User Story**: As ML owner, I want full-vector samples allocated with per-partition
quotas and a documented temporal split so that train is no longer starved under
`n_max`.

**Why P1**: Root cause of AUC≈0.51; without this, model/feature work cannot pass Q1–Q3.

**Acceptance Criteria**:

1. WHEN the export/smoke builds a batch THEN the system SHALL enforce configurable
   minimum full-vector counts for train, validation, and holdout partitions
   (holdout minimum SHALL be ≥ 200).
2. WHEN quotas cannot be met with available RO data THEN the system SHALL fail
   closed with an explicit stop reason (no silent underfill, no threshold waive).
3. WHEN the temporal window or `train_end` changes THEN the system SHALL emit a
   **new** `dataset_id` whose manifest records window bounds, split ends, seed,
   feature_order, deferred/included categoricals, quotas, and checksums.
4. WHEN selecting packs THEN the system SHALL NOT rely solely on global top-N
   that drains the train window; selection SHALL respect partition quotas.
5. WHEN using the database THEN the system SHALL use only `TRAINING_DATABASE_URL`
   (readonly) and SHALL never use the Score Engine `DATABASE_URL`.

**Independent Test**: Unit tests with synthetic packs prove quota enforcement and
fail-closed underfill; optional authorized RO audit prints sanitized monthly
counts + resulting partition sizes for the chosen window.

---

### P1: Categorical features in train + bundle ⭐ MVP

**User Story**: As ML owner, I want `trend_regime` and `volatility_regime` included
in the challenger feature vector and artifact bundle so that the model can use
signals already deferred in the FD.

**Why P1**: User required A+B; numerical-only may be insufficient even with more rows.

**Acceptance Criteria**:

1. WHEN vectorizing for challenger-quality runs THEN the system SHALL include
   encoded `trend_regime` and `volatility_regime` in addition to numerical-12.
2. WHEN a required categorical is missing THEN the sample SHALL be partial/skipped
   (fail-closed for that sample), not imputed with invented values.
3. WHEN exporting the artifact bundle THEN encoder artifacts and checksums SHALL
   satisfy the existing Score Engine bundle contract (optional encoder.pkl + sha).
4. WHEN the manifest is written THEN it SHALL record that categoricals are
   **included** (not deferred) for this dataset_id.

**Independent Test**: Unit tests cover encode/decode determinism, missing-cat
skip, and bundle validation with encoder present.

---

### P1: Complete T24 gate evaluation (Q1–M1) ⭐ MVP

**User Story**: As ML/Produto, I want the Heavy/real re-run to score all seven
signed criteria honestly so that PASS means promotion-ready quality, not a
partial waive.

**Why P1**: “Mais completo possível”; B1/G1 must not remain `None` by omission.

**Acceptance Criteria**:

1. WHEN evaluating the challenger on the signed holdout THEN the system SHALL
   compute Q1 (`auc_roc`), Q2 (`brier_score`), Q3 (`ece`) without using holdout
   for fitting.
2. WHEN computing B1/G1 THEN the system SHALL derive grades offline from the
   Score Engine `thresholds.json` (read-only path) and SHALL use `result_r`
   (or the fallback defined in `shadow-acceptance.md`) — never fabricate R.
3. WHEN `result_r` (or fallback inputs) are unavailable for grade-A sets THEN
   B1 SHALL be FAIL or BLOCKED (fail closed), not skipped.
4. WHEN probing L1/M1 THEN the system SHALL emit p95 ratio and RSS delta and
   compare to signed thresholds without rounding toward PASS.
5. WHEN any of Q1–M1 is FAIL or BLOCKED THEN `overall_verdict` SHALL be FAIL
   (or BLOCKED) and bundle export SHALL be refused.
6. WHEN all seven are PASS THEN the system SHALL allow bundle export and record
   sanitized Heavy/real evidence (no secrets).

**Independent Test**: Unit tests force each criterion FAIL in isolation; one
synthetic path can PASS all seven; evidence doc template lists all seven rows.

---

### P2: Score Engine pointer (docs only)

**User Story**: As the Score Engine agent, I want a short pointer to this
training-repo spec so that Phase 4 handoffs know where quality remediation lives.

**Why P2**: User 5B; avoids duplicating the full spec into SE.

**Acceptance Criteria**:

1. WHEN this feature is confirmed THEN the Score Engine SHALL gain a short
   markdown pointer (path, branch, CQ-IDs, link to training repo) under
   `docs/mlflow/` or the roadmap evidence index — **without** copying the full
   spec body.
2. WHEN the pointer is written THEN it SHALL state that limiares remain
   `shadow-acceptance-v1` in the training repo and that T26 is still required
   for online/batch shadow orchestration (this feature only does offline B1/G1).

**Independent Test**: File exists; contains absolute GitHub or clone-relative
paths; no secrets; no duplicated AC tables.

---

### P3: Serving-image baseline_heuristic probe

**User Story**: As ops, I want L1/M1 optionally measured against production
`baseline_heuristic` on the serving image.

**Why P3**: Stronger fidelity; not required to unblock data/feature MVP.

**Acceptance Criteria**:

1. WHEN an authorized serving-image probe is available THEN evidence MAY record
   L1/M1 vs `baseline_heuristic` in addition to peer LGBM.

---

## Edge Cases

- WHEN RO data cannot fill train quota THEN system SHALL stop with actionable
  sanitized counts (per month / partition) — suggest backfill Nest packs, not
  shrink feature_order.
- WHEN holdout would fall below 200 after quota logic THEN system SHALL BLOCK
  evaluation.
- WHEN label leakage features appear (exit-derived) THEN system SHALL reject
  the feature set.
- WHEN `TRAINING_DATABASE_URL` equals app `DATABASE_URL` or user is not readonly
  THEN system SHALL refuse to run Heavy/real.
- WHEN write probe succeeds THEN system SHALL abort (credential not RO).
- WHEN thresholds.json path is missing THEN B1/G1 computation SHALL FAIL closed.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| CQ-01 | P1: Partition-quota dataset | Design | Pending |
| CQ-02 | P1: Partition-quota fail-closed | Design | Pending |
| CQ-03 | P1: New dataset_id / manifest | Design | Pending |
| CQ-04 | P1: RO-only DB boundary | Design | Pending |
| CQ-05 | P1: Categoricals included | Design | Pending |
| CQ-06 | P1: Missing cat fail-closed | Design | Pending |
| CQ-07 | P1: Bundle encoder contract | Design | Pending |
| CQ-08 | P1: Holdout Q1–Q3 leakage-safe | Design | Pending |
| CQ-09 | P1: Offline B1/G1 honest compute | Design | Pending |
| CQ-10 | P1: L1/M1 + strict compare | Design | Pending |
| CQ-11 | P1: overall PASS iff all seven | Design | Pending |
| CQ-12 | P1: Sanitized Heavy/real evidence | Design | Pending |
| CQ-13 | P2: SE pointer doc | Design | Pending |
| CQ-14 | P3: baseline_heuristic probe | - | Pending (optional) |

**Coverage:** 14 total, 0 mapped to tasks, 14 unmapped ⚠️ (expected pre-Tasks)

---

## Success Criteria

- [ ] Novo `dataset_id` com cotas satisfeitas; train N ≫ 128 (alvo operacional ≥ 1000 se a RO permitir; senão máximo auditável + stop reason).
- [ ] Challenger LightGBM V1 + numerical-12 + cats inclusas.
- [ ] Heavy/real re-run: tabela Q1–M1 completa; **PASS** só com sete PASS.
- [ ] `docs/t24-challenger-eval-evidence.md` (ou doc dedicado) atualizado, sem secrets.
- [ ] Ponteiro no Score Engine publicado.
- [ ] Limiares `shadow-acceptance-v1` inalterados.

---

## Implicit-requirement dimensions (Medium sweep)

| Dimension | Resolution |
| --- | --- |
| Input validation & bounds | Quotas, holdout ≥ 200, window RO URL checks |
| Failure / partial-failure | Fail-closed underfill, missing cats, missing thresholds/R |
| Idempotency / retry | Dataset_id deterministic from manifest payload; re-run safe |
| Auth boundaries | TRAINING_DATABASE_URL readonly only; no SE DATABASE_URL |
| Concurrency / ordering | N/A — offline batch jobs, single-threaded eval |
| Data lifecycle | Manifest + evidence versioned in git; no prod mutation |
| Observability | Sanitized evidence metrics + stop reasons |
| External-dependency failure | DB unreachable → abort; document like prior AUTH attempt |
| State-transition integrity | FAIL ⇒ no bundle; PASS ⇒ bundle allowed; no alias moves here |

Remaining dimensions N/A beyond this offline training scope.
