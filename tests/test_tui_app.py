import asyncio
import threading
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual import events
from textual.coordinate import Coordinate
from textual.geometry import Size
from textual.pilot import Pilot
from textual.widgets import DataTable, Input, Static, TextArea
from textual.widgets._footer import FooterKey

from csvql.atomic_write import OperationToken
from csvql.exceptions import CSVQLError
from csvql.models import QueryResult
from csvql.tui_app import CSVQLMenuApp
from csvql.tui_result_store import TUIResultStore
from csvql.tui_results import make_result_view_state
from csvql.tui_state import TUIBufferResultTab, TUISessionState, TUISource, TUISourceColumn
from csvql.tui_workflows import export_last_result as workflows_export_last_result


def _read_readme_text() -> str:
    return (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def _read_doc_text(relative_path: str) -> str:
    return (Path(__file__).resolve().parents[1] / relative_path).read_text(encoding="utf-8")


def _normalized_markdown_text(text: str) -> str:
    return " ".join(text.split())


def app_history_statuses(state: TUISessionState) -> list[str]:
    return [item.status for item in state.query_history]


def app_history_run_modes(state: TUISessionState) -> list[str]:
    return [item.run_mode for item in state.query_history]


def _make_source_state(tmp_path: Path, *, alias: str = "customers") -> TUISessionState:
    csv_path = tmp_path / f"{alias}.csv"
    csv_path.write_text(
        "customer_id,email\nCUST-001,alex@example.com\nCUST-002,bob@example.com\n",
        encoding="utf-8",
    )
    state = TUISessionState()
    state.add_source(TUISource(name=alias, path=csv_path, origin="argument"))
    return state


def _result_grid_snapshot(app: CSVQLMenuApp) -> tuple[tuple[str, ...], int, str]:
    results = app.query_one("#results", DataTable)
    return (
        tuple(str(column.label) for column in results.columns.values()),
        results.row_count,
        app.query_one("#results-message", Static).content,
    )


def _footer_key_displays(app: CSVQLMenuApp) -> tuple[str, ...]:
    return tuple(key.key_display for key in app.query(FooterKey))


def _footer_entries(app: CSVQLMenuApp) -> tuple[tuple[str, str], ...]:
    return tuple((key.key_display, key.description) for key in app.query(FooterKey))


def _history_run_column_values(app: CSVQLMenuApp) -> tuple[str, ...]:
    history = app.query_one("#history", DataTable)
    return tuple(str(history.get_cell_at(Coordinate(row, 1))) for row in range(history.row_count))


def _focused_widget_id(app: CSVQLMenuApp) -> str:
    focused = app.focused
    if focused is None:
        return "None"
    return focused.id or type(focused).__name__


async def _settled_footer_key_displays(
    pilot: Pilot[None],
    app: CSVQLMenuApp,
    *,
    required_key: str | None = None,
) -> tuple[str, ...]:
    for _ in range(5):
        await pilot.pause(0.1)
        key_displays = _footer_key_displays(app)
        if key_displays and (required_key is None or required_key in key_displays):
            return key_displays
    return _footer_key_displays(app)


async def _settled_footer_entries(
    pilot: Pilot[None],
    app: CSVQLMenuApp,
    *,
    required_entry: tuple[str, str] | None = None,
    expected_entries: tuple[tuple[str, str], ...] | None = None,
) -> tuple[tuple[str, str], ...]:
    for _ in range(5):
        await pilot.pause(0.1)
        entries = _footer_entries(app)
        if expected_entries is not None and entries == expected_entries:
            return entries
        if entries and (required_entry is None or required_entry in entries):
            return entries
    return _footer_entries(app)


async def _settled_operation_idle(
    pilot: Pilot[None],
    app: CSVQLMenuApp,
    *,
    wait_for_status_settle: bool = True,
) -> None:
    if not wait_for_status_settle:
        for _ in range(60):
            await pilot.pause(0.05)
            if not app.state.operation_run.is_running:
                await pilot.pause(0.5)
                return
        pytest.fail("Timed out waiting for TUI operation to finish.")
        return

    for _ in range(1800):
        await pilot.pause(0.05)
        status_widget = app.query_one("#status", Static)
        status = status_widget.content
        if app.state.operation_run.is_running or status.endswith("..."):
            continue
        await pilot.pause(0.2)
        settled_status = app.query_one("#status", Static).content
        if not app.state.operation_run.is_running and not settled_status.endswith("..."):
            return
    pytest.fail("Timed out waiting for TUI operation status to settle.")


def _create_csv(tmp_path: Path, filename: str, content: str) -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_app_starts_empty() -> None:
    async def _inner() -> tuple[int, str]:
        app = CSVQLMenuApp(start_dir=Path.cwd())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            return sources.row_count, status

    row_count, status = asyncio.run(_inner())

    assert row_count == 0
    assert "No sources loaded." in status


def test_app_runs_query_and_updates_status_and_results(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)
            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            message = app.query_one("#results-message", Static).content
            return (
                status,
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
                message,
            )

    status, columns, row_count, message = asyncio.run(_inner())

    assert "2 returned row(s)" in status
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "Showing 2 returned row(s)." in message


def test_app_runs_query_records_result_handle_and_cleans_up_spilled_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources, sql
        from csvql.tui_state import TUIQueryOutcome

        rows = tuple((index,) for index in range(10_001))
        return TUIQueryOutcome.success(
            sequence=sequence,
            sql="SELECT * FROM customers",
            result=QueryResult(columns=("value",), rows=rows, elapsed_ms=1.0),
        )

    monkeypatch.setattr("csvql.tui_app.TUIResultStore", lambda: store)
    monkeypatch.setattr("csvql.tui_result_store._should_spill", lambda result: True)
    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[bool, bool, Path | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            handle = app.state.query_result_handle(1)
            return (
                handle is not None,
                handle.is_spilled if handle is not None else False,
                handle.temp_path if handle is not None else None,
            )

    has_handle, is_spilled, temp_path = asyncio.run(_inner())

    assert has_handle is True
    assert is_spilled is True
    assert temp_path is not None
    assert not temp_path.exists()


@pytest.mark.parametrize("key", ["f4", "f12"])
def test_run_shortcuts_preserve_previous_result_after_empty_sql(
    tmp_path: Path,
    key: str,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, bool, tuple[str, ...], int, str, str, str, bool, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("   \n")
            await pilot.press(key)
            await pilot.pause(0.2)

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.last_result == previous_result,
                app.state.result_view == previous_view,
                columns,
                row_count,
                message,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app.state.query_run.is_running,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        is_running,
        history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "Enter SQL before running a query." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Ready."
    assert is_running is False
    assert history_statuses == ["success"]


@pytest.mark.parametrize("key", ["f4", "f12"])
def test_run_shortcuts_preserve_previous_result_after_missing_sources(
    tmp_path: Path,
    key: str,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, bool, tuple[str, ...], int, str, str, str, bool, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            app.state.remove_source("customers")
            app._refresh_sources_table()
            sql.load_text("SELECT * FROM customers")
            await pilot.press(key)
            await pilot.pause(0.2)

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.last_result == previous_result,
                app.state.result_view == previous_view,
                columns,
                row_count,
                message,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app.state.query_run.is_running,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        is_running,
        history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "No sources loaded." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Ready."
    assert is_running is False
    assert history_statuses == ["success"]


def test_app_clears_stale_result_on_failed_query(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            assert app.state.last_result is not None

            sql.load_text("SELECT * FROM missing_table")
            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results-message", Static).content
            return app.state.last_result, status, results

    last_result, status, results = asyncio.run(_inner())

    assert last_result is None
    assert "Error:" in status
    assert "missing_table" in results or "missing_table" in status


def test_sql_editor_keeps_regular_text_keys_for_typing(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[str, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            await pilot.press("s")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            return sql.text, config_path.exists(), status

    sql_text, config_exists, status = asyncio.run(_inner())

    assert sql_text == "s"
    assert config_exists is False
    assert "Saved sources to" not in status


def test_printable_workbench_action_keys_type_in_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[str, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            for key in ["q", "i", "s", "p", "a", "d", "w", "r"]:
                await pilot.press(key)
            await pilot.pause()

            status = app.query_one("#status", Static).content
            return sql.text, config_path.exists(), status

    sql_text, config_exists, status = asyncio.run(_inner())

    assert sql_text == "qispadwr"
    assert config_exists is False
    assert "Saved sources to" not in status


def test_function_key_runs_query_from_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            return (
                status,
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
            )

    status, columns, row_count = asyncio.run(_inner())

    assert "2 returned row(s)" in status
    assert columns == ("customer_id", "email")
    assert row_count == 2


def test_f4_runs_query_from_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            return (
                status,
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
            )

    status, columns, row_count = asyncio.run(_inner())

    assert "2 returned row(s)" in status
    assert columns == ("customer_id", "email")
    assert row_count == 2


def test_run_shortcut_runs_selected_sql_when_editor_has_selection(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text(
                "SELECT * FROM missing;\n"
                "SELECT COUNT(*) AS selected_count FROM customers;\n"
                "SELECT * FROM also_missing;"
            )
            sql.move_cursor((1, 0))
            sql.move_cursor((1, 49), select=True)

            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            return (
                status,
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
            )

    status, columns, row_count = asyncio.run(_inner())

    assert "1 returned row(s)" in status
    assert columns == ("selected_count",)
    assert row_count == 1


def test_run_shortcut_runs_current_statement_when_editor_has_no_selection(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text(
                "SELECT * FROM missing;\n"
                "SELECT COUNT(*) AS current_count FROM customers;\n"
                "SELECT * FROM also_missing;"
            )
            sql.move_cursor((1, 8))

            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            return (
                status,
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
            )

    status, columns, row_count = asyncio.run(_inner())

    assert "1 returned row(s)" in status
    assert columns == ("current_count",)
    assert row_count == 1


def test_run_buffer_shortcut_records_buffer_rows_and_selects_latest_tab(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    seen_statements: list[str] = []
    seen_sequences: list[int] = []

    def fake_run_buffer_for_tui(
        sources: object,
        statements: tuple[str, ...],
        *,
        sequences: tuple[int, ...],
    ):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        seen_statements.extend(statements)
        seen_sequences.extend(sequences)
        return (
            TUIQueryOutcome.success(
                sequence=sequences[0],
                sql=statements[0],
                result=QueryResult(columns=("first",), rows=((1,),), elapsed_ms=1.0),
            ),
            TUIQueryOutcome.success(
                sequence=sequences[1],
                sql=statements[1],
                result=QueryResult(columns=("second",), rows=((2,),), elapsed_ms=1.0),
            ),
        )

    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", fake_run_buffer_for_tui)

    async def _inner() -> tuple[
        list[str],
        list[int],
        list[str],
        tuple[str, ...],
        tuple[str, ...],
        str,
        tuple[tuple[object, ...], ...],
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT 2 AS second;")

            await pilot.press("f12")
            await pilot.pause(0.2)

            results = app.query_one("#results", DataTable)
            return (
                seen_statements,
                seen_sequences,
                app_history_run_modes(app.state),
                _history_run_column_values(app),
                tuple(str(column.label) for column in results.columns.values()),
                app.query_one("#results-title", Static).content,
                app.state.last_result.rows if app.state.last_result is not None else (),
                app.query_one("#result-tabs", Static).content,
            )

    (
        seen_statements,
        seen_sequences,
        run_modes,
        run_labels,
        columns,
        results_title,
        active_rows,
        result_tabs,
    ) = asyncio.run(_inner())

    assert seen_statements == ["SELECT 1 AS first", "SELECT 2 AS second"]
    assert seen_sequences == [1, 2]
    assert run_modes == ["buffer", "buffer"]
    assert run_labels == ("buffer", "buffer")
    assert state.query_result_handle(1) is not None
    assert state.query_result_handle(2) is not None
    assert columns == ("second",)
    assert "Active result: buffer 2.2" in results_title
    assert "1: query 1" in result_tabs
    assert "2: query 2" in result_tabs
    assert active_rows == ((2,),)


def test_run_buffer_stops_after_middle_outcome_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    submitted_statements: list[str] = []

    def fake_run_buffer_for_tui(
        sources: object,
        statements: tuple[str, ...],
        *,
        sequences: tuple[int, ...],
    ):
        del sources, sequences
        from csvql.tui_state import TUIQueryOutcome

        submitted_statements.extend(statements)
        return (
            TUIQueryOutcome.success(
                sequence=1,
                sql=statements[0],
                result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            ),
            TUIQueryOutcome.error(
                sequence=2,
                sql=statements[1],
                error_message="simulated failure",
                suggestion="Fix statement 2.",
            ),
        )

    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", fake_run_buffer_for_tui)

    async def _inner() -> tuple[list[str], list[str], list[int], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT broken FROM customers;\nSELECT 3 AS third;")

            await pilot.press("f12")
            await pilot.pause(0.2)

            return (
                submitted_statements,
                app_history_statuses(app.state),
                [item.sequence for item in app.state.query_history],
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
            )

    submitted_statements, statuses, sequences, status, results_message, run_status = asyncio.run(
        _inner()
    )

    assert submitted_statements == [
        "SELECT 1 AS first",
        "SELECT broken FROM customers",
        "SELECT 3 AS third",
    ]
    assert statuses == ["success", "error"]
    assert sequences == [1, 2]
    assert "simulated failure" in status
    assert "simulated failure" in results_message
    assert run_status == "Ready."


def test_run_buffer_recovers_from_empty_worker_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_buffer_for_tui(
        sources: object,
        statements: tuple[str, ...],
        *,
        sequences: tuple[int, ...],
    ) -> tuple[object, ...]:
        del sources, statements, sequences
        return ()

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        )

    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", fake_run_buffer_for_tui)
    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[bool, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;")

            await pilot.press("f12")
            await pilot.pause(0.2)

            buffer_status = app.query_one("#status", Static).content
            buffer_run_status = app.query_one("#run-status", Static).content
            is_running = app.state.query_run.is_running

            sql.load_text("SELECT 1 AS value")
            await pilot.press("f4")
            await pilot.pause(0.2)

            return (
                is_running,
                buffer_status,
                buffer_run_status,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
            )

    (
        is_running,
        buffer_status,
        buffer_run_status,
        final_status,
        final_run_status,
    ) = asyncio.run(_inner())

    assert is_running is False
    assert buffer_run_status == "Ready."
    assert "no tabular result" in buffer_status.lower() or "unexpected" in buffer_status.lower()
    assert "Query already running." not in final_status
    assert final_run_status == "Ready."


def test_buffer_result_navigation_only_works_from_results_pane(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text(
                "SELECT customer_id FROM customers ORDER BY customer_id;"
                "SELECT email FROM customers ORDER BY email;"
            )
            await pilot.press("f12")
            await pilot.pause(0.2)
            initial_label = app.state.active_result.label

            app.query_one("#sources", DataTable).focus()
            await pilot.press("[")
            await pilot.pause()
            sources_label = app.state.active_result.label

            app.query_one("#results", DataTable).focus()
            await pilot.press("[")
            await pilot.pause()
            results_label = app.state.active_result.label
            return initial_label, sources_label, results_label

    initial_label, sources_label, results_label = asyncio.run(_inner())

    assert sources_label == initial_label
    assert results_label != initial_label


def test_run_shortcut_records_sql_run_mode_and_history_column(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[list[str], tuple[str, ...], tuple[str, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT COUNT(*) AS count FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.2)

            history = app.query_one("#history", DataTable)
            return (
                app_history_run_modes(app.state),
                tuple(str(column.label) for column in history.columns.values()),
                _history_run_column_values(app),
                app.query_one("#status", Static).content,
            )

    run_modes, columns, run_labels, status = asyncio.run(_inner())

    assert run_modes == ["current"]
    assert columns == ("seq", "run", "status", "rows", "sql")
    assert run_labels == ("current",)
    assert "1 returned row(s)" in status


@pytest.mark.parametrize("key", ["f12", "ctrl+b"])
def test_run_buffer_shortcut_records_buffer_run_mode(tmp_path: Path, key: str) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[list[str], tuple[str, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT COUNT(*) AS count FROM customers")

            await pilot.press(key)
            await pilot.pause(0.2)

            return (
                app_history_run_modes(app.state),
                _history_run_column_values(app),
                app.query_one("#status", Static).content,
            )

    run_modes, run_labels, status = asyncio.run(_inner())

    assert run_modes == ["buffer"]
    assert run_labels == ("buffer",)
    assert "1 returned row(s)" in status


def test_run_buffer_stops_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    seen_statements: list[str] = []

    def fake_run_buffer_for_tui(
        sources: object,
        statements: tuple[str, ...],
        *,
        sequences: tuple[int, ...],
    ):
        del sources, sequences
        from csvql.tui_state import TUIQueryOutcome

        seen_statements.extend(statements)
        return (
            TUIQueryOutcome.success(
                sequence=1,
                sql=statements[0],
                result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            ),
            TUIQueryOutcome.error(
                sequence=2,
                sql=statements[1],
                error_message="simulated failure",
                suggestion="Fix statement 2.",
            ),
        )

    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", fake_run_buffer_for_tui)

    async def _inner() -> tuple[list[str], list[str], list[int], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT broken FROM customers;\nSELECT 3 AS third;")

            await pilot.press("f12")
            await pilot.pause(0.2)

            return (
                seen_statements,
                app_history_statuses(app.state),
                [item.sequence for item in app.state.query_history],
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
            )

    (
        seen_statements,
        statuses,
        sequences,
        status,
        results_message,
        run_status,
    ) = asyncio.run(_inner())

    assert seen_statements == [
        "SELECT 1 AS first",
        "SELECT broken FROM customers",
        "SELECT 3 AS third",
    ]
    assert statuses == ["success", "error"]
    assert sequences == [1, 2]
    assert "simulated failure" in status
    assert "simulated failure" in results_message
    assert run_status == "Ready."


def test_history_rerun_records_rerun_mode_and_status_message(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT COUNT(*) AS count FROM customers")
    state.record_query_success(
        first_sequence,
        "SELECT COUNT(*) AS count FROM customers",
        QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
    )
    seen_sql: list[str] = []
    release_worker = threading.Event()

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        seen_sql.append(sql)
        release_worker.wait(timeout=1.0)
        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[list[str], tuple[str, ...], str, str, list[str]]:
        try:
            app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                sql = app.query_one("#sql", TextArea)
                sql.focus()
                sql.load_text("SELECT COUNT(*) AS edited_count FROM customers")
                history = app.query_one("#history", DataTable)
                history.focus()
                history.move_cursor(row=0)
                await pilot.press("r")
                await pilot.pause(0.05)
                run_status = app.query_one("#run-status", Static).content
                release_worker.set()
                await pilot.pause(0.2)
                return (
                    app_history_run_modes(app.state),
                    _history_run_column_values(app),
                    run_status,
                    app.query_one("#sql", TextArea).text,
                    seen_sql,
                )
        finally:
            monkeypatch.undo()

    run_modes, run_labels, run_status, sql_text, seen_sql = asyncio.run(_inner())

    assert run_modes == ["current", "rerun"]
    assert run_labels == ("current", "rerun")
    assert run_status == "Rerunning history query 1 as query 2..."
    assert sql_text == "SELECT COUNT(*) AS count FROM customers"
    assert seen_sql == ["SELECT COUNT(*) AS count FROM customers"]


def test_history_refresh_selects_new_query_sequence_after_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    for sequence in range(1, 11):
        run_sequence = state.begin_query_run(f"SELECT {sequence} AS value")
        state.record_query_success(
            run_sequence,
            f"SELECT {sequence} AS value",
            QueryResult(columns=("value",), rows=((sequence,),), elapsed_ms=1.0),
        )

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(columns=("value",), rows=((sequence,),), elapsed_ms=1.0),
        )

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[list[int], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 11 AS value")
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=8)

            await pilot.press("f4")
            await pilot.pause(0.2)

            return (
                [item.sequence for item in app.state.query_history],
                history.cursor_row,
                app.query_one("#status", Static).content,
            )

    sequences, cursor_row, status = asyncio.run(_inner())

    assert sequences == list(range(1, 12))
    assert cursor_row == 10
    assert "11 returned row(s)" not in status
    assert "1 returned row(s)" in status


def test_run_editor_reads_settled_editor_text_after_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    seen_sql: list[str] = []

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        from csvql.tui_state import TUIQueryOutcome

        seen_sql.append(sql)
        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        )

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[bool, tuple[object, ...], list[str], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM custo")

            app.action_run_selected_or_current_query()
            synchronous_is_running = app.state.query_run.is_running
            synchronous_history = app.state.query_history

            sql.load_text("SELECT * FROM customers")
            await pilot.pause(0.2)

            return (
                synchronous_is_running,
                synchronous_history,
                seen_sql,
                app.query_one("#status", Static).content,
            )

    synchronous_is_running, synchronous_history, run_sql, status = asyncio.run(_inner())

    assert synchronous_is_running is False
    assert synchronous_history == ()
    assert run_sql == ["SELECT * FROM customers"]
    assert "1 returned row(s)" in status


def test_schedule_failure_preserves_previous_result_and_resets_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, bool, tuple[str, ...], int, str, str, str, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("SELECT email FROM customers")
            monkeypatch.setattr(app, "call_after_refresh", lambda callback: False)
            app.action_run_query()
            await pilot.pause()

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.last_result == previous_result,
                app.state.result_view == previous_view,
                columns,
                row_count,
                message,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "Unable to schedule query run." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Ready."
    assert history_statuses == ["success"]


def test_query_run_returns_focus_to_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> object | None:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.2)

            return app.focused

    focused = asyncio.run(_inner())

    assert isinstance(focused, TextArea)


def test_new_query_shortcut_clears_sql_and_refocuses_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("ctrl+n")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            return sql.text, status, app.focused

    sql_text, status, focused = asyncio.run(_inner())

    assert sql_text == ""
    assert "Ready for next query." in status
    assert isinstance(focused, TextArea)


def test_can_run_another_query_after_starting_new_query(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            await pilot.press("ctrl+n")
            await pilot.pause()

            sql.load_text("SELECT COUNT(*) AS row_count FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            return (
                status,
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
            )

    status, columns, row_count = asyncio.run(_inner())

    assert "1 returned row(s)" in status
    assert columns == ("row_count",)
    assert row_count == 1


def test_focus_shortcuts_move_between_sources_and_sql(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, object | None, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_focus = app.focused

            await pilot.press("ctrl+up")
            await pilot.pause()
            source_focus = app.focused

            await pilot.press("ctrl+down")
            await pilot.pause()
            sql_focus = app.focused

            return initial_focus, source_focus, sql_focus

    initial_focus, source_focus, sql_focus = asyncio.run(_inner())

    assert isinstance(initial_focus, TextArea)
    assert isinstance(source_focus, DataTable)
    assert isinstance(sql_focus, TextArea)


def test_workbench_focus_shortcuts_cover_all_panes(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, object | None, object | None, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            sources_focus = app.focused
            await pilot.press("f8")
            await pilot.pause()
            history_focus = app.focused
            await pilot.press("f5")
            await pilot.pause()
            results_focus = app.focused
            await pilot.press("f2")
            await pilot.pause()
            sql_focus = app.focused
            return sources_focus, history_focus, results_focus, sql_focus

    sources_focus, history_focus, results_focus, sql_focus = asyncio.run(_inner())

    assert isinstance(sources_focus, DataTable)
    assert isinstance(history_focus, DataTable)
    assert isinstance(results_focus, DataTable)
    assert isinstance(sql_focus, TextArea)


@pytest.mark.parametrize("size", [(60, 18), (160, 45)])
def test_core_panes_mount_and_remain_focusable_at_simulated_viewport_sizes(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[int, int, int, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            history = app.query_one("#history", DataTable)
            results = app.query_one("#results", DataTable)

            await pilot.press("f6")
            await pilot.pause()
            sources_focus = _focused_widget_id(app)
            await pilot.press("f8")
            await pilot.pause()
            history_focus = _focused_widget_id(app)
            await pilot.press("f5")
            await pilot.pause()
            results_focus = _focused_widget_id(app)
            await pilot.press("f2")
            await pilot.pause()
            sql_focus = _focused_widget_id(app)
            return (
                sources.row_count,
                history.row_count,
                results.row_count,
                sources_focus,
                history_focus,
                results_focus,
                sql_focus,
            )

    (
        sources_count,
        history_count,
        results_count,
        sources_focus,
        history_focus,
        results_focus,
        sql_focus,
    ) = asyncio.run(_inner())

    assert sources_count == 1
    assert history_count == 0
    assert results_count == 0
    assert sources_focus == "sources"
    assert history_focus == "history"
    assert results_focus == "results"
    assert sql_focus == "sql"


def test_footer_is_contextual_between_primary_panes(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    expected_sql_footer = (
        ("F1", "Help"),
        ("F3", "Open CSV"),
        ("F4", "Run current"),
        ("F5", "Results"),
        ("F6", "Sources"),
        ("F8", "History"),
        ("F9", "Quit"),
        ("F10", "New query"),
        ("F12", "Run buffer"),
    )
    expected_sources_footer = (
        ("F1", "Help"),
        ("F2", "SQL"),
        ("F3", "Open CSV"),
        ("F5", "Results"),
        ("F8", "History"),
        ("F9", "Quit"),
    )
    expected_history_footer = (
        ("F1", "Help"),
        ("F2", "SQL"),
        ("F5", "Results"),
        ("F6", "Sources"),
        ("F7", "Export active"),
        ("F9", "Quit"),
        ("Ctrl+S/Alt+S", "Save active"),
    )
    expected_results_footer = (
        ("F1", "Help"),
        ("F2", "SQL"),
        ("F6", "Sources"),
        ("F7", "Export active"),
        ("F8", "History"),
        ("F9", "Quit"),
        ("Ctrl+S/Alt+S", "Save active"),
    )

    async def _inner() -> tuple[
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            sql_footer = await _settled_footer_entries(
                pilot,
                app,
                expected_entries=expected_sql_footer,
            )

            await pilot.press("f6")
            sources_footer = await _settled_footer_entries(
                pilot,
                app,
                expected_entries=expected_sources_footer,
            )

            await pilot.press("f8")
            history_footer = await _settled_footer_entries(
                pilot,
                app,
                expected_entries=expected_history_footer,
            )

            await pilot.press("f5")
            results_footer = await _settled_footer_entries(
                pilot,
                app,
                expected_entries=expected_results_footer,
            )

            return sql_footer, sources_footer, history_footer, results_footer

    sql_footer, sources_footer, history_footer, results_footer = asyncio.run(_inner())

    assert sql_footer == expected_sql_footer
    assert sources_footer == expected_sources_footer
    assert history_footer == expected_history_footer
    assert results_footer == expected_results_footer


def test_workbench_layout_prioritizes_sources_and_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            return (
                str(app.query_one("#left-pane").styles.width),
                str(app.query_one("#right-pane").styles.width),
                str(app.query_one("#sources").styles.height),
                str(app.query_one("#sql").styles.height),
            )

    left_width, right_width, sources_height, sql_height = asyncio.run(_inner())

    assert left_width == "38w"
    assert right_width == "62w"
    assert sources_height == "7"
    assert sql_height == "10"


def test_pane_context_updates_with_active_focus(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    sequence = state.begin_query_run("SELECT 1 AS value")
    state.record_query_success(
        sequence,
        "SELECT 1 AS value",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[str, str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_sql_title = app.query_one("#sql-title", Static).content
            initial_context = app.query_one("#context", Static).content

            await pilot.press("f6")
            await pilot.pause()
            sources_title = app.query_one("#sources-title", Static).content
            sources_context = app.query_one("#context", Static).content

            await pilot.press("f8")
            await pilot.pause()
            history_title = app.query_one("#history-title", Static).content
            history_context = app.query_one("#context", Static).content

            return (
                initial_sql_title,
                initial_context,
                sources_title,
                sources_context,
                history_title,
                history_context,
            )

    (
        initial_sql_title,
        initial_context,
        sources_title,
        sources_context,
        history_title,
        history_context,
    ) = asyncio.run(_inner())

    assert initial_sql_title == "ACTIVE: SQL editor"
    assert "Editor target: current SQL buffer" in initial_context
    assert "one DuckDB session" in initial_context
    assert sources_title == "ACTIVE: Sources"
    assert sources_context == (
        "Sources: F3 pick | a add | i inspect | s sample | p profile | "
        "c columns | l alias | x starter | d remove | w save catalog"
    )
    assert len(sources_context) <= 121
    assert "i inspect" in sources_context
    assert "c columns" in sources_context
    assert "w save catalog" in sources_context
    assert history_title == "ACTIVE: History"
    assert "History: selected row" in history_context
    assert "Enter reopen" in history_context


def test_focused_results_title_uses_active_result_banner(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    sequence = state.begin_query_run("SELECT 1 AS value")
    state.record_query_success(
        sequence,
        "SELECT 1 AS value",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            unfocused_title = app.query_one("#results-title", Static).content

            app.query_one("#results", DataTable).focus()
            await pilot.pause()
            focused_title = app.query_one("#results-title", Static).content

            return unfocused_title, focused_title

    unfocused_title, focused_title = asyncio.run(_inner())

    assert unfocused_title == "        Active result: query 1"
    assert focused_title == "ACTIVE RESULT: query 1"


def test_result_tabs_are_blank_until_buffer_results_exist(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            return app.query_one("#result-tabs", Static).content

    result_tabs = asyncio.run(_inner())

    assert result_tabs == ""


def test_buffer_result_tabs_show_navigation_hint(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text(
                "SELECT customer_id FROM customers ORDER BY customer_id;"
                "SELECT email FROM customers ORDER BY email;"
            )
            await pilot.press("f12")
            await pilot.pause(0.2)
            return app.query_one("#result-tabs", Static).content

    tabs = asyncio.run(_inner())

    assert "Buffer results" in tabs
    assert "[/] Results only" not in tabs
    assert "[ / ]" not in tabs
    assert "[ and ]" in tabs


def test_terminal_size_warning_below_minimum(tmp_path: Path) -> None:
    app = CSVQLMenuApp(start_dir=tmp_path)

    assert app._terminal_size_warning(width=99, height=30) == (
        "Terminal too small for full workbench; use at least 100x30."
    )
    assert app._terminal_size_warning(width=100, height=29) == (
        "Terminal too small for full workbench; use at least 100x30."
    )
    assert app._terminal_size_warning(width=100, height=30) is None


def test_terminal_size_warning_shows_on_mount_below_minimum(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(99, 29)) as pilot:
            await pilot.pause()
            return app.query_one("#status", Static).content

    status = asyncio.run(_inner())

    assert status == "Terminal too small for full workbench; use at least 100x30."


def test_terminal_size_warning_clears_after_resize_above_minimum(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(99, 29)) as pilot:
            await pilot.pause()
            assert app.query_one("#status", Static).content == (
                "Terminal too small for full workbench; use at least 100x30."
            )

            app.on_resize(
                events.Resize(
                    size=Size(120, 36),
                    virtual_size=Size(120, 36),
                )
            )
            await pilot.pause()
            return app.query_one("#status", Static).content, app._status_message()

    status, expected_status = asyncio.run(_inner())

    assert status == expected_status


def test_terminal_size_warning_keeps_newer_status_after_recovery(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(99, 29)) as pilot:
            await pilot.pause()
            assert app.query_one("#status", Static).content == (
                "Terminal too small for full workbench; use at least 100x30."
            )

            app._set_status("Query finished.")
            app._apply_terminal_size_warning(width=120, height=36)
            await pilot.pause()
            return app.query_one("#status", Static).content

    status = asyncio.run(_inner())

    assert status == "Query finished."


def test_add_source_action_adds_mapping_and_updates_table(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "new_customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[int, str, str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("a")
            await pilot.pause()

            mapping_input = app.screen.query_one("#mapping-input", Input)
            mapping_input.value = f"customers={csv_path}"
            await pilot.press("enter")
            await pilot.pause()

            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            selected_alias = app.state.selected_alias or ""
            return sources.row_count, app.state.sources[0].origin, status, selected_alias

    row_count, origin, status, selected_alias = asyncio.run(_inner())

    assert row_count == 1
    assert origin == "session"
    assert "Added source customers." in status
    assert selected_alias == "customers"


def test_add_source_action_accepts_pasted_csv_path(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "new customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[int, str, str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("a")
            await pilot.pause()

            mapping_input = app.screen.query_one("#mapping-input", Input)
            mapping_input.value = str(csv_path)
            await pilot.press("enter")
            await pilot.pause()

            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            selected_alias = app.state.selected_alias or ""
            return sources.row_count, app.state.sources[0].name, status, selected_alias

    row_count, source_name, status, selected_alias = asyncio.run(_inner())

    assert row_count == 1
    assert source_name == "new_customers"
    assert "Added source new_customers." in status
    assert selected_alias == "new_customers"


def test_choose_csv_source_action_adds_native_picker_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    csv_path = _create_csv(
        tmp_path,
        "picker_customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    monkeypatch.setattr(
        "csvql.tui_app._choose_csv_paths_with_native_picker",
        lambda: (str(csv_path),),
    )

    async def _inner() -> tuple[int, str, str, object]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f3")
            await pilot.pause()

            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            return sources.row_count, app.state.sources[0].name, status, app.focused

    row_count, source_name, status, focused = asyncio.run(_inner())

    assert row_count == 1
    assert source_name == "picker_customers"
    assert "Added source picker_customers." in status
    assert isinstance(focused, TextArea)


def test_choose_csv_source_action_handles_native_picker_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "csvql.tui_app._choose_csv_paths_with_native_picker",
        lambda: (),
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f3")
            await pilot.pause()

            return app.state.sources, app.query_one("#status", Static).content

    sources, status = asyncio.run(_inner())

    assert sources == ()
    assert "No CSV selected." in status


def test_choose_csv_source_action_falls_back_to_path_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    csv_path = _create_csv(
        tmp_path,
        "linux_customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    def unavailable_picker() -> tuple[str, ...]:
        raise CSVQLError(
            "Native CSV picker is only available on macOS.",
            suggestion="Paste a CSV path instead.",
        )

    monkeypatch.setattr("csvql.tui_app._choose_csv_paths_with_native_picker", unavailable_picker)

    async def _inner() -> tuple[int, str, str, object]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f3")
            await pilot.pause()
            await pilot.press(*str(csv_path))
            await pilot.press("enter")
            await pilot.pause()

            return (
                app.query_one("#sources", DataTable).row_count,
                app.state.sources[0].name,
                app.query_one("#status", Static).content,
                app.focused,
            )

    row_count, source_name, status, focused = asyncio.run(_inner())

    assert row_count == 1
    assert source_name == "linux_customers"
    assert "Added source linux_customers." in status
    assert isinstance(focused, TextArea)


def test_portable_open_csv_fallback_opens_add_source_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable_picker() -> tuple[str, ...]:
        raise CSVQLError(
            "Native CSV picker is only available on macOS.",
            suggestion="Paste a CSV path instead.",
        )

    monkeypatch.setattr("csvql.tui_app._choose_csv_paths_with_native_picker", unavailable_picker)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+o")
            await pilot.pause()

            mapping_input = app.screen.query_one("#mapping-input", Input)
            return type(app.screen).__name__, mapping_input.id or ""

    screen_name, input_id = asyncio.run(_inner())

    assert screen_name == "_PromptInputScreen"
    assert input_id == "mapping-input"


def test_ctrl_o_does_not_stack_add_source_prompts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable_picker() -> tuple[str, ...]:
        raise CSVQLError(
            "Native CSV picker is only available on macOS.",
            suggestion="Paste a CSV path instead.",
        )

    monkeypatch.setattr("csvql.tui_app._choose_csv_paths_with_native_picker", unavailable_picker)

    async def _inner() -> tuple[bool, int, int, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+o")
            await pilot.pause()
            first_screen = app.screen
            first_stack_len = len(app.screen_stack)
            first_input_id = app.screen.query_one("#mapping-input", Input).id or ""

            await pilot.press("ctrl+o")
            await pilot.pause()

            return (
                app.screen is first_screen,
                len(app.screen_stack),
                first_stack_len,
                first_input_id,
            )

    same_screen, second_stack_len, first_stack_len, input_id = asyncio.run(_inner())

    assert input_id == "mapping-input"
    assert same_screen is True
    assert second_stack_len == first_stack_len


def test_f1_does_not_stack_help_over_add_source_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable_picker() -> tuple[str, ...]:
        raise CSVQLError(
            "Native CSV picker is only available on macOS.",
            suggestion="Paste a CSV path instead.",
        )

    monkeypatch.setattr("csvql.tui_app._choose_csv_paths_with_native_picker", unavailable_picker)

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+o")
            await pilot.pause()
            prompt_screen = app.screen

            await pilot.press("f1")
            await pilot.pause()

            mapping_input = app.screen.query_one("#mapping-input", Input)
            return (
                type(app.screen).__name__,
                mapping_input.id or "",
                "same" if app.screen is prompt_screen else "changed",
            )

    screen_name, input_id, screen_state = asyncio.run(_inner())

    assert screen_name == "_PromptInputScreen"
    assert input_id == "mapping-input"
    assert screen_state == "same"


def test_export_prompt_blocks_global_new_query_action(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f7")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("f10")
            await pilot.pause()
            return screen_name, type(app.screen).__name__, sql.text

    first_screen, current_screen, sql_text = asyncio.run(_inner())

    assert first_screen == "_PromptInputScreen"
    assert current_screen == "_PromptInputScreen"
    assert sql_text == "SELECT * FROM customers"


def test_pasted_csv_path_adds_source_without_inserting_editor_text(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[str, tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.post_message(events.Paste(str(csv_path)))
            await pilot.pause()

            status = app.query_one("#status", Static).content
            return sql.text, app.state.sources, status

    sql_text, sources, status = asyncio.run(_inner())

    assert sql_text == ""
    assert sources == (TUISource(name="customers", path=csv_path.resolve(), origin="session"),)
    assert "Added source customers." in status


def test_run_shortcut_does_not_consume_typed_csv_path_text(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[str, tuple[TUISource, ...], str, str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql.load_text(str(csv_path))
            await pilot.press("f4")
            await _settled_operation_idle(pilot, app)
            return (
                sql.text,
                app.state.sources,
                app.query_one("#run-status", Static).content,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    editor_text, sources, run_status, status, results_message = asyncio.run(_inner())

    assert editor_text == str(csv_path)
    assert sources == ()
    assert run_status == "Ready."
    assert "No sources loaded." in status
    assert "No sources loaded." in results_message


def test_idle_editor_csv_path_text_does_not_add_source(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "customers.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[str, tuple[TUISource, ...]]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql.load_text(str(csv_path))
            await pilot.pause(0.2)
            return sql.text, app.state.sources

    editor_text, sources = asyncio.run(_inner())

    assert editor_text == str(csv_path)
    assert sources == ()


def test_embedded_terminal_path_text_inside_sql_is_not_consumed(
    tmp_path: Path,
) -> None:
    csv_path = _create_csv(
        tmp_path,
        "embedded_path.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[str, tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql_text = f"SELECT '{csv_path}' AS file_path;"
            sql.load_text(sql_text)
            await pilot.pause(0.1)

            status = app.query_one("#status", Static).content
            return sql.text, app.state.sources, status

    sql_text, sources, status = asyncio.run(_inner())

    assert sql_text == f"SELECT '{csv_path}' AS file_path;"
    assert sources == ()
    assert "Added source" not in status


def test_sql_comment_with_csv_path_is_not_consumed(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "comment_path.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )

    async def _inner() -> tuple[str, tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql_text = f"-- inspect {csv_path}\nSELECT 1 AS value;"
            sql.load_text(sql_text)
            await pilot.pause(0.1)

            status = app.query_one("#status", Static).content
            return sql.text, app.state.sources, status

    editor_text, sources, status = asyncio.run(_inner())

    assert editor_text == f"-- inspect {csv_path}\nSELECT 1 AS value;"
    assert sources == ()
    assert "Added source" not in status


def test_sql_string_with_csv_path_is_not_treated_as_pasted_path_text(tmp_path: Path) -> None:
    csv_path = _create_csv(
        tmp_path,
        "literal_path.csv",
        "customer_id,email\nCUST-101,zoe@example.com\n",
    )
    sql_text = f"SELECT * FROM read_csv('{csv_path}')"

    async def _inner() -> tuple[str, tuple[TUISource, ...]]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql.load_text(sql_text)
            await pilot.pause(0.1)

            return sql.text, app.state.sources

    editor_text, sources = asyncio.run(_inner())

    assert editor_text == sql_text
    assert sources == ()


def test_regular_sql_paste_stays_in_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[TUISource, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.post_message(events.Paste("SELECT * FROM customers"))
            await pilot.pause()

            return sql.text, app.state.sources

    sql_text, sources = asyncio.run(_inner())

    assert sql_text == "SELECT * FROM customers"
    assert sources == state.sources


def test_duplicate_regular_sql_paste_event_is_deduplicated(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    pasted_sql = (
        "CREATE TEMP TABLE customer_counts AS\n"
        "SELECT email, COUNT(*) AS customer_count\n"
        "FROM customers\n"
        "GROUP BY email;\n\n"
        "SELECT * FROM customer_counts ORDER BY customer_count DESC;"
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql.post_message(events.Paste(pasted_sql))
            sql.post_message(events.Paste(pasted_sql))
            await pilot.pause()

            return sql.text

    editor_text = asyncio.run(_inner())

    assert editor_text == pasted_sql


def test_default_inserted_regular_sql_paste_is_deduplicated(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    pasted_sql = (
        "CREATE TEMP TABLE customer_counts AS\n"
        "SELECT email, COUNT(*) AS customer_count\n"
        "FROM customers\n"
        "GROUP BY email;\n\n"
        "SELECT * FROM customer_counts ORDER BY customer_count DESC;"
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()

            sql.load_text(pasted_sql)
            sql.move_cursor((5, len("SELECT * FROM customer_counts ORDER BY customer_count DESC;")))
            sql.post_message(events.Paste(pasted_sql))
            await pilot.pause()

            return sql.text

    editor_text = asyncio.run(_inner())

    assert editor_text == pasted_sql


def test_export_action_requires_last_result(tmp_path: Path) -> None:
    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            status = app.query_one("#status", Static).content
            results = app.query_one("#results-message", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "Run a query before exporting." in status
    assert "Run a query before exporting." in results


def test_remove_selected_source_updates_state_and_table(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[int, tuple[TUISource, ...], str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("d")
            await pilot.pause()
            prompt = app.screen.query_one("#confirm-text", Static).content
            await pilot.press("y")
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            return sources.row_count, app.state.sources, status, prompt

    row_count, sources, status, prompt = asyncio.run(_inner())

    assert "Remove source customers?" in prompt
    assert row_count == 0
    assert sources == ()
    assert "No sources loaded." in status


def test_remove_selected_source_can_be_cancelled(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[int, tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            return sources.row_count, app.state.sources, status

    row_count, sources, status = asyncio.run(_inner())

    assert row_count == 1
    assert len(sources) == 1
    assert "Source removal cancelled." in status


def test_remove_source_confirmation_blocks_global_new_query_action(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            app.query_one("#sources", DataTable).focus()
            await pilot.press("d")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("f10")
            await pilot.pause()
            return screen_name, type(app.screen).__name__, sql.text, len(app.state.sources)

    first_screen, current_screen, sql_text, source_count = asyncio.run(_inner())

    assert first_screen == "_ConfirmationScreen"
    assert current_screen == "_ConfirmationScreen"
    assert sql_text == "SELECT * FROM customers"
    assert source_count == 1


def test_inspect_sample_and_profile_selected_source_update_output(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[
        str,
        tuple[str, ...],
        tuple[str, str],
        str,
        tuple[str, ...],
        int,
        str,
        str,
        tuple[str, ...],
        tuple[str, ...],
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()

            await pilot.press("i")
            await pilot.pause()
            inspect_status = app.query_one("#status", Static).content
            inspect_table = app.query_one("#results", DataTable)
            inspect_columns = tuple(str(column.label) for column in inspect_table.columns.values())
            inspect_first_row = (
                str(inspect_table.get_cell_at(Coordinate(0, 0))),
                str(inspect_table.get_cell_at(Coordinate(0, 1))),
            )

            await pilot.press("s")
            await pilot.pause()
            sample_status = app.query_one("#status", Static).content
            sample_results = app.query_one("#results", DataTable)
            sample_columns = tuple(str(column.label) for column in sample_results.columns.values())
            sample_row_count = sample_results.row_count
            sample_message = app.query_one("#results-message", Static).content

            await pilot.press("p")
            await pilot.pause()
            profile_status = app.query_one("#status", Static).content
            profile_results = app.query_one("#results", DataTable)
            profile_columns = tuple(
                str(column.label) for column in profile_results.columns.values()
            )
            profile_first_row = tuple(
                str(profile_results.get_cell_at(Coordinate(0, column)))
                for column in range(len(profile_columns))
            )
            profile_message = app.query_one("#results-message", Static).content

            return (
                inspect_status,
                inspect_columns,
                inspect_first_row,
                sample_status,
                sample_columns,
                sample_row_count,
                sample_message,
                profile_status,
                profile_columns,
                profile_first_row,
                profile_message,
            )

    (
        inspect_status,
        inspect_columns,
        inspect_first_row,
        sample_status,
        sample_columns,
        sample_row_count,
        sample_message,
        profile_status,
        profile_columns,
        profile_first_row,
        profile_message,
    ) = asyncio.run(_inner())

    assert "customers: 2 columns inspected." in inspect_status
    assert inspect_columns == ("field", "value")
    assert inspect_first_row == ("source alias/table name", "customers")
    assert "customers: 2 sample row(s)." in sample_status
    assert sample_columns == ("customer_id", "email")
    assert sample_row_count == 2
    assert "Showing 2 returned row(s)." in sample_message
    assert "customers: 2 rows, 2 columns, 0 duplicate rows." in profile_status
    assert profile_columns == (
        "column",
        "type",
        "non_null",
        "null",
        "null_%",
        "distinct",
        "min",
        "max",
    )
    assert profile_first_row[:2] == ("customer_id", "VARCHAR")
    assert profile_message == "Source profile: customers."


def test_source_intelligence_action_uses_operation_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_inspect_source(source: TUISource):
        started.set()
        release.wait(timeout=2)
        from csvql.inspection import inspect_csv_source
        from csvql.source import CSVSource, source_from_path

        resolved = source_from_path(str(source.path))
        return inspect_csv_source(CSVSource(resolved.path, source.name, resolved.fingerprint))

    monkeypatch.setattr("csvql.tui_app.inspect_source", slow_inspect_source)

    async def _inner() -> tuple[bool, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.1)
            running = app.state.operation_run.is_running
            status = app.query_one("#status", Static).content
            release.set()
            await pilot.pause(0.2)
            final_status = app.query_one("#status", Static).content
            return running, status, final_status

    running, status, final_status = asyncio.run(_inner())

    assert started.is_set()
    assert running is True
    assert "Inspecting customers" in status
    assert "customers: 2 columns inspected." in final_status


def test_source_worker_failure_preserves_csv_error_message_and_suggestion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    def failing_inspect_source(source: TUISource) -> object:
        del source
        raise CSVQLError(
            "Cannot inspect source.",
            suggestion="Check the CSV path.",
        )

    monkeypatch.setattr("csvql.tui_app.inspect_source", failing_inspect_source)

    async def _inner() -> tuple[str, str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.2)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
                app.state.operation_run.is_running,
            )

    status, results_message, run_status, is_running = asyncio.run(_inner())

    assert status == results_message
    assert "Error: Cannot inspect source." in status
    assert "Suggestion: Check the CSV path." in status
    assert "Operation failed." not in status
    assert run_status == "Ready."
    assert is_running is False


def test_sample_worker_failure_preserves_previous_active_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_failing_sample_source(source: TUISource) -> object:
        started.set()
        assert release.wait(timeout=2)
        raise CSVQLError(
            "Cannot sample source.",
            suggestion="Check the CSV path.",
        )

    monkeypatch.setattr("csvql.tui_app.sample_source", slow_failing_sample_source)

    async def _inner() -> tuple[bool, bool, bool, str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_active_result = app.state.active_result
            previous_view = app.state.result_view
            assert previous_result is not None

            app.query_one("#sources", DataTable).focus()
            await pilot.press("s")
            await pilot.pause(0.1)

            running_result_preserved = app.state.last_result == previous_result
            running_active_result_preserved = app.state.active_result == previous_active_result
            running_view_preserved = app.state.result_view == previous_view

            release.set()
            await pilot.pause(0.2)

            return (
                running_result_preserved,
                running_active_result_preserved,
                running_view_preserved,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    (
        running_result_preserved,
        running_active_result_preserved,
        running_view_preserved,
        status,
        results_message,
        is_running,
    ) = asyncio.run(_inner())

    assert started.is_set()
    assert running_result_preserved is True
    assert running_active_result_preserved is True
    assert running_view_preserved is True
    assert "Error: Cannot sample source." in status
    assert "Suggestion: Check the CSV path." in results_message
    assert is_running is False


def test_escape_cancels_running_source_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_inspect_source(source: TUISource):
        started.set()
        release.wait(timeout=2)
        from csvql.tui_workflows import inspect_source as real_inspect_source

        return real_inspect_source(source)

    monkeypatch.setattr("csvql.tui_app.inspect_source", slow_inspect_source)

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause()
            release.set()
            await pilot.pause(0.2)
            return app.query_one("#status", Static).content, app.state.operation_run.is_running

    status, is_running = asyncio.run(_inner())

    assert started.is_set()
    assert "Cancelled Inspecting customers." in status
    assert is_running is False


def test_cancelled_sample_worker_preserves_previous_active_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_sample_source(source: TUISource) -> object:
        started.set()
        assert release.wait(timeout=2)
        from csvql.tui_workflows import sample_source as real_sample_source

        return real_sample_source(source)

    monkeypatch.setattr("csvql.tui_app.sample_source", slow_sample_source)

    async def _inner() -> tuple[bool, bool, bool, str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_active_result = app.state.active_result
            previous_view = app.state.result_view
            previous_message = app.query_one("#results-message", Static).content
            assert previous_result is not None

            app.query_one("#sources", DataTable).focus()
            await pilot.press("s")
            await pilot.pause(0.1)

            running_result_preserved = app.state.last_result == previous_result
            running_active_result_preserved = app.state.active_result == previous_active_result
            running_view_preserved = app.state.result_view == previous_view

            await pilot.press("escape")
            await pilot.pause(0.1)
            release.set()
            await pilot.pause(0.2)

            return (
                running_result_preserved,
                running_active_result_preserved,
                running_view_preserved,
                app.query_one("#status", Static).content,
                previous_message,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    (
        running_result_preserved,
        running_active_result_preserved,
        running_view_preserved,
        status,
        previous_message,
        results_message,
        is_running,
    ) = asyncio.run(_inner())

    assert started.is_set()
    assert running_result_preserved is True
    assert running_active_result_preserved is True
    assert running_view_preserved is True
    assert "Cancelled Sampling customers." in status
    assert results_message == previous_message
    assert is_running is False


def test_export_last_result_preserves_visible_result_grid(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    export_path = export_dir / "customers.csv"
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], int, tuple[str, ...], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers ORDER BY customer_id")
            await pilot.press("f4")
            await pilot.pause(0.2)
            before_columns, before_rows, _ = _result_grid_snapshot(app)

            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app, wait_for_status_settle=False)

            after_columns, after_rows, _ = _result_grid_snapshot(app)
            content = export_path.read_text(encoding="utf-8")
            return before_columns, before_rows, after_columns, after_rows, content

    (
        before_columns,
        before_rows,
        after_columns,
        after_rows,
        content,
    ) = asyncio.run(_inner())

    assert before_columns == after_columns == ("customer_id", "email")
    assert before_rows == after_rows == 2
    assert content.startswith("customer_id,email")


def test_escape_cancels_running_export_before_final_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "exports" / "customers.csv"
    export_path.parent.mkdir()
    state = TUISessionState()
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))
    started = threading.Event()
    release = threading.Event()

    def slow_export_last_result(*args: object, **kwargs: object) -> Path:
        token = kwargs["token"]
        assert isinstance(token, OperationToken)
        started.set()
        release.wait(timeout=2)
        token.raise_if_cancelled()
        return workflows_export_last_result(*args, **kwargs)

    monkeypatch.setattr("csvql.tui_app.export_last_result", slow_export_last_result)

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause()
            release.set()
            await pilot.pause(0.2)
            return app.query_one("#status", Static).content, export_path.exists()

    status, exists = asyncio.run(_inner())

    assert started.is_set()
    assert "Cancelled Exporting active result." in status
    assert exists is False


def test_escape_cancels_running_save_result_before_final_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=1.0,
        )
    )
    started = threading.Event()
    release = threading.Event()
    derived_path = tmp_path / ".csvql" / "results" / "customer_emails.csv"

    def slow_save_derived_result_source(*args: object, **kwargs: object):
        token = kwargs["token"]
        assert isinstance(token, OperationToken)
        started.set()
        release.wait(timeout=2)
        token.raise_if_cancelled()
        from csvql.tui_workflows import (
            save_derived_result_source as real_save_derived_result_source,
        )

        return real_save_derived_result_source(*args, **kwargs)

    monkeypatch.setattr("csvql.tui_app.save_derived_result_source", slow_save_derived_result_source)

    async def _inner() -> tuple[str, bool, tuple[TUISource, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "customer_emails"
            await pilot.press("enter")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause()
            release.set()
            await pilot.pause(0.2)
            return (
                app.query_one("#status", Static).content,
                derived_path.exists(),
                app.state.sources,
            )

    status, exists, sources = asyncio.run(_inner())

    assert started.is_set()
    assert "Cancelled Saving active result as source." in status
    assert exists is False
    assert sources == _make_source_state(tmp_path).sources


def test_export_last_result_status_uses_relative_path_within_start_dir(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "customers.csv"
    export_path.parent.mkdir()
    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()

            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            return app.query_one("#status", Static).content

    status = asyncio.run(_inner())

    assert status == "Exported to exports/customers.csv."


def test_export_last_result_defaults_extensionless_path_to_csv(tmp_path: Path) -> None:
    export_path = tmp_path / "customers"
    defaulted_path = tmp_path / "customers.csv"

    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()

            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            status = app.query_one("#status", Static).content
            content = defaulted_path.read_text(encoding="utf-8")
            return status, content

    status, content = asyncio.run(_inner())

    assert not export_path.exists()
    assert defaulted_path.exists()
    assert content.startswith("customer_id,email")
    assert "customers.csv" in status


def test_export_last_result_writes_text_when_path_ends_txt(tmp_path: Path) -> None:
    export_path = tmp_path / "customers.txt"

    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()

            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            return export_path.read_text(encoding="utf-8")

    content = asyncio.run(_inner())

    assert "customer_id" in content
    assert "CUST-001" in content
    assert "1 row(s) in 12.35 ms" in content


def test_export_from_spilled_result_writes_full_output(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "large.csv"
    export_path.parent.mkdir()
    rows = tuple((index,) for index in range(10001))
    stored_result = QueryResult(columns=("id",), rows=rows, elapsed_ms=1.0)
    sentinel_result = QueryResult(columns=("id",), rows=(("preview-only",),), elapsed_ms=0.1)
    state = TUISessionState()

    async def _inner() -> tuple[int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            handle = app._result_store.put(stored_result, sequence=1)
            app.state.record_query_result_handle(1, handle)
            view = make_result_view_state(stored_result, source_result_sequence=1)
            app.state.record_query_success(1, "SELECT * FROM large", stored_result, view)
            app.state.set_last_result(sentinel_result)
            app._refresh_results_display()
            assert app.state.last_result == sentinel_result
            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)
            return (
                len(export_path.read_text(encoding="utf-8").splitlines()),
                app.query_one("#results-message", Static).content,
            )

    line_count, message = asyncio.run(_inner())

    assert line_count == 10002
    assert "Showing first 1,000 of 10,001 returned row(s)." in message
    assert export_path.read_text(encoding="utf-8").splitlines()[1] == "0"


def test_save_result_as_source_writes_full_output_from_spilled_result(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / ".csvql" / "results" / "large_rows.csv"
    rows = tuple((index,) for index in range(10001))
    stored_result = QueryResult(columns=("id",), rows=rows, elapsed_ms=1.0)
    sentinel_result = QueryResult(columns=("id",), rows=(("preview-only",),), elapsed_ms=0.1)
    state = TUISessionState()

    async def _inner() -> tuple[tuple[TUISource, ...], str | None, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            handle = app._result_store.put(stored_result, sequence=1)
            app.state.record_query_result_handle(1, handle)
            view = make_result_view_state(stored_result, source_result_sequence=1)
            app.state.record_query_success(1, "SELECT * FROM large", stored_result, view)
            app.state.set_last_result(sentinel_result)
            app._refresh_results_display()
            assert app.state.last_result == sentinel_result

            await pilot.press("f11")
            await pilot.pause()
            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "large_rows"
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            return (
                app.state.sources,
                app.state.selected_alias,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                export_path.read_text(encoding="utf-8"),
            )

    sources, selected_alias, status, message, content = asyncio.run(_inner())

    assert sources == (
        TUISource(
            name="large_rows",
            path=export_path.resolve(),
            origin="session",
            kind="derived",
        ),
    )
    assert selected_alias == "large_rows"
    assert "Saved result as derived source large_rows" in status
    assert "Showing first 1,000 of 10,001 returned row(s)." in message
    assert content.splitlines()[0] == "id"
    assert len(content.splitlines()) == 10002
    assert content.splitlines()[1] == "0"
    assert content.splitlines()[-1] == "10000"


def test_export_uses_recalled_history_result(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 'first' AS label")
    state.record_query_success(
        first_sequence,
        "SELECT 'first' AS label",
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
    )
    second_sequence = state.begin_query_run("SELECT 'second' AS label")
    state.record_query_success(
        second_sequence,
        "SELECT 'second' AS label",
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
    )
    export_path = tmp_path / "exports" / "recalled.csv"
    export_path.parent.mkdir()

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()

            await pilot.press("f7")
            await pilot.pause()
            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            return (
                app.query_one("#status", Static).content,
                export_path.read_text(encoding="utf-8"),
            )

    status, content = asyncio.run(_inner())

    assert "Exported to" in status
    assert content == "label\nfirst\n"


def test_buffer_result_selector_controls_export_target(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 'first' AS label")
    state.record_query_success(
        first_sequence,
        "SELECT 'first' AS label",
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=1,
    )
    second_sequence = state.begin_query_run("SELECT 'second' AS label")
    state.record_query_success(
        second_sequence,
        "SELECT 'second' AS label",
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=1, index=1, label="query 1"),
            TUIBufferResultTab(sequence=2, index=2, label="query 2"),
        ),
        selected_sequence=2,
    )
    export_path = tmp_path / "exports" / "buffer-selected.csv"
    export_path.parent.mkdir()

    async def _inner() -> tuple[str, str, tuple[tuple[object, ...], ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            results = app.query_one("#results", DataTable)
            results.focus()
            await pilot.press("[")
            await pilot.pause()

            await pilot.press("f7")
            await pilot.pause()
            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            return (
                app.query_one("#results-title", Static).content,
                app.query_one("#status", Static).content,
                app.state.last_result.rows if app.state.last_result is not None else (),
            )

    results_title, status, rows = asyncio.run(_inner())

    assert results_title == "ACTIVE RESULT: buffer 1.1"
    assert "Exported to" in status
    assert rows == (("first",),)
    assert export_path.read_text(encoding="utf-8") == "label\nfirst\n"


def test_sources_pane_keeps_origin_before_relative_project_path(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    state.add_source(
        TUISource(
            name="order_names",
            path=tmp_path / ".csvql" / "results" / "order_names.csv",
            origin="session",
            kind="derived",
        )
    )

    async def _inner() -> tuple[tuple[str, ...], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            return (
                tuple(str(column.label) for column in sources.columns.values()),
                sources.row_count,
                str(sources.get_cell_at(Coordinate(1, 3))),
            )

    columns, row_count, derived_path = asyncio.run(_inner())

    assert columns == ("alias", "kind", "origin", "path")
    assert row_count == 2
    assert derived_path == ".csvql/results/order_names.csv"


def test_save_result_as_source_requires_query_result(tmp_path: Path) -> None:
    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "Run a query before saving a result as a source." in status
    assert "Run a query before saving a result as a source." in message
    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_result_as_source_writes_csv_and_adds_derived_source(tmp_path: Path) -> None:
    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        )
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str | None, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()

            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "customer_emails"
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            output_path = tmp_path / ".csvql" / "results" / "customer_emails.csv"
            return (
                app.state.sources,
                app.state.selected_alias,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                output_path.read_text(encoding="utf-8"),
            )

    sources, selected_alias, status, message, content = asyncio.run(_inner())

    assert sources == (
        TUISource(
            name="customer_emails",
            path=(tmp_path / ".csvql" / "results" / "customer_emails.csv").resolve(),
            origin="session",
            kind="derived",
        ),
    )
    assert selected_alias == "customer_emails"
    assert "Saved result as derived source customer_emails" in status
    assert "Saved result as derived source customer_emails" in message
    assert ".csvql/results/customer_emails.csv" in status
    assert str(tmp_path) not in status
    assert "Use Save sources to persist the alias in .csvql.yml." in status
    assert "Use Save sources to persist the alias in .csvql.yml." in message
    assert content == "customer_id,email\nCUST-001,alex@example.com\n"


def test_save_result_as_source_uses_recalled_history_result(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 'first' AS label")
    state.record_query_success(
        first_sequence,
        "SELECT 'first' AS label",
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
    )
    second_sequence = state.begin_query_run("SELECT 'second' AS label")
    state.record_query_success(
        second_sequence,
        "SELECT 'second' AS label",
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()

            await pilot.press("f11")
            await pilot.pause()
            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "recalled_first"
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            output_path = tmp_path / ".csvql" / "results" / "recalled_first.csv"
            return (
                app.state.sources,
                app.query_one("#status", Static).content,
                output_path.read_text(encoding="utf-8"),
            )

    sources, status, content = asyncio.run(_inner())

    assert sources[-1] == TUISource(
        name="recalled_first",
        path=(tmp_path / ".csvql" / "results" / "recalled_first.csv").resolve(),
        origin="session",
        kind="derived",
    )
    assert "Saved result as derived source recalled_first" in status
    assert content == "label\nfirst\n"


@pytest.mark.parametrize("key", ["ctrl+s", "alt+s"])
def test_save_result_source_shortcuts(tmp_path: Path, key: str) -> None:
    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id",),
            rows=(("CUST-001",),),
            elapsed_ms=12.345,
        )
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()

            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "customer_ids"
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)

            return (
                app.state.sources,
                app.state.selected_alias,
                (tmp_path / ".csvql" / "results" / "customer_ids.csv").read_text(encoding="utf-8"),
            )

    sources, selected_alias, content = asyncio.run(_inner())

    assert sources == (
        TUISource(
            name="customer_ids",
            path=(tmp_path / ".csvql" / "results" / "customer_ids.csv").resolve(),
            origin="session",
            kind="derived",
        ),
    )
    assert selected_alias == "customer_ids"
    assert content == "customer_id\nCUST-001\n"


def test_save_result_as_source_refuses_after_no_result_statement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.no_result(sequence=sequence, sql=sql, elapsed_ms=4.0)

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("CREATE TABLE scratch(id INTEGER)")
            await pilot.press("f4")
            await pilot.pause(0.2)

            await pilot.press("f11")
            await pilot.pause()

            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "The last statement did not produce a tabular result." in status
    assert "The last statement did not produce a tabular result." in message
    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_result_as_source_refuses_duplicate_alias(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0))

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f11")
            await pilot.pause()

            alias_input = app.screen.query_one("#derived-source-alias", Input)
            alias_input.value = "customers"
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause(0.05)
                status = app.query_one("#status", Static).content
                if "Source alias 'customers' is already loaded" in status:
                    break

            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "Source alias 'customers' is already loaded" in status
    assert "Source alias 'customers' is already loaded" in message
    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_sources_requires_confirmation_before_writing_catalog(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[str, bool, bool, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            prompt = app.screen.query_one("#confirm-text", Static).content
            before_confirm = config_path.exists()
            await pilot.press("y")
            await pilot.pause()
            after = config_path.exists()
            status = app.query_one("#status", Static).content
            results_message = app.query_one("#results-message", Static).content
            return prompt, before_confirm, after, status, results_message

    prompt, before_confirm, after, status, results_message = asyncio.run(_inner())

    assert "Save 1 source path" in prompt
    assert ".csvql.yml" in prompt
    assert before_confirm is False
    assert after is True
    assert "Saved sources to" in status
    assert "Saved sources to" in results_message


def test_save_sources_confirmation_warns_for_external_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    external_csv = _create_csv(external_root, "orders.csv", "id\n1\n")
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=external_csv.resolve(), origin="session"))

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=project_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            return app.screen.query_one("#confirm-text", Static).content

    prompt = asyncio.run(_inner())

    assert "external local filesystem path" in prompt
    assert "may reveal machine-specific locations" in prompt


def test_save_sources_confirmation_omits_warning_for_relative_project_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    _create_csv(project_root, "orders.csv", "id\n1\n")
    monkeypatch.chdir(external_root)
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=Path("orders.csv"), origin="session"))

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=project_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            return app.screen.query_one("#confirm-text", Static).content

    prompt = asyncio.run(_inner())

    assert "external local filesystem path" not in prompt
    assert "may reveal machine-specific locations" not in prompt


def test_save_sources_confirmation_can_be_cancelled(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            return config_path.exists(), app.query_one("#status", Static).content

    exists, status = asyncio.run(_inner())

    assert exists is False
    assert "Source catalog save cancelled." in status


def test_save_sources_surfaces_project_config_errors(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: [", encoding="utf-8")

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            prompt = app.screen.query_one("#confirm-text", Static).content
            await pilot.press("y")
            await pilot.pause()
            status = app.query_one("#status", Static).content
            results = app.query_one("#results-message", Static).content
            return prompt, status, results

    prompt, status, results = asyncio.run(_inner())

    assert "Save 1 source path" in prompt
    assert "Error:" in status
    assert "Error:" in results


def test_workbench_history_pane_mounts_with_editor_focused(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            return app.focused, history.row_count

    focused, history_rows = asyncio.run(_inner())

    assert isinstance(focused, TextArea)
    assert history_rows == 0


def test_history_cursor_movement_does_not_change_source_selection(tmp_path: Path) -> None:
    alpha_path = _create_csv(
        tmp_path,
        "alpha.csv",
        "customer_id,email\nCUST-001,alex@example.com\n",
    )
    beta_path = _create_csv(
        tmp_path,
        "beta.csv",
        "customer_id,email\nCUST-002,bob@example.com\n",
    )
    state = TUISessionState()
    state.add_source(TUISource(name="alpha", path=alpha_path, origin="argument"))
    state.add_source(TUISource(name="beta", path=beta_path, origin="argument"))
    state.record_query_success(
        sequence=1,
        sql="SELECT * FROM alpha",
        result=QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=1.0,
        ),
    )
    state.record_query_success(
        sequence=2,
        sql="SELECT * FROM beta",
        result=QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-002", "bob@example.com"),),
            elapsed_ms=2.0,
        ),
    )

    async def _inner() -> str | None:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()

            await pilot.press("down")
            await pilot.pause()

            return app.state.selected_alias

    selected_alias = asyncio.run(_inner())

    assert selected_alias == "alpha"


def test_help_action_opens_and_escape_restores_editor_focus(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_help()
            await pilot.pause()
            help_text = app.screen.query_one("#help-text", Static).content
            await pilot.press("escape")
            await pilot.pause()
            return help_text, app.focused

    _help_text, focused = asyncio.run(_inner())

    assert isinstance(focused, TextArea)


def test_help_action_does_not_stack_multiple_help_screens(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            first_help_screen = app.screen
            await pilot.press("f1")
            await pilot.pause()
            same_help_screen = app.screen is first_help_screen
            await pilot.press("escape")
            await pilot.pause()
            return same_help_screen, app.focused

    same_help_screen, focused = asyncio.run(_inner())

    assert same_help_screen is True
    assert isinstance(focused, TextArea)


@pytest.mark.parametrize("selector", ["#sql", "#sources", "#history", "#results"])
def test_help_escape_restores_focus_to_opening_pane(tmp_path: Path, selector: str) -> None:
    state = _make_source_state(tmp_path)
    sequence = state.begin_query_run("SELECT 'saved' AS label")
    state.record_query_success(
        sequence,
        "SELECT 'saved' AS label",
        QueryResult(columns=("label",), rows=(("saved",),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[object | None, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            opening_widget = app.query_one(selector)
            opening_widget.focus()
            await pilot.pause()

            await pilot.press("f1")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            return opening_widget, app.focused

    opening_widget, focused = asyncio.run(_inner())

    assert focused is opening_widget


def test_help_text_documents_workbench_keymap() -> None:
    from csvql.tui_help import WORKBENCH_HELP

    help_text = WORKBENCH_HELP

    assert "Run SQL" in help_text
    assert "F4 / Ctrl+R         Run selected SQL, otherwise current statement" in help_text
    assert "Run selected SQL, otherwise current statement" in help_text
    assert "F12 / Ctrl+B        Run Buffer" in help_text
    assert "F3 / Ctrl+O         Choose CSV file(s) or prompt for paths" in help_text
    assert "F1                  Help" in help_text
    assert "?                   Help" not in help_text
    assert "Also opens help" not in help_text
    assert (
        "F7                  Export active result (.csv, .json, .md, .markdown, .txt)" in help_text
    )
    assert "last successful tabular" not in help_text
    assert "[ / ]               Previous/next buffer result when Results is focused" in help_text
    assert "F9 / q              Quit outside text entry" in help_text
    assert "Ctrl+S              Save active result to .csvql/results/{alias}.csv" in help_text
    assert "r                   Rerun selected query with current session sources" in help_text


def test_tui_guide_documents_portable_fallbacks_and_run_labels() -> None:
    guide = _read_doc_text("docs/tui-guide.md")

    assert "| `F7` | Export active result |" in guide
    assert "| `F12` or `Ctrl+B` | Run the buffer as separate History rows |" in guide
    assert "| `F3` or `Ctrl+O` | Choose CSV file(s) or prompt for paths |" in guide
    assert "| `F9` or `q` | Quit outside text entry |" in guide
    assert "The History run column uses semantic labels: `current` for F4/Ctrl+R runs," in guide
    assert "`buffer` for F12/Ctrl+B runs" in guide
    assert "`rerun` for History reruns." in guide


def test_troubleshooting_documents_portable_fallbacks() -> None:
    troubleshooting = _read_doc_text("docs/troubleshooting.md")

    assert "- `F3` or `Ctrl+O`: choose CSV file(s) or prompt for paths" in troubleshooting
    assert "- `F12` or `Ctrl+B`: run the buffer as separate History rows" in troubleshooting
    assert (
        "After `F12` or `Ctrl+B`, move through History to recall each successful" in troubleshooting
    )


def test_question_mark_types_in_sql_editor_and_f1_opens_help(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            editor_text = app.query_one("#sql", TextArea).text

            await pilot.press("f1")
            await pilot.pause()
            help_text = app.screen.query_one("#help-text", Static).content
            return editor_text, help_text

    editor_text, help_text = asyncio.run(_inner())

    assert editor_text == "?"
    assert help_text.startswith("CSVQL Workbench Lite")


def test_readme_documents_source_intelligence_keymap() -> None:
    readme = _normalized_markdown_text(_read_readme_text())

    assert (
        "Source Intelligence actions use `i` to inspect the selected source and load columns"
        in readme
    )
    assert "`c` to load/show columns directly" in readme
    assert "`l` to insert the selected source alias" in readme
    assert "`x` to open deterministic starter SQL templates" in readme


def test_help_text_documents_sql_assistance_keymap() -> None:
    from csvql.tui_help import WORKBENCH_HELP

    assert "Ctrl+Space          Complete SQL from loaded source metadata" in WORKBENCH_HELP
    assert "x                   Open starter SQL templates" in WORKBENCH_HELP
    assert "i                   Inspect selected source and load columns" in WORKBENCH_HELP


def test_readme_documents_deterministic_sql_assistance() -> None:
    readme = _normalized_markdown_text(_read_readme_text())

    assert "`Ctrl+Space` opens explicit SQL completion from loaded source metadata" in readme
    assert "`x` to open deterministic starter SQL templates" in readme
    assert "Generated SQL is inserted into the editor and does not run until you run it" in readme
    assert "natural-language" not in readme.lower()


def test_tui_guide_documents_completion_and_templates_without_ai_claims() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))

    assert "`Ctrl+Space` opens explicit SQL completion" in guide
    assert "column-aware templates appear after `c` or `i` loads metadata" in guide
    assert "Generated SQL is editable and does not execute automatically" in guide
    assert "AI insight" not in guide


def test_readme_documents_editor_quality_keymap() -> None:
    readme = _normalized_markdown_text(_read_readme_text())

    assert "`F4` or `Ctrl+R` to run selected SQL" in readme
    assert "`F12` or `Ctrl+B` runs the buffer of semicolon-delimited statements" in readme
    assert "current statement around the cursor" in readme
    assert "statement runs as `current`, buffer runs as `buffer`" in readme
    assert "History reruns as `rerun`" in readme


def test_readme_documents_history_rerun_keymap() -> None:
    readme = _normalized_markdown_text(_read_readme_text())

    assert "History" in readme
    assert (
        "In History, use `Enter` to reopen a query and `r` to rerun a query "
        "against the current session sources." in readme
    )


def test_source_letter_actions_only_work_when_sources_focused(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, tuple[str, ...], tuple[str, str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            editor_text = app.query_one("#sql", TextArea).text

            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", DataTable)
            columns = tuple(str(column.label) for column in results.columns.values())
            first_row = (
                str(results.get_cell_at(Coordinate(0, 0))),
                str(results.get_cell_at(Coordinate(0, 1))),
            )
            return editor_text, status, columns, first_row

    editor_text, status, columns, first_row = asyncio.run(_inner())

    assert editor_text == "i"
    assert "customers: 2 columns inspected." in status
    assert columns == ("field", "value")
    assert first_row == ("source alias/table name", "customers")


def test_documented_keys_have_predictable_pane_behavior(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    reopened_sequence = state.begin_query_run("SELECT 99 AS reopened")
    state.record_query_success(
        reopened_sequence,
        "SELECT 99 AS reopened",
        QueryResult(columns=("reopened",), rows=((99,),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            sql = app.query_one("#sql", TextArea)
            sql.focus()
            await pilot.press("a")
            await pilot.pause()
            editor_after_a = sql.text

            app.query_one("#sources", DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            focused_after_source_enter = _focused_widget_id(app)
            editor_after_source_enter = app.query_one("#sql", TextArea).text

            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()
            status_before_history_i = app.query_one("#status", Static).content
            results_before_history_i = app.query_one("#results-message", Static).content
            await pilot.press("i")
            await pilot.pause()
            editor_after_history_i = app.query_one("#sql", TextArea).text
            focused_after_history_i = _focused_widget_id(app)
            status_after_history_i = app.query_one("#status", Static).content
            results_after_history_i = app.query_one("#results-message", Static).content

            await pilot.press("f2")
            await pilot.pause()
            focused_after_f2 = _focused_widget_id(app)

            await pilot.press("f6")
            await pilot.pause()
            focused_after_f6 = _focused_widget_id(app)

            return (
                editor_after_a,
                focused_after_source_enter,
                editor_after_source_enter,
                editor_after_history_i,
                focused_after_history_i,
                status_before_history_i,
                status_after_history_i,
                results_before_history_i,
                results_after_history_i,
                focused_after_f2,
                focused_after_f6,
            )

    (
        editor_after_a,
        focused_after_source_enter,
        editor_after_source_enter,
        editor_after_history_i,
        focused_after_history_i,
        status_before_history_i,
        status_after_history_i,
        results_before_history_i,
        results_after_history_i,
        focused_after_f2,
        focused_after_f6,
    ) = asyncio.run(_inner())

    assert editor_after_a == "a"
    assert focused_after_source_enter == "sources"
    assert editor_after_source_enter == "a"
    assert editor_after_history_i == "a"
    assert focused_after_history_i == "history"
    assert status_after_history_i == status_before_history_i
    assert results_after_history_i == results_before_history_i
    assert focused_after_f2 == "sql"
    assert focused_after_f6 == "sources"


def test_no_result_outcome_clears_last_result_and_disables_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.no_result(sequence=sequence, sql=sql, elapsed_ms=4.0)

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[object | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("CREATE TABLE scratch(id INTEGER)")
            await pilot.press("f4")
            await pilot.pause(0.2)
            status = app.query_one("#status", Static).content
            message = app.query_one("#results-message", Static).content
            return app.state.last_result, status, message

    last_result, status, message = asyncio.run(_inner())

    assert last_result is None
    assert "no tabular result" in status
    assert "no tabular result" in message
    assert app_history_statuses(state) == ["no_result"]
    assert app_history_run_modes(state) == ["current"]


def test_error_outcome_records_run_mode_and_marks_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.error(
            sequence=sequence,
            sql=sql,
            error_message="boom",
            suggestion="Try again.",
        )

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "boom" in status
    assert "boom" in message
    assert app_history_statuses(state) == ["error"]
    assert app_history_run_modes(state) == ["current"]


def test_unexpected_worker_failure_records_error_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    original_run_query_for_tui = __import__(
        "csvql.tui_app", fromlist=["run_query_for_tui"]
    ).run_query_for_tui
    calls = {"count": 0}

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return original_run_query_for_tui(sources, sql, sequence=sequence)

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[bool, str, str, str, object | None, list[str], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.2)

            first_status = app.query_one("#status", Static).content
            first_message = app.query_one("#results-message", Static).content
            run_status = app.query_one("#run-status", Static).content

            sql.load_text("SELECT COUNT(*) AS row_count FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            second_status = app.query_one("#status", Static).content
            return (
                app.state.query_run.is_running,
                first_status,
                first_message,
                run_status,
                app.state.last_result,
                app_history_statuses(app.state),
                second_status,
            )

    (
        is_running,
        first_status,
        first_message,
        run_status,
        last_result,
        history_statuses,
        second_status,
    ) = asyncio.run(_inner())

    assert is_running is False
    assert "Unexpected worker failure" in first_status
    assert "Unexpected worker failure" in first_message
    assert run_status == "Ready."
    assert last_result is not None
    assert history_statuses == ["error", "success"]
    assert app_history_run_modes(state) == ["current", "current"]
    assert "1 returned row(s)" in second_status


def test_sample_after_query_clears_exportable_result_and_export_refuses(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, tuple[str, ...], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            app.query_one("#sources", DataTable).focus()
            await pilot.press("s")
            await _settled_operation_idle(pilot, app)

            await pilot.press("f7")
            await pilot.pause()

            return (
                app.state.last_result,
                app.state.result_view.columns,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
            )

    last_result, result_view_columns, status, message, run_status = asyncio.run(_inner())

    assert last_result is None
    assert result_view_columns == ()
    assert "Run a query before exporting." in status
    assert "Run a query before exporting." in message
    assert run_status == "Ready."


def test_second_run_while_worker_active_shows_already_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    worker_started = threading.Event()
    release_worker = threading.Event()

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        worker_started.set()
        assert release_worker.wait(timeout=1.0)
        return QueryResult(
            columns=("customer_id",),
            rows=(("CUST-001",),),
            elapsed_ms=5.0,
        )

    def fake_run_query_for_tui_outcome(sources: object, sql: str, *, sequence: int):
        result = fake_run_query_for_tui(sources, sql, sequence=sequence)
        from csvql.tui_state import TUIQueryOutcome

        return TUIQueryOutcome.success(sequence=sequence, sql=sql, result=result)

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui_outcome)

    async def _inner() -> tuple[str, str, bool, int | None, str, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.05)
            assert worker_started.is_set()

            await pilot.press("f4")
            await pilot.pause(0.05)

            status = app.query_one("#status", Static).content
            run_status = app.query_one("#run-status", Static).content
            is_running = app.state.query_run.is_running
            sequence = app.state.query_run.sequence

            release_worker.set()
            await pilot.pause(0.2)

            final_status = app.query_one("#status", Static).content
            return (
                status,
                run_status,
                is_running,
                sequence,
                final_status,
                app_history_statuses(app.state),
            )

    status, run_status, is_running, sequence, final_status, history_statuses = asyncio.run(_inner())

    assert status == "Query already running."
    assert run_status == "Running current SQL as query 1..."
    assert is_running is True
    assert sequence == 1
    assert "1 returned row(s)" in final_status
    assert history_statuses == ["success"]


def test_already_running_rejection_preserves_previous_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    worker_started = threading.Event()
    release_worker = threading.Event()
    calls = {"count": 0}

    def fake_run_query_for_tui(sources: object, sql: str, *, sequence: int):
        del sources
        from csvql.tui_state import TUIQueryOutcome

        calls["count"] += 1
        if calls["count"] == 1:
            return TUIQueryOutcome.success(
                sequence=sequence,
                sql=sql,
                result=QueryResult(
                    columns=("email",),
                    rows=(("alex@example.com",),),
                    elapsed_ms=1.0,
                ),
            )

        worker_started.set()
        assert release_worker.wait(timeout=1.0)
        return TUIQueryOutcome.success(
            sequence=sequence,
            sql=sql,
            result=QueryResult(
                columns=("customer_id",),
                rows=(("CUST-001",),),
                elapsed_ms=5.0,
            ),
        )

    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", fake_run_query_for_tui)

    async def _inner() -> tuple[
        bool,
        bool,
        tuple[str, ...],
        int,
        str,
        str,
        str,
        bool,
        int | None,
        list[str],
        list[str],
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT email FROM customers LIMIT 1")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.last_result
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("SELECT customer_id FROM customers LIMIT 1")
            await pilot.press("f4")
            await pilot.pause(0.05)
            assert worker_started.is_set()

            await pilot.press("f4")
            await pilot.pause(0.05)

            columns, row_count, message = _result_grid_snapshot(app)
            status = app.query_one("#status", Static).content
            run_status = app.query_one("#run-status", Static).content
            is_running = app.state.query_run.is_running
            sequence = app.state.query_run.sequence
            history_before_release = app_history_statuses(app.state)
            result_preserved = app.state.last_result == previous_result
            view_preserved = app.state.result_view == previous_view

            release_worker.set()
            await pilot.pause(0.2)

            return (
                result_preserved,
                view_preserved,
                columns,
                row_count,
                message,
                status,
                run_status,
                is_running,
                sequence,
                history_before_release,
                app_history_statuses(app.state),
            )

    (
        result_preserved,
        view_preserved,
        columns,
        row_count,
        message,
        status,
        run_status,
        is_running,
        sequence,
        history_before_release,
        final_history_statuses,
    ) = asyncio.run(_inner())

    assert result_preserved is True
    assert view_preserved is True
    assert columns == ("email",)
    assert row_count == 1
    assert "Query already running." in status
    assert "Previous result is still available." in status
    assert "Previous result is still available." in message
    assert run_status == "Running current SQL as query 2..."
    assert is_running is True
    assert sequence == 2
    assert history_before_release == ["success"]
    assert final_history_statuses == ["success", "success"]


def test_successful_query_populates_results_datatable(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers ORDER BY customer_id")
            await pilot.press("f4")
            await pilot.pause(0.2)
            results = app.query_one("#results", DataTable)
            status = app.query_one("#status", Static).content
            return (
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
                status,
            )

    columns, row_count, status = asyncio.run(_inner())

    assert columns == ("customer_id", "email")
    assert row_count == 2
    assert "2 returned row(s)" in status


def test_stale_worker_outcome_is_ignored(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    stale_result = QueryResult(columns=("value",), rows=(("stale",),), elapsed_ms=1.0)

    async def _inner() -> tuple[object | None, tuple[object, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            active_sequence = app.state.begin_query_run("SELECT 'newer'")
            stale_sequence = active_sequence - 1
            from csvql.tui_state import TUIQueryOutcome

            app._handle_query_outcome(
                TUIQueryOutcome.success(
                    sequence=stale_sequence,
                    sql="SELECT 'stale'",
                    result=stale_result,
                )
            )
            return app.state.last_result, app.state.query_history

    last_result, history = asyncio.run(_inner())

    assert last_result is None
    assert history == ()


def test_history_enter_reopens_query_in_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 1")
    state.record_query_success(
        first_sequence,
        "SELECT 1",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
    )
    second_sequence = state.begin_query_run("SELECT * FROM customers")
    state.record_query_success(
        second_sequence,
        "SELECT * FROM customers",
        QueryResult(columns=("customer_id",), rows=(("CUST-001",),), elapsed_ms=1.0),
    )

    async def _inner() -> tuple[str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=1)
            await pilot.press("enter")
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            return sql.text, app.focused

    sql_text, focused = asyncio.run(_inner())

    assert sql_text == "SELECT * FROM customers"
    assert isinstance(focused, TextArea)


def test_history_rerun_uses_current_session_sources(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.begin_query_run("SELECT 1")
    state.record_query_success(
        first_sequence,
        "SELECT 1",
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
    )
    second_sequence = state.begin_query_run("SELECT COUNT(*) AS count FROM customers")
    state.record_query_success(
        second_sequence,
        "SELECT COUNT(*) AS count FROM customers",
        QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
    )
    state.remove_source("customers")
    replacement_path = _create_csv(
        tmp_path,
        "orders.csv",
        "order_id,total\nORD-001,10\n",
    )
    state.add_source(TUISource(name="orders", path=replacement_path, origin="session"))

    async def _inner() -> tuple[str, str, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=1)
            await pilot.press("r")
            await pilot.pause(0.2)
            sql = app.query_one("#sql", TextArea).text
            return (
                sql,
                app.query_one("#status", Static).content,
                app_history_statuses(app.state),
            )

    sql, status, history_statuses = asyncio.run(_inner())

    assert sql == "SELECT COUNT(*) AS count FROM customers"
    assert "customers" in status
    assert history_statuses == ["success", "success", "error"]


def test_source_columns_loads_grid_and_disables_export(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    async def _inner() -> tuple[
        object | None,
        str,
        tuple[str, ...],
        tuple[str, str],
        str,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
            column_status = app.query_one("#status", Static).content
            columns_table = app.query_one("#results", DataTable)
            column_headers = tuple(str(column.label) for column in columns_table.columns.values())
            first_column = (
                str(columns_table.get_cell_at(Coordinate(0, 0))),
                str(columns_table.get_cell_at(Coordinate(0, 1))),
            )

            await pilot.press("f7")
            await pilot.pause()

            return (
                app.state.last_result,
                column_status,
                column_headers,
                first_column,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    (
        last_result,
        column_status,
        column_headers,
        first_column,
        export_status,
        export_message,
    ) = asyncio.run(_inner())

    assert last_result is None
    assert "customers: 2 columns loaded." in column_status
    assert column_headers == ("column", "type")
    assert first_column == ("customer_id", "VARCHAR")
    assert "Run a query before exporting." in export_status
    assert "Run a query before exporting." in export_message


def test_source_intelligence_printable_keys_only_work_when_sources_focused(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.press("l")
            await pilot.press("x")
            await pilot.pause()
            editor_text = app.query_one("#sql", TextArea).text

            app.query_one("#sources", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
            columns_table = app.query_one("#results", DataTable)
            column_headers = tuple(str(column.label) for column in columns_table.columns.values())
            return editor_text, column_headers

    editor_text, column_headers = asyncio.run(_inner())

    assert editor_text == "clx"
    assert column_headers == ("column", "type")


def test_insert_source_alias_appends_rendered_alias_and_preserves_result(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    existing_result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    state.set_last_result(existing_result)

    async def _inner() -> tuple[str, object | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM")
            app.query_one("#sources", DataTable).focus()
            await pilot.press("l")
            await pilot.pause()
            return sql.text, app.state.last_result, app.query_one("#status", Static).content

    editor_text, last_result, status = asyncio.run(_inner())

    assert editor_text == 'SELECT * FROM\n"customers"'
    assert last_result == existing_result
    assert status == "Inserted alias customers into SQL editor."


def test_insert_starter_select_appends_rendered_select_and_preserves_result(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    existing_result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    state.set_last_result(existing_result)

    async def _inner() -> tuple[str, object | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return (
                app.query_one("#sql", TextArea).text,
                app.state.last_result,
                app.query_one("#status", Static).content,
            )

    editor_text, last_result, status = asyncio.run(_inner())

    assert editor_text == 'SELECT *\nFROM "customers"\nLIMIT 10;'
    assert last_result == existing_result
    assert status == "Inserted template: Preview rows."


def test_inspect_source_is_distinct_from_columns_and_loads_completion_metadata(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], tuple[str, ...], tuple[TUISourceColumn, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause()

            table = app.query_one("#results", DataTable)
            headers = tuple(str(column.label) for column in table.columns.values())
            values = tuple(
                str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count)
            )
            return (
                headers,
                values,
                app.state.source_columns("customers"),
                app.query_one("#status", Static).content,
            )

    headers, values, cached_columns, status = asyncio.run(_inner())

    assert headers == ("field", "value")
    assert "source alias/table name" in values
    assert "column count" in values
    assert cached_columns == (
        TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
        TUISourceColumn(name="email", duckdb_type="VARCHAR"),
    )
    assert "customers: 2 columns inspected." in status


def test_inspect_source_shows_display_path_distinct_from_alias(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders_data.csv"
    csv_path.write_text("order_id,total\nORD-1,10\n", encoding="utf-8")
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=csv_path, origin="argument"))

    async def _inner() -> dict[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause()

            table = app.query_one("#results", DataTable)
            return {
                str(table.get_cell_at(Coordinate(row, 0))): str(
                    table.get_cell_at(Coordinate(row, 1))
                )
                for row in range(table.row_count)
            }

    rows = asyncio.run(_inner())

    assert rows["source alias/table name"] == "orders"
    assert rows["display path"] == "orders_data.csv"


def test_starter_picker_offers_metadata_free_templates_without_loading_columns(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("x")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("enter")
            await pilot.pause()
            return screen_name, app.query_one("#sql", TextArea).text

    screen_name, editor_text = asyncio.run(_inner())

    assert screen_name == "_SQLAssistPickerScreen"
    assert editor_text == 'SELECT *\nFROM "customers"\nLIMIT 10;'


def test_starter_picker_adds_column_templates_after_columns_are_loaded(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            table = app.screen.query_one("#sql-assist-options", DataTable)
            labels = tuple(
                str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count)
            )
            return labels, app.query_one("#status", Static).content

    labels, status = asyncio.run(_inner())

    assert "Preview rows" in labels
    assert "Row count" in labels
    assert "Group by category" in labels
    assert "Press c or i for column-aware templates" not in status


def test_sql_completion_single_source_replaces_token_with_bare_column(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (
            TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
            TUISourceColumn(name="email", duckdb_type="VARCHAR"),
        ),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT cust")
            sql.move_cursor((0, len("SELECT cust")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return sql.text

    assert asyncio.run(_inner()) == "SELECT customer_id"


def test_sql_completion_multi_source_uses_source_qualified_column(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    orders_csv = tmp_path / "orders.csv"
    orders_csv.write_text("customer_id,total\nCUST-001,10\n", encoding="utf-8")
    state.add_source(TUISource(name="orders", path=orders_csv, origin="argument"))
    state.set_source_columns(
        "customers", (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),)
    )
    state.set_source_columns(
        "orders", (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),)
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT ")
            sql.move_cursor((0, len("SELECT ")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return sql.text

    assert asyncio.run(_inner()).startswith('SELECT "customers"."customer_id"')


def test_sql_completion_unknown_range_alias_prefix_has_no_column_items(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers", (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),)
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT rm.")
            sql.move_cursor((0, len("SELECT rm.")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            return type(app.screen).__name__, app.query_one("#status", Static).content

    screen_name, status = asyncio.run(_inner())

    assert screen_name == "Screen"
    assert "No completion items" in status


def test_sql_completion_tab_single_source_replaces_token_with_bare_column(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (
            TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
            TUISourceColumn(name="email", duckdb_type="VARCHAR"),
        ),
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT cust")
            sql.move_cursor((0, len("SELECT cust")))
            await pilot.press("tab")
            await pilot.pause()
            screen_name = type(app.screen).__name__
            await pilot.press("enter")
            await pilot.pause()
            return screen_name, sql.text

    screen_name, editor_text = asyncio.run(_inner())

    assert screen_name == "_SQLAssistPickerScreen"
    assert editor_text == "SELECT customer_id"


def test_sql_completion_tab_inserts_spaces_and_keeps_focus_when_no_items(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT rm.")
            sql.move_cursor((0, len("SELECT rm.")))
            await pilot.press("tab")
            await pilot.pause()
            return sql.text, _focused_widget_id(app), type(app.screen).__name__

    editor_text, focused_widget, screen_name = asyncio.run(_inner())

    assert editor_text == "SELECT rm.    "
    assert focused_widget == "sql"
    assert screen_name == "Screen"


def test_sql_completion_tab_unknown_qualifier_indents_instead_of_guessing(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT rm.")
            sql.move_cursor((0, len("SELECT rm.")))
            await pilot.press("tab")
            await pilot.pause()
            return sql.text, app.query_one("#status", Static).content, type(app.screen).__name__

    editor_text, status, screen_name = asyncio.run(_inner())

    assert editor_text == "SELECT rm.    "
    assert "No completion items" not in status
    assert screen_name == "Screen"


def test_sql_completion_ctrl_space_still_opens_picker_after_tab_follow_up(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT rm.")
            sql.move_cursor((0, len("SELECT rm.")))
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("ctrl+space")
            await pilot.pause()
            return type(app.screen).__name__

    assert asyncio.run(_inner()) == "_SQLAssistPickerScreen"


def test_starter_picker_does_not_call_inspect_or_query_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    def _unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("unexpected hidden work")

    monkeypatch.setattr("csvql.tui_app.inspect_source", _unexpected)
    monkeypatch.setattr("csvql.tui_app.inspect_source_columns", _unexpected)
    monkeypatch.setattr("csvql.tui_app.sample_source", _unexpected)
    monkeypatch.setattr("csvql.tui_app.profile_source", _unexpected)
    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", _unexpected)
    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", _unexpected)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("x")
            await pilot.pause()
            return type(app.screen).__name__

    assert asyncio.run(_inner()) == "_SQLAssistPickerScreen"


def test_sql_completion_does_not_call_inspect_or_query_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    def _unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("unexpected hidden work")

    monkeypatch.setattr("csvql.tui_app.inspect_source", _unexpected)
    monkeypatch.setattr("csvql.tui_app.inspect_source_columns", _unexpected)
    monkeypatch.setattr("csvql.tui_app.sample_source", _unexpected)
    monkeypatch.setattr("csvql.tui_app.profile_source", _unexpected)
    monkeypatch.setattr("csvql.tui_app.run_query_for_tui", _unexpected)
    monkeypatch.setattr("csvql.tui_app.run_buffer_for_tui", _unexpected)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT cust")
            sql.move_cursor((0, len("SELECT cust")))
            await pilot.press("ctrl+space")
            await pilot.pause()
            return type(app.screen).__name__

    assert asyncio.run(_inner()) == "_SQLAssistPickerScreen"


def test_remove_source_is_blocked_while_inspect_operation_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_inspect_source(source: TUISource) -> object:
        started.set()
        assert release.wait(timeout=2)
        from csvql.tui_workflows import inspect_source as real_inspect_source

        return real_inspect_source(source)

    monkeypatch.setattr("csvql.tui_app.inspect_source", slow_inspect_source)

    async def _inner() -> tuple[int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.1)
            await pilot.press("d")
            await pilot.press("y")
            await pilot.pause(0.1)
            release.set()
            await pilot.pause(0.2)
            return app.query_one("#sources", DataTable).row_count, app.query_one(
                "#status", Static
            ).content

    row_count, status = asyncio.run(_inner())

    assert started.is_set()
    assert row_count == 1
    assert "customers: 2 columns inspected." in status


def test_source_insert_error_clears_exportable_result_when_no_source_selected(
    tmp_path: Path,
) -> None:
    state = TUISessionState()
    state.set_last_result(QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0))

    async def _inner() -> tuple[object | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("l")
            await pilot.pause()
            return (
                app.state.last_result,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    last_result, status, message = asyncio.run(_inner())

    assert last_result is None
    assert "No source selected." in status
    assert "No source selected." in message
