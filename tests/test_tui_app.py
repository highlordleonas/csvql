import asyncio
import threading
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Static, TextArea

from csvql.models import QueryResult
from csvql.tui_app import CSVQLMenuApp
from csvql.tui_state import TUISessionState, TUISource


def app_history_statuses(state: TUISessionState) -> list[str]:
    return [item.status for item in state.query_history]


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

            for key in ["?", "q", "i", "s", "p", "a", "d", "w", "r"]:
                await pilot.press(key)
            await pilot.pause()

            status = app.query_one("#status", Static).content
            return sql.text, config_path.exists(), status

    sql_text, config_exists, status = asyncio.run(_inner())

    assert sql_text == "?qispadwr"
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


def test_ctrl_enter_runs_query_from_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT * FROM customers")

            await pilot.press("ctrl+enter")
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

            app.action_run_query()
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
            await pilot.press("ctrl+enter")
            await pilot.pause(0.2)

            await pilot.press("ctrl+n")
            await pilot.pause()

            sql.load_text("SELECT COUNT(*) AS row_count FROM customers")
            await pilot.press("ctrl+enter")
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

    async def _inner() -> tuple[type[object], type[object], type[object], type[object]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            sources_focus = type(app.focused)
            await pilot.press("f8")
            await pilot.pause()
            history_focus = type(app.focused)
            await pilot.press("f5")
            await pilot.pause()
            results_focus = type(app.focused)
            await pilot.press("f2")
            await pilot.pause()
            sql_focus = type(app.focused)
            return sources_focus, history_focus, results_focus, sql_focus

    sources_focus, history_focus, results_focus, sql_focus = asyncio.run(_inner())

    assert sources_focus is DataTable
    assert history_focus is DataTable
    assert results_focus is DataTable
    assert sql_focus is TextArea


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

    async def _inner() -> tuple[int, tuple[TUISource, ...], str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("d")
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

    async def _inner() -> tuple[str, str, str, tuple[str, ...], int, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()

            await pilot.press("i")
            await pilot.pause()
            inspect_status = app.query_one("#status", Static).content
            inspect_results = app.query_one("#results-message", Static).content

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
            profile_results = app.query_one("#results-message", Static).content

            return (
                inspect_status,
                inspect_results,
                sample_status,
                sample_columns,
                sample_row_count,
                sample_message,
                profile_status,
                profile_results,
            )

    (
        inspect_status,
        inspect_results,
        sample_status,
        sample_columns,
        sample_row_count,
        sample_message,
        profile_status,
        profile_results,
    ) = asyncio.run(_inner())

    assert "customers: 2 columns." in inspect_status
    assert "customer_id, email" in inspect_results
    assert "customers: 2 sample row(s)." in sample_status
    assert sample_columns == ("customer_id", "email")
    assert sample_row_count == 2
    assert "Showing 2 returned row(s)." in sample_message
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
            results = app.query_one("#results-message", Static).content
            content = export_path.read_text(encoding="utf-8")
            return status, results, content

    status, results, content = asyncio.run(_inner())

    assert export_path.exists()
    assert content.startswith("customer_id,email")
    assert "Exported to" in status
    assert "Exported to" in results


def test_sources_pane_shows_source_kind(tmp_path: Path) -> None:
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

    async def _inner() -> tuple[tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            return (
                tuple(str(column.label) for column in sources.columns.values()),
                sources.row_count,
            )

    columns, row_count = asyncio.run(_inner())

    assert columns == ("alias", "kind", "path", "origin")
    assert row_count == 2


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
            await pilot.pause()

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
    assert "Use Save sources to persist the alias in .csvql.yml." in status
    assert "Use Save sources to persist the alias in .csvql.yml." in message
    assert content == "customer_id,email\nCUST-001,alex@example.com\n"


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
            await pilot.pause()

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
            await pilot.pause()

            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "Source alias 'customers' is already loaded" in status
    assert "Source alias 'customers' is already loaded" in message
    assert not (tmp_path / ".csvql" / "results").exists()


def test_save_sources_creates_catalog_only_when_invoked(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    config_path = tmp_path / ".csvql.yml"

    async def _inner() -> tuple[bool, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            before = config_path.exists()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
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
            app.query_one("#sources", DataTable).focus()
            await pilot.press("w")
            await pilot.pause()
            status = app.query_one("#status", Static).content
            results = app.query_one("#results-message", Static).content
            return status, results

    status, results = asyncio.run(_inner())

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

    help_text, focused = asyncio.run(_inner())

    assert "Run Editor" in help_text
    assert "F4" in help_text
    assert isinstance(focused, TextArea)


def test_help_text_documents_workbench_keymap(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            return app.screen.query_one("#help-text", Static).content

    help_text = asyncio.run(_inner())

    assert "Run Editor" in help_text
    assert "F4 / Ctrl+Enter" in help_text
    assert "F6 / Ctrl+Up" in help_text
    assert "Ctrl+S              Save last tabular result as a derived source" in help_text
    assert "Alt+S / F11         Alternate save-result shortcuts" in help_text
    assert "F11" in help_text
    assert "Save last tabular result as a derived source" in help_text
    assert "History pane" in help_text


def test_question_mark_help_only_outside_sql_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            editor_text = app.query_one("#sql", TextArea).text

            app.query_one("#sources", DataTable).focus()
            await pilot.press("?")
            await pilot.pause()
            help_text = app.screen.query_one("#help-text", Static).content
            return editor_text, help_text

    editor_text, help_text = asyncio.run(_inner())

    assert editor_text == "?"
    assert "Run Editor" in help_text


def test_source_letter_actions_only_work_when_sources_focused(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str]:
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
            message = app.query_one("#results-message", Static).content
            return editor_text, status, message

    editor_text, status, message = asyncio.run(_inner())

    assert editor_text == "i"
    assert "customers: 2 columns." in status
    assert "customer_id, email" in message


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
            await pilot.pause()

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
    assert run_status == "Running editor query 1..."
    assert is_running is True
    assert sequence == 1
    assert "1 returned row(s)" in final_status
    assert history_statuses == ["success"]


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
