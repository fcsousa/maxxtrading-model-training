# maxxtrading-model-training

Pipeline externo de dados, rotulagem, treino e avaliação de modelos para o
[`maxxtrading-scoreengine`](https://github.com/fcsousa/maxxtrading-scoreengine).

## Fronteira (AD-013)

Este repositório existe porque o Score Engine **não treina modelos** — ele só
serve inferência (MLflow → cache local → baseline). Todo o pipeline de dados
e treino vive aqui, isolado por design:

- Leitura **somente-leitura** em `trading.*` (nunca `DATABASE_URL` de app —
  usa uma credencial dedicada, disposable).
- Nenhuma escrita em `trading.*`.
- Nenhum código deste repositório é importado pelo Score Engine em tempo de
  execução; a única integração é o pacote de artefato (`model.pkl` +
  `feature_schema.json` + `metrics.json` + checksums) publicado no registry
  MLflow compartilhado, consumido pelo Score Engine via alias
  (`candidate`/`staging`/`production`).
- Consulte `docs/trading_read_contract.md` no `maxxtrading-scoreengine` para
  o contrato de colunas já validado por aquele serviço; este repositório
  pode precisar de colunas adicionais de `trading.trade_outcomes` para
  rotulagem — ver `docs/label-policy.md`.

## Stack

- Python 3.11+, gerenciado via `uv`.
- `pandas`/`numpy`/`scikit-learn`/`lightgbm` para dataset e treino.
- `joblib` para serialização do artefato (mesmo contrato do loader do Score
  Engine).
- `mlflow-skinny` para tracking/registry.
- `pytest` + `ruff` para testes e lint (mesmas convenções do Score Engine).

## Estrutura

```text
docs/            Políticas e decisões (label policy, acceptance criteria)
src/training/    Código do pipeline (exporter, dataset builder, trainer, ...)
tests/           Testes unitários/integração co-localizados por componente
```

## Rodando

```bash
uv sync   # só com autorização explícita em sessões de agent
uv run pytest tests/ -q
uv run ruff check .
uv run ruff format --check .
```

Nenhum comando acima deve ser executado contra um Postgres de produção ou
contra o `DATABASE_URL` do Score Engine. Acesso a dados reais exige uma
credencial somente-leitura dedicada e autorização explícita por sessão.

## Contexto do roadmap

Este repositório é a metade externa do plano de adoção do MLflow descrito em
`maxxtrading-scoreengine`:

- Spec: `.specs/features/mlflow-adoption-roadmap/spec.md`
- Tasks: `.specs/features/mlflow-adoption-roadmap/tasks.md` (Fases 1, 2, 4, 6)
- TDD fonte: `docs/analisys/mlflow_adoption_roadmap_tdd.md`
