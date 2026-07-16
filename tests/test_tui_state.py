from pathlib import Path

import pytest

from csvql.exceptions import TableMappingError
from csvql.models import TableSource
from csvql.tui_result_store import TUIResultHandle
from csvql.tui_state import (
    TUIActiveResultState,
    TUIBufferResultTab,
    TUIQueryHistoryItem,
    TUIResultRecord,
    TUIResultViewState,
    TUISessionState,
    TUISource,
    TUISourceColumn,
)


def _result_metadata(
    sequence: int,
    *,
    columns: tuple[str, ...] = ("value",),
    display_rows: tuple[tuple[str, ...], ...] = (("1",),),
    total_row_count: int = 1,
) -> tuple[TUIResultHandle, TUIResultViewState]:
    return (
        TUIResultHandle(sequence=sequence, is_spilled=False),
        TUIResultViewState(
            columns=columns,
            display_rows=display_rows,
            total_row_count=total_row_count,
            source_result_sequence=sequence,
        ),
    )


def test_tui_source_as_table_source_returns_table_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    source = TUISource(name="orders", path=csv_path, origin="argument")

    assert source.as_table_source() == TableSource(name="orders", path=csv_path)


def test_tui_source_defaults_to_csv_kind(tmp_path: Path) -> None:
    source = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")

    assert source.kind == "csv"
    assert source.as_table_source() == TableSource(name="orders", path=tmp_path / "orders.csv")


def test_tui_source_accepts_derived_kind(tmp_path: Path) -> None:
    source = TUISource(
        name="order_names",
        path=tmp_path / ".csvql" / "results" / "order_names.csv",
        origin="session",
        kind="derived",
    )

    assert source.kind == "derived"
    assert source.as_table_source() == TableSource(
        name="order_names",
        path=tmp_path / ".csvql" / "results" / "order_names.csv",
    )


def test_session_add_source_preserves_order_and_selects_first_by_default(
    tmp_path: Path,
) -> None:
    state = TUISessionState()
    first = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    second = TUISource(name="customers", path=tmp_path / "customers.csv", origin="catalog")

    state.add_source(first)
    state.add_source(second)

    assert state.sources == (first, second)
    assert state.table_sources == (
        TableSource(name="orders", path=tmp_path / "orders.csv"),
        TableSource(name="customers", path=tmp_path / "customers.csv"),
    )
    assert state.selected_source() == first


@pytest.mark.parametrize("alias", ["orders", "ORDERS"])
def test_duplicate_aliases_are_rejected_case_insensitively(tmp_path: Path, alias: str) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    with pytest.raises(TableMappingError):
        state.add_source(TUISource(name=alias, path=tmp_path / "duplicate.csv", origin="session"))


def test_removing_selected_source_advances_selection(
    tmp_path: Path,
) -> None:
    state = TUISessionState()
    first = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    second = TUISource(name="customers", path=tmp_path / "customers.csv", origin="catalog")

    state.add_source(first)
    state.add_source(second)

    removed = state.remove_source("orders")

    assert removed == first
    assert state.sources == (second,)
    assert state.selected_source() == second
    assert state.selected_alias == "customers"


def test_removing_unknown_alias_fails(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    with pytest.raises(
        TableMappingError,
        match=r"Source alias 'customers' is not loaded in the TUI session\.",
    ):
        state.remove_source("customers")


def test_selecting_and_getting_sources_is_case_insensitive(tmp_path: Path) -> None:
    state = TUISessionState()
    source = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    state.add_source(source)

    assert state.get_source("ORDERS") == source
    assert state.select_source("ORDERS") == source
    assert state.selected_source() == source

    with pytest.raises(
        TableMappingError,
        match=r"Source alias 'customers' is not loaded in the TUI session\.",
    ):
        state.get_source("customers")

    with pytest.raises(
        TableMappingError,
        match=r"Source alias 'customers' is not loaded in the TUI session\.",
    ):
        state.select_source("customers")


def test_query_success_stores_handle_and_view_without_full_result() -> None:
    state = TUISessionState()
    handle = TUIResultHandle(sequence=1, is_spilled=True, temp_path=Path("query-1.pickle"))
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("1",),),
        total_row_count=10_001,
        is_truncated=True,
        source_result_sequence=1,
    )

    state.record_query_success(
        1,
        "SELECT * FROM large",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
    )

    assert state.query_result_record(1) == TUIResultRecord(handle=handle, view=view)
    assert state.active_result.sequence == 1
    assert state.result_view is view
    assert not hasattr(state, "last_result")
    assert not hasattr(state, "_query_results")


def test_clear_last_result_resets_result_and_status(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))
    state.record_query_success(
        1,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=1.2,
    )

    state.clear_last_result()

    assert not state.has_active_result
    assert state.last_result_status == "none"
    assert state.result_view == TUIResultViewState()
    assert state.query_result_record(1) == TUIResultRecord(handle=handle, view=view)


def test_last_result_status_tracks_query_no_result_and_error(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))

    assert state.last_result_status == "none"

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(
        sequence,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=7.5,
    )

    assert state.last_result_status == "query"
    assert state.has_active_result

    no_result_sequence = state.begin_query_run("CREATE TABLE scratch AS SELECT 1")
    state.record_query_no_result(no_result_sequence, "CREATE TABLE scratch AS SELECT 1", 2.5)

    assert state.last_result_status == "no_result"
    assert not state.has_active_result

    error_sequence = state.begin_query_run("SELECT * FROM missing")
    state.record_query_error(error_sequence, "SELECT * FROM missing", "missing table")

    assert state.last_result_status == "error"
    assert not state.has_active_result


def test_query_history_records_success_error_and_no_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(
        sequence,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=7.5,
    )
    no_result_sequence = state.begin_query_run("CREATE TABLE scratch AS SELECT 1")
    state.record_query_no_result(no_result_sequence, "CREATE TABLE scratch AS SELECT 1", 2.5)
    error_sequence = state.begin_query_run("SELECT * FROM missing")
    state.record_query_error(error_sequence, "SELECT * FROM missing", "missing table")

    assert [item.status for item in state.query_history] == ["success", "no_result", "error"]
    assert state.query_history[0].row_count == 1
    assert state.query_history[0].elapsed_ms == 7.5
    assert state.query_history[1].row_count is None
    assert state.query_history[1].error_message is None
    assert state.query_history[2].error_message == "missing table"
    assert state.query_run.is_running is False
    assert not state.has_active_result


def test_query_history_records_result_handles(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(
        sequence,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=7.5,
    )

    assert state.query_result_handle(sequence) == handle
    assert state.query_result_handle(99) is None


def test_active_query_result_handle_uses_active_sequence(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(
        sequence,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=7.5,
    )

    assert state.active_query_result_handle() == handle


def test_query_success_sets_active_query_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(
        sequence,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=7.5,
    )

    assert state.active_result == TUIActiveResultState(
        kind="query",
        label="Active result: query 1",
        sequence=1,
    )
    assert state.active_query_result_record() == TUIResultRecord(handle=handle, view=view)
    assert state.last_result_status == "query"


def test_restore_query_result_marks_history_preview(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    handle, view = _result_metadata(1, columns=("count",), display_rows=(("2",),))
    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(
        sequence,
        "SELECT COUNT(*) FROM orders",
        handle=handle,
        result_view=view,
        elapsed_ms=7.5,
    )

    assert state.restore_query_result(sequence) is True

    assert state.active_result == TUIActiveResultState(
        kind="history",
        label="History preview: query 1",
        sequence=1,
    )
    assert state.result_view is view


def test_restore_query_result_reuses_stored_result_view() -> None:
    state = TUISessionState()
    handle = TUIResultHandle(sequence=1, is_spilled=False)
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("0",),),
        total_row_count=1001,
        is_truncated=True,
        source_result_sequence=1,
    )
    state.record_query_success(
        1,
        "SELECT * FROM large",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
    )
    state.clear_last_result()

    restored = state.restore_query_result(1)

    assert restored is True
    assert state.result_view is view
    assert state.result_view.display_rows == (("0",),)


def test_buffer_result_tabs_select_active_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    first_handle, first_view = _result_metadata(1, columns=("first",))
    second_handle, second_view = _result_metadata(2, columns=("second",), display_rows=(("2",),))

    first_sequence = state.begin_query_run("SELECT 1 AS first")
    state.record_query_success(
        first_sequence,
        "SELECT 1 AS first",
        handle=first_handle,
        result_view=first_view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
    )
    second_sequence = state.begin_query_run("SELECT 2 AS second")
    state.record_query_success(
        second_sequence,
        "SELECT 2 AS second",
        handle=second_handle,
        result_view=second_view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=1, index=1, label="query 1"),
            TUIBufferResultTab(sequence=2, index=2, label="query 2"),
        ),
        selected_sequence=1,
    )

    assert state.select_buffer_result(2) is True

    assert state.active_result == TUIActiveResultState(
        kind="buffer",
        label="Active result: buffer 2.2",
        sequence=2,
        buffer_result_index=2,
    )
    assert state.result_view is second_view


def test_clear_last_result_resets_active_result_and_buffer_tabs(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    sequence = state.begin_query_run("SELECT 1")
    handle, view = _result_metadata(sequence)
    state.record_query_success(
        sequence,
        "SELECT 1",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=1, index=1, label="query 1"),))

    state.clear_last_result()

    assert not state.has_active_result
    assert state.active_result == TUIActiveResultState()
    assert state.buffer_result_tabs == ()


def test_begin_query_run_prevents_overlapping_runs(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    sequence = state.begin_query_run("SELECT * FROM orders")

    assert sequence == 1
    assert state.query_run.is_running is True
    assert state.query_run.sequence == 1

    with pytest.raises(RuntimeError, match="query is already running"):
        state.begin_query_run("SELECT COUNT(*) FROM orders")


def test_begin_query_batch_reserves_contiguous_sequences(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    sequences = state.begin_query_batch(("SELECT 1", "SELECT 2", "SELECT 3"))

    assert sequences == (1, 2, 3)
    assert state.query_run.is_running is True
    assert state.query_run.sequence == 1

    with pytest.raises(RuntimeError, match="query is already running"):
        state.begin_query_batch(("SELECT 4",))


def test_tui_source_column_stores_name_and_duckdb_type() -> None:
    column = TUISourceColumn(name="Customer ID", duckdb_type="VARCHAR")

    assert column.name == "Customer ID"
    assert column.duckdb_type == "VARCHAR"


def test_query_history_item_defaults_to_current_run_mode() -> None:
    item = TUIQueryHistoryItem(sequence=1, sql="SELECT 1", status="success")

    assert item.run_mode == "current"


def test_record_query_success_stores_buffer_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    sequence = state.begin_query_run("SELECT 1")
    handle, view = _result_metadata(sequence)

    state.record_query_success(
        sequence,
        "SELECT 1",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
    )

    assert state.query_history[-1].run_mode == "buffer"
    assert state.active_result == TUIActiveResultState(
        kind="buffer",
        label="Active result: buffer 1.1",
        sequence=1,
        buffer_result_index=1,
    )


def test_record_query_success_requires_buffer_result_index(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    sequence = state.begin_query_run("SELECT 1")
    handle, view = _result_metadata(sequence)

    with pytest.raises(ValueError, match="buffer_result_index is required for buffer results"):
        state.record_query_success(
            sequence,
            "SELECT 1",
            handle=handle,
            result_view=view,
            elapsed_ms=1.0,
            run_mode="buffer",
        )

    assert not state.has_active_result
    assert state.active_result == TUIActiveResultState()


def test_buffer_result_tabs_reset_stale_active_result_when_cleared_or_replaced(
    tmp_path: Path,
) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    first_sequence = state.begin_query_run("SELECT 1 AS first")
    first_handle, first_view = _result_metadata(first_sequence, columns=("first",))
    state.record_query_success(
        first_sequence,
        "SELECT 1 AS first",
        handle=first_handle,
        result_view=first_view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=1, index=1, label="query 1"),))

    state.clear_buffer_result_tabs()

    assert state.buffer_result_tabs == ()
    assert state.active_result == TUIActiveResultState()

    second_sequence = state.begin_query_run("SELECT 2 AS second")
    second_handle, second_view = _result_metadata(
        second_sequence,
        columns=("second",),
        display_rows=(("2",),),
    )
    state.record_query_success(
        second_sequence,
        "SELECT 2 AS second",
        handle=second_handle,
        result_view=second_view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=2, index=2, label="query 2"),))

    assert state.active_result == TUIActiveResultState(
        kind="buffer",
        label="Active result: buffer 2.2",
        sequence=2,
        buffer_result_index=2,
    )

    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=3, index=1, label="query 3"),))

    assert state.buffer_result_tabs == (TUIBufferResultTab(sequence=3, index=1, label="query 3"),)
    assert state.active_result == TUIActiveResultState()


def test_storage_error_preserves_active_result_and_appends_history() -> None:
    state = TUISessionState()
    handle, view = _result_metadata(1, columns=("id",))
    state.record_query_success(
        1,
        "SELECT 1",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
    )
    sequence = state.begin_query_run("SELECT * FROM large")

    state.record_query_storage_error(
        sequence,
        "SELECT * FROM large",
        "Unable to store the query result.",
    )

    assert state.active_result.sequence == 1
    assert state.result_view is view
    assert state.query_history[-1].status == "error"
    assert state.query_history[-1].error_message == "Unable to store the query result."
    assert state.query_run.is_running is False


def test_mark_results_unavailable_keeps_preview() -> None:
    state = TUISessionState()
    handle = TUIResultHandle(sequence=1, is_spilled=True, temp_path=Path("query-1.pickle"))
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("1",),),
        total_row_count=10_001,
        is_truncated=True,
        source_result_sequence=1,
    )
    state.record_query_success(
        1,
        "SELECT * FROM large",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
    )

    state.mark_results_unavailable((1,), "The full result is no longer available.")

    record = state.query_result_record(1)
    assert record is not None
    assert record.availability == "preview_only"
    assert record.unavailable_message == "The full result is no longer available."
    assert state.result_view is view


def test_buffer_outcomes_finish_only_after_batch_completion() -> None:
    state = TUISessionState()
    sequences = state.begin_query_batch(("SELECT 1", "SELECT 2"))
    handle, view = _result_metadata(sequences[0])

    state.record_query_success(
        sequences[0],
        "SELECT 1",
        handle=handle,
        result_view=view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
        complete_run=False,
    )
    state.record_query_no_result(
        sequences[1],
        "SELECT 2",
        1.0,
        run_mode="buffer",
        complete_run=False,
    )

    assert state.query_run.is_running is True

    state.finish_query_run()

    assert state.query_run.is_running is False


def test_record_query_no_result_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    sequence = state.begin_query_run("CREATE TEMP TABLE t AS SELECT 1")

    state.record_query_no_result(
        sequence,
        "CREATE TEMP TABLE t AS SELECT 1",
        elapsed_ms=1.0,
        run_mode="rerun",
    )

    assert state.query_history[-1].run_mode == "rerun"


def test_record_query_error_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    sequence = state.begin_query_run("SELECT * FROM missing")

    state.record_query_error(
        sequence,
        "SELECT * FROM missing",
        "Catalog Error: missing table",
        run_mode="rerun",
    )

    assert state.query_history[-1].run_mode == "rerun"


def test_session_source_columns_are_case_insensitive_by_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    columns = (
        TUISourceColumn(name="order_id", duckdb_type="VARCHAR"),
        TUISourceColumn(name="total", duckdb_type="DOUBLE"),
    )

    state.set_source_columns("ORDERS", columns)

    assert state.source_columns("orders") == columns
    assert state.source_columns("ORDERS") == columns


def test_removing_source_clears_cached_columns_for_that_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    state.set_source_columns(
        "orders",
        (TUISourceColumn(name="order_id", duckdb_type="VARCHAR"),),
    )
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    state.remove_source("ORDERS")

    assert state.source_columns("orders") == ()
    assert state.source_columns("customers") == (
        TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
    )
