# Challenger Signal V1 — Context

**Gathered:** 2026-08-12 (Specify + Discuss opened)  
**Spec:** `.specs/features/challenger-signal-v1/spec.md`  
**Status:** Gray Areas presented (awaiting user)

---

## Feature Boundary

No `maxxtrading-model-training`, entregar **challenger-signal-v1**: (P0)
diagnóstico label↔serving + sign-off de política de rótulo; (P1)
fechamento/condicionamento A*/features com sinal mensurável no train; (P2)
grid LightGBM + calibração **somente se desbloqueado**. Limiares
`shadow-acceptance-v1` permanecem imutáveis. **Não** inclui T25/T26/T27,
treino no Score Engine, nem afrouxar Q1–Q3.

---

## Gray Areas presented (awaiting user)

Responda no formato `1x 2y 3z 4w` (ex.: `1B 2A 3C 4B`). Opção **D** =
“Você decide” (agent discretion no Design, registrada depois).

### 1. Label strategy

Alvo de treino vs hipótese de serving (`probabilityWin` ≈ hit target before
stop). Hoje: Nest PnL/R (`docs/label-policy.md`).

| Opção | Significado |
| --- | --- |
| **A** | Manter PnL/R win/loss como alvo canônico; documentar gap vs serving hyp |
| **B** | Redefinir alvo para proxy **target-before-stop** (campos Nest/reconstrução); atualizar `label-policy` com sign-off |
| **C** | Híbrido: treinar/avaliar ambos; promoção usa um alvo primário explícito |
| **D** | Você decide |

### 2. A* / feature parity

`docs/schema-discovery.md` — A* ainda PENDING/conditional. Quando novas
features / re-treino de sinal?

| Opção | Significado |
| --- | --- |
| **A** | A* **deve PASS** (ou conditional PASS assinado) **antes** de novas features / P1 signal work |
| **B** | Trilha **paralela**: A* + features/offline reconstruction ao mesmo tempo; gate de promoção exige A* fechado |
| **C** | A* só documental; prioridade é features/offline join mesmo se A* ficar FAIL |
| **D** | Você decide |

### 3. Quando desbloquear model grid / calibration

CQ-v1 3A adiou grid/calib. P2 desta feature.

| Opção | Significado |
| --- | --- |
| **A** | Só após **train AUC** atingir limiar **operacional** (número a definir no Design **sem** alterar Q1 shadow 0.55) |
| **B** | Sempre tentar grid/calib em paralelo (exploratório), mas evidência de promoção só se train mostrar sinal |
| **C** | Sempre tentar e permitir claim de promoção se holdout Q1–Q3 PASS, mesmo com train fraco |
| **D** | Você decide |

### 4. Spec location

Onde mora o canônico + handoff SE (como CQ-v1).

| Opção | Significado |
| --- | --- |
| **A** | Somente `maxxtrading-model-training/.specs/features/challenger-signal-v1/` |
| **B** | Training canônico **+** ponteiro curto no Score Engine (docs/mlflow ou evidence) — sem duplicar o corpo |
| **C** | Spec espelhado nos dois repos (não recomendado; só se insistir) |
| **D** | Você decide |

---

## Implementation Decisions

*(vazio — aguardando respostas 1–4)*

### Agent's Discretion

*(preencher após opções D ou lacunas declinadas)*

### Declined / Undiscussed Gray Areas → Assumptions

*(nenhuma ainda — discussão aberta)*

---

## Specific References

- CQ-v1 Heavy/real T9 FAIL: train=890, holdout=2300, feature_dim=18,
  auc≈0.493, brier≈0.267, ece≈0.108; B1/G1/L1/M1 PASS.
- Root cause: predictor/features/label fit — não train starvation.
- CQ-v1 deferred grid/calibration (decisão 3A).
- Label: `docs/label-policy.md` (APPROVED PnL/R); serving hyp target-before-stop.
- A*: `docs/schema-discovery.md` (PENDING / conditional).
- Limiares imutáveis: `docs/shadow-acceptance.md` (`shadow-acceptance-v1`).

---

## Deferred Ideas

- T25 MLflow registry / alias promotion.
- T26 shadow orchestrator no Score Engine; T27/T28 reports.
- Mudanças de código Nest para persistir boolean target-before-stop (se B/C
  precisarem de campos novos — fora deste repo).
- Alterar números de `shadow-acceptance-v1` — **proibido** nesta feature.
