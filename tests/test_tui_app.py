import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Static, TextArea

from csvql.tui_app import CSVQLMenuApp
from csvql.tui_state import TUISessionState, TUISource


def _run_app(app: CSVQLMenuApp) -> tuple[DataTable, Static, Static, TextArea]:
    async def _inner() -> tuple[DataTable, Static, Static, TextArea]:
        async with app.run_test() as pilot:
            await pilot.pause()
            sources = app.query_one("#sources", DataTable)
            status = app.query_one("#status", Static)
            results = app.query_one("#results", Static)
            sql = app.query_one("#sql", TextArea)
            return sources, status, results, sql

    return asyncio.run(_inner())


def test_app_renders_loaded_sources(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,email\nCUST-001,alex@example.com\n", encoding="utf-8")
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=csv_path, origin="argument"))

    sources, status, _, _ = _run_app(
        CSVQLMenuApp(initial_state=state, start_dir=tmp_path),
    )

    assert sources.row_count == 1
    assert "1 source loaded." in status.content


def test_app_starts_empty() -> None:
    sources, status, _, _ = _run_app(CSVQLMenuApp(start_dir=Path.cwd()))

    assert sources.row_count == 0
    assert "No sources loaded." in status.content


def test_app_runs_query_and_updates_status_and_results(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,email\nCUST-001,alex@example.com\n", encoding="utf-8")
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=csv_path, origin="argument"))

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

    assert "1 row(s) returned." in status
    assert "customer_id" in results
    assert "alex@example.com" in results


def test_app_clears_stale_result_on_failed_query(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,email\nCUST-001,alex@example.com\n", encoding="utf-8")
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=csv_path, origin="argument"))

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
