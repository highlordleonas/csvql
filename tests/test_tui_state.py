from pathlib import Path

import pytest

from csvql.exceptions import TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.tui_state import TUISessionState, TUISource


def test_tui_source_as_table_source_returns_table_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    source = TUISource(name="orders", path=csv_path, origin="argument")

    assert source.as_table_source() == TableSource(name="orders", path=csv_path)


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
