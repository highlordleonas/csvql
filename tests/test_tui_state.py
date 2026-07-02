from pathlib import Path

import pytest

from csvql.exceptions import TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.tui_state import (
    TUIQueryHistoryItem,
    TUIResultViewState,
    TUISessionState,
    TUISource,
    TUISourceColumn,
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


def test_last_result_tracking(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.2)

    state.set_last_result(result)

    assert state.last_result == result
    assert state.last_result_status == "query"


def test_clear_last_result_resets_result_and_status(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.2)

    state.set_last_result(result)
    state.result_view = TUIResultViewState(
        columns=("count",),
        display_rows=(("2",),),
        total_row_count=1,
        is_truncated=True,
        source_result_sequence=7,
    )

    state.clear_last_result()

    assert state.last_result is None
    assert state.last_result_status == "none"
    assert state.result_view == TUIResultViewState()


def test_last_result_status_tracks_query_no_result_and_error(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=7.5)

    assert state.last_result_status == "none"

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(sequence, "SELECT COUNT(*) FROM orders", result)

    assert state.last_result_status == "query"
    assert state.last_result == result

    no_result_sequence = state.begin_query_run("CREATE TABLE scratch AS SELECT 1")
    state.record_query_no_result(no_result_sequence, "CREATE TABLE scratch AS SELECT 1", 2.5)

    assert state.last_result_status == "no_result"
    assert state.last_result is None

    error_sequence = state.begin_query_run("SELECT * FROM missing")
    state.record_query_error(error_sequence, "SELECT * FROM missing", "missing table")

    assert state.last_result_status == "error"
    assert state.last_result is None


def test_query_history_records_success_error_and_no_result(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    result = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=7.5)

    sequence = state.begin_query_run("SELECT COUNT(*) FROM orders")
    state.record_query_success(sequence, "SELECT COUNT(*) FROM orders", result)
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
    assert state.last_result is None


def test_begin_query_run_prevents_overlapping_runs(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    sequence = state.begin_query_run("SELECT * FROM orders")

    assert sequence == 1
    assert state.query_run.is_running is True
    assert state.query_run.sequence == 1

    with pytest.raises(RuntimeError, match="query is already running"):
        state.begin_query_run("SELECT COUNT(*) FROM orders")


def test_tui_source_column_stores_name_and_duckdb_type() -> None:
    column = TUISourceColumn(name="Customer ID", duckdb_type="VARCHAR")

    assert column.name == "Customer ID"
    assert column.duckdb_type == "VARCHAR"


def test_query_history_item_defaults_to_sql_run_mode() -> None:
    item = TUIQueryHistoryItem(sequence=1, sql="SELECT 1", status="success")

    assert item.run_mode == "sql"


def test_record_query_success_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument"))
    sequence = state.begin_query_run("SELECT 1")

    state.record_query_success(
        sequence,
        "SELECT 1",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        run_mode="editor",
    )

    assert state.query_history[-1].run_mode == "editor"


def test_record_query_no_result_stores_run_mode(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument"))
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
    state.add_source(TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument"))
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
