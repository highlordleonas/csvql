import pickle
from pathlib import Path

import pytest

from csvql.models import QueryResult
from csvql.tui_result_store import (
    TUI_RESULT_SPILL_CELL_THRESHOLD,
    TUI_RESULT_SPILL_ROW_THRESHOLD,
    TUIResultHandle,
    TUIResultStore,
)


def _result(row_count: int, column_count: int = 1) -> QueryResult:
    columns = tuple(f"c{index}" for index in range(column_count))
    rows = tuple(
        tuple(f"{row}-{column}" for column in range(column_count)) for row in range(row_count)
    )
    return QueryResult(columns=columns, rows=rows, elapsed_ms=1.0)


def test_result_store_keeps_small_results_in_memory(tmp_path):
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(2), sequence=1)

    assert handle.is_spilled is False
    assert store.get(handle).row_count == 2


def test_result_store_spills_large_row_count(tmp_path):
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)

    assert handle.is_spilled is True
    assert handle.temp_path is not None
    assert handle.temp_path.exists()
    assert store.get(handle).row_count == TUI_RESULT_SPILL_ROW_THRESHOLD + 1


def test_result_store_spills_large_cell_count(tmp_path):
    row_count = 101
    column_count = (TUI_RESULT_SPILL_CELL_THRESHOLD // row_count) + 1
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(row_count, column_count), sequence=2)

    assert handle.is_spilled is True
    assert store.get(handle).row_count == row_count


def test_result_store_cleanup_removes_spilled_files(tmp_path):
    store = TUIResultStore(temp_root=tmp_path)
    handle = store.put(_result(TUI_RESULT_SPILL_ROW_THRESHOLD + 1), sequence=1)
    assert handle.temp_path is not None

    store.cleanup()

    assert not handle.temp_path.exists()


def test_result_store_rejects_foreign_spilled_paths_without_unpickling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    foreign_path = tmp_path / "foreign-result.pickle"
    foreign_path.write_bytes(pickle.dumps(_result(1)))
    handle = TUIResultHandle(sequence=99, is_spilled=True, temp_path=foreign_path)

    def fail_on_load(*args: object, **kwargs: object) -> object:
        raise AssertionError("foreign spilled paths must not be unpickled")

    monkeypatch.setattr("csvql.tui_result_store.pickle.load", fail_on_load)

    with pytest.raises(KeyError):
        store.get(handle)
