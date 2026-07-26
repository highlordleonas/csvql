import builtins
import importlib
import sys

import pytest
from rich.text import Text

from csvql.bounded_result import BoundedQueryResult
from csvql.models import QueryResult
from csvql.tui_result_store import TUIResultHandle
from csvql.tui_results import make_result_view_state, result_preview_message
from csvql.tui_state import TUIResultRecord, TUIResultViewState


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


def test_result_view_encodes_terminal_controls_before_applying_cell_cap() -> None:
    result = QueryResult(
        columns=("payload",),
        rows=(("\x1b[2Jabcdef",),),
        elapsed_ms=1.2,
    )

    view = make_result_view_state(result, source_result_sequence=1, cell_char_cap=10)

    assert view.display_rows == ((r"\x1b[2J...",),)
    assert result.rows == (("\x1b[2Jabcdef",),)


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


def test_bounded_result_view_preserves_preview_rows_and_truncation_metadata() -> None:
    from csvql.tui_results import make_bounded_result_view_state

    bounded = BoundedQueryResult(
        columns=("id", "payload"),
        rows=((1, "abcdef"), (2, "ghijkl")),
        elapsed_ms=1.2,
        preview_payload_bytes=12,
        has_more_rows=True,
        truncation_reason="row_limit",
    )

    view = make_bounded_result_view_state(
        bounded,
        source_result_sequence=11,
        cell_char_cap=5,
    )

    assert view.columns == ("id", "payload")
    assert view.display_rows == (("1", "ab..."), ("2", "gh..."))
    assert view.total_row_count == 2
    assert view.preview_row_cap == 2
    assert view.is_truncated is True
    assert view.truncation_reason == "row_limit"
    assert view.source_result_sequence == 11
    assert bounded.rows == ((1, "abcdef"), (2, "ghijkl"))


def test_legacy_result_preview_message_remains_backward_compatible() -> None:
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("1",),),
        total_row_count=3,
        preview_row_cap=1,
        is_truncated=True,
    )

    assert (
        result_preview_message(view)
        == "Showing first 1 of 3 returned row(s). Export/save use the full active result."
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            "executing",
            "Running query. Results will appear when the bounded preview is ready.",
        ),
        (
            "cancelled",
            "Query cancelled before a preview was retained.",
        ),
        (
            "failed",
            "Query failed before a preview was retained.",
        ),
    ],
)
def test_result_preview_message_handles_non_preview_lifecycle_states(
    state: str,
    expected: str,
) -> None:
    view = TUIResultViewState()
    record = TUIResultRecord(
        handle=None,
        state=state,
        reason=None,
        columns=(),
        preview_row_count=0,
        full_row_count=None,
        elapsed_ms=1.2,
    )

    assert result_preview_message(view, record=record) == expected


def test_result_preview_message_for_preserving_row_limited_preview() -> None:
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("1",), ("2",)),
        total_row_count=2,
        preview_row_cap=2,
        is_truncated=True,
        truncation_reason="row_limit",
    )
    record = TUIResultRecord(
        handle=None,
        state="preserving",
        reason=None,
        columns=("id",),
        preview_row_count=2,
        full_row_count=None,
        elapsed_ms=1.2,
    )

    assert result_preview_message(view, record=record) == (
        "Showing 2 retained preview row(s). More rows exist beyond the interactive row limit. "
        "Full result preservation is still running. "
        "Full export/save stay unavailable until it finishes."
    )


def test_result_preview_message_for_preserving_byte_limited_preview() -> None:
    view = TUIResultViewState(
        columns=("payload",),
        display_rows=(("retained",),),
        total_row_count=1,
        preview_row_cap=1000,
        is_truncated=True,
        truncation_reason="byte_limit",
    )
    record = TUIResultRecord(
        handle=None,
        state="preserving",
        reason=None,
        columns=("payload",),
        preview_row_count=1,
        full_row_count=None,
        elapsed_ms=1.2,
    )

    assert result_preview_message(view, record=record) == (
        "Showing 1 retained preview row(s). "
        "More rows exist beyond the fixed preview byte ceiling. "
        "Full result preservation is still running. "
        "Full export/save stay unavailable until it finishes."
    )


def test_result_preview_message_for_complete_result_uses_exact_final_count() -> None:
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("1",), ("2",)),
        total_row_count=2,
        preview_row_cap=2,
        is_truncated=True,
    )
    record = TUIResultRecord(
        handle=TUIResultHandle(sequence=9, store_id="store", nonce="nonce"),
        state="complete",
        reason=None,
        columns=("id",),
        preview_row_count=2,
        full_row_count=7,
        elapsed_ms=1.2,
    )

    assert result_preview_message(view, record=record) == (
        "Showing 2 retained preview row(s) from 7 total row(s). "
        "Full export/save use the preserved result."
    )


@pytest.mark.parametrize(
    ("reason", "expected_detail"),
    [
        ("user_cancelled", "Preservation stopped because it was cancelled."),
        (
            "session_spool_limit",
            "Preservation stopped because the TUI session capacity was exhausted.",
        ),
        ("preservation_failed", "Preservation stopped because writing the full result failed."),
    ],
)
def test_result_preview_message_for_preview_only_names_exact_reason(
    reason: str,
    expected_detail: str,
) -> None:
    view = TUIResultViewState(
        columns=("id",),
        display_rows=(("1",),),
        total_row_count=1,
        preview_row_cap=1,
        is_truncated=False,
    )
    record = TUIResultRecord(
        handle=None,
        state="preview_only",
        reason=reason,
        columns=("id",),
        preview_row_count=1,
        full_row_count=None,
        elapsed_ms=1.2,
    )

    assert result_preview_message(view, record=record) == (
        f"Showing 1 retained preview row(s). {expected_detail} "
        "Full export/save are unavailable for this result."
    )


def test_populate_result_table_writes_columns_and_rows() -> None:
    pytest.importorskip("textual")

    from csvql.tui_results import populate_result_table

    class _TableRecorder:
        def __init__(self) -> None:
            self.cleared_with_columns = False
            self.columns: tuple[object, ...] = ()
            self.rows: tuple[tuple[object, ...], ...] = ()

        def clear(self, *, columns: bool = False) -> object:
            self.cleared_with_columns = columns
            return None

        def add_columns(self, *labels: object) -> object:
            self.columns = labels
            return None

        def add_row(self, *cells: object) -> object:
            self.rows += (cells,)
            return None

    table = _TableRecorder()
    view = TUIResultViewState(
        columns=("id", "payload"),
        display_rows=(("1", "alpha"), ("2", "beta")),
    )

    populate_result_table(table, view)

    assert table.cleared_with_columns is True
    assert tuple(str(column) for column in table.columns) == ("id", "payload")
    assert tuple(tuple(str(cell) for cell in row) for row in table.rows) == (
        ("1", "alpha"),
        ("2", "beta"),
    )


def test_populate_result_table_uses_literal_control_safe_text() -> None:
    pytest.importorskip("textual")

    from csvql.tui_results import populate_result_table

    class _TableRecorder:
        def __init__(self) -> None:
            self.columns: tuple[object, ...] = ()
            self.rows: tuple[tuple[object, ...], ...] = ()

        def clear(self, *, columns: bool = False) -> object:
            del columns
            return None

        def add_columns(self, *labels: object) -> object:
            self.columns = labels
            return None

        def add_row(self, *cells: object) -> object:
            self.rows += (cells,)
            return None

    result = QueryResult(
        columns=("\x1b]0;spoof\x07[red]header[/red]",),
        rows=(("\x1b[31m[link=https://example.invalid]cell[/link]\x9b",),),
        elapsed_ms=1.2,
    )
    view = make_result_view_state(result, source_result_sequence=1)
    table = _TableRecorder()

    populate_result_table(table, view)

    column = table.columns[0]
    cell = table.rows[0][0]
    assert isinstance(column, Text)
    assert column.plain == r"\x1b]0;spoof\x07[red]header[/red]"
    assert column.spans == []
    assert isinstance(cell, Text)
    assert cell.plain == r"\x1b[31m[link=https://example.invalid]cell[/link]\x9b"
    assert cell.spans == []


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
