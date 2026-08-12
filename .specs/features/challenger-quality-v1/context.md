# Challenger Quality V1 — Context

**Gathered:** 2026-08-12  
**Spec:** `.specs/features/challenger-quality-v1/spec.md`  
**Status:** Ready for design (pending user confirm of spec)

---

## Feature Boundary

Entregar, no `maxxtrading-model-training`, um caminho reproduzível para
**aumentar train/features** (sem afrouxar `shadow-acceptance-v1`), re-rodar
Heavy/real T24 e atingir o gate **mais completo possível** (Q1–M1), com
evidência sanitizada e ponteiro no Score Engine. **Não** inclui registro
MLflow (T25), orquestrador shadow SE (T26) nem relatório T27.

---

## Implementation Decisions

### 1. Como aumentar train

- **Cota por partição** no export/smoke: mínimos explícitos de full-vectors em
  train / validation / holdout (holdout ≥ 200 por `shadow-acceptance-v1`).
- **E** ajuste documentado de `train_end` / janela temporal → **novo
  `dataset_id`** (manifesto imutável; não reutilizar o id do FAIL atual).
- Seleção top-N global sozinha é insuficiente; cota + janela juntos.

### 2. Features

- Manter `feature_order=numerical` (12) alinhado ao FD do Score Engine —
  **não** encolher.
- **Incluir** categoricals adiados `trend_regime` e `volatility_regime` neste
  MVP (encoder no bundle / vetor de treino), com testes de contrato.

### 3. Modelo / calibração

- **Somente** LightGBM V1 defaults (`challenger_config.py`) com mais dados.
- **Fora deste MVP:** grid de hiperparâmetros, early stopping tuning loop,
  calibração isotonic/Platt (Deferred Ideas se ECE falhar após dados+cats).

### 4. Sucesso do gate (mais completo possível)

- Avaliar **os 7 critérios** Q1–Q3, B1, G1, L1, M1 contra
  `docs/shadow-acceptance.md` (`shadow-acceptance-v1`).
- B1/G1 **não** ficam `None` fail-closed por omissão: esta feature **deve**
  computar honestamente grades (thresholds do SE) e proxy R (`result_r` /
  fallback documentado na acceptance) na mesma população holdout/shadow
  offline — sem esperar o orquestrador T26.
- `overall_verdict=PASS` só se **todos** os sete forem PASS; senão FAIL /
  BLOCKED (sem waive, sem arredondar).
- Bundle export só com PASS (já invariante em `challenger_eval`).

### 5. Onde mora o spec

- Canônico de execução: `maxxtrading-model-training/.specs/features/challenger-quality-v1/`.
- Ponteiro curto no Score Engine (docs/roadmap ou evidence) apontando path +
  branch + requirement IDs — sem duplicar o corpo do spec.

### Agent's Discretion

- Números exatos das cotas mínimas de train/validation (desde que holdout ≥
  200 e train ≫ holdout de forma auditável).
- Forma exata do encoder categórico (one-hot vs ordinal) desde que
  determinística, versionada no manifesto e compatível com o bundle SE.
- Layout do ponteiro no Score Engine (arquivo curto vs seção em evidence).

### Declined / Undiscussed Gray Areas → Assumptions

- Hiperparâmetro grid / calibração: **fora** (decisão 3A) — se Q3 falhar com
  AUC ok após dados+cats, vira feature seguinte, não expandir silenciosamente.
- Backfill Nest `se-fd-v1` de packs históricos: **recomendado** se a auditoria
  temporal mostrar train vazio por packs pre-ponte; execução do backfill em
  si pode ser pré-requisito operacional externo (não código SE).

---

## Specific References

- Heavy/real FAIL: `docs/t24-challenger-eval-evidence.md` —
  `dataset_id=5813bf75…`, train 128 / val 1565 / holdout 307.
- Limiares imutáveis: `docs/shadow-acceptance.md` (`shadow-acceptance-v1`).
- Política: `docs/agent-repo-policy.md` + canônico SE
  `docs/mlflow/agent-repo-policy.md`.

---

## Deferred Ideas

- Grid LightGBM + early stop na validation.
- Calibração pós-hoc se ECE falhar com AUC ≥ 0.55.
- Probe L1/M1 contra `baseline_heuristic` na imagem de serving real (além do
  peer LGBM).
- T25 registry VPS / T26 shadow orchestrator / T27 comparison report.
