# Project State — maxxtrading-model-training

## Decisions

| ID | Decisão | Rationale | Status | Data |
| -- | ------- | --------- | ------ | ---- |
| AD-T01 | Datasets challenger-quality usam `quota_batch` + FD numerical-12 completo + categoricals incluídas; nunca afrouxar `shadow-acceptance-v1`; nunca `DATABASE_URL` do Score Engine | Spec CQ-v1 | active | 2026-08-12 |

## Handoff

**Última atualização:** 2026-08-12 — Design+Tasks `challenger-quality-v1` prontos

- Spec Confirmed; Design Approved; Tasks Approved for Execute
- Próximo: Execute Batch A (T1–T5) — oferecer subagent se usuário aceitar
- T9 (Heavy/real) exige AUTH explícito separado

