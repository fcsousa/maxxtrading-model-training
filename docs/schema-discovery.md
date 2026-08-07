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

### TF-3 correction (2026-08-01, same session) — the order/signal join was the wrong join for historical_import

The zero-intersection conclusion above checked `entry_indicator_pack_id`
and the `order_id → orders.signal_id → indicator_packs.signal_id` path
(TF-2's confirmed link for **live/paper** trades). Both are correctly empty
for `historical_import` rows, but that's because neither applies to them —
not because no feature data exists. `IndicatorPack` has a **second,
independent** FK not checked before: `trade_sample_id`
(`subject_type = 'trade_sample'` in the enum), a direct pack↔sample
relation that doesn't go through orders/signals at all.

| Check | Result |
| --- | --- |
| `indicator_packs` with `subject_type = 'trade_sample'` | 5416 (vs. 259 `subject_type = 'signal'`) |
| Win/loss-eligible `trade_samples` joined via `indicator_packs.trade_sample_id = trade_samples.id` | **5404** (essentially all of them have a pack row) |
| ...of those, with `current_pack_json` populated (`current_status = 'succeeded'`) | **383** |

**Corrected conclusion**: real, computed feature data already exists for
**383 historical_import win/loss samples**, via `indicator_packs`'s
`trade_sample_id` relation — not zero. `entry_indicator_pack_id` on
`trade_samples` appears unused in this dataset (always null); it is not the
right column to join on for historical imports. TF-3's premise ("no feature
data exists anywhere for any eligible sample") is **withdrawn** for the
`trade_sample_id` path; the order/signal-based paths (TF-3's original
finding) remain correctly empty for live/paper (which barely has eligible
data anyway — 12 `partial`-quality samples, not win/loss-eligible).

**Leakage risk is lower here than TF-2's original concern.** TF-2 flagged
`IndicatorPack.currentPackJson` as reprocessable/mutable, risking post-entry
data leaking into a live-signal's "current" pack. For `historical_import`,
that risk doesn't transfer the same way: the pack's computation window is
always relative to the trade's fixed historical `entry_at`, not to "now" —
a reprocess recomputes the same point-in-time window (e.g. after a bug fix
or methodology change), it doesn't pull in data from after the trade
closed. Still worth confirming (not yet done) that the indicator
computation logic actually windows strictly relative to `entry_at` and not,
e.g., to `updated_at`/"latest available data as of reprocessing time" — but
the a priori risk is structurally smaller than for live signals.

**Revised next step**: the 383-sample population is small relative to 5404
total eligible samples (the other 5021 are stuck `pending`/`failed_*`), but
it's real and non-zero. This reopens whether A*'s live-scored-signal path
(`signal_scores.request_json`, still 0 real rows) is even the right primary
focus right now, versus using this already-available `trade_sample`-subject
pack data for historical imports. Not decided here — flagging for the next
decision rather than choosing unilaterally.

### Decision (2026-08-01, fcsousa): prioritize the 383-sample path, conditional A\*

1. Prioritize the `indicator_packs.trade_sample_id` path (383 real samples)
   for A* now. Treat it as **conditional A\* (parity = anchor_policy)**, not
   an online hash proof — i.e. parity is established by proving the pack's
   computation is correctly anchored to `entry_at` with no post-entry
   leakage, not by matching a `featuresHash` (there is nothing to match
   against for historical imports; no `signal_scores` row exists for them).
2. `signal_scores.request_json` + `featuresHash` remains the **future hard
   gate** for live/paper-scored signals once `signal_scores` has real rows
   — not a blocker for Phase 1 today, since that table is empty.
3. Windowing must be verified in code (and empirically if possible) before
   relying on the 383-sample path: candle/feature computation must be
   strictly as-of `entry_at`, not "now," and reprocessing must not be able
   to introduce post-entry data into the stored snapshot.

### Windowing verification (2026-08-01) — PASS at code level

Source: `fcsousa/maxxtrading` read-only clone, same commit family as
`65ebecd`. Three independent pieces of evidence, all pointing the same way:

1. **`src/modules/indicator-packs/subjects/indicator-pack-subject.resolver.ts::resolveTradeSample`**
   sets `anchorTime: sample.entryAt` — the anchor for a `trade_sample`-subject
   pack is the sample's real historical entry time, never "now" or the
   reprocessing timestamp. Re-running this resolver (on retry/reprocess)
   re-derives the same `entryAt`-based anchor every time, since it re-reads
   `sample.entryAt` from the DB, not from run-local state.
2. **`src/modules/indicator-packs/subjects/validate-anchor-candles.util.ts`**
   (`validateAnchorCandles`, called from
   `indicator-pack-schema2-calculation.service.ts` right after
   `historicalMarketData.fetchClosedCandles(..., anchorTime, ...)`): any
   candle with `closeTime > anchorTime` fails the **entire** pack
   computation with `FUTURE_CANDLE_REJECTED` — not a silent truncation, a
   hard failure. This guard runs unconditionally, on every computation
   (initial, retry, `reprocess_single`, `reprocess_batch`, `sweeper`) —
   there is no code path that skips it.
3. **`src/modules/indicator-packs/schemas/indicator-pack-schema-v2.schema.ts`**:
   the persisted pack JSON schema itself requires
   `leakageCheckStatus: z.literal('passed')` — a pack cannot even validate
   as schema-2 (and therefore cannot be stored in `current_pack_json`)
   without this field being exactly `'passed'`. `metadata.anchorTime` is
   also part of the persisted schema, so the anchor used is recorded
   alongside the pack, not just implied.

**Empirical spot-check: attempted, not completed.** Planned to compare a
real succeeded pack's `current_pack_json -> metadata ->> 'anchorTime'` and
`-> timeframes -> primary -> candles ->> 'lastCandleCloseTime'` against its
`trade_samples.entry_at`, for one of the 383 real rows. The DB connection
timed out on three attempts (same host churn as the earlier backup-restore
session) — not completed yet. Given the specificity of the three code
findings above (a named `FUTURE_CANDLE_REJECTED` guard plus a schema-level
required `leakageCheckStatus` field), this is recorded as **PASS at code
level, high confidence**; the empirical spot-check remains a nice-to-have
follow-up, not a blocker, and can be run opportunistically once the DB is
reachable again.

**A\* status**: **conditional PASS** for the historical_import /
`trade_sample`-subject-pack path (383 real samples), per the decision
above. T6b feature-export SQL may now be written **for this path only**
(join via `indicator_packs.trade_sample_id`, `current_status = 'succeeded'`,
`current_pack_json`) — still no SQL against `signal_scores`/live-signal
paths, which remain gated on that table having real rows.

## Finding TF-4 (open, 2026-08-01) — feature-vocabulary mismatch, not a coverage gap

**Phase 1 smoke export executed** under explicit AUTH (export-only, RO
credential `scoreengine_readonly` on `192.168.3.10:5432/maxxtrading`,
window `2025-07-29..2026-07-02`, N=100, no writes). T6b → T6 → vectorize →
T7 pipeline run against 100 real succeeded `trade_sample`-subject packs.
**Stopped at the vectorize step, exactly per AUTH's "stop if errors"** — no
`dataset_id`/manifest produced, no training attempted.

Per-feature coverage across the 100-sample batch (canonical order =
Feature Dictionary `"numerical"` list, Phase 1 default):

| Feature | Coverage |
| --- | --- |
| `ema_9`, `ema_40`, `ema_80`, `rsi_14`, `atr_14` | **100/100 (100%)** |
| `risk_reward_ratio`, `volume_ratio`, `distance_price_ema9_pct`, `distance_price_ema40_pct`, `ema40_above_ema80`, `hour_of_day`, `day_of_week` | **0/100 (0%)** |

0 of 100 samples had all 12 required numerical features. This is not
sparse/missing data on a few samples — it is a **consistent, 100%-across-
the-batch split**: exactly 5 of 12 canonical fields are always present,
the other 7 are always absent.

Real packs also compute a rich set of indicators **not in the Score
Engine's Feature Dictionary at all** (100/100 each): `ema_20`, `ema_200`,
`sma_20`, `sma_50`, `adx_14`, `natr_14`, `bollinger_bands_20_2`,
`stddev_20`, `rsi_2`, `slow_stochastic_14_3_3`, `macd_12_26_9`,
`williams_r_14`, `mfi_14`, `volume_sma_20`, `obv`, and more.

**Conclusion**: this is not a data-quality/backfill-coverage problem (like
TF-3's `pending` packs). It is a **feature-vocabulary divergence** —
NestJS's indicator-pack computation and the Score Engine's
`feature_dictionary_v1.json` were built independently and were never
reconciled against each other. The two systems currently speak different
feature languages; only 5 names happen to coincide.

**Not decided here (needs a product/ML decision, not a code fix)**:

- (a) Redefine `feature_order` to the 5 fields that are actually 100%
  covered (`ema_9`, `ema_40`, `ema_80`, `rsi_14`, `atr_14`) — smallest,
  immediately viable vector, but drops `risk_reward_ratio` (a feature
  AD-005/AD-006 in the Score Engine treat as significant) and ignores the
  15+ real indicators NestJS already computes.
- (b) Update the Score Engine's Feature Dictionary to match what NestJS
  actually computes — **out of scope for this phase** per explicit
  instruction (`app/artifacts/feature_dictionary_v1.json` not to be
  touched this phase) and is a Score Engine-side change requiring its own
  sign-off/versioning (MLF-09-adjacent, likely a Phase 2 concern).
  Not attempted, not proposed as a diff.
- (c) Some subset/mapping between the two vocabularies (e.g. NestJS's
  `natr_14` as a substitute for a volatility-adjacent required field) —
  would need domain judgment, not something to infer from field names.

**Owner**: fcsousa. **Blocks**: T7-with-real-vectors / T8 real dual-run
until a feature_order decision is made for this vocabulary. No further
DB queries attempted after this diagnostic; standing down per AUTH.

### Resolution path (2026-08-01, fcsousa) — supersedes options a/b/c above

Neither (a) shrink to 5 fields, (b) edit the Score Engine's Feature
Dictionary, nor (c) an inferred name-mapping. Instead:

1. A cross-repo semantic contract already exists and is adopted on the
   Score Engine side: `maxxtrading-scoreengine/docs/analisys/feature_semantics_se_fd_v1.md`
   (commit `a1e316f`) — `FEATURES_CONTRACT_VERSION = se-fd-v1`, defining
   canonical `trend_regime`/`volatility_regime` string alphabets and the
   exact `volume_ratio` formula (last closed primary candle's volume ÷
   `volume_sma_20`, fail-closed/omitted if the divisor is missing or zero
   — matches this repo's own fail-closed philosophy). TF-4's resolution is
   for NestJS to **promote its own pack computation** to emit fields
   matching this contract, not for either repo to bend to the other's
   current output.
2. Once "Nest bridge + SE Q1/Q2 done" (NestJS promotes
   `FEATURES_CONTRACT_VERSION` to `se-fd-v1`) and packs are regenerated
   under that contract, re-run the Phase 1 smoke export against those new
   packs. **Old packs computed before the bridge will still fail-closed at
   vectorize — expected, not a regression**, since they were never
   contracted to emit the required fields.
3. Before the next export AUTH: fix `TRAINING_DATABASE_URL` to an RO role
   on `db=maxxtrading` (currently the `postgres` superuser — flagged this
   session, not yet corrected) and target packs produced after the bridge
   (or an explicit Nest backfill of old ones).
4. Next AUTH will re-run Passo 1 (export-only) with
   `feature_order=numerical` (the full 12, not a shrunk 5), plus whatever
   categoricals policy is documented at that point. Dual-run AUTH stays a
   separate, later authorization after a green manifest/`dataset_id`.

No DB/training action taken or planned until that AUTH block arrives.

### Re-run Passo 1 (2026-08-07) — after Nest se-fd-v1 + SE Q1/Q2/Q3 AUTH

AUTH export-only re-run executed on branch `feature/mlflow-p1-data-foundation`
against `192.168.3.10:5432` / db=`maxxtrading` / user=`scoreengine_readonly`
(`TRAINING_DATABASE_URL` RO — matches `SCOREENGINE_READONLY_DATABASE_URL`).
Window `2025-07-29..2026-07-02`, N=100. SELECT-only; write probe rejected.

**Pipeline changes in this re-run (code):**

- T6b reads immutable `indicator_pack_runs.pack_json` (run-pin / DISTINCT ON
  latest succeeded run per sample) — not mutable
  `indicator_packs.current_pack_json` / `last_successful_pack_json`.
- Bridge enrichment: `hour_of_day` / `day_of_week` from `metadata.anchorTime`
  (UTC, Nest `getUTCDay` semantics); `risk_reward_ratio` derived from
  `historical_trades` entry/stop/target when absent from pack flatten.
- Soft vectorize (`vectorize_all_soft`) reports coverage; does **not** shrink
  `feature_order` from numerical-12. Manifest only when ≥1 full vector.

**Live coverage (N=100 batch, feature_order=numerical 12):**

| Metric | Value |
| --- | --- |
| labels_eligible (window) | 4933 |
| packs_succeeded (run-pinned, window) | 383 |
| batch_size | 100 |
| vectorized (full 12) | **0** |
| partial | 100 |
| skipped | 100 |

| Feature | Present after B2+RRR enrich |
| --- | --- |
| `ema_9`, `ema_40`, `ema_80`, `rsi_14`, `atr_14` | 100/100 |
| `risk_reward_ratio` (HT-derived) | 100/100 |
| `hour_of_day`, `day_of_week` (B2) | 100/100 |
| `volume_ratio`, `distance_price_ema9_pct`, `distance_price_ema40_pct`, `ema40_above_ema80` | **0/100** |

DB-wide probe: **0** succeeded trade_sample runs mention `volume_ratio` /
`distance_price_ema9_pct` / `ema40_above_ema80`; **0** runs with
`finished_at >= 2026-07-14`. Packs in this DB are still pre-ponte schema
(fd versions 2–3, no `globalFeatures`). Nest `se-fd-v1` promotion is live
in code, but **no regenerated/backfilled packs** are visible here yet.

**Result:** STOP — no `dataset_id` / DatasetManifest. Fail-closed correct.
Dual-run AUTH remains blocked until Nest emits contracted packs (or
backfills) into `maxxtrading`.
