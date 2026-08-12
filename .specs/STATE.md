# Project State — maxxtrading-model-training

## Decisions

| ID | Decisão | Rationale | Status | Data |
| -- | ------- | --------- | ------ | ---- |
| AD-T01 | Datasets challenger-quality usam `quota_batch` + FD numerical-12 completo + categoricals incluídas; nunca afrouxar `shadow-acceptance-v1`; nunca `DATABASE_URL` do Score Engine | Spec CQ-v1 | active | 2026-08-12 |

## Handoff

**Última atualização:** 2026-08-12 — Execute CQ-v1 Batches A+B + Verifier PASS

- T1–T8 done; validation PASS (sensor 0 survived after fix `a165dbc`)
- T9 Heavy/real **pending AUTH**
- Branch local commits pushed to `feature/mlflow-p4-challenger-shadow` (if push succeeded)
- SE pointer: `docs/mlflow/challenger-quality-v1-pointer.md` @ `fcc9e6a`
- Próximo: `AUTH T9` para Heavy/real quality_export re-run

