# Project State — maxxtrading-model-training

## Decisions

| ID | Decisão | Rationale | Status | Data |
| -- | ------- | --------- | ------ | ---- |
| AD-T01 | Datasets challenger-quality usam `quota_batch` + FD numerical-12 completo + categoricals incluídas; nunca afrouxar `shadow-acceptance-v1`; nunca `DATABASE_URL` do Score Engine | Spec CQ-v1 | active | 2026-08-12 |

## Handoff

**Última atualização:** 2026-08-12 — T9 Heavy/real CQ-v1 executado (AUTH)

- T1–T9 done; validation code PASS; Heavy/real **overall FAIL** (Q1–Q3)
- dataset_id `95764ac1…`; train=890 holdout=2300; B1/G1/L1/M1 PASS; Q1–Q3 FAIL
- Commits evidência: `ebed07c` (+ fix Decimal `cbcd8bd`); push OK
- Limiares `shadow-acceptance-v1` **inalterados**
- Próximo: melhorar sinal (features/modelo além V1 defaults — fora do MVP 3A) ou aceitar FAIL e não promover; T25 bloqueado sem PASS

