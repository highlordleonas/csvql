from csvql.models import QueryResult
from csvql.tui_results import make_result_view_state


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
