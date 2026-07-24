import asyncio
import os
import shutil
import threading
from pathlib import Path
from types import MethodType
from unittest.mock import Mock

import pytest
from rich.text import Text

pytest.importorskip("textual")

from textual import events
from textual.coordinate import Coordinate
from textual.geometry import Size
from textual.pilot import Pilot
from textual.widgets import DataTable, Input, Static, TextArea
from textual.widgets._footer import FooterKey

from csvql import tui_app as tui_app_module
from csvql.atomic_write import OperationToken
from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.csv_adapter import CSVSourceAdapter
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, SourceError, TableMappingError
from csvql.export import ExportFormat
from csvql.models import QueryResult
from csvql.operation import OperationCancelled, OperationContext
from csvql.result_codec import encode_row_payload
from csvql.source import SourceCapabilityStatus
from csvql.tui_app import CSVQLMenuApp
from csvql.tui_help import WORKBENCH_HELP
from csvql.tui_query_runner import (
    TUICancelledBeforePreviewEvent,
    TUICompleteEvent,
    TUIFailedBeforePreviewEvent,
    TUINoResultEvent,
    TUIPreservationProgress,
    TUIPreservationProgressEvent,
    TUIPreviewOnlyEvent,
    TUIPreviewReadyEvent,
    TUIRunRequest,
)
from csvql.tui_result_store import (
    DEFAULT_TUI_RESULT_CAPACITY_BYTES,
    TUIResultCleanupSummary,
    TUIResultStorageError,
    TUIResultStore,
)
from csvql.tui_results import make_result_view_state
from csvql.tui_state import (
    TUIActiveResultState,
    TUIBufferResultTab,
    TUIQueryRunMode,
    TUIResultRecord,
    TUISessionState,
    TUISource,
    TUISourceColumn,
)
from csvql.tui_workflows import build_initial_state
from csvql.tui_workflows import (
    export_last_result as workflows_export_last_result,
)


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


def test_unavailable_source_action_reports_exact_capability_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    unavailable = SourceCapabilityStatus(
        operation="sample",
        state="unavailable",
        reason_code="missing_driver",
        remediation="Install the csv-driver extra.",
    )
    monkeypatch.setattr(
        tui_app_module,
        "source_capability_status",
        lambda source, operation: unavailable,
        raising=False,
    )

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(start_dir=tmp_path, initial_state=state)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            app.action_sample_source()
            await pilot.pause()
            return (
                app.query_one("#status", Static).content,
                app.state.operation_run.is_running,
            )

    status, is_running = asyncio.run(_inner())

    assert "missing_driver" in status
    assert "Install the csv-driver extra." in status
    assert is_running is False


@pytest.mark.parametrize(
    ("action_name", "operation"),
    [
        ("action_inspect_source", "inspect"),
        ("action_sample_source", "sample"),
        ("action_profile_source", "profile"),
        ("action_show_source_columns", "inspect"),
    ],
)
@pytest.mark.parametrize("capability_state", ["unavailable", "unsupported"])
def test_contextual_source_actions_reject_exact_capability_without_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
    operation: str,
    capability_state: str,
) -> None:
    state = _make_source_state(tmp_path)
    reason_code = f"{capability_state}_test_reason"
    remediation = f"Remediate {capability_state} {operation}."
    worker_calls: list[object] = []
    monkeypatch.setattr(
        tui_app_module,
        "source_capability_status",
        lambda source, requested_operation: SourceCapabilityStatus(
            operation=requested_operation,
            state=capability_state,
            reason_code=reason_code,
            remediation=remediation,
        ),
    )
    monkeypatch.setattr(
        CSVQLMenuApp,
        "_start_operation_worker",
        lambda self, **kwargs: worker_calls.append((self, kwargs)),
    )

    async def _inner() -> tuple[str, bool]:
        app = CSVQLMenuApp(start_dir=tmp_path, initial_state=state)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            getattr(app, action_name)()
            await pilot.pause()
            return (
                app.query_one("#status", Static).content,
                app.state.operation_run.is_running,
            )

    status, is_running = asyncio.run(_inner())

    assert f"'{operation}' is {capability_state} ({reason_code})" in status
    assert remediation in status
    assert worker_calls == []
    assert is_running is False


def _result_grid_snapshot(app: CSVQLMenuApp) -> tuple[tuple[str, ...], int, str]:
    results = app.query_one("#results", DataTable)
    return (
        tuple(str(column.label) for column in results.columns.values()),
        results.row_count,
        app.query_one("#results-message", Static).content,
    )


def _reject_query_execution(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise AssertionError("result export must not execute SQL")


def _record_stored_result(
    state: TUISessionState,
    result: QueryResult,
    *,
    sequence: int,
    sql: str,
    store: TUIResultStore | None = None,
    run_mode: TUIQueryRunMode = "current",
    buffer_result_index: int | None = None,
) -> TUIResultStore:
    result_store = store or TUIResultStore()
    handle = _store_complete_result(result_store, result, sequence=sequence).handle
    view = make_result_view_state(result, source_result_sequence=sequence)
    state.record_query_success(
        sequence,
        sql,
        handle=handle,
        result_view=view,
        elapsed_ms=result.elapsed_ms,
        run_mode=run_mode,
        buffer_result_index=buffer_result_index,
    )
    return result_store


def _active_stored_rows(app: CSVQLMenuApp) -> tuple[tuple[object, ...], ...]:
    record = app.state.active_query_result_record()
    assert record is not None
    assert record.handle is not None
    source = app._result_store.open_rows(record.handle)
    return tuple(source.iter_rows())


def _store_complete_result(
    result_store: TUIResultStore,
    result: QueryResult,
    *,
    sequence: int,
):
    writer = result_store.begin_complete(sequence=sequence, columns=result.columns)
    for row in result.rows:
        writer.append_payload(encode_row_payload(tuple(row)))
    return writer.commit(elapsed_ms=result.elapsed_ms)


def _store_preview_only_result(
    result_store: TUIResultStore,
    preview: BoundedQueryResult,
    *,
    sequence: int,
    reason: str = "preservation_failed",
):
    encoded_payloads = tuple(encode_row_payload(tuple(row)) for row in preview.rows)
    stored = result_store.persist_preview(
        sequence=sequence,
        preview=preview,
        reason=reason,
        elapsed_ms=preview.elapsed_ms,
        encoded_payloads=encoded_payloads,
    )
    assert stored is not None
    return stored


def _record_preview_only_result(
    state: TUISessionState,
    result_store: TUIResultStore,
    *,
    sequence: int,
    sql: str,
    preview: BoundedQueryResult,
    reason: str = "preservation_failed",
    run_mode: TUIQueryRunMode = "current",
    buffer_result_index: int | None = None,
) -> None:
    stored = _store_preview_only_result(
        result_store,
        preview,
        sequence=sequence,
        reason=reason,
    )
    state.record_query_result(
        sequence,
        sql,
        record=TUIResultRecord(
            handle=stored.handle,
            state="preview_only",
            reason=reason,
            columns=preview.columns,
            preview_row_count=len(preview.rows),
            full_row_count=None,
            elapsed_ms=preview.elapsed_ms,
        ),
        result_view=make_result_view_state(
            QueryResult(
                columns=preview.columns,
                rows=preview.rows,
                elapsed_ms=preview.elapsed_ms,
            ),
            source_result_sequence=sequence,
        ),
        run_mode=run_mode,
        buffer_result_index=buffer_result_index,
    )


def _patch_run_tui_request(
    monkeypatch: pytest.MonkeyPatch,
    callback,
) -> None:
    def fake_run_tui_request(
        request: TUIRunRequest,
        *,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
        **kwargs: object,
    ) -> None:
        del kwargs
        callback(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            operation=operation,
        )

    monkeypatch.setattr("csvql.tui_app.run_tui_request", fake_run_tui_request)


def _emit_complete_result(
    *,
    request: TUIRunRequest,
    result_store: TUIResultStore,
    event_sink,
    result: QueryResult,
    sequence: int | None = None,
) -> None:
    result_sequence = request.sequences[0] if sequence is None else sequence
    preview = BoundedQueryResult(
        columns=result.columns,
        rows=tuple(tuple(row) for row in result.rows),
        elapsed_ms=result.elapsed_ms,
        preview_payload_bytes=sum(len(encode_row_payload(tuple(row))) for row in result.rows),
        has_more_rows=False,
        truncation_reason=None,
    )
    event_sink(TUIPreviewReadyEvent(sequence=result_sequence, preview=preview))
    stored = _store_complete_result(result_store, result, sequence=result_sequence)
    event_sink(TUICompleteEvent(sequence=result_sequence, stored=stored))


def _emit_buffer_complete_results(
    *,
    request: TUIRunRequest,
    result_store: TUIResultStore,
    event_sink,
) -> None:
    for statement, sequence in zip(request.statements, request.sequences, strict=True):
        label = statement.split()[-1]
        result = QueryResult(columns=(label,), rows=((sequence,),), elapsed_ms=1.0)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=result,
            sequence=sequence,
        )


def _emit_failed_event(
    *,
    sequence: int,
    event_sink,
    error_message: str,
    suggestion: str | None = None,
) -> None:
    event_sink(
        TUIFailedBeforePreviewEvent(
            sequence=sequence,
            error_message=error_message,
            suggestion=suggestion,
        )
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


async def _settled_query_idle(pilot: Pilot[None], app: CSVQLMenuApp) -> None:
    for _ in range(1800):
        await pilot.pause(0.05)
        if app._run_editor_pending or app.state.query_run.is_running:
            continue
        await pilot.pause()
        if not app._run_editor_pending and not app.state.query_run.is_running:
            return
    pytest.fail("Timed out waiting for TUI query to finish.")


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


def test_direct_app_construction_does_not_recover_abandoned_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = Mock()
    monkeypatch.setattr(
        "csvql.tui_result_store.recover_abandoned_result_workspaces",
        recovery,
    )

    app = CSVQLMenuApp(start_dir=tmp_path)

    assert app.cleanup_summary == TUIResultCleanupSummary()
    recovery.assert_not_called()
    app.on_unmount()


def test_unmount_merges_recovery_and_store_cleanup_summaries_once(
    tmp_path: Path,
) -> None:
    recovery = TUIResultCleanupSummary(workspaces_failed=1)
    cleanup = TUIResultCleanupSummary(files_failed=2)
    store = Mock(spec=TUIResultStore)
    store.cleanup.return_value = cleanup
    app = CSVQLMenuApp(
        initial_state=TUISessionState(),
        start_dir=tmp_path,
        result_store=store,
        initial_cleanup_summary=recovery,
    )

    app.on_unmount()
    app.on_unmount()

    assert app.cleanup_summary.warning_count == 3
    store.cleanup.assert_called_once_with()


def test_tui_non_query_tables_statuses_and_errors_use_literal_control_safe_text() -> None:
    table_payload = "\x1b]0;spoof\x07[red]table[/red]\x85"
    message_payload = "\x1b]0;message\x07[red]message[/red]\x00"

    async def _inner() -> tuple[object, object, object, object, object]:
        app = CSVQLMenuApp(start_dir=Path.cwd())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._show_non_query_result_table(
                (table_payload,),
                ((table_payload,),),
                message=message_payload,
            )
            table = app.query_one("#results", DataTable)
            column = next(iter(table.columns.values())).label
            cell = table.get_cell_at(Coordinate(0, 0))
            message = app.query_one("#results-message", Static).render()

            app._show_error(CSVQLError(message_payload, suggestion=table_payload))
            status = app.query_one("#status", Static).render()
            error = app.query_one("#results-message", Static).render()
            return column, cell, message, status, error

    column, cell, message, status, error = asyncio.run(_inner())

    assert isinstance(column, Text)
    assert column.plain == r"\x1b]0;spoof\x07[red]table[/red]\x85"
    assert column.spans == []
    assert isinstance(cell, Text)
    assert cell.plain == r"\x1b]0;spoof\x07[red]table[/red]\x85"
    assert cell.spans == []
    assert message.plain == r"\x1b]0;message\x07[red]message[/red]\x00"
    assert message.spans == []
    assert (
        status.plain == "Error: "
        r"\x1b]0;message\x07[red]message[/red]\x00"
        "\nSuggestion: "
        r"\x1b]0;spoof\x07[red]table[/red]\x85"
    )
    assert status.spans == []
    assert error.plain == status.plain
    assert error.spans == []


def test_app_rejects_injected_store_with_explicit_capacity_bytes(tmp_path: Path) -> None:
    store = TUIResultStore(temp_root=tmp_path)

    with pytest.raises(ValueError, match="result_store_capacity_bytes cannot be overridden"):
        CSVQLMenuApp(
            start_dir=tmp_path,
            result_store=store,
            result_store_capacity_bytes=DEFAULT_TUI_RESULT_CAPACITY_BYTES,
        )


def test_query_events_marshal_via_call_from_thread_and_preview_keeps_editor_usable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    release = threading.Event()

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        preview = BoundedQueryResult(
            columns=("value",),
            rows=((1,), (2,)),
            elapsed_ms=1.0,
            preview_payload_bytes=sum(len(encode_row_payload((value,))) for value in (1, 2)),
            has_more_rows=True,
            truncation_reason="row_limit",
        )
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        event_sink(
            TUIPreservationProgressEvent(
                sequence=request.sequences[0],
                progress=TUIPreservationProgress(
                    sequence=request.sequences[0],
                    rows_written=2,
                    logical_bytes_written=42,
                    elapsed_ms=2.0,
                    remaining_capacity_bytes=1_000,
                ),
            )
        )
        assert release.wait(5.0)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((1,), (2,), (3,)), elapsed_ms=3.0),
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[str, str, str, int, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        call_from_thread_calls: list[str] = []
        original_call_from_thread = app.call_from_thread

        def recording_call_from_thread(self, callback, *args, **kwargs):
            call_from_thread_calls.append(getattr(callback, "__name__", repr(callback)))
            return original_call_from_thread(callback, *args, **kwargs)

        app.call_from_thread = MethodType(recording_call_from_thread, app)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(40):
                await pilot.pause(0.05)
                if app.query_one("#results", DataTable).row_count == 2:
                    break
            status_during = app.query_one("#status", Static).content
            message_during = app.query_one("#results-message", Static).content
            run_status_during = app.query_one("#run-status", Static).content
            focused_during = _focused_widget_id(app)
            assert app.state.query_run.is_running is True
            release.set()
            await _settled_query_idle(pilot, app)
            return (
                status_during,
                message_during,
                run_status_during,
                app.query_one("#results", DataTable).row_count,
                app.query_one("#results-message", Static).content,
                ",".join(call_from_thread_calls) + f"|focus={focused_during}",
            )

    (
        status_during,
        message_during,
        run_status_during,
        final_row_count,
        final_message,
        call_trace,
    ) = asyncio.run(_inner())

    assert "Preserving query 1:" in status_during
    assert "Full result preservation is still running." in message_during
    assert "remaining" in run_status_during
    assert "%" not in run_status_during
    assert "ETA" not in run_status_during
    assert final_row_count == 2
    assert "Showing 2 retained preview row(s)." in final_message
    assert "Full export/save" in final_message
    assert "_handle_query_event" in call_trace
    assert call_trace.endswith("|focus=sql")


@pytest.mark.parametrize(
    ("event_factory", "expected_status", "expected_history_status"),
    [
        (
            lambda sequence: TUINoResultEvent(sequence=sequence, elapsed_ms=1.0),
            "Statement completed; no tabular result to display.",
            "no_result",
        ),
        (
            lambda sequence: TUICancelledBeforePreviewEvent(sequence=sequence),
            "Query 1 was cancelled before a preview was retained.",
            "cancelled",
        ),
        (
            lambda sequence: TUIFailedBeforePreviewEvent(
                sequence=sequence,
                error_message="preview failed",
                suggestion="Retry.",
            ),
            "Error: preview failed\nSuggestion: Retry.",
            "error",
        ),
    ],
)
def test_terminal_runner_events_update_history_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_factory,
    expected_status: str,
    expected_history_status: str,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        event_sink(event_factory(request.sequences[0]))

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 1")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            return (
                app.query_one("#status", Static).content,
                app.state.query_history[-1].status,
            )

    status, history_status = asyncio.run(_inner())

    assert status == expected_status
    assert history_status == expected_history_status


def test_complete_event_preserves_recalled_history_result_and_records_background_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("prior",), rows=(("prior-row",),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT prior",
    )
    release = threading.Event()

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        preview = BoundedQueryResult(
            columns=("value",),
            rows=(("new-row",),),
            elapsed_ms=2.0,
            preview_payload_bytes=len(encode_row_payload(("new-row",))),
            has_more_rows=False,
            truncation_reason=None,
        )
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        assert release.wait(5.0)
        stored = _store_complete_result(
            result_store,
            QueryResult(columns=("value",), rows=(("new-row",),), elapsed_ms=3.0),
            sequence=request.sequences[0],
        )
        event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=stored))

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int | None, str, str, str | None, int | None, str, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT current")
            await pilot.press("f4")
            for _ in range(40):
                await pilot.pause(0.05)
                if (
                    app.state.active_query_result_record() is not None
                    and app.state.active_query_result_record().state == "preserving"
                ):
                    break
            app.query_one("#history", DataTable).focus()
            app._show_history_result_at_row(0)
            release.set()
            await _settled_query_idle(pilot, app)
            await pilot.pause()
            settled_status = app.query_one("#status", Static).content
            preserved_columns, preserved_row_count, recalled_message = _result_grid_snapshot(app)
            assert app.state.active_result.sequence == 1
            assert preserved_columns == ("prior",)
            assert preserved_row_count == 1

            completed_record = app.state.query_result_record(2)
            app._show_history_result_at_row(1)
            recalled_completed_message = app.query_one("#results-message", Static).content
            history_table = app.query_one("#history", DataTable)
            return (
                app.state.query_history[0].sequence,
                settled_status,
                recalled_message,
                None if completed_record is None else completed_record.state,
                None if completed_record is None else completed_record.preview_row_count,
                recalled_completed_message,
                history_table.cursor_row,
            )

    (
        first_history_sequence,
        status,
        recalled_message,
        completed_state,
        completed_preview_rows,
        recalled_completed_message,
        history_cursor_row,
    ) = asyncio.run(_inner())

    assert first_history_sequence == 1
    assert status == "Query 2 completed in the background: 1 row(s) preserved for later recall."
    assert "History query 1." in recalled_message
    assert completed_state == "complete"
    assert completed_preview_rows == 1
    assert "History query 2." in recalled_completed_message
    assert history_cursor_row == 0


def test_unexpected_worker_failure_after_history_recall_preserves_visible_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("prior",), rows=(("prior-row",),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT prior",
    )
    release = threading.Event()

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        preview = BoundedQueryResult(
            columns=("value",),
            rows=((2,),),
            elapsed_ms=1.0,
            preview_payload_bytes=len(encode_row_payload((2,))),
            has_more_rows=True,
            truncation_reason="row_limit",
        )
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        assert release.wait(5.0)
        raise RuntimeError("internal failure after preview")

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int | None, str, str, list[str], str | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT broken")
            await pilot.press("f4")
            for _ in range(40):
                await pilot.pause(0.05)
                if (
                    app.state.active_query_result_record() is not None
                    and app.state.active_query_result_record().state == "preserving"
                ):
                    break
            app.query_one("#history", DataTable).focus()
            app._show_history_result_at_row(0)
            release.set()
            await _settled_query_idle(pilot, app)
            await pilot.pause()
            failed_record = app.state.query_result_record(2)
            columns, row_count, recalled_message = _result_grid_snapshot(app)
            assert columns == ("prior",)
            assert row_count == 1
            return (
                app.state.active_result.sequence,
                app.query_one("#status", Static).content,
                recalled_message,
                app_history_statuses(app.state),
                None if failed_record is None else failed_record.state,
            )

    (
        active_sequence,
        status,
        recalled_message,
        history_statuses,
        failed_state,
    ) = asyncio.run(_inner())

    assert active_sequence == 1
    assert status == "Error: Unable to complete the query. Try running it again."
    assert "History query 1." in recalled_message
    assert history_statuses == ["success", "error"]
    assert failed_state is None


@pytest.mark.parametrize(
    ("event_factory", "expected_status", "expected_history_status"),
    [
        (
            lambda sequence: TUINoResultEvent(sequence=sequence, elapsed_ms=1.0),
            "Statement completed; no tabular result to display.",
            "no_result",
        ),
        (
            lambda sequence: TUICancelledBeforePreviewEvent(sequence=sequence),
            "Query 2 was cancelled before a preview was retained.",
            "cancelled",
        ),
        (
            lambda sequence: TUIFailedBeforePreviewEvent(
                sequence=sequence,
                error_message="preview failed",
                suggestion="Retry.",
            ),
            "Error: preview failed\nSuggestion: Retry.",
            "error",
        ),
    ],
)
def test_terminal_runner_events_preserve_recalled_history_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_factory,
    expected_status: str,
    expected_history_status: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("prior",), rows=(("prior-row",),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT prior",
    )
    release = threading.Event()

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        assert release.wait(5.0)
        event_sink(event_factory(request.sequences[0]))

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int | None, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT current")
            await pilot.press("f4")
            await pilot.pause(0.1)
            app.query_one("#history", DataTable).focus()
            app._show_history_result_at_row(0)
            release.set()
            await _settled_query_idle(pilot, app)
            await pilot.pause()
            columns, row_count, recalled_message = _result_grid_snapshot(app)
            assert columns == ("prior",)
            assert row_count == 1
            return (
                app.state.active_result.sequence,
                app.query_one("#status", Static).content,
                recalled_message,
                app.state.query_history[-1].status,
            )

    active_sequence, status, recalled_message, history_status = asyncio.run(_inner())

    assert active_sequence == 1
    assert status == expected_status
    assert "History query 1." in recalled_message
    assert history_status == expected_history_status


def test_buffer_completion_preserves_selected_prior_tab_while_later_result_finishes_in_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    release = threading.Event()

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("first",), rows=(("first-row",),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        preview = BoundedQueryResult(
            columns=("second",),
            rows=(("second-row",),),
            elapsed_ms=2.0,
            preview_payload_bytes=len(encode_row_payload(("second-row",))),
            has_more_rows=False,
            truncation_reason=None,
        )
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[1], preview=preview))
        assert release.wait(5.0)
        stored = _store_complete_result(
            result_store,
            QueryResult(columns=("second",), rows=(("second-row",),), elapsed_ms=3.0),
            sequence=request.sequences[1],
        )
        event_sink(TUICompleteEvent(sequence=request.sequences[1], stored=stored))

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        int | None,
        tuple[str, ...],
        int,
        str,
        str | None,
        int | None,
        str,
        tuple[str, ...],
        int,
        str,
        int | None,
        tuple[str, ...],
        int,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 1 AS first;\nSELECT 2 AS second;")
            await pilot.press("f12")
            for _ in range(60):
                await pilot.pause(0.05)
                if (
                    len(app.state.buffer_result_tabs) == 2
                    and app.state.active_query_result_record() is not None
                    and app.state.active_query_result_record().state == "preserving"
                ):
                    break
            app._show_buffer_result_at_tab(app.state.buffer_result_tabs[0])
            initial_columns, initial_row_count, initial_message = _result_grid_snapshot(app)
            release.set()
            await _settled_query_idle(pilot, app)
            await pilot.pause()
            completed_record = app.state.query_result_record(2)
            preserved_columns, preserved_row_count, preserved_message = _result_grid_snapshot(app)
            background_status = app.query_one("#status", Static).content
            background_sequence = app.state.active_result.sequence
            app._show_buffer_result_at_tab(app.state.buffer_result_tabs[1])
            reopened_columns, reopened_row_count, reopened_message = _result_grid_snapshot(app)
            return (
                background_sequence,
                initial_columns,
                initial_row_count,
                background_status,
                None if completed_record is None else completed_record.state,
                None if completed_record is None else completed_record.preview_row_count,
                initial_message,
                preserved_columns,
                preserved_row_count,
                preserved_message,
                app.state.active_result.sequence,
                reopened_columns,
                reopened_row_count,
                reopened_message,
            )

    (
        active_sequence,
        columns,
        row_count,
        status,
        completed_state,
        completed_preview_rows,
        message,
        preserved_columns,
        preserved_row_count,
        preserved_message,
        reopened_sequence,
        reopened_columns,
        reopened_row_count,
        reopened_message,
    ) = asyncio.run(_inner())

    assert active_sequence == 1
    assert columns == ("first",)
    assert row_count == 1
    assert status == "Query 2 completed in the background: 1 row(s) preserved for later recall."
    assert completed_state == "complete"
    assert completed_preview_rows == 1
    assert "Buffer result 1.1." in message
    assert preserved_columns == ("first",)
    assert preserved_row_count == 1
    assert preserved_message == message
    assert reopened_sequence == 2
    assert reopened_columns == ("second",)
    assert reopened_row_count == 1
    assert "Buffer result 2.2." in reopened_message


def test_displaced_preview_only_without_handle_retains_transient_owner_and_pauses_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("prior",), rows=(("prior-row",),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT prior",
    )
    release = threading.Event()
    queued_started = threading.Event()
    release_queued = threading.Event()
    seen_requests: list[TUIRunRequest] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        seen_requests.append(request)
        if len(seen_requests) > 1:
            queued_started.set()
            assert release_queued.wait(timeout=5.0)
            _emit_complete_result(
                request=request,
                result_store=store,
                event_sink=event_sink,
                result=QueryResult(columns=("queued",), rows=(("queued-row",),), elapsed_ms=1.0),
            )
            return
        preview = BoundedQueryResult(
            columns=("value",),
            rows=(("preview-row",),),
            elapsed_ms=1.0,
            preview_payload_bytes=len(encode_row_payload(("preview-row",))),
            has_more_rows=True,
            truncation_reason="row_limit",
        )
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        assert release.wait(5.0)
        event_sink(
            tui_app_module.TUIPreviewOnlyEvent(
                sequence=request.sequences[0],
                preview=preview,
                reason="preservation_failed",
                stored=None,
            )
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        str,
        list[str],
        str,
        int | None,
        int | None,
        bool,
        int | None,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT preview_only")
            await pilot.press("f4")
            for _ in range(40):
                await pilot.pause(0.05)
                if (
                    app.state.active_query_result_record() is not None
                    and app.state.active_query_result_record().state == "preserving"
                ):
                    break
            app.query_one("#history", DataTable).focus()
            app._show_history_result_at_row(0)
            app.query_one("#sql", TextArea).load_text("SELECT queued")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None
            release.set()
            await _settled_query_idle(pilot, app)
            await pilot.pause()
            return (
                app.query_one("#status", Static).content,
                app_history_statuses(app.state),
                app.query_one("#results-message", Static).content,
                (
                    None
                    if app._transient_preview_only_result is None
                    else app._transient_preview_only_result.sequence
                ),
                app.state.active_result.sequence,
                queued_started.is_set(),
                (
                    None
                    if app.state.query_result_record(1) is None
                    or app.state.query_result_record(1).handle is None
                    else app.state.query_result_record(1).handle.sequence
                ),
            )

    (
        status,
        history_statuses,
        results_message,
        transient_sequence,
        active_sequence,
        queued_started_early,
        preserved_sequence,
    ) = asyncio.run(_inner())

    assert status == (
        "Query 2 kept only its active preview because preview preservation did not complete "
        "after a preservation failure. Remove older stored results and retry preview "
        "preservation, or delete this preview to continue the queued run."
    )
    assert history_statuses == ["success", "success"]
    assert "Showing 1 retained preview row(s)." in results_message
    assert transient_sequence == 2
    assert active_sequence == 2
    assert queued_started_early is False
    assert preserved_sequence == 1


def test_source_columns_empty_outcome_during_query_preserves_visible_preview(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            request = TUIRunRequest(
                statements=("SELECT 1",),
                sequences=(1,),
                sources=state.table_sources,
                fallback_sources=(),
                preview_policy=PreviewPolicy(),
                run_mode="current",
                submission_order=1,
            )
            app.state.start_query_request(request)
            app._active_query_sql[1] = "SELECT 1"
            app._active_query_run_modes[1] = "current"
            app._active_query_records[1] = TUIResultRecord(
                handle=None,
                state="executing",
                reason=None,
                columns=(),
                preview_row_count=0,
                full_row_count=None,
                elapsed_ms=0.0,
            )
            app.state.set_active_result_record(
                1,
                TUIResultRecord(
                    handle=None,
                    state="executing",
                    reason=None,
                    columns=(),
                    preview_row_count=0,
                    full_row_count=None,
                    elapsed_ms=0.0,
                ),
            )
            preview = BoundedQueryResult(
                columns=("value",),
                rows=(("preview",),),
                elapsed_ms=1.0,
                preview_payload_bytes=len(encode_row_payload(("preview",))),
                has_more_rows=True,
                truncation_reason="row_limit",
            )
            app._handle_preview_ready_event(TUIPreviewReadyEvent(sequence=1, preview=preview))
            app._apply_operation_outcome(
                tui_app_module._SourceColumnsOutcome(source_name="customers", columns=()),
                operation_label="Loading columns for customers",
            )
            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.query_one("#status", Static).content,
                message,
                columns,
                row_count,
            )

    status, message, columns, row_count = asyncio.run(_inner())

    assert status == (
        "customers: no columns available. "
        "Query results remain visible until the current query finishes."
    )
    assert "Full result preservation is still running." in message
    assert columns == ("value",)
    assert row_count == 1


def test_operation_worker_error_during_query_preserves_visible_preview(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            request = TUIRunRequest(
                statements=("SELECT 1",),
                sequences=(1,),
                sources=state.table_sources,
                fallback_sources=(),
                preview_policy=PreviewPolicy(),
                run_mode="current",
                submission_order=1,
            )
            app.state.start_query_request(request)
            app._active_query_sql[1] = "SELECT 1"
            app._active_query_run_modes[1] = "current"
            app._active_query_records[1] = TUIResultRecord(
                handle=None,
                state="executing",
                reason=None,
                columns=(),
                preview_row_count=0,
                full_row_count=None,
                elapsed_ms=0.0,
            )
            app.state.set_active_result_record(
                1,
                TUIResultRecord(
                    handle=None,
                    state="executing",
                    reason=None,
                    columns=(),
                    preview_row_count=0,
                    full_row_count=None,
                    elapsed_ms=0.0,
                ),
            )
            preview = BoundedQueryResult(
                columns=("value",),
                rows=(("preview",),),
                elapsed_ms=1.0,
                preview_payload_bytes=len(encode_row_payload(("preview",))),
                has_more_rows=True,
                truncation_reason="row_limit",
            )
            app._handle_preview_ready_event(TUIPreviewReadyEvent(sequence=1, preview=preview))
            app._handle_operation_worker_failure(
                CSVQLError("private failure"),
                operation_label="Loading columns for customers",
            )
            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.query_one("#status", Static).content,
                message,
                columns,
                row_count,
            )

    status, message, columns, row_count = asyncio.run(_inner())

    assert status == (
        "Loading columns for customers failed while a query result is active. "
        "Query results remain visible."
    )
    assert "Full result preservation is still running." in message
    assert columns == ("value",)
    assert row_count == 1


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
    assert message == "Showing 2 total row(s). Full export/save use the preserved result."


def test_app_runs_query_records_result_handle_and_cleans_up_spilled_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        rows = tuple((index,) for index in range(10_001))
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=rows, elapsed_ms=1.0),
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[bool, tuple[tuple[object, ...], ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            handle = app.state.query_result_handle(1)
            return (
                handle is not None,
                _active_stored_rows(app),
            )

    has_handle, rows = asyncio.run(_inner())

    assert has_handle is True
    assert len(rows) == 10_001


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

            previous_result = app.state.active_query_result_record()
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("   \n")
            await pilot.press(key)
            await pilot.pause(0.2)

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.active_query_result_record() == previous_result,
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

            previous_result = app.state.active_query_result_record()
            previous_view = app.state.result_view
            assert previous_result is not None

            app.state.remove_source("customers")
            app._refresh_sources_table()
            sql.load_text("SELECT * FROM customers")
            await pilot.press(key)
            await pilot.pause(0.2)

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.active_query_result_record() == previous_result,
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

            assert app.state.has_active_result

            sql.load_text("SELECT * FROM missing_table")
            await pilot.press("f4")
            await pilot.pause(0.2)

            status = app.query_one("#status", Static).content
            results = app.query_one("#results-message", Static).content
            return app.state.has_active_result, status, results

    has_active_result, status, results = asyncio.run(_inner())

    assert has_active_result is False
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

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_statements.extend(request.statements)
        seen_sequences.extend(request.sequences)
        _emit_buffer_complete_results(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

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
            await _settled_query_idle(pilot, app)

            results = app.query_one("#results", DataTable)
            return (
                seen_statements,
                seen_sequences,
                app_history_run_modes(app.state),
                _history_run_column_values(app),
                tuple(str(column.label) for column in results.columns.values()),
                app.query_one("#results-title", Static).content,
                _active_stored_rows(app),
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


def test_run_buffer_storage_failure_preserves_tabs_and_continues_with_dense_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    submitted_statements: list[str] = []
    finish_query_run_calls: list[TUISessionState] = []
    storage_message = "Unable to write the query result to temporary storage."
    unsafe_storage_detail = f"private spill path: {tmp_path / 'query-2.pickle'}"
    original_finish_query_run = state.finish_query_run

    def track_finish_query_run(run_state: TUISessionState) -> None:
        finish_query_run_calls.append(run_state)
        original_finish_query_run()

    monkeypatch.setattr(TUISessionState, "finish_query_run", track_finish_query_run)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        submitted_statements.extend(request.statements)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value_1",), rows=((1,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        _emit_failed_event(
            sequence=request.sequences[1],
            event_sink=event_sink,
            error_message=storage_message,
        )
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value_3",), rows=((3,),), elapsed_ms=1.0),
            sequence=request.sequences[2],
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        str,
        str,
        str,
        int | None,
        tuple[tuple[object, ...], ...],
        int | None,
        tuple[tuple[object, ...], ...],
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first; SELECT 2 AS second; SELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            terminal_status = app.query_one("#status", Static).content
            terminal_message = app.query_one("#results-message", Static).content
            latest_sequence = app.state.active_result.sequence
            latest_rows = _active_stored_rows(app)
            app._show_buffer_result_at_tab(app.state.buffer_result_tabs[0])
            return (
                app.query_one("#run-status", Static).content,
                terminal_status,
                terminal_message,
                latest_sequence,
                latest_rows,
                app.state.active_result.sequence,
                _active_stored_rows(app),
                app.query_one("#results-message", Static).content,
            )

    (
        run_status,
        terminal_status,
        terminal_message,
        latest_sequence,
        latest_rows,
        selected_sequence,
        selected_rows,
        selected_message,
    ) = asyncio.run(_inner())

    assert submitted_statements == [
        "SELECT 1 AS first",
        "SELECT 2 AS second",
        "SELECT 3 AS third",
    ]
    assert [(item.sequence, item.status, item.run_mode) for item in state.query_history] == [
        (1, "success", "buffer"),
        (2, "error", "buffer"),
    ]
    assert state.query_history[1].error_message == storage_message
    assert [(tab.sequence, tab.index) for tab in state.buffer_result_tabs] == [(1, 1)]
    assert state.query_result_record(2) is None
    assert state.query_result_handle(2) is None
    assert state.query_result_record(3) is None
    assert state.query_result_handle(3) is None
    assert latest_sequence == 1
    assert latest_rows == ((1,),)
    assert selected_sequence == 1
    assert selected_rows == ((1,),)
    assert "Buffer result 1.1." in selected_message
    assert state.query_run.is_running is False
    assert finish_query_run_calls == [state]
    assert run_status == "Ready."
    assert terminal_status == f"Error: {storage_message}"
    assert terminal_message == "Showing 1 total row(s). Full export/save use the preserved result."
    for safe_text in (terminal_status, terminal_message, selected_message):
        assert unsafe_storage_detail not in safe_text


def test_run_buffer_final_storage_failure_preserves_prior_tab_and_error_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    finish_query_run_calls: list[TUISessionState] = []
    storage_message = "Unable to write the query result to temporary storage."
    unsafe_storage_detail = f"private spill path: {tmp_path / 'query-3.pickle'}"
    original_finish_query_run = state.finish_query_run

    def track_finish_query_run(run_state: TUISessionState) -> None:
        finish_query_run_calls.append(run_state)
        original_finish_query_run()

    monkeypatch.setattr(TUISessionState, "finish_query_run", track_finish_query_run)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value_1",), rows=((1,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value_2",), rows=((2,),), elapsed_ms=1.0),
            sequence=request.sequences[1],
        )
        _emit_failed_event(
            sequence=request.sequences[2],
            event_sink=event_sink,
            error_message=storage_message,
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[str, str, str, str, tuple[tuple[object, ...], ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first; SELECT 2 AS second; SELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
                _focused_widget_id(app),
                _active_stored_rows(app),
            )

    status, results_message, run_status, focused_widget, active_rows = asyncio.run(_inner())

    assert [(item.sequence, item.status, item.run_mode) for item in state.query_history] == [
        (1, "success", "buffer"),
        (2, "success", "buffer"),
        (3, "error", "buffer"),
    ]
    assert state.query_history[-1].error_message == storage_message
    assert [(tab.sequence, tab.index) for tab in state.buffer_result_tabs] == [(1, 1), (2, 2)]
    assert state.active_result.sequence == 2
    assert active_rows == ((2,),)
    assert state.query_result_record(3) is None
    assert state.query_result_handle(3) is None
    assert status == f"Error: {storage_message}"
    assert results_message == "Showing 1 total row(s). Full export/save use the preserved result."
    assert unsafe_storage_detail not in status
    assert unsafe_storage_detail not in results_message
    assert state.query_run.is_running is False
    assert finish_query_run_calls == [state]
    assert run_status == "Ready."
    assert focused_widget == "sql"


def test_run_buffer_all_storage_failures_leave_no_tab_and_preserve_error_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    finish_query_run_calls: list[TUISessionState] = []
    storage_message = "Unable to write the query result to temporary storage."
    unsafe_storage_detail = f"private spill path: {tmp_path / 'query-result.pickle'}"
    original_finish_query_run = state.finish_query_run

    def track_finish_query_run(run_state: TUISessionState) -> None:
        finish_query_run_calls.append(run_state)
        original_finish_query_run()

    monkeypatch.setattr(TUISessionState, "finish_query_run", track_finish_query_run)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        for sequence in request.sequences:
            _emit_failed_event(
                sequence=sequence,
                event_sink=event_sink,
                error_message=storage_message,
            )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[str, str, str, str, tuple[str, ...], int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first; SELECT 2 AS second; SELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            results = app.query_one("#results", DataTable)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
                _focused_widget_id(app),
                tuple(str(column.label) for column in results.columns.values()),
                results.row_count,
            )

    status, results_message, run_status, focused_widget, columns, row_count = asyncio.run(_inner())

    assert [(item.sequence, item.status, item.run_mode) for item in state.query_history] == [
        (1, "error", "buffer"),
    ]
    assert tuple(item.error_message for item in state.query_history) == (storage_message,)
    assert state.buffer_result_tabs == ()
    assert state.has_active_result is False
    assert state.active_result.sequence is None
    assert columns == ()
    assert row_count == 0
    for sequence in (1, 2, 3):
        assert state.query_result_record(sequence) is None
        assert state.query_result_handle(sequence) is None
    assert status == f"Error: {storage_message}"
    assert results_message == f"Error: {storage_message}"
    assert unsafe_storage_detail not in status
    assert unsafe_storage_detail not in results_message
    assert state.query_run.is_running is False
    assert finish_query_run_calls == [state]
    assert run_status == "Ready."
    assert focused_widget == "sql"


@pytest.mark.parametrize(
    "prior_case",
    [
        "in_memory_query",
        "spilled_query",
        "invalidated_spilled_query",
        "buffer_tabs",
    ],
)
def test_run_buffer_all_storage_failures_preserve_prior_active_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_case: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    prior_sequences: list[int] = list(
        state.reserve_query_sequences(2 if prior_case == "buffer_tabs" else 1)
    )
    if prior_case == "buffer_tabs":
        for index, sequence in enumerate(prior_sequences, start=1):
            _record_stored_result(
                state,
                QueryResult(
                    columns=("prior_value",),
                    rows=((f"prior-{index}",),),
                    elapsed_ms=1.0,
                ),
                sequence=sequence,
                sql=f"SELECT {index} AS prior_value",
                store=store,
                run_mode="buffer",
                buffer_result_index=index,
            )
        prior_tabs = tuple(
            TUIBufferResultTab(sequence=sequence, index=index, label=f"query {index}")
            for index, sequence in enumerate(prior_sequences, start=1)
        )
        state.set_buffer_result_tabs(prior_tabs, selected_sequence=prior_sequences[0])
    elif prior_case == "invalidated_spilled_query":
        preview = BoundedQueryResult(
            columns=("prior_value",),
            rows=(("prior-1",),),
            elapsed_ms=1.0,
            preview_payload_bytes=len(encode_row_payload(("prior-1",))),
            has_more_rows=False,
            truncation_reason=None,
        )
        _record_preview_only_result(
            state,
            store,
            sequence=prior_sequences[0],
            sql="SELECT 1 AS prior_value",
            preview=preview,
        )
    else:
        _record_stored_result(
            state,
            QueryResult(
                columns=("prior_value",),
                rows=(("prior-1",),),
                elapsed_ms=1.0,
            ),
            sequence=prior_sequences[0],
            sql="SELECT 1 AS prior_value",
            store=store,
        )

    previous_active = state.active_result
    previous_tabs = state.buffer_result_tabs
    previous_history = state.query_history

    storage_messages = (
        "Unable to write the query result to temporary storage.",
        "Unable to serialize the query result for temporary storage.",
        "Unable to use secure temporary result storage.",
    )
    unsafe_storage_detail = f"private spill path: {tmp_path / 'query-result.pickle'}"
    finish_query_run_calls: list[TUISessionState] = []
    original_finish_query_run = state.finish_query_run

    def track_finish_query_run(run_state: TUISessionState) -> None:
        finish_query_run_calls.append(run_state)
        original_finish_query_run()

    monkeypatch.setattr(TUISessionState, "finish_query_run", track_finish_query_run)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        for sequence, message in zip(request.sequences, storage_messages, strict=True):
            _emit_failed_event(
                sequence=sequence,
                event_sink=event_sink,
                error_message=message,
            )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        tuple[tuple[str, ...], int, str],
        tuple[tuple[str, ...], int, str],
        str,
        str,
        str,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            before_grid = _result_grid_snapshot(app)
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 10 AS first; SELECT 20 AS second; SELECT 30 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            after_grid = _result_grid_snapshot(app)
            status = app.query_one("#status", Static).content
            results_message = app.query_one("#results-message", Static).content
            run_status = app.query_one("#run-status", Static).content
            focused_widget = _focused_widget_id(app)
            return (before_grid, after_grid, status, results_message, run_status, focused_widget)

    (
        before_grid,
        after_grid,
        status,
        results_message,
        run_status,
        focused_widget,
    ) = asyncio.run(_inner())

    assert state.query_history[: len(previous_history)] == previous_history
    new_history = state.query_history[len(previous_history) :]
    expected_failure_sequence = prior_sequences[-1] + 1
    assert tuple((item.sequence, item.status, item.run_mode) for item in new_history) == (
        (expected_failure_sequence, "error", "buffer"),
    )
    assert tuple(item.error_message for item in new_history) == (storage_messages[0],)
    for sequence in range(prior_sequences[-1] + 1, prior_sequences[-1] + 4):
        assert state.query_result_record(sequence) is None
        assert state.query_result_handle(sequence) is None

    if prior_case == "buffer_tabs":
        assert state.active_result == previous_active
        assert state.buffer_result_tabs == previous_tabs
        assert before_grid[:2] == after_grid[:2]
        assert results_message == before_grid[2]
    else:
        assert state.has_active_result is False
        assert state.buffer_result_tabs == ()
        assert after_grid[:2] == ((), 0)
        assert results_message == f"Error: {storage_messages[0]}"
    assert status == f"Error: {storage_messages[0]}"
    assert unsafe_storage_detail not in status
    assert unsafe_storage_detail not in results_message
    assert state.query_run.is_running is False
    assert finish_query_run_calls == [state]
    assert run_status == "Ready."
    assert focused_widget == "sql"


def test_run_buffer_storage_invalidation_keeps_prior_preview_selectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    storage_message = "Unable to write the query result to temporary storage."
    unsafe_storage_detail = f"private spill path: {tmp_path / 'query-2.pickle'}"
    original_load_preview = store.load_preview
    preview_load_allowed = True

    def guarded_load_preview(handle, policy):
        if not preview_load_allowed:
            raise AssertionError("actions must not reload the visible preview")
        return original_load_preview(handle, policy)

    monkeypatch.setattr(store, "load_preview", guarded_load_preview)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value_1",), rows=(("private-row-1",),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        _emit_failed_event(
            sequence=request.sequences[1],
            event_sink=event_sink,
            error_message=storage_message,
        )
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value_3",), rows=(("private-row-3",),), elapsed_ms=1.0),
            sequence=request.sequences[2],
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        TUIResultRecord | None,
        int | None,
        tuple[tuple[str, ...], ...],
        str,
        str,
        str,
        bool,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first; SELECT 2 AS second; SELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            app._show_buffer_result_at_tab(app.state.buffer_result_tabs[0])
            selected_view = app.state.result_view.display_rows
            nonlocal preview_load_allowed
            preview_load_allowed = False
            app.action_export_last_result()
            await pilot.pause()
            app.screen.query_one("#export-path", Input)
            export_status = app.query_one("#status", Static).content
            await pilot.press("escape")
            await pilot.pause()
            app.action_save_result_as_source()
            await pilot.pause()
            app.screen.query_one("#derived-source-alias", Input)
            return (
                app.state.query_result_record(1),
                app.state.active_result.sequence,
                selected_view,
                export_status,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    (
        first_record,
        selected_sequence,
        selected_view,
        export_status,
        save_status,
        results_message,
        operation_running,
    ) = asyncio.run(_inner())

    assert [(tab.sequence, tab.index) for tab in state.buffer_result_tabs] == [(1, 1)]
    assert state.query_result_record(2) is None
    assert state.query_result_handle(2) is None
    assert state.query_result_record(3) is None
    assert state.query_result_handle(3) is None
    assert first_record is not None
    assert first_record.state == "complete"
    assert selected_sequence == 1
    assert selected_view == (("private-row-1",),)
    assert export_status == "Showing buffer result 1.1."
    assert save_status == "Showing buffer result 1.1."
    assert "Full export/save use the preserved result." in results_message
    assert operation_running is False
    assert state.query_history[1].error_message == storage_message
    for safe_text in (
        state.query_history[1].error_message or "",
        export_status,
        save_status,
        results_message,
    ):
        assert unsafe_storage_detail not in safe_text


def test_run_buffer_stops_after_middle_outcome_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    submitted_statements: list[str] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        submitted_statements.extend(request.statements)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        _emit_failed_event(
            sequence=request.sequences[1],
            event_sink=event_sink,
            error_message="simulated failure",
            suggestion="Fix statement 2.",
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        list[str],
        list[str],
        list[int],
        str,
        str,
        str,
        dict[int, str],
        dict[int, str],
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT broken FROM customers;\nSELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            return (
                submitted_statements,
                app_history_statuses(app.state),
                [item.sequence for item in app.state.query_history],
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
                dict(app._active_query_sql),
                dict(app._active_query_run_modes),
            )

    (
        submitted_statements,
        statuses,
        sequences,
        status,
        results_message,
        run_status,
        active_query_sql,
        active_query_run_modes,
    ) = asyncio.run(_inner())

    assert submitted_statements == [
        "SELECT 1 AS first",
        "SELECT broken FROM customers",
        "SELECT 3 AS third",
    ]
    assert statuses == ["success", "error"]
    assert sequences == [1, 2]
    assert "simulated failure" in status
    assert results_message == "Showing 1 total row(s). Full export/save use the preserved result."
    assert run_status == "Ready."
    assert active_query_sql == {}
    assert active_query_run_modes == {}


def test_run_buffer_recovers_from_empty_worker_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        if request.run_mode == "buffer":
            return
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[bool, str, str, str, str, dict[int, str], dict[int, str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            buffer_status = app.query_one("#status", Static).content
            buffer_run_status = app.query_one("#run-status", Static).content
            is_running = app.state.query_run.is_running

            sql.load_text("SELECT 1 AS value")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            return (
                is_running,
                buffer_status,
                buffer_run_status,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                dict(app._active_query_sql),
                dict(app._active_query_run_modes),
            )

    (
        is_running,
        buffer_status,
        buffer_run_status,
        final_status,
        final_run_status,
        active_query_sql,
        active_query_run_modes,
    ) = asyncio.run(_inner())

    assert is_running is False
    assert buffer_run_status == "Ready."
    assert "no tabular result" in buffer_status.lower()
    assert "Query already running." not in final_status
    assert final_run_status == "Ready."
    assert active_query_sql == {}
    assert active_query_run_modes == {}


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

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_statements.extend(request.statements)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        _emit_failed_event(
            sequence=request.sequences[1],
            event_sink=event_sink,
            error_message="simulated failure",
            suggestion="Fix statement 2.",
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[list[str], list[str], list[int], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT broken FROM customers;\nSELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

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
    assert results_message == "Showing 1 total row(s). Full export/save use the preserved result."
    assert run_status == "Ready."


def test_history_rerun_records_rerun_mode_and_status_message(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT COUNT(*) AS count FROM customers",
    )
    seen_sql: list[str] = []
    release_worker = threading.Event()

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_sql.extend(request.statements)
        assert release_worker.wait(timeout=5.0)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )

    monkeypatch = pytest.MonkeyPatch()
    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[list[str], tuple[str, ...], str, str, list[str]]:
        try:
            app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
                await _settled_query_idle(pilot, app)
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


def test_history_refresh_preserves_cursor_after_append_while_new_query_becomes_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore()
    for sequence in state.reserve_query_sequences(10):
        _record_stored_result(
            state,
            QueryResult(columns=("value",), rows=((sequence,),), elapsed_ms=1.0),
            sequence=sequence,
            sql=f"SELECT {sequence} AS value",
            store=store,
        )

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(
                columns=("value",),
                rows=((request.sequences[0],),),
                elapsed_ms=1.0,
            ),
            sequence=request.sequences[0],
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[list[int], int, int | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 11 AS value")
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=8)

            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            return (
                [item.sequence for item in app.state.query_history],
                history.cursor_row,
                app.state.active_result.sequence,
                app.query_one("#status", Static).content,
            )

    sequences, cursor_row, active_sequence, status = asyncio.run(_inner())

    assert sequences == list(range(1, 12))
    assert cursor_row == 8
    assert active_sequence == 11
    assert status == "1 returned row(s) in 1.0 ms."


def test_run_editor_reads_settled_editor_text_after_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    seen_sql: list[str] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_sql.extend(request.statements)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

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
            await _settled_query_idle(pilot, app)

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

            previous_result = app.state.active_query_result_record()
            previous_view = app.state.result_view
            assert previous_result is not None

            sql.load_text("SELECT email FROM customers")
            monkeypatch.setattr(app, "call_after_refresh", lambda callback: False)
            app.action_run_query()
            await pilot.pause()

            columns, row_count, message = _result_grid_snapshot(app)
            return (
                app.state.active_query_result_record() == previous_result,
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


def test_pane_title_and_chrome_clicks_focus_their_target_panes(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            initial_focus = _focused_widget_id(app)

            await pilot.click("#results-title")
            await pilot.pause()
            results_focus = _focused_widget_id(app)

            await pilot.click("#history-title")
            await pilot.pause()
            history_focus = _focused_widget_id(app)

            await pilot.click("#sources-title")
            await pilot.pause()
            sources_focus = _focused_widget_id(app)

            await pilot.click("#run-status")
            await pilot.pause()
            sql_focus = _focused_widget_id(app)

            return initial_focus, results_focus, history_focus, sources_focus, sql_focus

    initial_focus, results_focus, history_focus, sources_focus, sql_focus = asyncio.run(_inner())

    assert initial_focus == "sources"
    assert results_focus == "results"
    assert history_focus == "history"
    assert sources_focus == "sources"
    assert sql_focus == "sql"


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
        ("F9", "Quit"),
    )
    expected_results_footer = (
        ("F1", "Help"),
        ("F2", "SQL"),
        ("F6", "Sources"),
        ("F8", "History"),
        ("F9", "Quit"),
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


def test_focus_check_returns_false_after_screen_stack_teardown(tmp_path: Path) -> None:
    app = CSVQLMenuApp(start_dir=tmp_path)

    assert app._is_focused("#history") is False


def test_pane_context_updates_with_active_focus(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
    )

    async def _inner() -> tuple[str, str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = _record_stored_result(
        state,
        QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT 1 AS id",
    )

    async def _inner() -> tuple[str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
        app = CSVQLMenuApp(initial_state=_make_source_state(tmp_path), start_dir=tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.action_export_last_result()
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

    def slow_inspect_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ):
        del operation
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

    def failing_inspect_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ) -> object:
        del operation
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


def test_unexpected_operation_worker_failure_sanitizes_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    sentinel = (
        "private_path=/tmp/customer-results.csv "
        "result=alex@example.com detail=internal-worker-state"
    )

    def failing_inspect_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ) -> object:
        del operation
        del source
        raise RuntimeError(sentinel)

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

    assert status == "Error: Unable to complete this action. Try again."
    assert results_message == status
    assert sentinel not in status
    assert sentinel not in results_message
    assert run_status == "Ready."
    assert is_running is False


def test_sample_worker_failure_preserves_previous_active_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_failing_sample_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ) -> object:
        del source, operation
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

            previous_result = app.state.active_query_result_record()
            previous_active_result = app.state.active_result
            previous_view = app.state.result_view
            assert previous_result is not None

            app.query_one("#sources", DataTable).focus()
            await pilot.press("s")
            await pilot.pause(0.1)

            running_result_preserved = app.state.active_query_result_record() == previous_result
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

    def slow_inspect_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ):
        started.set()
        release.wait(timeout=2)
        from csvql.tui_workflows import inspect_source as real_inspect_source

        return real_inspect_source(source, operation=operation)

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


def test_escape_requests_shared_context_interrupt_and_worker_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    interrupted = threading.Event()
    cleaned_up = threading.Event()

    def cancellable_inspect_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ) -> object:
        del source
        operation.attach_interrupt(interrupted.set)
        started.set()
        try:
            assert interrupted.wait(timeout=2)
            operation.checkpoint()
        finally:
            operation.detach_interrupt()
            cleaned_up.set()
        raise AssertionError("cancelled source operation returned a success result")

    monkeypatch.setattr("csvql.tui_app.inspect_source", cancellable_inspect_source)

    async def _inner() -> tuple[str, bool, object]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("i")
            await pilot.pause(0.1)
            assert started.is_set()
            await pilot.press("escape")
            await pilot.pause(0.2)
            return (
                app.query_one("#status", Static).content,
                app.state.operation_run.is_running,
                app.state.active_result,
            )

    status, is_running, active_result = asyncio.run(_inner())

    assert interrupted.is_set()
    assert cleaned_up.is_set()
    assert "Cancelled Inspecting customers." in status
    assert is_running is False
    assert active_result.kind == "none"


def test_cancelled_sample_worker_preserves_previous_active_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_sample_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ) -> object:
        started.set()
        assert release.wait(timeout=2)
        from csvql.tui_workflows import sample_source as real_sample_source

        return real_sample_source(source, operation=operation)

    monkeypatch.setattr("csvql.tui_app.sample_source", slow_sample_source)

    async def _inner() -> tuple[bool, bool, bool, str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await pilot.pause(0.2)

            previous_result = app.state.active_query_result_record()
            previous_active_result = app.state.active_result
            previous_view = app.state.result_view
            previous_message = app.query_one("#results-message", Static).content
            assert previous_result is not None

            app.query_one("#sources", DataTable).focus()
            await pilot.press("s")
            await pilot.pause(0.1)

            running_result_preserved = app.state.active_query_result_record() == previous_result
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
    store = _record_stored_result(
        state,
        QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT 1 AS id",
    )
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
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=1.0,
        ),
        sequence=1,
        sql="SELECT customer_id, email FROM customers",
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
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
        sequence=1,
        sql="SELECT customer_id, email FROM customers",
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
        sequence=1,
        sql="SELECT customer_id, email FROM customers",
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
        sequence=1,
        sql="SELECT customer_id, email FROM customers",
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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


def test_export_from_spilled_result_writes_full_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_path = tmp_path / "exports" / "large.csv"
    export_path.parent.mkdir()
    rows = tuple((index,) for index in range(10001))
    stored_result = QueryResult(columns=("id",), rows=rows, elapsed_ms=1.0)
    state = TUISessionState()
    monkeypatch.setattr("csvql.tui_app.run_tui_request", _reject_query_execution)
    monkeypatch.setattr("csvql.tui_workflows.CSVQLEngine", _reject_query_execution)

    async def _inner() -> tuple[int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            handle = _store_complete_result(app._result_store, stored_result, sequence=1).handle
            view = make_result_view_state(stored_result, source_result_sequence=1)
            app.state.record_query_success(
                1,
                "SELECT * FROM large",
                handle=handle,
                result_view=view,
                elapsed_ms=stored_result.elapsed_ms,
            )
            app._refresh_results_display()
            assert app.state.active_query_result_record() is not None
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
    assert "Showing 1,000 retained preview row(s) from 10,001 total row(s)." in message
    assert export_path.read_text(encoding="utf-8").splitlines()[1] == "0"


def test_full_tui_export_streams_preserved_rows_once_without_rerunning_sql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    source_path = state.sources[0].path
    source_bytes_before = source_path.read_bytes()
    source_stat_before = source_path.stat()
    export_path = tmp_path / "exports" / "ordered.csv"
    export_path.parent.mkdir()
    sql = "SELECT range AS id FROM range(2501) ORDER BY id"
    executed_sql: list[str] = []
    opened_handles: list[object] = []
    real_stream = CSVQLEngine.stream
    store = TUIResultStore(temp_root=tmp_path)
    real_open_rows = store.open_rows

    def recording_stream(
        engine: CSVQLEngine,
        statement: str,
        params: tuple[object, ...] | None = None,
    ):
        executed_sql.append(statement)
        return real_stream(engine, statement, params)

    def recording_open_rows(handle: object):
        opened_handles.append(handle)
        return real_open_rows(handle)  # type: ignore[arg-type]

    monkeypatch.setattr(CSVQLEngine, "stream", recording_stream)
    monkeypatch.setattr(store, "open_rows", recording_open_rows)

    async def _inner() -> object:
        app = CSVQLMenuApp(
            initial_state=state,
            start_dir=tmp_path,
            result_store=store,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text(sql)
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            record = app.state.active_query_result_record()
            assert record is not None
            assert record.handle is not None
            assert record.full_row_count == 2_501

            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(export_path)
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app, wait_for_status_settle=False)
            return record.handle

    exported_handle = asyncio.run(_inner())
    exported_lines = export_path.read_text(encoding="utf-8").splitlines()

    assert exported_lines == ["id", *(str(index) for index in range(2_501))]
    assert executed_sql == [sql]
    assert opened_handles == [exported_handle]
    assert source_path.read_bytes() == source_bytes_before
    source_stat_after = source_path.stat()
    assert source_stat_after.st_size == source_stat_before.st_size
    assert source_stat_after.st_mtime_ns == source_stat_before.st_mtime_ns


def test_queued_source_fingerprint_mutation_terminalizes_as_source_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    source_path = state.sources[0].path
    first_started = threading.Event()
    release_first = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    second_events: list[object] = []
    source_error_codes: list[str] = []
    real_run_tui_request = tui_app_module.run_tui_request
    real_bind = CSVSourceAdapter.bind

    def recording_bind(
        adapter: CSVSourceAdapter,
        connection: object,
        source: object,
        operation: OperationContext,
    ):
        try:
            return real_bind(adapter, connection, source, operation)  # type: ignore[arg-type]
        except SourceError as exc:
            source_error_codes.append(exc.code)
            raise

    def controlled_run_tui_request(
        request: TUIRunRequest,
        *,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        seen_requests.append(request)
        if len(seen_requests) == 1:
            first_started.set()
            assert release_first.wait(timeout=5.0)
            _emit_complete_result(
                request=request,
                result_store=result_store,
                event_sink=event_sink,
                result=QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            )
            return

        def record_second_event(event: object) -> None:
            second_events.append(event)
            event_sink(event)

        real_run_tui_request(
            request,
            result_store=result_store,
            event_sink=record_second_event,
            operation=operation,
        )

    monkeypatch.setattr(CSVSourceAdapter, "bind", recording_bind)
    monkeypatch.setattr(tui_app_module, "run_tui_request", controlled_run_tui_request)

    async def _inner() -> tuple[object, tuple[object, ...], bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if first_started.is_set():
                    break
            assert first_started.is_set()

            sql.load_text("SELECT count(*) AS total FROM customers")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None
            queued_request = app.state.queued_run.request
            queued_fingerprint = queued_request.sources[0].fingerprint

            source_path.write_text(
                source_path.read_text(encoding="utf-8") + "CUST-003,cora@example.com\n",
                encoding="utf-8",
            )
            release_first.set()
            for _ in range(300):
                await pilot.pause(0.02)
                if len(app.state.query_history) == 2 and not app.state.query_run.is_running:
                    break

            return (
                queued_fingerprint,
                app.state.query_history,
                app.state.query_run.is_running,
            )

    queued_fingerprint, history, query_is_running = asyncio.run(_inner())
    failed_events = [
        event for event in second_events if isinstance(event, TUIFailedBeforePreviewEvent)
    ]

    assert queued_fingerprint is not None
    assert source_error_codes == ["source_changed"]
    assert len(failed_events) == 1
    assert failed_events[0].error_message == "CSV source changed after submission."
    assert failed_events[0].suggestion == (
        "Submit the operation again to capture the current CSV source."
    )
    assert [item.status for item in history] == ["success", "error"]
    assert history[-1].error_message == "CSV source changed after submission."
    assert len(seen_requests) == 2
    assert query_is_running is False


def test_private_spool_path_is_not_admitted_by_direct_ui_or_catalog_workflows(
    tmp_path: Path,
) -> None:
    store = TUIResultStore(temp_root=tmp_path)
    stored = _store_complete_result(
        store,
        QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0),
        sequence=1,
    )
    workspace = store.workspace_path
    assert workspace is not None
    private_spool = workspace / "query-1.result"
    spool_bytes = private_spool.read_bytes()

    async def _direct_ui_attempt() -> tuple[bool, tuple[TUISource, ...]]:
        app = CSVQLMenuApp(initial_state=TUISessionState(), start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            handled_as_source = app._handle_pasted_csv_sources(str(private_spool))
            await pilot.pause()
            return handled_as_source, app.state.sources

    handled_as_source, direct_sources = asyncio.run(_direct_ui_attempt())

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".csvql.yml").write_text(
        f"version: 1\ntables:\n  private_result:\n    path: {private_spool}\n",
        encoding="utf-8",
    )
    with pytest.raises(TableMappingError) as catalog_error:
        build_initial_state(
            csv_path=None,
            table_mappings=(),
            start_dir=project_root,
        )

    assert handled_as_source is False
    assert direct_sources == ()
    assert catalog_error.value.message == (
        "Private TUI result artifacts cannot be used as sources."
    )
    assert catalog_error.value.suggestion == ("Use Save as source to create a normal CSV source.")
    assert stored.handle.sequence == 1
    assert private_spool.read_bytes() == spool_bytes


def test_save_result_as_source_writes_full_output_from_spilled_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_path = tmp_path / ".csvql" / "results" / "large_rows.csv"
    rows = tuple((index,) for index in range(10001))
    stored_result = QueryResult(columns=("id",), rows=rows, elapsed_ms=1.0)
    state = TUISessionState()
    monkeypatch.setattr("csvql.tui_app.run_tui_request", _reject_query_execution)
    monkeypatch.setattr("csvql.tui_workflows.CSVQLEngine", _reject_query_execution)

    async def _inner() -> tuple[tuple[TUISource, ...], str | None, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            handle = _store_complete_result(app._result_store, stored_result, sequence=1).handle
            view = make_result_view_state(stored_result, source_result_sequence=1)
            app.state.record_query_success(
                1,
                "SELECT * FROM large",
                handle=handle,
                result_view=view,
                elapsed_ms=stored_result.elapsed_ms,
            )
            app._refresh_results_display()
            assert app.state.active_query_result_record() is not None

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
            origin="derived",
            kind="csv",
        ),
    )
    assert selected_alias == "large_rows"
    assert "Saved result as derived source large_rows" in status
    assert "Showing 1,000 retained preview row(s) from 10,001 total row(s)." in message
    assert content.splitlines()[0] == "id"
    assert len(content.splitlines()) == 10002
    assert content.splitlines()[1] == "0"
    assert content.splitlines()[-1] == "10000"


def test_export_uses_recalled_history_result(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore()
    first_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT 'first' AS label",
        store=store,
    )
    second_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        sequence=second_sequence,
        sql="SELECT 'second' AS label",
        store=store,
    )
    export_path = tmp_path / "exports" / "recalled.csv"
    export_path.parent.mkdir()

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            app._show_history_result_at_row(0)
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
    store = TUIResultStore()
    first_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT 'first' AS label",
        store=store,
        run_mode="buffer",
        buffer_result_index=1,
    )
    second_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        sequence=second_sequence,
        sql="SELECT 'second' AS label",
        store=store,
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
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
                _active_stored_rows(app),
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
            origin="derived",
            kind="csv",
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
        app = CSVQLMenuApp(initial_state=_make_source_state(tmp_path), start_dir=tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.action_save_result_as_source()
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
    store = _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=12.345,
        ),
        sequence=1,
        sql="SELECT customer_id, email FROM customers",
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str | None, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
            origin="derived",
            kind="csv",
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
    store = TUIResultStore()
    first_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT 'first' AS label",
        store=store,
    )
    second_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        sequence=second_sequence,
        sql="SELECT 'second' AS label",
        store=store,
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
                output_path.read_text(encoding="utf-8") if output_path.exists() else "",
            )

    sources, status, content = asyncio.run(_inner())

    assert content, status
    assert sources[-1] == TUISource(
        name="recalled_first",
        path=(tmp_path / ".csvql" / "results" / "recalled_first.csv").resolve(),
        origin="derived",
        kind="csv",
    )
    assert "Saved result as derived source recalled_first" in status
    assert content == "label\nfirst\n"


@pytest.mark.parametrize("key", ["ctrl+s", "alt+s"])
def test_save_result_source_shortcuts(tmp_path: Path, key: str) -> None:
    state = TUISessionState()
    store = _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id",),
            rows=(("CUST-001",),),
            elapsed_ms=12.345,
        ),
        sequence=1,
        sql="SELECT customer_id FROM customers",
    )

    async def _inner() -> tuple[tuple[TUISource, ...], str | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
            origin="derived",
            kind="csv",
        ),
    )
    assert selected_alias == "customer_ids"
    assert content == "customer_id\nCUST-001\n"


def test_save_result_as_source_refuses_after_no_result_statement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0),
        sequence=state.reserve_query_sequences(1)[0],
        sql="SELECT 'stale' AS old",
    )

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        event_sink(TUINoResultEvent(sequence=request.sequences[0], elapsed_ms=4.0))

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("CREATE TABLE scratch(id INTEGER)")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            app.action_save_result_as_source()
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
    store = _record_stored_result(
        state,
        QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT 1 AS id",
    )

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = TUIResultStore()
    _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-001", "alex@example.com"),),
            elapsed_ms=1.0,
        ),
        sequence=1,
        sql="SELECT * FROM alpha",
        store=store,
    )
    _record_stored_result(
        state,
        QueryResult(
            columns=("customer_id", "email"),
            rows=(("CUST-002", "bob@example.com"),),
            elapsed_ms=2.0,
        ),
        sequence=2,
        sql="SELECT * FROM beta",
        store=store,
    )

    async def _inner() -> str | None:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("saved",),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 'saved' AS label",
    )

    async def _inner() -> tuple[object | None, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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


def test_help_screen_renders_current_workbench_help_text(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            return app.screen.query_one("#help-text", Static).content

    help_text = asyncio.run(_inner())

    assert help_text == WORKBENCH_HELP


def test_tui_guide_documents_portable_fallbacks_and_run_labels() -> None:
    guide = _read_doc_text("docs/tui-guide.md")

    assert "| `F7` | Export active result |" in guide
    assert "| `F12` or `Ctrl+B` | Run the buffer as separate History rows |" in guide
    assert "| `F3` or `Ctrl+O` | Choose CSV file(s) or prompt for paths |" in guide
    assert "| `F9` or `q` | Quit outside text entry |" in guide
    assert "The History run column labels entries as `current` for F4/Ctrl+R runs," in guide
    assert "`buffer` for F12/Ctrl+B runs" in guide
    assert "`rerun` for History reruns." in guide


def test_troubleshooting_documents_menu_entry_points() -> None:
    troubleshooting = _read_doc_text("docs/troubleshooting.md")

    assert "Use `F4` or `Ctrl+R` to run the current SQL." in troubleshooting
    assert "`F3` opens a native CSV picker on macOS." in troubleshooting
    assert "`Ctrl+O` opens the path prompt on every" in troubleshooting
    assert "platform." in troubleshooting
    assert "[Terminal menu guide](tui-guide.md)" in troubleshooting


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


def test_tui_guide_documents_source_intelligence_keymap() -> None:
    guide = _read_doc_text("docs/tui-guide.md")

    assert "| `i` | Inspect selected source and load columns |" in guide
    assert "| `c` | Load or show source columns |" in guide
    assert "| `l` | Insert selected source alias into SQL |" in guide
    assert "| `x` | Open starter SQL templates |" in guide


def test_help_text_documents_sql_assistance_keymap() -> None:
    from csvql.tui_help import WORKBENCH_HELP

    assert "Tab                 Complete SQL if available, otherwise indent" in WORKBENCH_HELP
    assert (
        "Ctrl+Space          Alternate SQL completion where terminal supports it" in WORKBENCH_HELP
    )
    assert "x                   Open starter SQL templates" in WORKBENCH_HELP
    assert "i                   Inspect selected source and load columns" in WORKBENCH_HELP


def test_completion_docs_describe_tab_primary_and_ctrl_space_secondary() -> None:
    from csvql.tui_help import WORKBENCH_HELP

    guide_text = _read_doc_text("docs/tui-guide.md")
    guide = _normalized_markdown_text(guide_text)
    guide_source_actions = _normalized_markdown_text(
        guide_text[
            guide_text.index("When the Sources pane is focused:") : guide_text.index(
                "The Add source prompt accepts"
            )
        ]
    )

    assert "Tab                 Complete SQL if available, otherwise indent" in WORKBENCH_HELP
    assert (
        "Ctrl+Space          Alternate SQL completion where terminal supports it" in WORKBENCH_HELP
    )
    assert "| `Tab` |" not in guide_source_actions
    assert "| `Ctrl+Space` |" not in guide_source_actions
    assert "`Tab` is the primary SQL-editor completion key." in guide
    assert "Pane focus stays on `F2`, `F5`, `F6`, and `F8`." in guide
    assert "`Ctrl+Space` remains available where the terminal delivers it." in guide


def test_tui_guide_documents_deterministic_sql_assistance() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))

    assert (
        "When completion items are available, it opens the completion list; "
        "otherwise it inserts four spaces and keeps focus in the SQL editor." in guide
    )
    assert "`Ctrl+Space` remains available where the terminal delivers it." in guide
    assert "| `x` | Open starter SQL templates |" in guide
    assert "Generated SQL is editable and does not execute automatically" in guide
    assert "natural-language" not in guide.lower()


def test_tui_guide_documents_completion_and_templates_without_ai_claims() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))

    assert "`Tab` is the primary SQL-editor completion key." in guide
    assert "it opens the completion list; otherwise it inserts four spaces" in guide
    assert "`Ctrl+Space` remains available where the terminal delivers it." in guide
    assert "column-aware templates appear after `c` or `i` loads metadata" in guide
    assert "Generated SQL is editable and does not execute automatically" in guide
    assert "AI insight" not in guide


def test_tui_guide_documents_editor_quality_keymap() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))

    assert "| `F4` or `Ctrl+R` | Run selected SQL or the current statement |" in guide
    assert "| `F12` or `Ctrl+B` | Run the buffer as separate History rows |" in guide
    assert "runs the selected or current statement in a fresh DuckDB session" in guide
    assert "`current` for F4/Ctrl+R runs" in guide
    assert "`buffer` for F12/Ctrl+B runs, and `rerun` for History reruns." in guide


def test_tui_guide_documents_history_rerun_keymap() -> None:
    guide = _normalized_markdown_text(_read_doc_text("docs/tui-guide.md"))

    assert "History" in guide
    assert "`Enter` reopens a query in the editor" in guide
    assert "`r` reruns a query against the current session sources" in guide


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
            await _settled_operation_idle(pilot, app)

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
    reopened_sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("reopened",), rows=((99,),), elapsed_ms=1.0),
        sequence=reopened_sequence,
        sql="SELECT 99 AS reopened",
    )

    async def _inner() -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    previous_sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0),
        sequence=previous_sequence,
        sql="SELECT 'stale' AS old",
    )

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        event_sink(TUINoResultEvent(sequence=request.sequences[0], elapsed_ms=4.0))

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[bool, str, str, tuple[int, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("CREATE TABLE scratch(id INTEGER)")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            status = app.query_one("#status", Static).content
            message = app.query_one("#results-message", Static).content
            return (
                app.state.has_active_result,
                status,
                message,
                tuple(item.sequence for item in app.state.query_history),
            )

    has_active_result, status, message, history_sequences = asyncio.run(_inner())

    assert has_active_result is False
    assert "no tabular result" in status
    assert "no tabular result" in message
    assert app_history_statuses(state) == ["success", "no_result"]
    assert app_history_run_modes(state) == ["current", "current"]
    assert history_sequences == (1, 2)


@pytest.mark.parametrize(
    "action_name",
    [
        "action_export_last_result",
        "action_save_result_as_source",
    ],
)
def test_preview_only_result_refuses_export_and_save_without_loading_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    store = TUIResultStore(temp_root=tmp_path)
    sql_execution_calls: list[tuple[object, ...]] = []
    _record_preview_only_result(
        state,
        store,
        sequence=sequence,
        sql="SELECT 1 AS value",
        preview=BoundedQueryResult(
            columns=("value",),
            rows=((1,),),
            elapsed_ms=1.0,
            preview_payload_bytes=len(encode_row_payload((1,))),
            has_more_rows=False,
            truncation_reason=None,
        ),
    )

    def fail_if_loaded(handle: object) -> object:
        raise AssertionError(f"preview-only rows must not be loaded: {handle!r}")

    def fail_if_sql_executes(*args: object, **kwargs: object) -> None:
        sql_execution_calls.append((*args, kwargs))
        raise AssertionError("preview-only export/save must not execute SQL")

    monkeypatch.setattr(store, "open_rows", fail_if_loaded)
    monkeypatch.setattr(tui_app_module, "run_tui_request", fail_if_sql_executes)
    monkeypatch.setattr(CSVQLEngine, "stream", fail_if_sql_executes)

    async def _inner() -> tuple[str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            getattr(app, action_name)()
            await pilot.pause()
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.has_active_result,
            )

    status, message, has_active_result = asyncio.run(_inner())

    assert "Full export/save are unavailable for this result." in status
    assert "Full export/save are unavailable for this result." in message
    assert has_active_result is True
    assert sql_execution_calls == []


@pytest.mark.parametrize("focus", ["results", "history"])
def test_delete_result_requires_confirmed_identity_and_preserves_other_handles(
    tmp_path: Path,
    focus: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    first_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT 'first' AS label",
        store=store,
    )
    second_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("second",),), elapsed_ms=1.0),
        sequence=second_sequence,
        sql="SELECT 'second' AS label",
        store=store,
    )

    target_sequence = first_sequence if focus == "history" else second_sequence
    preserved_sequence = second_sequence if focus == "history" else first_sequence

    async def _inner() -> tuple[bool, bool, tuple[tuple[object, ...], ...] | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            if focus == "history":
                history = app.query_one("#history", DataTable)
                history.focus()
                history.move_cursor(row=0)
                app._show_history_result_at_row(0)
            else:
                results = app.query_one("#results", DataTable)
                results.focus()
            await pilot.pause()

            app.action_delete_result()
            await pilot.pause()
            confirmation = app.screen.query_one("#confirm-text", Static).content

            if focus == "history":
                history = app.query_one("#history", DataTable)
                history.move_cursor(row=1)
                app._show_history_result_at_row(1)
            await pilot.press("y")
            await pilot.pause()

            remaining = app.state.query_result_record(preserved_sequence)
            preserved_rows = None
            if remaining is not None and remaining.handle is not None:
                source = app._result_store.open_rows(remaining.handle)
                preserved_rows = tuple(source.iter_rows())
            return (
                app.state.query_result_record(target_sequence) is None,
                remaining is not None,
                preserved_rows,
                confirmation,
            )

    removed, preserved, preserved_rows, confirmation = asyncio.run(_inner())

    assert removed is True
    assert preserved is True
    expected_rows = (("second",),) if focus == "history" else (("first",),)
    assert preserved_rows == expected_rows
    assert str(target_sequence) in confirmation


def test_delete_result_cancel_keeps_selected_record_and_store_handle(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 'first' AS label",
        store=store,
    )

    async def _inner() -> tuple[bool, tuple[tuple[object, ...], ...] | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_delete_result()
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            record = app.state.query_result_record(sequence)
            if record is None or record.handle is None:
                return False, None
            source = app._result_store.open_rows(record.handle)
            return True, tuple(source.iter_rows())

    kept, rows = asyncio.run(_inner())

    assert kept is True
    assert rows == (("first",),)


def test_delete_key_does_not_remove_results_while_sources_is_focused(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=state.reserve_query_sequences(1)[0],
        sql="SELECT 'first' AS label",
    )

    async def _inner() -> tuple[str, bool, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.pause()
            await pilot.press("delete")
            await pilot.pause()
            return (
                type(app.screen).__name__,
                app.state.active_query_result_record() is not None,
                app.query_one("#sources", DataTable).row_count,
            )

    screen_name, has_active_result, source_count = asyncio.run(_inner())

    assert screen_name == "Screen"
    assert has_active_result is True
    assert source_count == 1


@pytest.mark.parametrize("lifecycle_state", ["executing", "preserving"])
def test_delete_result_is_disabled_for_non_terminal_result_lifecycle(
    tmp_path: Path,
    lifecycle_state: str,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    executing = TUIResultRecord(
        handle=None,
        state="executing",
        reason=None,
        columns=(),
        preview_row_count=0,
        full_row_count=None,
        elapsed_ms=0.0,
    )
    state.set_active_result_record(sequence, executing)
    if lifecycle_state == "preserving":
        preview_result = QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0)
        preserving = TUIResultRecord(
            handle=None,
            state="preserving",
            reason=None,
            columns=preview_result.columns,
            preview_row_count=len(preview_result.rows),
            full_row_count=None,
            elapsed_ms=preview_result.elapsed_ms,
        )
        state.set_active_result_record(
            sequence,
            preserving,
            result_view=make_result_view_state(
                preview_result,
                source_result_sequence=sequence,
            ),
        )

    async def _inner() -> tuple[bool, str, str | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#results", DataTable).focus()
            await pilot.pause()
            enabled = app.check_action("delete_result", ())
            app.action_delete_result()
            await pilot.pause()
            record = app.state.active_query_result_record()
            return enabled, type(app.screen).__name__, None if record is None else record.state

    enabled, screen_name, observed_state = asyncio.run(_inner())

    assert enabled is False
    assert screen_name == "Screen"
    assert observed_state == lifecycle_state


def test_delete_result_discards_memory_only_preview_without_store_remove(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=False,
        truncation_reason=None,
    )
    state.active_result = TUIActiveResultState(
        kind="query",
        label=f"Active result: query {sequence}",
        sequence=sequence,
    )
    state._active_result_record = TUIResultRecord(
        handle=None,
        state="preview_only",
        reason="preservation_failed",
        columns=preview.columns,
        preview_row_count=len(preview.rows),
        full_row_count=None,
        elapsed_ms=preview.elapsed_ms,
    )
    state.result_view = make_result_view_state(
        QueryResult(columns=preview.columns, rows=preview.rows, elapsed_ms=preview.elapsed_ms),
        source_result_sequence=sequence,
    )
    remove_calls: list[object] = []
    store = TUIResultStore(temp_root=tmp_path)
    monkeypatch.setattr(store, "remove", lambda handle: remove_calls.append(handle))

    async def _inner() -> tuple[bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#results", DataTable).focus()
            await pilot.pause()
            app.action_delete_result()
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            return app.state.active_query_result_record() is None, app.query_one(
                "#status", Static
            ).content

    deleted, status = asyncio.run(_inner())

    assert deleted is True
    assert remove_calls == []
    assert "Deleted preserved result" in status


def test_delete_result_storage_failure_marks_result_unavailable_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TUISessionState()
    store = _record_stored_result(
        state,
        QueryResult(columns=("label",), rows=(("first",),), elapsed_ms=1.0),
        sequence=state.reserve_query_sequences(1)[0],
        sql="SELECT 'first' AS label",
    )
    record = state.active_query_result_record()
    assert record is not None and record.handle is not None

    def fail_remove(handle: object) -> None:
        del handle
        raise TUIResultStorageError(
            "The full result is no longer available because its temporary storage was lost.",
            kind="result_unavailable",
            invalidated_sequences=(record.handle.sequence,),
        )

    monkeypatch.setattr(store, "remove", fail_remove)

    async def _inner() -> tuple[bool, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#results", DataTable).focus()
            await pilot.pause()
            app.action_delete_result()
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            return (
                app.state.active_query_result_record() is None,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    deleted, status, message = asyncio.run(_inner())

    assert deleted is True
    assert "temporary storage was lost" in status
    assert "temporary storage was lost" in message


@pytest.mark.parametrize(
    ("action_name", "input_selector"),
    [
        ("action_export_last_result", "#export-path"),
        ("action_save_result_as_source", "#derived-source-alias"),
    ],
)
def test_full_result_rows_are_not_opened_before_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
    input_selector: str,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
    )
    monkeypatch.setattr(
        store,
        "open_rows",
        Mock(
            side_effect=TUIResultStorageError(
                "The full result is no longer available.",
                kind="result_unavailable",
                invalidated_sequences=(sequence,),
            )
        ),
    )

    async def run_case() -> tuple[TUIResultRecord | None, bool, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            getattr(app, action_name)()
            await pilot.pause()
            app.screen.query_one(input_selector, Input)
            await pilot.press("escape")
            await pilot.pause()
            return (
                app.state.query_result_record(sequence),
                app.state.operation_run.is_running,
                store.open_rows.call_count,  # type: ignore[attr-defined]
            )

    record, operation_running, open_calls = asyncio.run(run_case())

    assert record is not None
    assert operation_running is False
    assert open_calls == 0


def test_streaming_export_close_failure_does_not_mask_primary_iteration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
    )
    close_calls = {"count": 0}

    class _FailingIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise RuntimeError("primary iteration failure")

        def close(self) -> None:
            close_calls["count"] += 1
            raise RuntimeError("close failure")

    class _FailingRows:
        columns = ("value",)
        elapsed_ms = 1.0

        def iter_rows(self):
            return _FailingIterator()

    monkeypatch.setattr(store, "open_rows", Mock(return_value=_FailingRows()))

    async def run_case() -> tuple[bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f7")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = "failed-export.csv"
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)
            return (
                app.state.query_result_record(sequence) is not None,
                app.query_one("#status", Static).content,
            )

    preserved, status = asyncio.run(run_case())

    assert close_calls["count"] == 1
    assert preserved is True
    assert "Unable to complete this action" in status
    assert "close failure" not in status
    assert not (tmp_path / "failed-export.csv").exists()


@pytest.mark.parametrize(
    ("action_key", "input_selector", "input_value"),
    [
        ("f7", "#export-path", "race-export.csv"),
        ("f11", "#derived-source-alias", "race_saved_result"),
    ],
    ids=("export", "save-result"),
)
def test_full_result_load_failure_during_stream_marks_result_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_key: str,
    input_selector: str,
    input_value: str,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
    )
    load_error = TUIResultStorageError(
        "The full result is no longer available.",
        kind="result_unavailable",
        invalidated_sequences=(sequence,),
    )

    open_rows = Mock(side_effect=load_error)
    monkeypatch.setattr(store, "open_rows", open_rows)

    async def run_case() -> tuple[TUIResultRecord | None, str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(action_key)
            await pilot.pause()
            prompt_input = app.screen.query_one(input_selector, Input)
            prompt_input.value = input_value
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)
            return (
                app.state.query_result_record(sequence),
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    record, status, message, operation_running = asyncio.run(run_case())

    assert record is None
    assert "no longer available" in status.lower()
    assert "no longer available" in message.lower()
    assert operation_running is False
    assert open_rows.call_count == 1
    assert state.sources == ()
    assert not (tmp_path / "race-export.csv").exists()
    assert not (tmp_path / ".csvql" / "results" / "race_saved_result.csv").exists()


def _two_spilled_buffer_results(
    tmp_path: Path,
) -> tuple[TUISessionState, TUIResultStore, tuple[int, int]]:
    state = TUISessionState()
    store = TUIResultStore(temp_root=tmp_path, session_id="a" * 32)
    sequences = list(state.reserve_query_sequences(2))
    for value, sequence in zip((1, 2), sequences, strict=True):
        sql = f"SELECT {value} AS value"
        _record_stored_result(
            state,
            QueryResult(columns=("value",), rows=((value,),), elapsed_ms=1.0),
            sequence=sequence,
            sql=sql,
            store=store,
            run_mode="buffer",
            buffer_result_index=value,
        )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=sequences[0], index=1, label="query 1"),
            TUIBufferResultTab(sequence=sequences[1], index=2, label="query 2"),
        ),
        selected_sequence=sequences[1],
    )
    return state, store, (sequences[0], sequences[1])


@pytest.mark.parametrize(
    ("action_name", "input_selector"),
    [
        ("action_export_last_result", "#export-path"),
        ("action_save_result_as_source", "#derived-source-alias"),
    ],
)
def test_lost_workspace_is_not_inspected_before_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
    input_selector: str,
) -> None:
    state, store, sequences = _two_spilled_buffer_results(tmp_path)
    workspace = store.workspace_path
    assert workspace is not None
    if os.name == "nt":
        assert store._close_active_lease()
    shutil.rmtree(workspace)

    async def run_case() -> bool:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            getattr(app, action_name)()
            await pilot.pause()
            app.screen.query_one(input_selector, Input)
            await pilot.press("escape")
            await pilot.pause()
            return app.state.operation_run.is_running

    operation_running = asyncio.run(run_case())

    for sequence in sequences:
        record = state.query_result_record(sequence)
        assert record is not None
    assert operation_running is False


@pytest.mark.parametrize(
    ("action_key", "input_selector", "input_value"),
    [
        ("f7", "#export-path", "lost-workspace.csv"),
        ("f11", "#derived-source-alias", "lost_workspace_result"),
    ],
    ids=("export", "save-result"),
)
def test_lost_workspace_after_prompt_marks_all_spilled_siblings_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_key: str,
    input_selector: str,
    input_value: str,
) -> None:
    state, store, sequences = _two_spilled_buffer_results(tmp_path)
    workspace = store.workspace_path
    assert workspace is not None

    async def run_case() -> tuple[str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(action_key)
            await pilot.pause()
            if os.name == "nt":
                assert store._close_active_lease()
            shutil.rmtree(workspace)
            app.screen.query_one(input_selector, Input).value = input_value
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    status, message, operation_running = asyncio.run(run_case())

    for sequence in sequences:
        assert state.query_result_record(sequence) is None
    assert "no longer available" in status.lower()
    assert "no longer available" in message.lower()
    assert operation_running is False
    assert not (tmp_path / "lost-workspace.csv").exists()
    assert not (tmp_path / ".csvql" / "results" / "lost_workspace_result.csv").exists()


@pytest.mark.parametrize(
    ("action_key", "input_selector", "input_value"),
    [
        ("f7", "#export-path", "corrupt-before-prompt.csv"),
        ("f11", "#derived-source-alias", "corrupt_before_prompt_result"),
    ],
    ids=("export", "save-result"),
)
def test_corrupt_spill_import_error_before_prompt_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_key: str,
    input_selector: str,
    input_value: str,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
        store=store,
    )
    workspace = store.workspace_path
    assert workspace is not None
    result_paths = tuple(workspace.glob("query-*.result"))
    assert len(result_paths) == 1
    result_paths[0].write_bytes(b"cno_such_localql_module\nMissing\n.")

    async def run_case() -> tuple[str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(action_key)
            await pilot.pause()
            app.screen.query_one(input_selector, Input).value = input_value
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    status, message, operation_running = asyncio.run(run_case())

    assert state.query_result_record(sequence) is None
    assert "no longer available" in status.lower()
    assert "no_such_localql_module" not in status
    assert "no_such_localql_module" not in message
    assert str(tmp_path) not in status
    assert operation_running is False
    assert not (tmp_path / "corrupt-before-prompt.csv").exists()
    assert not (tmp_path / ".csvql" / "results" / "corrupt_before_prompt_result.csv").exists()


@pytest.mark.parametrize(
    ("action_key", "input_selector", "input_value"),
    [
        ("f7", "#export-path", "corrupt-spill.csv"),
        ("f11", "#derived-source-alias", "corrupt_spill_result"),
    ],
    ids=("export", "save-result"),
)
def test_corrupt_spill_import_error_after_prompt_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_key: str,
    input_selector: str,
    input_value: str,
) -> None:
    state = TUISessionState()
    sequence = state.reserve_query_sequences(1)[0]
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=sequence,
        sql="SELECT 1 AS value",
        store=store,
    )
    workspace = store.workspace_path
    assert workspace is not None
    result_paths = tuple(workspace.glob("query-*.result"))
    assert len(result_paths) == 1

    async def run_case() -> tuple[str, str, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(action_key)
            await pilot.pause()
            result_paths[0].write_bytes(b"cno_such_localql_module\nMissing\n.")
            app.screen.query_one(input_selector, Input).value = input_value
            await pilot.press("enter")
            await _settled_operation_idle(pilot, app)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.state.operation_run.is_running,
            )

    status, message, operation_running = asyncio.run(run_case())

    assert state.query_result_record(sequence) is None
    assert "no longer available" in status.lower()
    assert "no_such_localql_module" not in status
    assert "no_such_localql_module" not in message
    assert operation_running is False
    assert not (tmp_path / "corrupt-spill.csv").exists()
    assert not (tmp_path / ".csvql" / "results" / "corrupt_spill_result.csv").exists()


def test_spill_failure_preserves_prior_preview_and_disables_full_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    previous_sequence = state.reserve_query_sequences(1)[0]
    store = TUIResultStore(temp_root=tmp_path)
    preview = BoundedQueryResult(
        columns=("previous_value",),
        rows=(("prior-row-value",),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload(("prior-row-value",))),
        has_more_rows=False,
        truncation_reason=None,
    )
    _record_preview_only_result(
        state,
        store,
        sequence=previous_sequence,
        sql="SELECT 1 AS previous_value",
        preview=preview,
        run_mode="buffer",
        buffer_result_index=1,
    )
    previous_tabs = (TUIBufferResultTab(sequence=previous_sequence, index=1, label="query 1"),)
    state.set_buffer_result_tabs(previous_tabs, selected_sequence=previous_sequence)
    storage_message = "Unable to use secure temporary result storage."

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        _emit_failed_event(
            sequence=request.sequences[0],
            event_sink=event_sink,
            error_message=storage_message,
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def run_case() -> tuple[
        TUIResultRecord | None,
        TUIResultRecord | None,
        object,
        object,
        tuple[TUIBufferResultTab, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[int, ...],
        str,
        str,
        str,
        str,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            previous_active = app.state.active_result
            app.query_one("#sql", TextArea).load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            status = app.query_one("#status", Static).content
            failed_message = app.query_one("#results-message", Static).content
            run_status = app.query_one("#run-status", Static).content
            active_after_failure = app.state.active_result
            app._show_history_result_at_row(0)
            history_message = app.query_one("#results-message", Static).content
            return (
                app.state.query_result_record(previous_sequence),
                app.state.query_result_record(previous_sequence + 1),
                active_after_failure,
                previous_active,
                app.state.buffer_result_tabs,
                tuple(item.status for item in app.state.query_history),
                tuple(item.run_mode for item in app.state.query_history),
                tuple(item.sequence for item in app.state.query_history),
                status,
                failed_message,
                history_message,
                run_status,
                _focused_widget_id(app),
            )

    (
        previous_record,
        failed_record,
        active_result,
        _previous_active,
        tabs,
        history_statuses,
        history_run_modes,
        history_sequences,
        status,
        failed_message,
        history_message,
        run_status,
        focused_widget,
    ) = asyncio.run(run_case())

    assert previous_record is not None
    assert previous_record.state == "preview_only"
    assert failed_record is None
    assert active_result.kind == "none"
    assert tabs == ()
    assert history_statuses == ("success", "error")
    assert history_run_modes == ("buffer", "current")
    assert history_sequences == (previous_sequence, previous_sequence + 1)
    assert status == f"Error: {storage_message}"
    assert failed_message == f"Error: {storage_message}"
    assert "History query 1." in history_message
    assert run_status == "Ready."
    assert focused_widget == "sql"
    for unsafe_text in (
        "prior-row-value",
        "new-secret-row-value",
        "private path",
        str(tmp_path),
        *(f"private_column_{index}" for index in range(20)),
    ):
        assert unsafe_text not in status
        assert unsafe_text not in failed_message


def test_rerun_storage_failure_preserves_selection_and_records_rerun_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    first_sequence = state.reserve_query_sequences(1)[0]
    previous = QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0)
    previous_view = make_result_view_state(previous, source_result_sequence=first_sequence)
    store = TUIResultStore(temp_root=tmp_path)
    previous_stored = _store_complete_result(store, previous, sequence=first_sequence)
    state.record_query_success(
        first_sequence,
        "SELECT COUNT(*) AS count FROM customers",
        handle=previous_stored.handle,
        result_view=previous_view,
        elapsed_ms=previous.elapsed_ms,
    )

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        _emit_failed_event(
            sequence=request.sequences[0],
            event_sink=event_sink,
            error_message="Unable to use secure temporary result storage.",
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def run_case() -> tuple[object, object, tuple[object, ...], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            previous_active = app.state.active_result
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.press("r")
            await _settled_query_idle(pilot, app)
            return (
                app.state.active_result,
                previous_active,
                app.state.query_history,
                app.query_one("#run-status", Static).content,
                _focused_widget_id(app),
                app.query_one("#status", Static).content,
            )

    active_result, _previous_active, history, run_status, focused_widget, status = asyncio.run(
        run_case()
    )
    history_sequences = tuple(item.sequence for item in history)

    assert history_sequences == (first_sequence, first_sequence + 1)
    assert len(set(history_sequences)) == 2
    assert tuple(item.status for item in history) == ("success", "error")
    assert tuple(item.run_mode for item in history) == ("current", "rerun")
    assert active_result.kind == "none"
    assert state.result_view.columns == ()
    assert state.query_result_record(first_sequence) is not None
    assert state.query_result_record(first_sequence + 1) is None
    assert state.buffer_result_tabs == ()
    assert run_status == "Ready."
    assert focused_widget == "sql"
    assert status == "Error: Unable to use secure temporary result storage."
    assert "private path" not in status
    assert str(tmp_path) not in status


@pytest.mark.parametrize(
    ("spill_previous", "failure_kind"),
    [
        (True, "capacity"),
        (False, "workspace_unavailable"),
    ],
    ids=("healthy-spilled-storage", "lost-workspace-with-in-memory-result"),
)
def test_storage_failure_keeps_usable_prior_result_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spill_previous: bool,
    failure_kind: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    previous_sequence = state.reserve_query_sequences(1)[0]
    previous = QueryResult(columns=("value",), rows=(("previous",),), elapsed_ms=1.0)
    previous_outcome = _store_complete_result(store, previous, sequence=previous_sequence)
    previous_view = make_result_view_state(previous, source_result_sequence=previous_sequence)
    state.record_query_success(
        previous_sequence,
        "SELECT 'previous' AS value",
        handle=previous_outcome.handle,
        result_view=previous_view,
        elapsed_ms=previous.elapsed_ms,
    )
    storage_message = "Unable to store the query result."

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        _emit_failed_event(
            sequence=request.sequences[0],
            event_sink=event_sink,
            error_message=storage_message,
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def run_case() -> tuple[TUIResultRecord | None, object, bool, str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 'failed' AS value")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            record = app.state.query_result_record(previous_sequence)
            assert record is not None
            loaded = tuple(app._result_store.open_rows(record.handle).iter_rows())
            return (
                record,
                loaded,
                app.state.has_active_result,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
            )

    record, loaded, has_active_result, status, message, run_status = asyncio.run(run_case())

    assert record is not None
    assert record.state == "complete"
    assert loaded == previous.rows
    assert has_active_result is False
    assert state.query_result_record(previous_sequence) is not None
    assert state.query_result_record(previous_sequence + 1) is None
    assert tuple(item.status for item in state.query_history) == ("success", "error")
    assert status == f"Error: {storage_message}"
    assert message == f"Error: {storage_message}"
    assert run_status == "Ready."


def test_storage_failure_without_prior_result_keeps_no_active_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        _emit_failed_event(
            sequence=request.sequences[0],
            event_sink=event_sink,
            error_message="Unable to write the query result to temporary storage.",
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def run_case() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 'failed' AS value")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            return (
                app.query_one("#run-status", Static).content,
                app.query_one("#status", Static).content,
            )

    run_status, status = asyncio.run(run_case())

    assert state.has_active_result is False
    assert state.result_view.columns == ()
    assert state.query_result_record(1) is None
    assert tuple(item.status for item in state.query_history) == ("error",)
    assert state.query_history[0].run_mode == "current"
    assert run_status == "Ready."
    assert status == "Error: Unable to write the query result to temporary storage."


def test_successful_storage_applies_prior_workspace_invalidations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    previous_sequence = state.reserve_query_sequences(1)[0]
    previous = QueryResult(columns=("value",), rows=(("previous",),), elapsed_ms=1.0)
    previous_stored = _store_complete_result(store, previous, sequence=previous_sequence)
    state.record_query_success(
        previous_sequence,
        "SELECT 'previous' AS value",
        handle=previous_stored.handle,
        result_view=make_result_view_state(
            previous,
            source_result_sequence=previous_sequence,
        ),
        elapsed_ms=previous.elapsed_ms,
    )
    state.mark_results_unavailable((previous_sequence,), "The full result is no longer available.")

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=(("new",),), elapsed_ms=2.0),
            sequence=request.sequences[0],
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def run_case() -> tuple[TUIResultRecord | None, TUIResultRecord | None, int | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 'new' AS value")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            return (
                app.state.query_result_record(previous_sequence),
                app.state.query_result_record(previous_sequence + 1),
                app.state.active_result.sequence,
            )

    previous_record, new_record, active_sequence = asyncio.run(run_case())

    assert previous_record is None
    assert new_record is not None
    assert new_record.state == "complete"
    assert active_sequence == previous_sequence + 1


def test_error_outcome_records_run_mode_and_marks_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        _emit_failed_event(
            sequence=request.sequences[0],
            event_sink=event_sink,
            error_message="boom",
            suggestion="Try again.",
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
            return (
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    status, message = asyncio.run(_inner())

    assert "boom" in status
    assert "boom" in message
    assert app_history_statuses(state) == ["error"]
    assert app_history_run_modes(state) == ["current"]


def test_unexpected_worker_failure_sanitizes_details_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    sentinel = (
        "private_path=/tmp/customer-results.csv "
        "result=alex@example.com detail=internal-worker-state"
    )
    calls = {"count": 0}

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError(sentinel)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(
                columns=("row_count",),
                rows=((2,),),
                elapsed_ms=1.0,
            ),
            sequence=request.sequences[0],
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        bool,
        str,
        str,
        str,
        object | None,
        list[str],
        str | None,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            first_status = app.query_one("#status", Static).content
            first_message = app.query_one("#results-message", Static).content
            run_status = app.query_one("#run-status", Static).content

            sql.load_text("SELECT COUNT(*) AS row_count FROM customers")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            second_status = app.query_one("#status", Static).content
            return (
                app.state.query_run.is_running,
                first_status,
                first_message,
                run_status,
                app.state.has_active_result,
                app_history_statuses(app.state),
                app.state.query_history[0].error_message,
                second_status,
            )

    (
        is_running,
        first_status,
        first_message,
        run_status,
        has_active_result,
        history_statuses,
        first_history_error,
        second_status,
    ) = asyncio.run(_inner())

    assert is_running is False
    assert first_status == "Error: Unable to complete the query. Try running it again."
    assert first_message == first_status
    assert first_history_error == "Unable to complete the query. Try running it again."
    assert sentinel not in first_status
    assert sentinel not in first_message
    assert sentinel not in first_history_error
    assert run_status == "Ready."
    assert has_active_result is True
    assert history_statuses == ["error", "success"]
    assert app_history_run_modes(state) == ["current", "current"]
    assert "1 returned row(s)" in second_status


def test_sample_after_query_clears_exportable_result_and_export_refuses(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[bool, tuple[str, ...], str, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)

            app.query_one("#sources", DataTable).focus()
            await pilot.press("s")
            await _settled_operation_idle(pilot, app)

            app.action_export_last_result()
            await pilot.pause()

            return (
                app.state.has_active_result,
                app.state.result_view.columns,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
                app.query_one("#run-status", Static).content,
            )

    has_active_result, result_view_columns, status, message, run_status = asyncio.run(_inner())

    assert has_active_result is False
    assert result_view_columns == ()
    assert "Run a query before exporting." in status
    assert "Run a query before exporting." in message
    assert run_status == "Ready."


def test_queued_run_buffer_uses_one_immutable_captured_request_after_worker_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    worker_started = threading.Event()
    release_worker = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    event_order: list[str] = []
    first_worker: list[object] = []
    prior_worker_finished_at_queue_start: list[bool] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        event_order.append(f"query-{request.sequences[0]}-start")
        if len(seen_requests) == 1:
            event_sink(
                TUIPreviewReadyEvent(
                    sequence=request.sequences[0],
                    preview=BoundedQueryResult(
                        columns=("customer_id",),
                        rows=(("CUST-001",),),
                        elapsed_ms=1.0,
                        preview_payload_bytes=len(encode_row_payload(("CUST-001",))),
                        has_more_rows=True,
                        truncation_reason="row_limit",
                    ),
                )
            )
            worker_started.set()
            assert release_worker.wait(timeout=5.0)
            completed = _store_complete_result(
                result_store,
                QueryResult(columns=("customer_id",), rows=(("CUST-001",),), elapsed_ms=5.0),
                sequence=request.sequences[0],
            )
            event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))
        else:
            prior_worker_finished_at_queue_start.append(
                bool(first_worker and first_worker[0].is_finished)
            )
            _emit_buffer_complete_results(
                request=request,
                result_store=result_store,
                event_sink=event_sink,
            )
        event_order.append(f"query-{request.sequences[0]}-return")

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        TUIRunRequest,
        OperationContext | None,
        OperationContext | None,
        tuple[str, ...],
        PreviewPolicy,
        int,
        list[int],
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers")

            await pilot.press("f4")
            await pilot.pause(0.05)
            assert worker_started.is_set()
            active_operation = app._active_query_operation
            assert app._active_query_worker is not None
            first_worker.append(app._active_query_worker)
            preserving_record = app.state.active_result_record
            preserving_view = app.state.result_view
            preserving_grid = _result_grid_snapshot(app)

            sql.load_text("SELECT 2 AS second; SELECT 3 AS third")
            await pilot.press("f12")
            for _ in range(50):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None
            queued_request = app.state.queued_run.request
            operation_after_enqueue = app._active_query_operation
            assert app.state.active_result_record == preserving_record
            assert app.state.result_view == preserving_view
            assert _result_grid_snapshot(app) == preserving_grid

            sql.load_text("SELECT 999 AS mutated")
            changed_source = tmp_path / "changed.csv"
            changed_source.write_text("value\nchanged\n", encoding="utf-8")
            app.state.add_source(TUISource(name="changed", path=changed_source, origin="session"))
            app._preview_policy = PreviewPolicy(row_limit=7, payload_limit_bytes=4096)

            release_worker.set()
            for _ in range(300):
                await pilot.pause(0.02)
                if (
                    len(seen_requests) == 2
                    and not app.state.query_run.is_running
                    and app.state.queued_run is None
                ):
                    break
            assert len(seen_requests) == 2
            return (
                queued_request,
                active_operation,
                operation_after_enqueue,
                tuple(source.spec.alias for source in seen_requests[1].sources),
                seen_requests[1].preview_policy,
                seen_requests[1].submission_order,
                [item.sequence for item in app.state.query_history],
            )

    (
        queued_request,
        active_operation,
        operation_after_enqueue,
        executed_aliases,
        executed_policy,
        submission_order,
        history_sequences,
    ) = asyncio.run(_inner())

    assert seen_requests[1] is queued_request
    assert seen_requests[1].statements == ("SELECT 2 AS second", "SELECT 3 AS third")
    assert len(seen_requests[1].sequences) == 2
    assert active_operation is operation_after_enqueue
    assert executed_aliases == ("customers",)
    assert executed_policy == PreviewPolicy()
    assert submission_order == 2
    assert history_sequences == [1, *seen_requests[1].sequences]
    assert prior_worker_finished_at_queue_start == [True]
    assert event_order.count("query-1-start") == 1
    assert event_order.count(f"query-{seen_requests[1].sequences[0]}-start") == 1


def test_queued_run_replacement_is_identity_bound_and_cancel_preserves_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    worker_started = threading.Event()
    release_worker = threading.Event()
    seen_requests: list[TUIRunRequest] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        if len(seen_requests) == 1:
            event_sink(
                TUIPreviewReadyEvent(
                    sequence=request.sequences[0],
                    preview=BoundedQueryResult(
                        columns=("value",),
                        rows=((1,),),
                        elapsed_ms=1.0,
                        preview_payload_bytes=len(encode_row_payload((1,))),
                        has_more_rows=True,
                        truncation_reason="row_limit",
                    ),
                )
            )
            worker_started.set()
            assert release_worker.wait(timeout=5.0)
            completed = _store_complete_result(
                result_store,
                QueryResult(
                    columns=("value",),
                    rows=((request.sequences[0],),),
                    elapsed_ms=1.0,
                ),
                sequence=request.sequences[0],
            )
            event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))
            return
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(
                columns=("value",),
                rows=((request.sequences[0],),),
                elapsed_ms=1.0,
            ),
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[TUIRunRequest, TUIRunRequest, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 1")
            await pilot.press("f4")
            await pilot.pause(0.05)
            assert worker_started.is_set()
            preserving_record = app.state.active_result_record
            preserving_view = app.state.result_view
            preserving_grid = _result_grid_snapshot(app)

            sql.load_text("SELECT 2")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None and not app._run_editor_pending:
                    break
            assert app.state.queued_run is not None
            original = app.state.queued_run.request
            assert app.state.active_result_record == preserving_record
            assert app.state.result_view == preserving_view
            assert _result_grid_snapshot(app) == preserving_grid

            sql.load_text("SELECT 3")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen), (
                app.query_one("#status", Static).content,
                app._run_editor_pending,
                app.state.queued_run,
            )
            cancelled_prompt = app.screen.query_one("#confirm-text", Static).content
            await pilot.press("n")
            for _ in range(100):
                await pilot.pause(0.02)
                if not isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert app.state.queued_run is not None
            assert app.state.queued_run.request is original
            assert app.state.active_result_record == preserving_record
            assert app.state.result_view == preserving_view
            assert _result_grid_snapshot(app) == preserving_grid

            sql.load_text("SELECT 4")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            confirmed_prompt = app.screen.query_one("#confirm-text", Static).content
            await pilot.press("y")
            for _ in range(100):
                await pilot.pause(0.02)
                if not isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert app.state.queued_run is not None
            replacement = app.state.queued_run.request
            assert app.state.active_result_record == preserving_record
            assert app.state.result_view == preserving_view
            assert _result_grid_snapshot(app) == preserving_grid
            release_worker.set()
            for _ in range(300):
                await pilot.pause(0.02)
                if len(seen_requests) == 2 and not app.state.query_run.is_running:
                    break
            assert len(seen_requests) == 2
            return original, replacement, cancelled_prompt, confirmed_prompt

    original, replacement, cancelled_prompt, confirmed_prompt = asyncio.run(_inner())

    assert "SELECT 2" in cancelled_prompt
    assert "SELECT 3" in cancelled_prompt
    assert "SELECT 2" in confirmed_prompt
    assert "SELECT 4" in confirmed_prompt
    assert original.statements == ("SELECT 2",)
    assert replacement.statements == ("SELECT 4",)
    assert replacement.submission_order == 4
    assert [request.statements for request in seen_requests] == [
        ("SELECT 1",),
        ("SELECT 4",),
    ]


@pytest.mark.parametrize("export_terminal", ["success", "failure", "cancel"])
def test_attached_export_terminalizes_before_queued_query_and_keeps_bound_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    export_terminal: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((99,),), elapsed_ms=1.0),
        sequence=state.reserve_query_sequences(1)[0],
        sql="SELECT 99 AS value",
    )
    preview_ready = threading.Event()
    release_preservation = threading.Event()
    export_started = threading.Event()
    release_export = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    exported_rows: list[tuple[tuple[object, ...], ...]] = []
    exported_paths: list[Path] = []
    event_order: list[str] = []
    first_query_worker: list[object] = []
    attached_export_worker: list[object] = []
    first_worker_finished_at_export_start: list[bool] = []
    export_worker_finished_at_queue_start: list[bool] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        event_order.append(f"query-{request.sequences[0]}-start")
        if len(seen_requests) == 1:
            event_sink(
                TUIPreviewReadyEvent(
                    sequence=request.sequences[0],
                    preview=BoundedQueryResult(
                        columns=("value",),
                        rows=((2,),),
                        elapsed_ms=1.0,
                        preview_payload_bytes=len(encode_row_payload((2,))),
                        has_more_rows=True,
                        truncation_reason="row_limit",
                    ),
                )
            )
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            completed = _store_complete_result(
                result_store,
                QueryResult(
                    columns=("value",),
                    rows=((request.sequences[0],),),
                    elapsed_ms=1.0,
                ),
                sequence=request.sequences[0],
            )
            event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))
        else:
            export_worker_finished_at_queue_start.append(
                bool(attached_export_worker and attached_export_worker[0].is_finished)
            )
            _emit_complete_result(
                request=request,
                result_store=result_store,
                event_sink=event_sink,
                result=QueryResult(
                    columns=("value",),
                    rows=((request.sequences[0],),),
                    elapsed_ms=1.0,
                ),
            )
        event_order.append(f"query-{request.sequences[0]}-return")

    def fake_export_last_result(
        result_store: TUIResultStore,
        handle,
        path_value: str,
        *,
        export_format: ExportFormat,
        base_dir: Path,
        force: bool = False,
        token: OperationToken | None = None,
        **kwargs: object,
    ) -> Path:
        del export_format, base_dir, force, kwargs
        source = result_store.open_rows(handle)
        exported_rows.append(tuple(source.iter_rows()))
        exported_paths.append(Path(path_value))
        event_order.append("export-start")
        first_worker_finished_at_export_start.append(
            bool(first_query_worker and first_query_worker[0].is_finished)
        )
        export_started.set()
        if export_terminal != "cancel":
            assert release_export.wait(timeout=5.0)
        if export_terminal == "failure":
            event_order.append("export-failed")
            raise CSVQLError("attached export failed")
        if export_terminal == "cancel":
            assert token is not None
            for _ in range(500):
                if token.is_cancelled:
                    event_order.append("export-cancelled")
                    raise OperationCancelled("cancelled")
                threading.Event().wait(0.01)
            raise AssertionError("attached export was not cancelled")
        event_order.append("export-succeeded")
        return Path(path_value)

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)
    monkeypatch.setattr(tui_app_module, "export_last_result", fake_export_last_result)
    destination = tmp_path / f"attached-{export_terminal}.csv"

    async def _inner() -> tuple[
        int | None,
        int | None,
        TUIResultRecord,
        TUIResultRecord,
        tuple[tuple[object, ...], ...],
    ]:
        app = CSVQLMenuApp(
            initial_state=state,
            start_dir=tmp_path,
            result_store=store,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 2 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_result_record is not None:
                    break
            assert app.state.active_result_record is not None
            assert app.state.active_result_record.state == "preserving"
            assert app._active_query_worker is not None
            first_query_worker.append(app._active_query_worker)

            app.action_export_last_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._PromptInputScreen):
                    break
            app.screen.query_one("#export-path", Input).value = str(destination)
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.export_intent is not None
            attached_sequence = app.state.export_intent.result_sequence

            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            app._show_history_result_at_row(0)
            await pilot.pause()
            assert app.state.active_result.sequence == 1

            sql.load_text("SELECT 3 AS value")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None
            queued_sequence = app.state.queued_run.request.sequences[0]

            release_preservation.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if export_started.is_set():
                    break
            assert export_started.is_set()
            assert app._active_operation_worker is not None
            attached_export_worker.append(app._active_operation_worker)
            record_before_export_terminal = app.state.query_result_record(attached_sequence)
            assert record_before_export_terminal is not None
            if export_terminal == "cancel":
                await pilot.press("escape")
            else:
                release_export.set()

            for _ in range(400):
                await pilot.pause(0.02)
                if (
                    len(seen_requests) == 2
                    and not app.state.query_run.is_running
                    and not app.state.operation_run.is_running
                    and app.state.queued_run is None
                ):
                    break
            assert len(seen_requests) == 2
            assert app.state.export_intent is None
            record_after_export_terminal = app.state.query_result_record(attached_sequence)
            assert record_after_export_terminal is not None
            assert record_after_export_terminal.handle is not None
            source = app._result_store.open_rows(record_after_export_terminal.handle)
            try:
                retained_rows = tuple(source.iter_rows())
            finally:
                close = getattr(source, "close", None)
                if callable(close):
                    close()
            return (
                attached_sequence,
                queued_sequence,
                record_before_export_terminal,
                record_after_export_terminal,
                retained_rows,
            )

    (
        attached_sequence,
        queued_sequence,
        record_before_export_terminal,
        record_after_export_terminal,
        retained_rows,
    ) = asyncio.run(_inner())

    assert attached_sequence == 2
    assert queued_sequence == 3
    assert exported_rows == [((2,),)]
    assert exported_paths == [destination]
    assert destination.exists() is False
    export_start_index = event_order.index("export-start")
    queued_start_index = event_order.index("query-3-start")
    assert export_start_index < queued_start_index
    assert first_worker_finished_at_export_start == [True]
    assert export_worker_finished_at_queue_start == [True]
    assert event_order.count("export-start") == 1
    assert event_order.count("query-3-start") == 1
    assert record_after_export_terminal == record_before_export_terminal
    assert record_after_export_terminal.handle == record_before_export_terminal.handle
    assert retained_rows == ((2,),)


@pytest.mark.parametrize(
    "unrelated_terminal",
    ["success", "failure", "cancel", "success_before_query_terminal"],
)
def test_attached_export_waits_for_unrelated_result_operation_before_queued_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unrelated_terminal: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=state.reserve_query_sequences(1)[0],
        sql="SELECT 1 AS value",
    )
    preview_ready = threading.Event()
    release_preservation = threading.Event()
    unrelated_started = threading.Event()
    release_unrelated = threading.Event()
    attached_started = threading.Event()
    release_attached = threading.Event()
    queued_started = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    exported_paths: list[Path] = []
    event_order: list[str] = []
    unrelated_worker: list[object] = []
    attached_worker: list[object] = []
    unrelated_finished_at_attached_start: list[bool] = []
    attached_finished_at_queue_start: list[bool] = []
    manual_destination = tmp_path / "manual.csv"
    attached_destination = tmp_path / "attached.csv"

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        event_order.append(f"query-{request.sequences[0]}-start")
        if len(seen_requests) == 1:
            event_sink(
                TUIPreviewReadyEvent(
                    sequence=request.sequences[0],
                    preview=BoundedQueryResult(
                        columns=("value",),
                        rows=((2,),),
                        elapsed_ms=1.0,
                        preview_payload_bytes=len(encode_row_payload((2,))),
                        has_more_rows=True,
                        truncation_reason="row_limit",
                    ),
                )
            )
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            completed = _store_complete_result(
                result_store,
                QueryResult(columns=("value",), rows=((2,),), elapsed_ms=1.0),
                sequence=request.sequences[0],
            )
            event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))
        else:
            attached_finished_at_queue_start.append(
                bool(attached_worker and attached_worker[0].is_finished)
            )
            queued_started.set()
            _emit_complete_result(
                request=request,
                result_store=result_store,
                event_sink=event_sink,
                result=QueryResult(columns=("value",), rows=((3,),), elapsed_ms=1.0),
            )
        event_order.append(f"query-{request.sequences[0]}-return")

    def fake_export_last_result(
        result_store: TUIResultStore,
        handle,
        path_value: str,
        *,
        token: OperationToken | None = None,
        **kwargs: object,
    ) -> Path:
        del kwargs
        source = result_store.open_rows(handle)
        assert tuple(source.iter_rows())
        destination = Path(path_value)
        exported_paths.append(destination)
        if destination == manual_destination:
            event_order.append("unrelated-export-start")
            unrelated_started.set()
            if unrelated_terminal == "cancel":
                assert token is not None
                for _ in range(500):
                    if token.is_cancelled:
                        event_order.append("unrelated-export-terminal")
                        raise OperationCancelled("cancelled")
                    threading.Event().wait(0.01)
                raise AssertionError("unrelated export was not cancelled")
            assert release_unrelated.wait(timeout=5.0)
            event_order.append("unrelated-export-terminal")
            if unrelated_terminal == "failure":
                raise CSVQLError("unrelated export failed")
            return destination
        assert destination == attached_destination
        event_order.append("attached-export-start")
        unrelated_finished_at_attached_start.append(
            bool(unrelated_worker and unrelated_worker[0].is_finished)
        )
        attached_started.set()
        assert release_attached.wait(timeout=5.0)
        event_order.append("attached-export-finish")
        return destination

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)
    monkeypatch.setattr(tui_app_module, "export_last_result", fake_export_last_result)

    async def _submit_export_path(
        pilot: Pilot[None],
        app: CSVQLMenuApp,
        destination: Path,
    ) -> None:
        app.action_export_last_result()
        for _ in range(100):
            await pilot.pause(0.02)
            if isinstance(app.screen, tui_app_module._PromptInputScreen):
                break
        app.screen.query_one("#export-path", Input).value = str(destination)
        await pilot.press("enter")
        await pilot.pause()

    async def _inner() -> tuple[bool, bool, int, bool, bool]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 2 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_result_record is not None:
                    break

            await _submit_export_path(pilot, app, attached_destination)
            assert app.state.export_intent is not None
            original_intent = app.state.export_intent

            sql.load_text("SELECT 3 AS value")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None
            original_queue = app.state.queued_run

            app._show_history_result_at_row(0)
            await pilot.pause()
            assert app.state.active_result.sequence == 1
            await _submit_export_path(pilot, app, manual_destination)
            for _ in range(100):
                await pilot.pause(0.02)
                if unrelated_started.is_set():
                    break
            assert unrelated_started.is_set()
            assert app._active_operation_worker is not None
            unrelated_worker.append(app._active_operation_worker)

            no_op_while_query_running = False
            if unrelated_terminal == "success_before_query_terminal":
                release_unrelated.set()
                for _ in range(150):
                    await pilot.pause(0.02)
                    if not app.state.operation_run.is_running:
                        break
                no_op_while_query_running = (
                    app.state.query_run.is_running
                    and app.state.export_intent is original_intent
                    and app.state.queued_run is original_queue
                    and len(seen_requests) == 1
                    and not attached_started.is_set()
                )
                deferred_intent_retained = app.state.export_intent is original_intent
                deferred_queue_retained = app.state.queued_run is original_queue
                request_count_during_deferral = len(seen_requests)
                operation_still_running = app.state.operation_run.is_running
                release_preservation.set()
            else:
                release_preservation.set()
                for _ in range(150):
                    await pilot.pause(0.02)
                    if not app.state.query_run.is_running:
                        break
                deferred_intent_retained = app.state.export_intent is original_intent
                deferred_queue_retained = app.state.queued_run is original_queue
                request_count_during_deferral = len(seen_requests)
                operation_still_running = app.state.operation_run.is_running

                if unrelated_terminal == "cancel":
                    await pilot.press("escape")
                else:
                    release_unrelated.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if attached_started.is_set():
                    break
            if attached_started.is_set():
                assert app._active_operation_worker is not None
                attached_worker.append(app._active_operation_worker)
            release_attached.set()

            for _ in range(300):
                await pilot.pause(0.02)
                if (
                    queued_started.is_set()
                    and not app.state.query_run.is_running
                    and not app.state.operation_run.is_running
                ):
                    break
            return (
                deferred_intent_retained,
                deferred_queue_retained,
                request_count_during_deferral,
                operation_still_running,
                no_op_while_query_running,
            )

    (
        deferred_intent_retained,
        deferred_queue_retained,
        request_count_during_deferral,
        operation_still_running,
        no_op_while_query_running,
    ) = asyncio.run(_inner())

    assert deferred_intent_retained is True
    assert deferred_queue_retained is True
    assert request_count_during_deferral == 1
    assert operation_still_running is (unrelated_terminal != "success_before_query_terminal")
    assert no_op_while_query_running is (unrelated_terminal == "success_before_query_terminal")
    assert attached_started.is_set()
    assert queued_started.is_set()
    assert unrelated_finished_at_attached_start == [True]
    assert attached_finished_at_queue_start == [True]
    assert exported_paths == [manual_destination, attached_destination]
    assert event_order.index("unrelated-export-terminal") < event_order.index(
        "attached-export-start"
    )
    assert event_order.index("attached-export-finish") < event_order.index("query-3-start")
    assert event_order.count("attached-export-start") == 1
    assert event_order.count("query-3-start") == 1


def test_export_intent_replacement_confirmation_cannot_replace_in_flight_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    preview_ready = threading.Event()
    release_preservation = threading.Event()
    export_started = threading.Event()
    release_export = threading.Event()
    queued_started = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    exported_paths: list[Path] = []
    original_destination = tmp_path / "original.csv"
    replacement_destination = tmp_path / "replacement.csv"

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        if len(seen_requests) == 1:
            event_sink(
                TUIPreviewReadyEvent(
                    sequence=request.sequences[0],
                    preview=BoundedQueryResult(
                        columns=("value",),
                        rows=((1,),),
                        elapsed_ms=1.0,
                        preview_payload_bytes=len(encode_row_payload((1,))),
                        has_more_rows=True,
                        truncation_reason="row_limit",
                    ),
                )
            )
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            completed = _store_complete_result(
                result_store,
                QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
                sequence=request.sequences[0],
            )
            event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))
            return
        queued_started.set()
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((2,),), elapsed_ms=1.0),
        )

    def fake_export_last_result(
        result_store: TUIResultStore,
        handle,
        path_value: str,
        **kwargs: object,
    ) -> Path:
        del kwargs
        source = result_store.open_rows(handle)
        assert tuple(source.iter_rows())
        destination = Path(path_value)
        exported_paths.append(destination)
        export_started.set()
        assert release_export.wait(timeout=5.0)
        return destination

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)
    monkeypatch.setattr(tui_app_module, "export_last_result", fake_export_last_result)

    async def _submit_export_path(
        pilot: Pilot[None],
        app: CSVQLMenuApp,
        destination: Path,
    ) -> None:
        app.action_export_last_result()
        for _ in range(100):
            await pilot.pause(0.02)
            if isinstance(app.screen, tui_app_module._PromptInputScreen):
                break
        app.screen.query_one("#export-path", Input).value = str(destination)
        await pilot.press("enter")
        await pilot.pause()

    async def _inner() -> tuple[bool, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_result_record is not None:
                    break

            await _submit_export_path(pilot, app, original_destination)
            assert app.state.export_intent is not None
            original_intent = app.state.export_intent

            sql.load_text("SELECT 2 AS value")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None

            await _submit_export_path(pilot, app, replacement_destination)
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen)

            release_preservation.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if export_started.is_set():
                    break
            assert export_started.is_set()
            in_flight_identity_preserved = app._attached_export_intent_in_flight is original_intent

            await pilot.press("y")
            for _ in range(100):
                await pilot.pause(0.02)
                if not isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert not isinstance(app.screen, tui_app_module._ConfirmationScreen)
            intent_after_confirmation_is_original = app.state.export_intent is original_intent
            confirmation_status = app.query_one("#status", Static).content

            release_export.set()
            for _ in range(300):
                await pilot.pause(0.02)
                if (
                    queued_started.is_set()
                    and not app.state.query_run.is_running
                    and not app.state.operation_run.is_running
                ):
                    break
            return (
                in_flight_identity_preserved,
                intent_after_confirmation_is_original,
                confirmation_status,
            )

    (
        in_flight_identity_preserved,
        intent_after_confirmation_is_original,
        confirmation_status,
    ) = asyncio.run(_inner())

    assert in_flight_identity_preserved is True
    assert intent_after_confirmation_is_original is True
    assert "already started" in confirmation_status
    assert str(original_destination) in confirmation_status
    assert exported_paths == [original_destination]
    assert queued_started.is_set()
    assert len(seen_requests) == 2


@pytest.mark.parametrize(
    "resolution",
    ["submit", "cancel", "invalid", "non_complete", "stale_existing"],
)
def test_preserving_export_prompt_reserves_order_until_identity_bound_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolution: str,
) -> None:
    state = _make_source_state(tmp_path)
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=True,
        truncation_reason="row_limit",
    )
    preview_ready = threading.Event()
    release_preservation = threading.Event()
    export_started = threading.Event()
    release_export = threading.Event()
    queued_started = threading.Event()
    release_queued = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    exported_paths: list[Path] = []
    event_order: list[str] = []
    first_worker: list[object] = []
    original_destination = tmp_path / "original.csv"
    late_destination = tmp_path / "late.csv"
    invalid_destination = tmp_path / "late.exe"

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        event_order.append(f"query-{request.sequences[0]}-start")
        if len(seen_requests) == 1:
            event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            if resolution == "non_complete":
                preview_only = _store_preview_only_result(
                    result_store,
                    preview,
                    sequence=request.sequences[0],
                    reason="preservation_failed",
                )
                event_sink(
                    TUIPreviewOnlyEvent(
                        sequence=request.sequences[0],
                        preview=preview,
                        reason="preservation_failed",
                        stored=preview_only,
                    )
                )
            else:
                completed = _store_complete_result(
                    result_store,
                    QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
                    sequence=request.sequences[0],
                )
                event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))
        else:
            queued_started.set()
            assert release_queued.wait(timeout=5.0)
            _emit_complete_result(
                request=request,
                result_store=result_store,
                event_sink=event_sink,
                result=QueryResult(columns=("value",), rows=((2,),), elapsed_ms=1.0),
            )
        event_order.append(f"query-{request.sequences[0]}-return")

    def fake_export_last_result(
        result_store: TUIResultStore,
        handle,
        path_value: str,
        **kwargs: object,
    ) -> Path:
        del kwargs
        source = result_store.open_rows(handle)
        assert tuple(source.iter_rows())
        destination = Path(path_value)
        exported_paths.append(destination)
        event_order.append(f"export-{destination.name}-start")
        export_started.set()
        assert release_export.wait(timeout=5.0)
        event_order.append(f"export-{destination.name}-finish")
        return destination

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)
    monkeypatch.setattr(tui_app_module, "export_last_result", fake_export_last_result)

    async def _open_export_prompt(
        pilot: Pilot[None],
        app: CSVQLMenuApp,
    ) -> Input:
        app.action_export_last_result()
        for _ in range(100):
            await pilot.pause(0.02)
            if isinstance(app.screen, tui_app_module._PromptInputScreen):
                break
        return app.screen.query_one("#export-path", Input)

    async def _submit_export_path(
        pilot: Pilot[None],
        app: CSVQLMenuApp,
        destination: Path,
    ) -> None:
        prompt_input = await _open_export_prompt(pilot, app)
        prompt_input.value = str(destination)
        await pilot.press("enter")
        await pilot.pause()

    async def _inner() -> tuple[bool, bool, int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_result_record is not None:
                    break
            assert app._active_query_worker is not None
            first_worker.append(app._active_query_worker)

            if resolution == "stale_existing":
                await _submit_export_path(pilot, app, original_destination)
                assert app.state.export_intent is not None

            sql.load_text("SELECT 2 AS value")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None
            queued_identity = app.state.queued_run

            prompt_input = await _open_export_prompt(pilot, app)
            assert late_destination.exists() is False
            assert invalid_destination.exists() is False
            release_preservation.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if first_worker[0].is_finished:
                    break
            assert first_worker[0].is_finished

            held_before_resolution = (
                not queued_started.is_set() and app.state.queued_run is queued_identity
            )
            prompt_dismissed_after_non_complete = False
            rejection_message = ""

            if resolution == "stale_existing":
                for _ in range(150):
                    await pilot.pause(0.02)
                    if export_started.is_set():
                        break
                assert export_started.is_set()
                release_export.set()
                for _ in range(150):
                    await pilot.pause(0.02)
                    if queued_started.is_set():
                        break
                prompt_input.value = str(late_destination)
                await pilot.press("enter")
                await pilot.pause(0.2)
            elif resolution == "non_complete":
                for _ in range(150):
                    await pilot.pause(0.02)
                    if queued_started.is_set():
                        break
                prompt_dismissed_after_non_complete = not isinstance(
                    app.screen,
                    tui_app_module._PromptInputScreen,
                )
                rejection_message = app.query_one("#results-message", Static).content
            elif resolution == "cancel":
                await pilot.press("escape")
                for _ in range(150):
                    await pilot.pause(0.02)
                    if queued_started.is_set():
                        break
            elif resolution == "invalid":
                prompt_input.value = str(invalid_destination)
                await pilot.press("enter")
                for _ in range(150):
                    await pilot.pause(0.02)
                    if queued_started.is_set():
                        break
                rejection_message = app.query_one("#results-message", Static).content
            else:
                prompt_input.value = str(late_destination)
                await pilot.press("enter")
                for _ in range(150):
                    await pilot.pause(0.02)
                    if export_started.is_set():
                        break
                assert late_destination.exists() is False
                release_export.set()
                for _ in range(150):
                    await pilot.pause(0.02)
                    if queued_started.is_set():
                        break

            release_queued.set()
            for _ in range(300):
                await pilot.pause(0.02)
                if (
                    len(seen_requests) == 2
                    and not app.state.query_run.is_running
                    and not app.state.operation_run.is_running
                ):
                    break
            return (
                held_before_resolution,
                prompt_dismissed_after_non_complete,
                len(exported_paths),
                rejection_message,
            )

    (
        held_before_resolution,
        prompt_dismissed_after_non_complete,
        export_count,
        rejection_message,
    ) = asyncio.run(_inner())

    if resolution in {"submit", "cancel", "invalid"}:
        assert held_before_resolution is True
    if resolution == "submit":
        assert exported_paths == [late_destination]
        assert event_order.index("export-late.csv-finish") < event_order.index("query-2-start")
    elif resolution == "stale_existing":
        assert exported_paths == [original_destination]
    else:
        assert export_count == 0
    if resolution == "invalid":
        assert "Unsupported export file type" in rejection_message
    if resolution == "non_complete":
        assert prompt_dismissed_after_non_complete is True
        assert "was not started" in rejection_message
        assert "did not produce a complete result" in rejection_message
    assert event_order.count("query-2-start") == 1
    assert late_destination.exists() is False
    assert invalid_destination.exists() is False


def test_export_intent_replacement_confirmation_is_identity_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    preview_ready = threading.Event()
    release_preservation = threading.Event()
    exported_paths: list[Path] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        event_sink(
            TUIPreviewReadyEvent(
                sequence=request.sequences[0],
                preview=BoundedQueryResult(
                    columns=("value",),
                    rows=((1,),),
                    elapsed_ms=1.0,
                    preview_payload_bytes=len(encode_row_payload((1,))),
                    has_more_rows=True,
                    truncation_reason="row_limit",
                ),
            )
        )
        preview_ready.set()
        assert release_preservation.wait(timeout=5.0)
        completed = _store_complete_result(
            result_store,
            QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
            sequence=request.sequences[0],
        )
        event_sink(TUICompleteEvent(sequence=request.sequences[0], stored=completed))

    def fake_export_last_result(
        result_store: TUIResultStore,
        handle,
        path_value: str,
        **kwargs: object,
    ) -> Path:
        del kwargs
        source = result_store.open_rows(handle)
        assert tuple(source.iter_rows())
        path = Path(path_value)
        exported_paths.append(path)
        return path

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)
    monkeypatch.setattr(tui_app_module, "export_last_result", fake_export_last_result)
    first = tmp_path / "first.csv"
    cancelled = tmp_path / "cancelled.csv"
    replacement = tmp_path / "replacement.csv"

    async def _submit_export_path(
        pilot: Pilot[None],
        app: CSVQLMenuApp,
        path: Path,
    ) -> None:
        app.action_export_last_result()
        for _ in range(100):
            await pilot.pause(0.02)
            if isinstance(app.screen, tui_app_module._PromptInputScreen):
                break
        app.screen.query_one("#export-path", Input).value = str(path)
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause(0.02)
            if not isinstance(app.screen, tui_app_module._PromptInputScreen):
                break

    async def _inner() -> tuple[str, str, Path]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_result_record is not None:
                    break

            await _submit_export_path(pilot, app, first)
            assert app.state.export_intent is not None
            original_intent = app.state.export_intent

            await _submit_export_path(pilot, app, cancelled)
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            cancel_prompt = app.screen.query_one("#confirm-text", Static).content
            await pilot.press("n")
            await pilot.pause()
            assert app.state.export_intent is original_intent

            await _submit_export_path(pilot, app, replacement)
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            replace_prompt = app.screen.query_one("#confirm-text", Static).content
            await pilot.press("y")
            await pilot.pause()
            assert app.state.export_intent is not None
            attached_destination = app.state.export_intent.destination

            release_preservation.set()
            for _ in range(300):
                await pilot.pause(0.02)
                if (
                    not app.state.query_run.is_running
                    and not app.state.operation_run.is_running
                    and app.state.export_intent is None
                ):
                    break
            return cancel_prompt, replace_prompt, attached_destination

    cancel_prompt, replace_prompt, attached_destination = asyncio.run(_inner())

    assert str(first) in cancel_prompt
    assert str(cancelled) in cancel_prompt
    assert str(first) in replace_prompt
    assert str(replacement) in replace_prompt
    assert attached_destination == replacement
    assert exported_paths == [replacement]


def test_non_complete_preservation_rejects_attached_export_then_starts_queue_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=True,
        truncation_reason="row_limit",
    )
    preview_ready = threading.Event()
    release_preservation = threading.Event()
    queued_started = threading.Event()
    release_queued = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    export_calls: list[object] = []

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del operation
        seen_requests.append(request)
        if len(seen_requests) == 1:
            event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            preview_only = _store_preview_only_result(
                result_store,
                preview,
                sequence=request.sequences[0],
                reason="preservation_failed",
            )
            event_sink(
                TUIPreviewOnlyEvent(
                    sequence=request.sequences[0],
                    preview=preview,
                    reason="preservation_failed",
                    stored=preview_only,
                )
            )
            return
        queued_started.set()
        assert release_queued.wait(timeout=5.0)
        _emit_complete_result(
            request=request,
            result_store=result_store,
            event_sink=event_sink,
            result=QueryResult(columns=("value",), rows=((2,),), elapsed_ms=1.0),
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)
    monkeypatch.setattr(
        tui_app_module,
        "export_last_result",
        lambda *args, **kwargs: export_calls.append((args, kwargs)),
    )
    destination = tmp_path / "must-not-start.csv"

    async def _inner() -> tuple[str, int]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_result_record is not None:
                    break

            app.action_export_last_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._PromptInputScreen):
                    break
            app.screen.query_one("#export-path", Input).value = str(destination)
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.export_intent is not None

            sql.load_text("SELECT 2 AS value")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None

            release_preservation.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if queued_started.is_set():
                    break
            assert queued_started.is_set()
            assert app.state.export_intent is None
            rejection_message = app.query_one("#results-message", Static).content
            queued_sequence = seen_requests[1].sequences[0]
            release_queued.set()
            for _ in range(200):
                await pilot.pause(0.02)
                if not app.state.query_run.is_running:
                    break
            return rejection_message, queued_sequence

    rejection_message, queued_sequence = asyncio.run(_inner())

    assert "was not started" in rejection_message
    assert "did not produce a complete result" in rejection_message
    assert export_calls == []
    assert queued_sequence == 2
    assert [request.sequences[0] for request in seen_requests].count(2) == 1


def test_unexpected_buffer_worker_failure_uses_active_sequence_and_clears_pending_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        assert request.run_mode == "buffer"
        preview = BoundedQueryResult(
            columns=("value",),
            rows=((2,),),
            elapsed_ms=1.0,
            preview_payload_bytes=len(encode_row_payload((2,))),
            has_more_rows=True,
            truncation_reason="row_limit",
        )
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[1], preview=preview))
        raise RuntimeError("internal failure after preview")

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        list[tuple[int, str, str]],
        int | None,
        str | None,
        str,
        str,
        bool,
        dict[int, str],
        dict[int, str],
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.focus()
            sql.load_text("SELECT 1 AS first;\nSELECT 2 AS second;\nSELECT 3 AS third;")

            await pilot.press("f12")
            await _settled_query_idle(pilot, app)

            active_record = app.state.active_query_result_record()
            return (
                [(item.sequence, item.status, item.run_mode) for item in app.state.query_history],
                app.state.active_result.sequence,
                None if active_record is None else active_record.state,
                app.query_one("#status", Static).content,
                app.query_one("#run-status", Static).content,
                app.state.query_run.is_running,
                dict(app._active_query_sql),
                dict(app._active_query_run_modes),
            )

    (
        history,
        active_sequence,
        active_state,
        status,
        run_status,
        is_running,
        active_query_sql,
        active_query_run_modes,
    ) = asyncio.run(_inner())

    assert history == [(2, "success", "buffer")]
    assert active_sequence == 2
    assert active_state == "preview_only"
    assert "Showing 1 retained preview row(s)." in status
    assert run_status == "Ready."
    assert is_running is False
    assert active_query_sql == {}
    assert active_query_run_modes == {}


def test_successful_query_populates_results_datatable(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)

    async def _inner() -> tuple[tuple[str, ...], int, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM customers ORDER BY customer_id")
            await pilot.press("f4")
            await _settled_query_idle(pilot, app)
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

    async def _inner() -> tuple[bool, tuple[object, ...]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            active_sequence = app.state.reserve_query_sequences(1)[0]
            app.state.start_query_request(
                TUIRunRequest(
                    statements=("SELECT 'newer'",),
                    sequences=(active_sequence,),
                    sources=(),
                    fallback_sources=(),
                    preview_policy=PreviewPolicy(),
                    run_mode="current",
                    submission_order=active_sequence,
                )
            )
            stale_sequence = active_sequence - 1
            app._handle_failed_before_preview_event(
                TUIFailedBeforePreviewEvent(
                    sequence=stale_sequence,
                    error_message="stale failure",
                )
            )
            return app.state.has_active_result, app.state.query_history

    has_active_result, history = asyncio.run(_inner())

    assert has_active_result is False
    assert history == ()


def test_history_enter_reopens_query_in_editor(tmp_path: Path) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore()
    first_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT 1",
        store=store,
    )
    second_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("customer_id",), rows=(("CUST-001",),), elapsed_ms=1.0),
        sequence=second_sequence,
        sql="SELECT * FROM customers",
        store=store,
    )

    async def _inner() -> tuple[str, object | None]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = TUIResultStore()
    first_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("value",), rows=((1,),), elapsed_ms=1.0),
        sequence=first_sequence,
        sql="SELECT 1",
        store=store,
    )
    second_sequence = state.reserve_query_sequences(1)[0]
    _record_stored_result(
        state,
        QueryResult(columns=("count",), rows=((2,),), elapsed_ms=1.0),
        sequence=second_sequence,
        sql="SELECT COUNT(*) AS count FROM customers",
        store=store,
    )
    state.remove_source("customers")
    replacement_path = _create_csv(
        tmp_path,
        "orders.csv",
        "order_id,total\nORD-001,10\n",
    )
    state.add_source(TUISource(name="orders", path=replacement_path, origin="session"))

    async def _inner() -> tuple[str, str, list[str]]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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
    store = _record_stored_result(
        state,
        QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT 'stale' AS old",
    )

    async def _inner() -> tuple[
        bool,
        str,
        tuple[str, ...],
        tuple[str, str],
        str,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
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

            app.action_export_last_result()
            await pilot.pause()

            return (
                app.state.has_active_result,
                column_status,
                column_headers,
                first_column,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    (
        has_active_result,
        column_status,
        column_headers,
        first_column,
        export_status,
        export_message,
    ) = asyncio.run(_inner())

    assert has_active_result is False
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
            await _settled_operation_idle(pilot, app)
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
    store = _record_stored_result(
        state,
        existing_result,
        sequence=1,
        sql="SELECT 1 AS id",
    )
    existing_record = state.active_query_result_record()

    async def _inner() -> tuple[str, object | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT * FROM")
            app.query_one("#sources", DataTable).focus()
            await pilot.press("l")
            await pilot.pause()
            return (
                sql.text,
                app.state.active_query_result_record(),
                app.query_one("#status", Static).content,
            )

    editor_text, last_result, status = asyncio.run(_inner())

    assert editor_text == 'SELECT * FROM\n"customers"'
    assert last_result == existing_record
    assert status == "Inserted alias customers into SQL editor."


def test_insert_starter_select_appends_rendered_select_and_preserves_result(
    tmp_path: Path,
) -> None:
    state = _make_source_state(tmp_path)
    existing_result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)
    store = _record_stored_result(
        state,
        existing_result,
        sequence=1,
        sql="SELECT 1 AS id",
    )
    existing_record = state.active_query_result_record()

    async def _inner() -> tuple[str, object | None, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            return (
                app.query_one("#sql", TextArea).text,
                app.state.active_query_result_record(),
                app.query_one("#status", Static).content,
            )

    editor_text, last_result, status = asyncio.run(_inner())

    assert editor_text == 'SELECT *\nFROM "customers"\nLIMIT 10;'
    assert last_result == existing_record
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
            await _settled_operation_idle(pilot, app)

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
            await _settled_operation_idle(pilot, app)

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
            await _settled_operation_idle(pilot, app)
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
    monkeypatch.setattr("csvql.tui_app.run_tui_request", _unexpected)

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
    monkeypatch.setattr("csvql.tui_app.run_tui_request", _unexpected)

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

    def slow_inspect_source(
        source: TUISource,
        *,
        operation: OperationContext,
    ) -> object:
        started.set()
        assert release.wait(timeout=2)
        from csvql.tui_workflows import inspect_source as real_inspect_source

        return real_inspect_source(source, operation=operation)

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
    store = _record_stored_result(
        state,
        QueryResult(columns=("old",), rows=(("stale",),), elapsed_ms=1.0),
        sequence=1,
        sql="SELECT 'stale' AS old",
    )

    async def _inner() -> tuple[bool, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sources", DataTable).focus()
            await pilot.press("l")
            await pilot.pause()
            return (
                app.state.has_active_result,
                app.query_one("#status", Static).content,
                app.query_one("#results-message", Static).content,
            )

    has_active_result, status, message = asyncio.run(_inner())

    assert has_active_result is False
    assert "No source selected." in status
    assert "No source selected." in message
