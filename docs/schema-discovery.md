# `trading.trade_outcomes` — Schema Discovery Checklist

**Status**: not yet executed. Blocks `label-policy.md` sections 2-4.

The Score Engine's read contract only ever needed `signal_id` and
`closed_at` from this table, so neither repository has an inventory of its
remaining columns. This checklist closes that gap using a read-only,
disposable credential — **never** the Score Engine's `DATABASE_URL`.

## 1. Column inventory

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'trading' AND table_name = 'trade_outcomes'
ORDER BY ordinal_position;
```

Record every column name/type here (sanitized — no row-level data with
account/order identifiers beyond what's needed to explain the label rule).

## 2. Distinct values of any result/exit/status-shaped column

For each column found in step 1 that looks like it encodes outcome/result
(e.g. `result`, `exit_reason`, `status`, `close_type`):

```sql
SELECT <column>, count(*)
FROM trading.trade_outcomes
GROUP BY <column>
ORDER BY 2 DESC;
```

## 3. Numeric outcome columns

For any `pnl`/`r_multiple`/`realized_*`-shaped column, record its type,
sign convention (does a loss show as negative, or is there a separate
win/loss flag?), and whether `NULL` occurs for closed trades (and what
that means if so).

## 4. Timeout / partial evidence

- Does any row have `closed_at IS NOT NULL` but no clear win/loss signal
  (e.g. a `status` value like `expired`, `manual_close`, `partial`)?
- Is there a maximum holding-period concept (a signal that never resolves
  and is force-closed after N bars/hours)?

## 5. Open trades

- Confirm `closed_at IS NULL` reliably means "not yet resolved" (not, say,
  a soft-delete or an error state) — sample a few rows if possible.

## Output

Paste the findings (sanitized) into `docs/label-policy.md` §"Schema
findings" and use them to fill the win/loss/timeout/partial disposition
table before requesting ML/Tech Lead sign-off.
