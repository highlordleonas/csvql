import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Static, TextArea

from csvql.models import QueryResult
from csvql.tui_app import CSVQLMenuApp
from csvql.tui_state import TUISessionState, TUISource


def _make_source_state(tmp_path: Path, *, alias: str = "customers") -> TUISessionState:
    csv_path = tmp_path / f"{alias}.csv"
    csv_path.write_text(
        "customer_id,email\nCUST-001,alex@example.com\nCUST-002,bob@example.com\n",
        encoding="utf-8",
    )
    state = TUISessionState()
    state.add_source(TUISource(name=alias, path=csv_path, origin="argument"))
    return state


def _create_csv(tmp_path: Path, filename: str, content: str) -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_app_starts_empty() -> None:
    async def _inner() -> tuple[int, str]:
        app = CSVQLMenuApp(start_dir=Path.cwd())
        async with app.run_test() as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            return sources.row_count, status

    row_count, status = asyncio.run(_inner())

    assert row_count == 0
    assert "No sources loaded." in status


def test_app_runs_query_and_updates_status_and_results(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            app.action_run_query()
            await pilot.pause()
            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "2 row(s) returned." in status
    assert "customer_id" in results
    assert "alex@example.com" in results


def test_app_clears_stale_result_on_failed_query(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[object | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            app.action_run_query()
            await pilot.pause()

            assert app.state.last_result is not None

            sql.load_text("SELECT * FROM missing_table")
            app.action_run_query()
            await pilot.pause()

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
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


def test_function_key_runs_query_from_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "2 row(s) returned." in status
    assert "alex@example.com" in results


def test_ctrl_enter_runs_query_from_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("ctrl+enter")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "2 row(s) returned." in status
    assert "alex@example.com" in results


def test_query_run_returns_focus_to_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> object | None:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("ctrl+enter")
            await pilot.pause()

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

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")
            await pilot.press("ctrl+enter")
            await pilot.pause()

            await pilot.press("ctrl+n")
            await pilot.pause()

            sql.load_text("SELECT COUNT(*) AS row_count FROM customers")
            await pilot.press("ctrl+enter")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "1 row(s) returned." in status
    assert "row_count" in results
    assert "2" in results


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
            await pilot.press("f5")
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


def test_export_action_requires_last_result(tmp_path: Path) -> None:
    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "Run a query before exporting." in status
    assert "Run a query before exporting." in results


def test_remove_selected_source_updates_state_and_table(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[int, tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static).content
            return sources.row_count, app.state.sources, status

    row_count, sources, status = asyncio.run(_inner())

    assert row_count == 0
    assert sources == ()
    assert "No sources loaded." in status


def test_inspect_sample_and_profile_selected_source_update_output(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f1")
            await pilot.pause()
            inspect_status = app.query_one("#status", Static).content
            inspect_results = app.query_one("#results", Static).content

            await pilot.press("f2")
            await pilot.pause()
            sample_status = app.query_one("#status", Static).content
            sample_results = app.query_one("#results", Static).content

            await pilot.press("f3")
            await pilot.pause()
            profile_status = app.query_one("#status", Static).content
            profile_results = app.query_one("#results", Static).content

            return (
                inspect_status,
                inspect_results,
                sample_status,
                sample_results,
                profile_status,
                profile_results,
            )

    (
        inspect_status,
        inspect_results,
        sample_status,
        sample_results,
        profile_status,
        profile_results,
    ) = asyncio.run(_inner())

    assert "customers: 2 columns." in inspect_status
    assert "customer_id, email" in inspect_results
    assert "customers: 2 sample row(s)." in sample_status
    assert "alex@example.com" in sample_results
    assert "customers: 2 rows, 2 columns, 0 duplicate rows." in profile_status
    assert "Rows: 2" in profile_results
    assert "Columns: 2" in profile_results
    assert "Duplicate rows: 0" in profile_results


def test_export_last_result_writes_file_when_result_exists(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    export_path = export_dir / "customers.csv"

    state = TUISessionState()
    state.set_last_result(
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
    )

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()

            export_input = app.screen.query_one("#export-path", Input)
            export_input.value = str(export_path)
            await pilot.press("enter")
            await pilot.pause()

            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            content = export_path.read_text(encoding="utf-8")
            return status, results, content

    status, results, content = asyncio.run(_inner())

    assert export_path.exists()
    assert content.startswith("customer_id,email")
    assert "Exported to" in status
    assert "Exported to" in results


def test_save_sources_creates_catalog_only_when_invoked(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[bool, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            before = config_path.exists()
            await pilot.press("f8")
            await pilot.pause()
            after = config_path.exists()
            status = app.query_one("#status", Static).content
            return before, after, status

    before, after, status = asyncio.run(_inner())

    assert before is False
    assert after is True
    assert "Saved sources to" in status


def test_save_sources_surfaces_project_config_errors(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: [", encoding="utf-8")

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f8")
            await pilot.pause()
            status = app.query_one("#status", Static).content
            results = app.query_one("#results", Static).content
            return status, results

    status, results = asyncio.run(_inner())

    assert "Error:" in status
    assert "Error:" in results
