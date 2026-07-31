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

### A* parity study (2026-08-01, code-level — no live DB access)

Source: `fcsousa/maxxtrading` (NestJS) @ read-only clone, same commit family
as `65ebecd`.

**Revised recommendation — bypass `indicator_packs` for scored live/paper
trades.** Reading `prisma/schema.prisma`'s `SignalScore` model changes the
picture from the original A* framing (which assumed features had to be
reconstructed from `IndicatorPack`):

```
model SignalScore {
  ...
  featuresVersion String
  featuresHash    String
  requestJson     Json   // NOT NULL — literal ScoreRequest sent online
  responseJson    Json?
  outcome         SignalScoreOutcome  // ok | timeout | error | schema_invalid
  @@unique([signalId, modelVersion, featuresVersion, featuresHash, scoreMode])
}
```

`src/modules/score-models/signal-score.service.ts:76-95` shows `requestJson`
is persisted **verbatim** from the `ScoreRequest` object built by
`buildScoreRequest` (`score-request-builder.util.ts`), only when
`outcome === 'ok'`. `request.featuresHash` (same object) is stored in the
`featuresHash` column. Both are frozen at the moment of the real online
`/v1/score` call and never touched again — no mutability/reprocessing risk
(unlike `IndicatorPack.currentPackJson`/`lastSuccessfulPackJson`, TF-2).

**Revised A\*\*\* for scored live/paper**: read `signal_scores.request_json`
directly as the feature source (`request_json.features`) for any row with
`outcome = 'ok'`, instead of reconstructing from `indicator_packs`. Join path
(same as TF-2's confirmed link): `trade_samples.order_id → orders.id →
orders.signal_id (signals.id PK) → signal_scores.signal_id`.

**Cross-language hash compatibility (verified at code level):**

- NestJS: `computeFeaturesHash` (`features-hash.util.ts`) = `sha256(stableStringify(features))`,
  keys sorted, no whitespace, JS `JSON.stringify` per-value.
- Score Engine (Python, AD-007): `app/domain/services/features_hash.py` =
  `sha256(json.dumps(features, sort_keys=True, separators=(",", ":")))`.
- Both algorithms are structurally identical (sorted-key, no-whitespace
  canonical JSON, SHA-256 hex). The one cross-language risk is number
  rendering (Python `float` renders integer values with a trailing `.0`;
  JS numbers never do). This is a **non-issue here**: the Score Engine's
  request schema declares `features: dict[str, Any]`
  (`app/schemas/score_request.py:29`) — no Pydantic float coercion — so a
  whole-number value arrives over the wire as JSON `1` (JS never emits
  `1.0`), `json.loads` parses it as Python `int`, and `json.dumps` renders
  it back as `"1"`, matching JS's own rendering. Fractional values use each
  language's shortest-round-trip float formatting, which converge for the
  same IEEE-754 double. **No known case where the two hashes would diverge
  for equal feature values.**

**Status: PENDING, not PASS.** The hash algorithms are proven compatible at
the code level, and `request_json`/`features_hash` are proven immutable and
verified by construction (§ above). What's still missing is (a) required by
the gate: an actual hash-match run against ≥1 real `signal_scores` row —
recompute `compute_features_hash(request_json["features"])` in Python and
confirm it equals the stored `features_hash` column. This requires read
access to the **NestJS database** (not the Score Engine's — confirmed
separate; this session's `scoreengine_readonly` credential got
`FATAL: no pg_hba.conf entry` when it tried the NestJS host). No T6b SQL
will be written until this runs and passes on real data, or is written up
as a FAIL with a concrete blocker.

**Historical_import gap (unresolved, separate from live/paper):** rows with
no live order/signal (per TF-2 point 5) have no `signal_scores` row at all —
they were never scored online. `request_json` cannot help there. If those
rows are needed for training, feature reconstruction falls back to
`IndicatorPackRun` (see below) or is excluded from V1 (a scope decision, not
made here).

**`IndicatorPackRun` — reconstruction fallback / audit only, not primary
path.** For any case where `signal_scores.request_json` isn't available
(historical_import rows, or a live/paper trade whose `SignalScore` row is
missing/non-`ok`), the immutable per-attempt history in `IndicatorPackRun`
(`packJson`, `startedAt`, `trigger`, `attemptNumber` — unlike the mutable
`IndicatorPack.currentPackJson`/`lastSuccessfulPackJson`, TF-2) is the
correct join target, but which specific run corresponds to "the one that
would have produced this signal's request" has not been established and is
out of scope until the live/paper path is proven or fails.

**Next step (blocked on DB access, do not skip)**: obtain a read-only
credential to the NestJS database (`fcsousa/maxxtrading`'s own Postgres, a
separate host/DB from `maxxtrading-scoreengine`) to run the hash-match
proof on real `signal_scores` rows.

### Finding TF-3 (open, 2026-08-01) — no usable feature data exists yet, on either path

DB access resolved: `SCOREENGINE_READONLY_DATABASE_URL` (`.env`, host
`192.168.3.10:5432`, DB `maxxtrading` — distinct from
`maxxtrading-scoreengine`) is a read-only credential to the real NestJS
database (confirmed: `signal_scores`, `trade_samples`, `orders`, `signals`,
`indicator_packs`, `indicator_pack_runs` all present in `public`, matching
the Prisma schema exactly). Used only for aggregate `COUNT(*)`/`GROUP BY`
queries below — no row content was read or logged.

**Both feature paths are currently empty, not just methodologically
unresolved:**

| Check | Result |
| --- | --- |
| `signal_scores` (any) | **0 rows** — confirms Phase 0's OF-1: no signal has ever actually been scored online |
| `trade_samples` (any) | 372 rows |
| `trade_samples` by `(source_type, sample_quality, result_label)` | **100% `historical_import` / `complete`** — 201 `win`, 171 `loss`. Zero `live_order`/`paper_order` samples exist at all |
| `trade_samples.entry_indicator_pack_id IS NOT NULL` | **0 of 372** — not one historical sample is linked to a pack |
| `indicator_packs.current_status` | 372 `pending`, 2 `succeeded`, 2 `failed_terminal` (of 376 total) |
| `indicator_packs` with `current_pack_json` populated | 2 (both unlinked to any `trade_sample`) |

**Implication**: the revised A* path (`signal_scores.request_json`) has
zero applicable rows — not a proof gap, a data gap (nothing has ever been
scored online). The fallback path (`indicator_packs`/`indicator_pack_runs`)
also has zero usable rows for the population that actually exists
(historical_import): indicator-pack computation for these 372 samples is
stuck at `pending` and was never linked back via `entry_indicator_pack_id`.
**There is currently no feature data anywhere in the system for any of the
372 labeled samples this repo could otherwise train on.**

This is an operational/NestJS-side gap (the indicator-pack backfill job for
historical imports needs to actually run and link `entry_indicator_pack_id`
back to `trade_samples`), not a Score-Engine or training-repo code problem,
and out of scope for this repo to fix directly.

**Owner**: fcsousa. **Blocks**: all of T6b/T7-with-real-features/T8's real
run, regardless of how A* resolves — there is nothing to export yet either
way.

**A* status update**: still PENDING (not PASS, not FAIL) — the code-level
hash-compatibility reasoning stands, but it cannot be exercised because no
`signal_scores` row exists to test against. This isn't a rejection of the
hypothesis, just an unmet precondition.

### TF-3 reconfirmed against a larger restored backup (2026-08-01, same session)

Between the checks above and this one, the target DB briefly went through a
backup restore (schema dropped/empty, then repopulated) — confirmed
intentional by fcsousa, not an incident. Re-ran the same aggregate checks
against the stable, restored state (verified stable across two reads 5s
apart): 5416 `trade_samples`, 704 `orders`, 527 `signals`, `signal_scores`
still 0.

| Check | Result (restored backup) |
| --- | --- |
| `trade_samples` by `(source_type, sample_quality, result_label)` | 2951 `historical_import`/`complete`/`win`, 2453 `historical_import`/`complete`/`loss`, 12 `paper_order`/`partial`/`NULL` (excluded by label-policy §2 quality rule anyway) |
| `trade_samples.entry_indicator_pack_id IS NOT NULL` | still 0 of 5416 |
| `trade_samples.order_id IS NOT NULL` | **12** (exactly the `paper_order`/`partial` rows — zero overlap with win/loss-eligible samples) |
| `indicator_packs.current_status` | 4981 `pending`, **523 `succeeded`**, 87 `failed_retriable`, 84 `failed_terminal` |
| Win/loss-eligible samples joined to a pack via TF-2's real path (`order_id → orders.signal_id → indicator_packs.signal_id`) | **0** |
| Win/loss-eligible samples joined to `signal_scores` via the same real path | **0** |

**Conclusion reinforced, not overturned, by 15x more data**: even though
523 `indicator_packs` now have real computed `current_pack_json` (up from 2
in the smaller snapshot), and 704 `orders` carry a real `signal_id` link,
there is **zero intersection** between win/loss-eligible `trade_samples`
(all 5404 of them, 100% `historical_import`) and any real feature source —
because none of them have `order_id` set at all. The 12 samples that *do*
have an order link are `partial` quality and excluded from training by
`label-policy.md` §2 regardless. TF-3's blocker stands: no feature data
exists for any currently-eligible training sample, on any path.
