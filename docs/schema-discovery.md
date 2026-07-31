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

## Finding TF-2 (open) — label↔feature join is UNKNOWN/REJECTED

**Do not** join `trade_samples`/`historical_trades` (label source, §1b) back
to `trading.trading_signals`/`trading.signal_features` (the Score Engine's
feature-source assumption in `docs/trading_read_contract.md`) via
`trade_samples.correlation_id = trading_signals.signal_id`. That join is
rejected, not just undocumented:

1. `trading.trading_signals`/`signal_features`/`trade_outcomes` don't exist
   in NestJS (§1b) — there is no destination table for this join anyway.
2. `correlation_id` is a request-tracing id, not a business `signal_id`;
   `signals.signal_id`, `signals.correlation_id`,
   `trade_samples.correlation_id`, and `orders.correlation_id` are distinct
   columns on/around the same NestJS `Signal` model.
3. The only real link (live/paper only) is
   `trade_samples.order_id → orders.id → orders.signal_id → signals.id`
   (`orders.signal_id` is the `signals` **cuid PK**, not the business
   `signal_id`).
4. NestJS features live in `indicator_packs`
   (`current_pack_json`/`last_successful_pack_json`), linked via
   `trade_samples.entry_indicator_pack_id` and/or
   `indicator_packs.trade_sample_id`/`indicator_packs.signal_id` —
   `TradeSampleFeatureReader` builds windows from other `trade_samples`
   rows, not from a `trading.*` store.
5. `historical_import` rows frequently have no live order/signal at all
   (only `historical_trade_id` + an optional pack) — any join that requires
   `signals` silently drops or misrepresents that volume.

**Owner**: fcsousa. **Blocks**: the feature side of T6 (and therefore T7).
**Does not block**: exporting labels alone from `trade_samples` per
`label-policy.md` (no `trading.*` join required for that slice).

**Options for the feature-join decision (none adopted — pick one, with
evidence, before writing feature-export SQL)**:

- **(A)** Read `indicator_packs` directly in the training-repo exporter
  (NestJS schema, still read-only).
- **(B)** Reconstruct features offline in the training repo (recompute from
  raw price/indicator history rather than reading NestJS's stored packs).
- **(C)** Wait for NestJS to materialize a stable `trading.signal_features`-
  shaped ACL table; export against that once it exists and is contracted.

### Decision (2026-08-01, fcsousa): A\* adopted, B/C as contingency

Read `indicator_packs` directly (option A), but gated on validation, not
assumed:

- **T6 now**: export **labels only** from `trade_samples`/`historical_trades`
  (per `label-policy.md` §2-3). No feature/`indicator_packs` read yet.
- **Feature export unblocks only after** evidence that `indicator_packs`
  content (`current_pack_json`/`last_successful_pack_json` reached via
  `entry_indicator_pack_id`) has **parity with what NestJS's
  `ScoreRequestBuilder` actually sends as `features` in a live
  `POST /v1/score` request** — same keys, same values, snapshotted at/before
  `entry_at` (no post-entry leakage). Validate against an **immutable run**
  (a specific pinned historical signal + its real request payload), not a
  live/moving comparison.
- If parity fails or can't be evidenced, fall back to **(B)** offline
  reconstruction or **(C)** wait for a materialized ACL table — in that
  order of preference, per the original trade-offs above.
