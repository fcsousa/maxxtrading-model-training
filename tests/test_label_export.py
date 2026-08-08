from datetime import datetime
from types import SimpleNamespace

import pytest

from training.label_export import (
    LabelExportError,
    WriteAttemptRejected,
    _to_rows,
    assert_read_only_sql,
    export_labeled_samples,
)


def _row(**overrides: object) -> SimpleNamespace:
    base = dict(
        id="ts_1",
        source_type="live_order",
        entry_at=datetime(2026, 1, 1, 10, 0, 0),
        exit_at=datetime(2026, 1, 1, 12, 0, 0),
        symbol="BTCUSDT",
        timeframe="15m",
        side="long",
        result_label="win",
        entry_indicator_pack_id="pack_1",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeConnection:
    def __init__(self, rows: list[SimpleNamespace]):
        self._rows = rows
        self.executed_params: dict[str, object] | None = None

    def execute(self, _query: object, params: dict[str, object]) -> list[SimpleNamespace]:
        self.executed_params = params
        return self._rows

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeEngine:
    def __init__(self, rows: list[SimpleNamespace]):
        self._connection = FakeConnection(rows)

    def connect(self) -> FakeConnection:
        return self._connection


class TestWindowBoundsAreMandatory:
    def test_missing_window_start_raises(self):
        with pytest.raises(LabelExportError):
            list(
                export_labeled_samples(
                    FakeEngine([]),
                    window_start=None,  # type: ignore[arg-type]
                    window_end=datetime(2026, 1, 2),
                    as_of=datetime(2026, 1, 2),
                )
            )

    def test_missing_as_of_raises(self):
        with pytest.raises(LabelExportError):
            list(
                export_labeled_samples(
                    FakeEngine([]),
                    window_start=datetime(2026, 1, 1),
                    window_end=datetime(2026, 1, 2),
                    as_of=None,  # type: ignore[arg-type]
                )
            )

    def test_window_start_after_window_end_raises(self):
        with pytest.raises(LabelExportError):
            list(
                export_labeled_samples(
                    FakeEngine([]),
                    window_start=datetime(2026, 1, 2),
                    window_end=datetime(2026, 1, 1),
                    as_of=datetime(2026, 1, 2),
                )
            )

    def test_as_of_before_window_end_raises(self):
        with pytest.raises(LabelExportError):
            list(
                export_labeled_samples(
                    FakeEngine([]),
                    window_start=datetime(2026, 1, 1),
                    window_end=datetime(2026, 1, 2),
                    as_of=datetime(2026, 1, 1, 12, 0, 0),
                )
            )

    def test_valid_bounds_are_passed_as_query_params(self):
        engine = FakeEngine([])
        window_start = datetime(2026, 1, 1)
        window_end = datetime(2026, 1, 8)
        as_of = datetime(2026, 1, 10)

        list(
            export_labeled_samples(
                engine, window_start=window_start, window_end=window_end, as_of=as_of
            )
        )

        assert engine._connection.executed_params == {
            "window_start": window_start,
            "window_end": window_end,
            "as_of": as_of,
        }


class TestWriteAttemptGuard:
    def test_select_is_accepted(self):
        assert_read_only_sql("SELECT * FROM public.trade_samples")

    @pytest.mark.parametrize(
        "keyword",
        ["INSERT INTO", "UPDATE public.trade_samples SET", "DELETE FROM", "DROP TABLE"],
    )
    def test_write_or_ddl_keywords_are_rejected(self, keyword: str):
        with pytest.raises(WriteAttemptRejected):
            assert_read_only_sql(f"{keyword} public.trade_samples")

    def test_export_raises_before_connecting_if_query_were_a_write(self, monkeypatch):
        import training.label_export as label_export

        monkeypatch.setattr(
            label_export, "_SELECT_LABELED_SAMPLES", "DELETE FROM public.trade_samples"
        )

        with pytest.raises(WriteAttemptRejected):
            list(
                export_labeled_samples(
                    FakeEngine([]),
                    window_start=datetime(2026, 1, 1),
                    window_end=datetime(2026, 1, 8),
                    as_of=datetime(2026, 1, 8),
                )
            )


class TestToRowsColumnValidation:
    def test_missing_column_fails_closed(self):
        row = _row()
        del row.symbol

        with pytest.raises(LabelExportError, match="missing expected column 'symbol'"):
            list(_to_rows(iter([row])))

    def test_unexpected_type_fails_closed(self):
        row = _row(side=123)

        with pytest.raises(LabelExportError, match="unexpected type"):
            list(_to_rows(iter([row])))

    def test_unexpected_result_label_value_fails_closed(self):
        row = _row(result_label="breakeven")

        with pytest.raises(LabelExportError, match="unexpected result_label value"):
            list(_to_rows(iter([row])))

    def test_bad_pack_id_type_fails_closed(self):
        row = _row(entry_indicator_pack_id=123)

        with pytest.raises(LabelExportError, match="entry_indicator_pack_id"):
            list(_to_rows(iter([row])))

    def test_error_message_never_contains_a_dsn(self):
        row = _row()
        del row.symbol

        with pytest.raises(LabelExportError) as exc_info:
            list(_to_rows(iter([row])))

        assert "://" not in str(exc_info.value)


class TestToRowsHappyPath:
    def test_win_row_maps_to_label_one(self):
        rows = list(_to_rows(iter([_row(result_label="win")])))

        assert rows[0].label == 1

    def test_loss_row_maps_to_label_zero(self):
        rows = list(_to_rows(iter([_row(result_label="loss")])))

        assert rows[0].label == 0

    def test_null_pack_id_is_allowed(self):
        rows = list(_to_rows(iter([_row(entry_indicator_pack_id=None)])))

        assert rows[0].entry_indicator_pack_id is None

    def test_all_fields_pass_through(self):
        row = _row()

        result = list(_to_rows(iter([row])))[0]

        assert result.id == row.id
        assert result.source_type == row.source_type
        assert result.entry_at == row.entry_at
        assert result.exit_at == row.exit_at
        assert result.symbol == row.symbol
        assert result.timeframe == row.timeframe
        assert result.side == row.side
        assert result.entry_indicator_pack_id == row.entry_indicator_pack_id


class TestQueryEncodesDispositionFilters:
    def test_query_filters_complete_quality_win_loss_only(self):
        from training.label_export import _SELECT_LABELED_SAMPLES

        assert "sample_quality = 'complete'" in _SELECT_LABELED_SAMPLES
        assert "result_label IN ('win', 'loss')" in _SELECT_LABELED_SAMPLES

    def test_query_enforces_lookahead_cutoff(self):
        from training.label_export import _SELECT_LABELED_SAMPLES

        assert "exit_at IS NOT NULL" in _SELECT_LABELED_SAMPLES
        assert "exit_at <= :as_of" in _SELECT_LABELED_SAMPLES

    def test_query_requires_valid_historical_status_for_imports(self):
        from training.label_export import _SELECT_LABELED_SAMPLES

        assert "ht.status = 'valid'" in _SELECT_LABELED_SAMPLES
