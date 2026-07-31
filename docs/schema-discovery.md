# `trading.trade_outcomes` — Schema Discovery Checklist

**Status**: executed 2026-07-31 — finding: table does **not** exist.
**Blocks lifted for**: `label-policy.md` sections 2–4 (policy now targets NestJS
`trade_samples` / `historical_trades` instead of the Score Engine ACL assumption).

The Score Engine's read contract only ever needed `signal_id` and `closed_at`
from a presumed `trading.trade_outcomes` table. That table is an ACL assumption
in `maxxtrading-scoreengine` (`docs/trading_read_contract.md`,
`db/testdata/000_trading_schema_testonly.sql`) and was **never created** by the
NestJS owner (`fcsousa/maxxtrading`).

## 1. Column inventory

### 1a. SQL against Score Engine DB (read-only `scoreengine_readonly`)

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'trading' AND table_name = 'trade_outcomes'
ORDER BY ordinal_position;
```

| Check | Result (sanitized) |
| --- | --- |
| Host / DB | `192.168.3.10` / `maxxtrading-scoreengine` |
| User | `scoreengine_readonly` |
| Schemas present | `ml`, `public` only — **no `trading` schema** |
| `trade_outcomes` anywhere | **0** tables |
| Tables present | `ml.inference_logs`, `ml.score_jobs`, `ml.signal_scores` |

Attempt to open NestJS DB `maxxtrading` with the same RO user from this host:
`FATAL: no pg_hba.conf entry` — distinct-value samples against live NestJS data
remain pending a dedicated `TRAINING_DATABASE_URL` with SELECT on NestJS tables.

### 1b. NestJS source of truth (authoritative)

Repo: `https://github.com/fcsousa/maxxtrading` @ `65ebecd` (2026-07-31).

There is **no** Prisma model / migration for `trading.trade_outcomes`,
`trading.trading_signals`, or `trading.signal_features`.

Canonical labeled-trade tables (migration
`prisma/migrations/20260608120000_historico_trades_score_llm_phase1/migration.sql`):

#### `public.trade_samples` (training unit)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `TEXT` PK | sample id |
| `source_type` | enum `TradeSampleSourceType` | `historical_import` / `live_order` / `paper_order` |
| `historical_trade_id` / `order_id` | `TEXT` nullable | mutually exclusive sources |
| `strategy_id`, `account_id` | `TEXT` | ownership |
| `broker`, `market` | enums | |
| `symbol`, `timeframe`, `side` | `TEXT` | |
| `entry_at`, `entry_price` | timestamptz / decimal | required for complete |
| `exit_at`, `exit_price` | timestamptz / decimal **nullable** | null ⇒ still open / unresolved |
| `quantity`, `fees` | decimal | |
| `realized_pnl`, `realized_pnl_pct` | decimal nullable | sign drives label |
| `result_r` | decimal nullable | R-multiple vs stop risk |
| `result_label` | enum `TradeResultLabel` nullable | `win` / `loss` / `breakeven` |
| `sample_quality` | enum `TradeSampleQuality` | `complete` / `partial` / `invalid` (default `partial`) |
| `sample_quality_reason` | `TEXT` nullable | missing-field reason |
| `risk_plan_source` | enum nullable | `explicit` / `inferred_from_exit_1r` |
| `correlation_id`, timestamps | | |

#### `public.historical_trades` (import source)

Same outcome fields (`realized_pnl`, `result_r`, `result_label`) plus
`status` (`valid` / `invalid` / `voided` / `superseded`). `exit_at` /
`exit_price` are **NOT NULL** on this table (imports are closed rows).

## 2. Distinct values of result/exit/status-shaped columns

**Live `GROUP BY` samples**: blocked — no NestJS RO credential reachable from
this host yet. Enum domains from Prisma (closed set):

| Column / enum | Allowed values |
| --- | --- |
| `TradeResultLabel` | `win`, `loss`, `breakeven` |
| `TradeSampleQuality` | `complete`, `partial`, `invalid` |
| `TradeSampleSourceType` | `historical_import`, `live_order`, `paper_order` |
| `HistoricalTradeStatus` | `valid`, `invalid`, `voided`, `superseded` |
| `RiskPlanSource` | `explicit`, `inferred_from_exit_1r` |

No `timeout` / `expired` / `manual_close` value exists on the trade-result enum.
(`SignalScoreOutcome.timeout` is Score Engine HTTP failure, unrelated to trade
holding period.)

## 3. Numeric outcome columns

| Column | Type | Sign convention | NULL on closed? |
| --- | --- | --- | --- |
| `realized_pnl` | `DECIMAL(20,8)` | loss &lt; 0, win &gt; 0, breakeven = 0 | Allowed; then `result_label` may be null / quality ≠ complete |
| `realized_pnl_pct` | `DECIMAL(20,8)` | same sign as PnL | optional |
| `result_r` | `DECIMAL(20,8)` | R-multiple = signed move / \|entry−stop\|; ~0 ⇒ breakeven (`ε = 1e-8`) | optional; used when risk plan present |

Label derivation in NestJS (not “TP before SL” as a stored predicate):

- `TradeSampleQualityService.deriveResultLabel(pnl)` → sign of `realized_pnl`
- `computeResultR(...)` → sign of `result_r` when stop risk is known
  (`src/modules/historical-trades/utils/exit-1r-risk-plan.util.ts`)

## 4. Timeout / partial evidence

- **Timeout as trade outcome**: does not exist in schema. A force-closed or
  time-expired trade, if recorded, still lands as a normal exit with
  `realized_pnl` / `result_label`.
- **Partial**: `sample_quality = partial` means **missing fields** (exit/pnl
  incomplete), not a partial-fill PnL class. NestJS training/calibration paths
  already require `sample_quality = complete` and `result_label IS NOT NULL`.

## 5. Open trades

- On `trade_samples`: `exit_at IS NULL` (and typically missing exit/pnl) means
  unresolved — treat as not eligible for labeling.
- On `historical_trades`: rows are imported closed (`exit_at` NOT NULL); filter
  `status = 'valid'` only.

## Output

Findings applied to `docs/label-policy.md` §1–4.
