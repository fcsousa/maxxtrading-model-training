# Política de uso dos repositórios (agentes) — Model Training

**Status**: vigente (espelho operacional)  
**Canônico completo**: no clone do Score Engine → `docs/mlflow/agent-repo-policy.md`  
**GitHub Score Engine**: https://github.com/fcsousa/maxxtrading-scoreengine  
**Este repo**: https://github.com/fcsousa/maxxtrading-model-training

Agentes que abrirem **só** este clone devem seguir as regras abaixo. Em caso de
conflito, prevalece o documento canônico no Score Engine.

---

## Papel deste repo

Pipeline externo de dados/treino (AD-013). Integração com o Score Engine = artefato
publicado no MLflow registry — **nunca** import Python cruzado.

| Faça aqui | Não faça aqui |
| --- | --- |
| Label policy, exporter RO, dataset, trainer, artifact pack, shadow report, drift | Editar `app/` / loaders / Compose do Score Engine |
| Docs de política ML sob `docs/` | Usar `DATABASE_URL` do Score Engine |
| Testes sob `tests/` deste repo | INSERT/UPDATE/DELETE/DDL em tabelas de trading/app |
| Branches `feature/mlflow-p*-…` → PR para `main` | Dois agentes no mesmo branch sem claim |

---

## Tasks deste repo (roadmap)

Fonte canônica: Score Engine `.specs/features/mlflow-adoption-roadmap/tasks.md`.

| Tasks | Branch típica |
| --- | --- |
| T5–T8 (P1) | `feature/mlflow-p1-data-foundation` |
| T10 (P2) | `feature/mlflow-p2-artifact-contract` |
| T23–T25, T27 (P4) | `feature/mlflow-p4-challenger-shadow` |
| T35–T36 (P6) | `feature/mlflow-p6-operations` |

Evidências de fechamento de fase (T9, T15, T28, T37) são escritas **no Score Engine**,
não aqui — após merge deste PR e `HANDOFF` com SHA imutável.

---

## Claim / release (anti-colisão)

Antes de editar:

```text
CLAIM
repo: model-training
path: /home/app/maxxtrading-model-training   # ou path real do clone
branch: feature/mlflow-p1-data-foundation
task: T6
base: origin/<branch> @ <sha7>
ação: implementar | docs | push | pr
```

- Um claim ativo por branch. Sem rewrite/force push sem pedido explícito.
- Push/PR só com autorização explícita na sessão.
- Ao terminar: `RELEASE` + SHAs + local vs origin.

Leitura permitida no Score Engine (sem editar): `docs/trading_read_contract.md`,
`docs/mlflow/evidence/`, spec/tasks da feature. Edição no Score Engine exige claim
separado naquele clone.

---

## Gates locais

```bash
uv run pytest tests/ -q
uv run ruff check .
uv run ruff format --check .
```

Sem `uv sync`, treino real ou DB real sem autorização explícita. Credencial de dados:
somente-leitura dedicada — nunca o DSN de app do Score Engine.

---

## Handoff para o Score Engine

```text
HANDOFF
phase: P1|P2|P4|P6
from_repo: model-training
merge_commit: <sha>
pr: <url>
next_task: T9|T11|T26|T37  # no scoreengine
secrets: none
```

---

## Paths locais tipicos

| Repo | Path |
| --- | --- |
| Score Engine | `/workspace` |
| Model Training | `/home/app/maxxtrading-model-training` |
| Multi-root VS Code/Cursor | `/home/app/maxxtrading.code-workspace` |
