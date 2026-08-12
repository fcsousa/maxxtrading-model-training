# Project State — maxxtrading-model-training

## Decisions

| ID | Decisão | Rationale | Status | Data |
| -- | ------- | --------- | ------ | ---- |
| AD-T01 | Datasets challenger-quality usam `quota_batch` + FD numerical-12 completo + categoricals incluídas; nunca afrouxar `shadow-acceptance-v1`; nunca `DATABASE_URL` do Score Engine | Spec CQ-v1 | active | 2026-08-12 |

## Handoff

**Última atualização:** 2026-08-12 — Specify in progress: `challenger-signal-v1`

- **Specify in progress**; waiting gray-area answers for
  `.specs/features/challenger-signal-v1/` (`spec.md` Draft + `context.md`)
- Precedente CQ-v1: T1–T9 done; Heavy/real **overall FAIL** (Q1–Q3);
  train=890 holdout=2300; B1/G1/L1/M1 PASS; root cause = fit label/features
  (não starvation); limiares `shadow-acceptance-v1` **inalterados**
- Próximo: usuário responde gray areas (`1x 2y 3z 4w`) → fechar Assumptions →
  Confirm spec → **só então** Design (não iniciar Design antes)
- T25 bloqueado sem PASS de qualidade

