# maxxtrading-model-training — Agent Instructions

Pipeline externo de dados/treino do `maxxtrading-scoreengine` (AD-013). Ver
`README.md` para a fronteira completa.

## Regras de agent

- **Nunca** escrever em `trading.*`; leitura somente-leitura, credencial
  dedicada (nunca o `DATABASE_URL` do Score Engine).
- Nenhum código deste repo é importado pelo Score Engine — a integração é
  só o artefato de modelo publicado no MLflow registry.
- Artefatos pickle só a partir de runs autorizados deste repositório;
  checksum documenta integridade, não substitui controle de autoria do
  registry.
- Sem `uv sync`/`uv lock`, treino real ou acesso a dados reais sem
  autorização explícita do usuário na sessão.
- PT-BR em docs/mensagens; identificadores de código em inglês.
- Decisões de negócio (regra de rotulagem win/loss/timeout/partial,
  limiares numéricos de aceite) exigem sign-off explícito do usuário — não
  inventar valores.

## Referências

- Repositório irmão: `maxxtrading-scoreengine`
  (`.specs/features/mlflow-adoption-roadmap/` para spec/design/tasks).
- Contrato de leitura: `docs/trading_read_contract.md` naquele repositório.
