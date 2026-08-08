"""Read-only export of labeled trade samples for training (T6).

Scope: labels only, from public.trade_samples (joined to
public.historical_trades for status on imported rows). Feature export is
blocked on docs/schema-discovery.md's A* decision (parity evidence against
NestJS's ScoreRequestBuilder/request_json) — do not add indicator_packs
reads here until that gate is resolved. See docs/label-policy.md for the
win/loss/timeout/partial disposition this query encodes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

_FORBIDDEN_SQL_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
)


class LabelExportError(Exception):
    """Raised when labeled samples cannot be exported safely."""


class WriteAttemptRejected(LabelExportError):
    """Raised when a query would perform a write/DDL operation."""


_SELECT_LABELED_SAMPLES = """
    SELECT
        ts.id,
        ts.source_type,
        ts.entry_at,
        ts.exit_at,
        ts.symbol,
        ts.timeframe,
        ts.side,
        ts.result_label,
        ts.entry_indicator_pack_id
    FROM public.trade_samples ts
    LEFT JOIN public.historical_trades ht ON ht.id = ts.historical_trade_id
    WHERE ts.sample_quality = 'complete'
      AND ts.result_label IN ('win', 'loss')
      AND ts.exit_at IS NOT NULL
      AND ts.exit_at <= :as_of
      AND ts.entry_at >= :window_start
      AND ts.entry_at < :window_end
      AND (ts.source_type <> 'historical_import' OR ht.status = 'valid')
    ORDER BY ts.entry_at, ts.id
"""


@dataclass(frozen=True)
class LabeledTradeSample:
    id: str
    source_type: str
    entry_at: datetime
    exit_at: datetime
    symbol: str
    timeframe: str
    side: str
    label: int  # 1 = win, 0 = loss — docs/label-policy.md §2
    entry_indicator_pack_id: str | None


_EXPECTED_COLUMNS: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "source_type": str,
    "entry_at": datetime,
    "exit_at": datetime,
    "symbol": str,
    "timeframe": str,
    "side": str,
    "result_label": str,
}

_LABEL_VALUES = {"win": 1, "loss": 0}


def assert_read_only_sql(sql: str) -> None:
    """Raise WriteAttemptRejected if sql contains a write/DDL keyword."""
    upper = sql.upper()
    for keyword in _FORBIDDEN_SQL_KEYWORDS:
        if keyword in upper:
            raise WriteAttemptRejected(f"query contains forbidden keyword '{keyword}'")


def export_labeled_samples(
    engine: Engine,
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> Iterator[LabeledTradeSample]:
    """Export labeled trade samples read-only, per docs/label-policy.md.

    window_start/window_end bound ts.entry_at (mandatory, exclusive end).
    as_of is the lookahead cutoff: only samples resolved by then
    (exit_at <= as_of) are eligible, per label-policy.md section 3.
    """
    if window_start is None or window_end is None or as_of is None:
        raise LabelExportError("window_start, window_end and as_of are all mandatory")
    if window_start >= window_end:
        raise LabelExportError("window_start must be before window_end")
    if as_of < window_end:
        raise LabelExportError("as_of must not be before window_end")

    assert_read_only_sql(_SELECT_LABELED_SAMPLES)
    query = text(_SELECT_LABELED_SAMPLES)
    params = {"window_start": window_start, "window_end": window_end, "as_of": as_of}

    with engine.connect() as conn:
        result = conn.execute(query, params)
        yield from _to_rows(result)


def _to_rows(result: Iterator[Any]) -> Iterator[LabeledTradeSample]:
    for row in result:
        values: dict[str, Any] = {}
        for field, expected_type in _EXPECTED_COLUMNS.items():
            try:
                value = getattr(row, field)
            except AttributeError as exc:
                raise LabelExportError(
                    f"trade_samples row missing expected column '{field}'"
                ) from exc
            if value is None or not isinstance(value, expected_type):
                raise LabelExportError(
                    f"trade_samples row column '{field}' has unexpected type {type(value).__name__}"
                )
            values[field] = value

        result_label = values.pop("result_label")
        if result_label not in _LABEL_VALUES:
            raise LabelExportError(f"unexpected result_label value '{result_label}'")

        pack_id: Any = getattr(row, "entry_indicator_pack_id", None)
        if pack_id is not None and not isinstance(pack_id, str):
            raise LabelExportError(
                "trade_samples row column 'entry_indicator_pack_id' has unexpected type "
                f"{type(pack_id).__name__}"
            )

        yield LabeledTradeSample(
            label=_LABEL_VALUES[result_label],
            entry_indicator_pack_id=pack_id,
            **values,
        )
