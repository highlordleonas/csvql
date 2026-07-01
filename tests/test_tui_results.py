import builtins
import importlib
import sys

import pytest

from csvql.models import QueryResult
from csvql.tui_results import make_result_view_state
from csvql.tui_state import TUIResultViewState


def test_result_view_caps_display_rows_without_mutating_source_result() -> None:
    result = QueryResult(
        columns=("id",),
        rows=tuple((index,) for index in range(5)),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=7, preview_row_cap=3)

    assert view.columns == ("id",)
    assert view.display_rows == (("0",), ("1",), ("2",))
    assert view.total_row_count == 5
    assert view.is_truncated is True
    assert view.source_result_sequence == 7
    assert result.row_count == 5


def test_result_view_truncates_wide_cells_for_display_only() -> None:
    result = QueryResult(
        columns=("payload",),
        rows=(("abcdef",),),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=1, cell_char_cap=5)

    assert view.display_rows == (("ab...",),)
    assert result.rows == (("abcdef",),)


def test_result_view_preserves_all_columns_for_horizontal_scroll() -> None:
    result = QueryResult(
        columns=("c1", "c2", "c3", "c4"),
        rows=((1, 2, 3, 4),),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=2)

    assert view.columns == ("c1", "c2", "c3", "c4")
    assert view.display_rows == (("1", "2", "3", "4"),)


@pytest.mark.parametrize(
    ("cell_char_cap", "expected"),
    [
        (0, ""),
        (1, "a"),
        (3, "abc"),
    ],
)
def test_result_view_handles_tiny_cell_char_caps(cell_char_cap: int, expected: str) -> None:
    result = QueryResult(
        columns=("payload",),
        rows=(("abcdef",),),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=3, cell_char_cap=cell_char_cap)

    assert view.display_rows == ((expected,),)


def test_populate_result_table_writes_columns_and_rows() -> None:
    pytest.importorskip("textual")

    from csvql.tui_results import populate_result_table

    class _TableRecorder:
        def __init__(self) -> None:
            self.cleared_with_columns = False
            self.columns: tuple[str, ...] = ()
            self.rows: tuple[tuple[str, ...], ...] = ()

        def clear(self, *, columns: bool = False) -> object:
            self.cleared_with_columns = columns
            return None

        def add_columns(self, *labels: str) -> object:
            self.columns = labels
            return None

        def add_row(self, *cells: str) -> object:
            self.rows += (cells,)
            return None

    table = _TableRecorder()
    view = TUIResultViewState(
        columns=("id", "payload"),
        display_rows=(("1", "alpha"), ("2", "beta")),
    )

    populate_result_table(table, view)

    assert table.cleared_with_columns is True
    assert table.columns == ("id", "payload")
    assert table.rows == (("1", "alpha"), ("2", "beta"))


def test_tui_results_imports_without_textual(monkeypatch: pytest.MonkeyPatch) -> None:
    def guarded_import(
        name: str,
        globals: object | None = None,
        locals: object | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "textual" or name.startswith("textual."):
            raise ModuleNotFoundError("No module named 'textual'")
        return original_import(name, globals, locals, fromlist, level)

    original_import = builtins.__import__
    monkeypatch.delitem(sys.modules, "csvql.tui_results", raising=False)
    for module_name in tuple(
        name for name in sys.modules if name == "textual" or name.startswith("textual.")
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("csvql.tui_results")

    assert hasattr(module, "populate_result_table")
