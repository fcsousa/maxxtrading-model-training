# Challenger Quality V1 — Runbook

**Feature**: `.specs/features/challenger-quality-v1/` (CQ-01..CQ-13)  
**Repo**: [maxxtrading-model-training](https://github.com/fcsousa/maxxtrading-model-training)  
**Clone**: `/home/app/maxxtrading-model-training`  
**Gate numérico**: `docs/shadow-acceptance.md` (`shadow-acceptance-v1`) — **imutável** nesta feature  
**SE pointer**: Score Engine `docs/mlflow/challenger-quality-v1-pointer.md`

---

## O que muda vs smoke T8/T24

| Peça | Smoke legado | Quality V1 |
| --- | --- | --- |
| Seleção | top-N global | cotas por partição (`quota_batch`) |
| Entrypoint | `run_export_smoke` | `run_quality_export` |
| Cats | deferidas | `trend_regime` / `volatility_regime` (fit no train) |
| B1 / G1 | frequentemente `None` (fail-closed) | offline via `thresholds.json` + `result_r` |
| Overall | PASS só se Q1–M1 todos PASS | idem; export recusa non-PASS |

Limiares Q1–M1 **não** são alterados aqui. Sem afrouxar `shadow-acceptance-v1`.

---

## Cotas e janela

Defaults do quality export (overridable pelo caller):

- `train_min=800`, `validation_min=200`, `holdout_min=200` (holdout **≥ 200** obrigatório)
- `n_max` limita o universo antes da cota
- Underfill → erro fail-closed (sem dataset_id falso)

Janela / `train_end` revisados geram **novo** `dataset_id` (não reutilizar o smoke que falhou no Heavy/real).

---

## Categoricals

- Encoder fit **somente** no train; transform em val/holdout
- Sample sem cat obrigatória → excluído; se a cota quebrar → FAIL
- Manifest marca cats incluídas; bundle pode carregar o encoder

---

## Como rodar (unit / synth)

```bash
# Gates de regressão da feature
uv run pytest tests/test_quota_batch.py tests/test_categorical_encode.py \
  tests/test_offline_scoring.py tests/test_quality_export.py \
  tests/test_label_export.py tests/test_challenger_eval.py -q
```

Eval sintético com B1/G1 offline:

```python
from pathlib import Path
from training.challenger_eval import evaluate_challenger_quality

evaluation = evaluate_challenger_quality(
    partitions,
    features_by_sample_id,
    dataset_id="...",
    baseline_predict=baseline_predict,
    thresholds_path=Path("tests/fixtures/thresholds.json"),  # ou path RO do SE
    result_r_by_sample_id={sample.id: sample.result_r for sample in partitions.holdout},
    grade_confidence=0.8,
    risk_reward_ratio=2.0,
)
assert evaluation.overall_verdict in {"PASS", "FAIL", "BLOCKED"}
```

`export_challenger_bundle` recusa `overall_verdict != PASS`.

---

## Regras do gate (Q1–M1)

Fonte assinada: `docs/shadow-acceptance.md` + `src/training/shadow_acceptance.py`.

| ID | Métrica | Operador | Valor |
| --- | --- | --- | --- |
| Q1 | auc_roc | >= | 0.55 |
| Q2 | brier_score | <= | 0.25 |
| Q3 | ece | <= | 0.10 |
| B1 | mean_result_r_at_grade_A_delta | >= | 0.0 |
| G1 | max_abs_grade_share_delta_pp | <= | 15.0 |
| L1 | p95_latency_ratio_vs_baseline | <= | 2.0 |
| M1 | rss_delta_mib | <= | 256.0 |

**B1/G1 offline** (`offline_scoring` + `evaluate_challenger_quality`):

- Grades A/B/C espelham SE `thresholds.json` / AD-006 (C = não A e não B)
- Sem `result_r` útil no conjunto grade-A → B1 FAIL (fail-closed)
- Sem thresholds path → B1/G1 FAIL
- Overall PASS **somente** se os sete critérios PASS

---

## Heavy/real (T9 — fora deste batch)

Requer AUTH explícito + `TRAINING_DATABASE_URL` RO (nunca `DATABASE_URL` do Score Engine).  
Evidência em `docs/t24-challenger-eval-evidence.md`. Não inventar PASS.

---

## Fronteira Score Engine

- Orquestração shadow online/batch (**T26**) continua **obrigatória** e separada — esta feature só cobre B1/G1 offline.
- Sem secrets neste doc; sem cópia do spec completo no SE (só o pointer curto).
