# Trade Outcome Label Policy

**Status**: APPROVED — 2026-07-31 (ML + Tech Lead: fcsousa).
**Requirement**: MLF-05 (`maxxtrading-scoreengine` spec.md).
**Related**: TDD serviço §14.4 ("Regra de rotulagem `trade_outcomes` —
🔴 Aberta" — fechada aqui por evidência NestJS), roadmap TDD risk row
("Rotulagem de `trade_outcomes` indefinida").
**Evidence**: `docs/schema-discovery.md`; NestJS `fcsousa/maxxtrading@65ebecd`.

This document is the single source of truth for how NestJS trade rows become
the training target for models consumed by the Score Engine.

> **Schema correction**: `trading.trade_outcomes` does **not** exist (neither
> in NestJS Prisma nor in DB `maxxtrading-scoreengine`). The Score Engine ACL
> assumption (`signal_id`/`closed_at`) is obsolete for training. T6+ SHALL
> export from NestJS `public.trade_samples` (preferred) and/or
> `public.historical_trades`, never from a fictional `trading.trade_outcomes`.

## 1. Schema findings

Canonical training row = `public.trade_samples` (see discovery doc for full
column list). Outcome-relevant fields:

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | `TEXT` | trade sample PK |
| `source_type` | enum | `historical_import` / `live_order` / `paper_order` |
| `entry_at` / `exit_at` | timestamptz | `exit_at IS NULL` ⇒ unresolved |
| `entry_price` / `exit_price` | decimal | prices; exit nullable while open |
| `realized_pnl` | decimal nullable | primary label driver (sign) |
| `result_r` | decimal nullable | R-multiple vs stop risk when known |
| `result_label` | `TradeResultLabel?` | `win` / `loss` / `breakeven` |
| `sample_quality` | `TradeSampleQuality` | `complete` / `partial` / `invalid` |
| `status` (historical only) | `HistoricalTradeStatus` | use only `valid` |

NestJS derivation (authoritative code):

1. **PnL path** — `TradeSampleQualityService.deriveResultLabel` /
   `deriveResultLabel(realizedPnl)`:
   - `realized_pnl > 0` → `win`
   - `realized_pnl < 0` → `loss`
   - `realized_pnl = 0` → `breakeven`
   - `realized_pnl` null → no label
2. **R path** (historical schema-2 / risk plan) — `computeResultR`:
   - `result_r > ε` → `win`
   - `result_r < -ε` → `loss`
   - `|result_r| < ε` (`ε = 1e-8`) → `breakeven`

The Score Engine product hypothesis “probabilityWin = hit target before stop”
describes the **semantic intent** of the served probability, not a stored
boolean on NestJS rows. Stored labels are PnL/R-sign based.

## 2. Win / loss / timeout / partial disposition

Training target for binary `probabilityWin`: **`win` → 1**, **`loss` → 0**.
Every observed state maps to exactly one of `win`, `loss`, `excluded`.

| Observed state | Disposition | Rationale |
| --- | --- | --- |
| `result_label = win` **and** `sample_quality = complete` | `win` | NestJS positive PnL / positive R |
| `result_label = loss` **and** `sample_quality = complete` | `loss` | NestJS negative PnL / negative R |
| `result_label = breakeven` (any quality) | `excluded` | Not a binary win; keep out of V1 classifier |
| `sample_quality = partial` | `excluded` | Incomplete exit/PnL fields — NestJS definition of partial |
| `sample_quality = invalid` | `excluded` | Missing critical entry fields |
| `result_label IS NULL` | `excluded` | Unlabeled |
| `exit_at IS NULL` (open / unresolved sample) | `excluded` | Incomplete outcome — lookahead guard |
| `source_type` any of the three enums, if otherwise complete+labeled | eligible | Live/paper/import all OK when quality/label gates pass |
| `historical_trades.status ∈ {invalid, voided, superseded}` | `excluded` | Non-valid import rows |
| Trade “timeout” / expired holding period | `excluded` unless NestJS persisted a complete labeled exit | **No timeout enum exists**; if a timed exit is stored as a normal close with PnL/label, it follows the `result_label` rows above |
| Order `PARTIALLY_FILLED` without a complete closed sample | `excluded` | Only projected closed samples with complete quality enter training |

## 3. Lookahead cutoff and exclusions

- **As-of rule**: a sample is eligible for a training window ending at `as_of`
  only if `exit_at IS NOT NULL AND exit_at <= as_of` **and** disposition from
  §2 is `win` or `loss`.
- **Still-open signals/samples**: excluded while `exit_at IS NULL` (never
  labeled win/loss for training).
- **Quality gate**: require `sample_quality = complete` (aligns with NestJS
  calibration/readers that already filter this way).
- **Other exclusions**: `breakeven`; `invalid`/`partial` quality; null
  `result_label`; non-`valid` historical statuses; any row failing the as-of
  rule.
- **Temporal split (T7)**: partitions by `entry_at` (or `exit_at` — builder
  must pick one and record it in the manifest) must be monotonic and
  non-overlapping; no future exits relative to `as_of`.

## 4. Approval

| Role | Name | Date | Signed |
| --- | --- | --- | --- |
| ML owner | fcsousa | 2026-07-31 | ☑ |
| Tech Lead | fcsousa | 2026-07-31 | ☑ |

**Evidence refs**:

- NestJS migration `20260608120000_historico_trades_score_llm_phase1`
- `src/modules/trade-samples/trade-sample-quality.service.ts`
- `src/modules/historical-trades/utils/exit-1r-risk-plan.util.ts`
- `docs/schema-discovery.md` (SQL: no `trading.trade_outcomes` on SE DB)

**Gate**: T6 (dataset exporter) may proceed against NestJS `trade_samples`
using this disposition table. Exporter MUST use a dedicated
`TRAINING_DATABASE_URL` with read-only SELECT on NestJS tables — never the
Score Engine app `DATABASE_URL`. Live distinct-count sampling remains a
follow-up once that credential is reachable (does not re-open §2–3).
