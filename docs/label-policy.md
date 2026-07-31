# Trade Outcome Label Policy

**Status**: DRAFT — blocked on schema discovery (`docs/schema-discovery.md`).
**Requirement**: MLF-05 (`maxxtrading-scoreengine` spec.md).
**Related**: TDD serviço §14.4 ("Regra de rotulagem `trade_outcomes` —
🔴 Aberta"), roadmap TDD risk row ("Rotulagem de `trade_outcomes`
indefinida | Alto | Alta").

This document is the single source of truth for how `trading.trade_outcomes`
rows become the training target. It is not valid for use until every section
below is filled from real schema evidence and signed off by ML + Tech Lead
(Phase 0 decisions.md names both roles as `fcsousa`).

## 1. Schema findings

_Fill in from `docs/schema-discovery.md` step 1-3. Do not proceed to §2-4
until this section reflects the real `trading.trade_outcomes` columns._

| Column | Type | Meaning (as confirmed with the trading/NestJS side) |
| --- | --- | --- |
| `signal_id` | `TEXT` | join key (already known — Score Engine contract) |
| `closed_at` | `TIMESTAMPTZ NULL` | non-null ⇒ trade resolved (already known) |
| _TBD_ | _TBD_ | _TBD_ |

## 2. Win / loss / timeout / partial disposition

_Every state a closed trade can be in must map to exactly one of: `win`,
`loss`, `excluded`. No state may be left ambiguous._

| Observed state (from §1) | Disposition | Rationale |
| --- | --- | --- |
| _TBD_ | _TBD_ | _TBD_ |

## 3. Lookahead cutoff and exclusions

- **As-of rule**: a signal is eligible for a training window ending at
  `as_of` only if its outcome was already resolved by `as_of` — i.e.
  `closed_at IS NOT NULL AND closed_at <= as_of`. _(Working default —
  confirm no other leakage path exists once §1 is known.)_
- **Still-open signals**: excluded from every window (never labeled
  win/loss while `closed_at IS NULL`).
- **Any other exclusion** (e.g. malformed rows, test/synthetic signals,
  a status value from §1 that shouldn't reach training at all): _TBD_.

## 4. Approval

| Role | Name | Date | Signed |
| --- | --- | --- | --- |
| ML owner | fcsousa | | ☐ |
| Tech Lead | fcsousa | | ☐ |

**Gate**: this policy is not usable by T6 (dataset exporter) until every
`_TBD_` above is resolved and both signatures are recorded.
