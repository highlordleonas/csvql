import asyncio
import threading
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Static, TextArea

from csvql import tui_app as tui_app_module
from csvql.bounded_result import BoundedQueryResult, PreviewPolicy
from csvql.export import ExportFormat
from csvql.models import QueryResult
from csvql.operation import OperationContext
from csvql.result_codec import encode_row_payload
from csvql.tui_app import CSVQLMenuApp, _TransientPreviewOnlyResult
from csvql.tui_query_runner import TUIPreviewOnlyEvent, TUIPreviewReadyEvent, TUIRunRequest
from csvql.tui_result_store import TUIResultStorageError, TUIResultStore
from csvql.tui_results import make_result_view_state
from csvql.tui_state import (
    TUIBufferResultTab,
    TUIExportIntent,
    TUIQueuedRun,
    TUIResultRecord,
    TUISessionState,
    TUISource,
)


def _make_source_state(tmp_path: Path) -> TUISessionState:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id,email\nCUST-001,alex@example.com\nCUST-002,bob@example.com\n",
        encoding="utf-8",
    )
    state = TUISessionState()
    state.add_source(TUISource(name="customers", path=csv_path, origin="argument"))
    return state


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


def _record_stored_result(
    state: TUISessionState,
    result_store: TUIResultStore,
    *,
    sequence: int,
    sql: str,
    result: QueryResult,
) -> None:
    stored = _store_complete_result(result_store, result, sequence=sequence)
    state.record_query_success(
        sequence,
        sql,
        handle=stored.handle,
        result_view=make_result_view_state(result, source_result_sequence=sequence),
        elapsed_ms=result.elapsed_ms,
    )


def test_non_durable_preview_only_rejects_export_and_pauses_queue_until_discard(
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

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        seen_requests.append(request)
        if len(seen_requests) == 1:
            event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            event_sink(
                TUIPreviewOnlyEvent(
                    sequence=request.sequences[0],
                    preview=preview,
                    reason="session_spool_limit",
                    stored=None,
                )
            )
            return
        queued_started.set()
        assert release_queued.wait(timeout=5.0)

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[bool, str, str, int, int, str, bool]:
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

            app.state.attach_export_intent(
                TUIExportIntent(
                    result_sequence=1,
                    destination=tmp_path / "blocked-export.csv",
                    format=ExportFormat.csv,
                )
            )
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
                if not app.state.query_run.is_running:
                    break
            await pilot.pause(0.1)

            paused_before_discard = app.state.queued_run is not None and not queued_started.is_set()
            status_before_discard = app.query_one("#status", Static).content
            message_before_discard = app.query_one("#results-message", Static).content
            sql.load_text("SELECT 3 AS blocked")
            await pilot.press("f4")
            await pilot.pause(0.1)
            seen_requests_before_discard = len(seen_requests)

            app.query_one("#results", DataTable).focus()
            await pilot.pause()
            app.action_delete_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen)
            await pilot.press("y")
            for _ in range(150):
                await pilot.pause(0.02)
                if queued_started.is_set():
                    break
            release_queued.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if not app.state.query_run.is_running:
                    break
            return (
                paused_before_discard,
                status_before_discard,
                message_before_discard,
                seen_requests_before_discard,
                len(seen_requests),
                app.query_one("#status", Static).content,
                app.state.queued_run is not None,
            )

    (
        paused_before_discard,
        status_before_discard,
        message_before_discard,
        seen_requests_before_discard,
        seen_request_count,
        final_status,
        queue_retained_after_discard,
    ) = asyncio.run(_inner())

    assert paused_before_discard is True
    assert "Attached export for query 1 was not started" in message_before_discard
    assert "Remove older stored results" in status_before_discard
    assert "delete this preview" in status_before_discard
    assert seen_requests_before_discard == 1
    assert queue_retained_after_discard is False
    assert "Unable to start queued run" not in final_status
    assert seen_request_count == 2


def test_preview_only_status_surfaces_cleanup_warning_separately(
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
    cleanup_note = "Cleanup uncertainty: the engine connection could not be closed."
    primary_error_message = "Unable to serialize the query result for temporary storage."

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del request, result_store, operation
        event_sink(TUIPreviewReadyEvent(sequence=1, preview=preview))
        event_sink(
            TUIPreviewOnlyEvent(
                sequence=1,
                preview=preview,
                reason="session_spool_limit",
                stored=None,
                primary_error_message=primary_error_message,
                cleanup_notes=(cleanup_note,),
            )
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 1 AS value")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.active_result_record is not None:
                    break
            return app.query_one("#status", Static).content

    status = asyncio.run(_inner())
    assert "Showing 1 retained preview row(s)." in status
    assert primary_error_message in status
    assert cleanup_note in status


def test_deleting_older_result_can_retry_preview_persistence_then_start_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        store,
        sequence=1,
        sql="SELECT old",
        result=QueryResult(columns=("old",), rows=(("row",),), elapsed_ms=1.0),
    )
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=True,
        truncation_reason="row_limit",
    )
    preview_ready = threading.Event()
    queued_started = threading.Event()
    release_preservation = threading.Event()
    release_queued = threading.Event()
    seen_requests: list[TUIRunRequest] = []
    persist_calls: list[int] = []
    original_persist_preview = store.persist_preview

    def persist_preview(**kwargs):
        persist_calls.append(kwargs["sequence"])
        return original_persist_preview(**kwargs)

    monkeypatch.setattr(store, "persist_preview", persist_preview)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        seen_requests.append(request)
        if len(seen_requests) == 1:
            event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
            preview_ready.set()
            assert release_preservation.wait(timeout=5.0)
            event_sink(
                TUIPreviewOnlyEvent(
                    sequence=request.sequences[0],
                    preview=preview,
                    reason="session_spool_limit",
                    stored=None,
                )
            )
            return
        queued_started.set()
        assert release_queued.wait(timeout=5.0)

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int, bool, bool, int | None, int | None, str, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 2 AS paused")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set() and app.state.active_query_result_record() is not None:
                    break

            sql.load_text("SELECT 3 AS queued")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            assert app.state.queued_run is not None

            release_preservation.set()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.active_query_result_record() is not None:
                    record = app.state.active_query_result_record()
                    if record is not None and record.state == "preview_only":
                        break
            active_before_history = app.state.active_result.sequence
            message_before_history = app.query_one("#results-message", Static).content

            app.query_one("#history", DataTable).focus()
            history = app.query_one("#history", DataTable)
            history.move_cursor(row=0)
            await pilot.pause()
            active_after_history = app.state.active_result.sequence
            message_after_history = app.query_one("#results-message", Static).content
            app.action_delete_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen)
            await pilot.press("y")
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen)
            await pilot.press("y")
            for _ in range(150):
                await pilot.pause(0.02)
                if queued_started.is_set():
                    break
            release_queued.set()
            for _ in range(150):
                await pilot.pause(0.02)
                if not app.state.query_run.is_running:
                    break
            record = app.state.query_result_record(2)
            return (
                len(seen_requests),
                record is not None and record.handle is not None,
                app.state.queued_run is None,
                active_before_history,
                active_after_history,
                message_before_history,
                message_after_history,
            )

    (
        seen_request_count,
        rebound_handle,
        queue_cleared,
        active_before_history,
        active_after_history,
        message_before_history,
        message_after_history,
    ) = asyncio.run(_inner())

    assert persist_calls == [2]
    assert seen_request_count == 2
    assert rebound_handle is True
    assert queue_cleared is True
    assert active_before_history == 2
    assert active_after_history == 2
    assert message_before_history == message_after_history


def test_retry_preview_persistence_can_fail_closed_and_leave_queue_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        store,
        sequence=1,
        sql="SELECT old",
        result=QueryResult(columns=("old",), rows=(("row",),), elapsed_ms=1.0),
    )
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
    seen_requests: list[TUIRunRequest] = []
    persist_calls: list[int] = []

    def persist_preview(**kwargs):
        persist_calls.append(kwargs["sequence"])
        return None

    monkeypatch.setattr(store, "persist_preview", persist_preview)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        seen_requests.append(request)
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        preview_ready.set()
        assert release_preservation.wait(timeout=5.0)
        event_sink(
            TUIPreviewOnlyEvent(
                sequence=request.sequences[0],
                preview=preview,
                reason="session_spool_limit",
                stored=None,
            )
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 2 AS paused")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set():
                    break
            app.query_one("#sql", TextArea).load_text("SELECT 3 AS queued")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            release_preservation.set()
            for _ in range(100):
                await pilot.pause(0.02)
                record = app.state.active_query_result_record()
                if record is not None and record.state == "preview_only":
                    break

            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()
            app.action_delete_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            await pilot.press("y")
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            await pilot.press("y")
            await pilot.pause(0.1)
            return (
                len(seen_requests),
                app.state.queued_run is not None,
                app.query_one("#status", Static).content,
            )

    seen_request_count, queue_retained, status = asyncio.run(_inner())

    assert persist_calls == [2]
    assert seen_request_count == 1
    assert queue_retained is True
    assert "Remove older stored results" in status
    assert "session result storage is full" in status


def test_retry_preview_persistence_exception_stays_paused_with_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        store,
        sequence=1,
        sql="SELECT old",
        result=QueryResult(columns=("old",), rows=(("row",),), elapsed_ms=1.0),
    )
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
    seen_requests: list[TUIRunRequest] = []
    persist_calls: list[int] = []
    persist_error = TUIResultStorageError(
        "Unable to serialize the query result for temporary storage.",
        kind="serialization",
    )
    persist_error.add_note("Cleanup uncertainty: the engine connection could not be closed.")

    def persist_preview(**kwargs):
        persist_calls.append(kwargs["sequence"])
        raise persist_error

    monkeypatch.setattr(store, "persist_preview", persist_preview)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        seen_requests.append(request)
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        preview_ready.set()
        assert release_preservation.wait(timeout=5.0)
        event_sink(
            TUIPreviewOnlyEvent(
                sequence=request.sequences[0],
                preview=preview,
                reason="session_spool_limit",
                stored=None,
            )
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT 2 AS paused")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set():
                    break
            app.query_one("#sql", TextArea).load_text("SELECT 3 AS queued")
            app.action_run_selected_or_current_query()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.queued_run is not None:
                    break
            release_preservation.set()
            for _ in range(100):
                await pilot.pause(0.02)
                record = app.state.active_query_result_record()
                if record is not None and record.state == "preview_only":
                    break
            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()
            app.action_delete_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            await pilot.press("y")
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            await pilot.press("y")
            await pilot.pause(0.1)
            return (
                len(seen_requests),
                app.state.queued_run is not None,
                app.query_one("#status", Static).content,
            )

    seen_request_count, queue_retained, status = asyncio.run(_inner())

    assert persist_calls == [2]
    assert seen_request_count == 1
    assert queue_retained is True
    assert "session result storage is full" in status
    assert "Unable to serialize the query result for temporary storage." in status
    assert "Cleanup uncertainty: the engine connection could not be closed." in status


def test_preview_persist_capacity_with_cleanup_uncertainty_raises_sanitized_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=True,
        truncation_reason="row_limit",
    )
    payload = encode_row_payload((1,))
    store = TUIResultStore(
        temp_root=tmp_path,
        capacity_bytes=14 + 8 + (8 + len(b"value")) + 9 + len(payload) + 9 - 1,
    )
    real_remove_staging_file = TUIResultStore._remove_staging_file

    def fail_staging_removal(store_: TUIResultStore, path: Path) -> bool:
        return False if path.name.endswith(".tmp") else real_remove_staging_file(store_, path)

    monkeypatch.setattr(TUIResultStore, "_remove_staging_file", fail_staging_removal)

    with pytest.raises(TUIResultStorageError) as error:
        store.persist_preview(
            sequence=1,
            preview=preview,
            reason="session_spool_limit",
            elapsed_ms=2.0,
        )

    assert error.value.kind == "io"
    assert error.value.user_message == "Unable to serialize the query result for temporary storage."
    assert "incomplete preserved result could not be fully removed" in "\n".join(
        getattr(error.value, "__notes__", ())
    )


def test_retry_confirmation_is_stale_when_paused_preview_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=True,
        truncation_reason="row_limit",
    )
    persisted: list[int] = []
    monkeypatch.setattr(
        store,
        "persist_preview",
        lambda **kwargs: persisted.append(kwargs["sequence"]),
    )

    async def _inner() -> str:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.state.set_active_result_record(
                2,
                TUIResultRecord(
                    handle=None,
                    state="executing",
                    reason=None,
                    columns=(),
                    preview_row_count=0,
                    full_row_count=None,
                    elapsed_ms=0.0,
                ),
                result_view=None,
            )
            app.state.set_active_result_record(
                2,
                TUIResultRecord(
                    handle=None,
                    state="preserving",
                    reason=None,
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
                    source_result_sequence=2,
                ),
            )
            app.state.record_query_result(
                2,
                "SELECT 2",
                record=TUIResultRecord(
                    handle=None,
                    state="preview_only",
                    reason="session_spool_limit",
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
                    source_result_sequence=2,
                ),
                complete_run=False,
            )
            app._transient_preview_only_result = _TransientPreviewOnlyResult(
                sequence=2,
                preview=preview,
                reason="session_spool_limit",
            )
            app.state.queued_run = TUIQueuedRun(
                request=TUIRunRequest(
                    statements=("SELECT 3",),
                    sequences=(3,),
                    sources=(),
                    fallback_sources=(),
                    preview_policy=PreviewPolicy(),
                    run_mode="current",
                    submission_order=2,
                )
            )
            app._clear_transient_preview_only(2)
            app._handle_paused_preview_retry_confirmation(2, True)
            await pilot.pause()
            return app.query_one("#status", Static).content

    status = asyncio.run(_inner())

    assert persisted == []
    assert "no longer available" in status.lower()


@pytest.mark.parametrize(
    "reason",
    ["session_spool_limit", "user_cancelled", "preservation_failed"],
)
def test_handleless_preview_without_queue_blocks_new_run_and_allows_explicit_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        store,
        sequence=1,
        sql="SELECT old",
        result=QueryResult(columns=("old",), rows=(("row",),), elapsed_ms=1.0),
    )
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
    seen_requests: list[TUIRunRequest] = []
    persist_calls: list[int] = []
    original_persist_preview = store.persist_preview

    def persist_preview(**kwargs):
        persist_calls.append(kwargs["sequence"])
        return original_persist_preview(**kwargs)

    monkeypatch.setattr(store, "persist_preview", persist_preview)

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, operation
        seen_requests.append(request)
        event_sink(TUIPreviewReadyEvent(sequence=request.sequences[0], preview=preview))
        preview_ready.set()
        assert release_preservation.wait(timeout=5.0)
        event_sink(
            TUIPreviewOnlyEvent(
                sequence=request.sequences[0],
                preview=preview,
                reason=reason,
                stored=None,
            )
        )

    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[int, int, bool, str]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            sql = app.query_one("#sql", TextArea)
            sql.load_text("SELECT 2 AS paused")
            await pilot.press("f4")
            for _ in range(100):
                await pilot.pause(0.02)
                if preview_ready.is_set():
                    break
            release_preservation.set()
            for _ in range(100):
                await pilot.pause(0.02)
                record = app.state.active_query_result_record()
                if record is not None and record.state == "preview_only":
                    break

            sql.load_text("SELECT 3 AS blocked")
            await pilot.press("f4")
            await pilot.pause(0.1)
            seen_requests_after_block = len(seen_requests)

            history = app.query_one("#history", DataTable)
            history.focus()
            history.move_cursor(row=0)
            await pilot.pause()
            app.action_delete_result()
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen)
            await pilot.press("y")
            for _ in range(100):
                await pilot.pause(0.02)
                if isinstance(app.screen, tui_app_module._ConfirmationScreen):
                    break
            assert isinstance(app.screen, tui_app_module._ConfirmationScreen)
            await pilot.press("y")
            await pilot.pause(0.1)
            record = app.state.query_result_record(2)
            return (
                seen_requests_after_block,
                len(seen_requests),
                record is not None and record.handle is not None,
                app.query_one("#status", Static).content,
            )

    seen_requests_after_block, final_seen_requests, rebound_handle, status = asyncio.run(_inner())

    assert seen_requests_after_block == 1
    assert final_seen_requests == 1
    assert persist_calls == [2]
    assert rebound_handle is True
    assert "remove older stored results" not in status.lower()


def test_transient_preview_blocks_buffer_tabs_and_non_query_result_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_source_state(tmp_path)
    store = TUIResultStore(temp_root=tmp_path)
    _record_stored_result(
        state,
        store,
        sequence=1,
        sql="SELECT old",
        result=QueryResult(columns=("old",), rows=(("row",),), elapsed_ms=1.0),
    )
    preview = BoundedQueryResult(
        columns=("value",),
        rows=((1,),),
        elapsed_ms=1.0,
        preview_payload_bytes=len(encode_row_payload((1,))),
        has_more_rows=True,
        truncation_reason="row_limit",
    )
    state.record_query_result(
        2,
        "SELECT paused",
        record=TUIResultRecord(
            handle=None,
            state="preview_only",
            reason="session_spool_limit",
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
            source_result_sequence=2,
        ),
        complete_run=False,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=1, index=1, label="query 1"),))
    state.queued_run = TUIQueuedRun(
        request=TUIRunRequest(
            statements=("SELECT queued",),
            sequences=(3,),
            sources=(),
            fallback_sources=(),
            preview_policy=PreviewPolicy(),
            run_mode="current",
            submission_order=2,
        )
    )
    inspect_calls: list[str] = []
    seen_requests: list[TUIRunRequest] = []

    def fake_inspect_source_columns(*args, **kwargs):
        del args, kwargs
        inspect_calls.append("inspect")
        raise AssertionError(
            "source columns should stay blocked while the transient preview is active"
        )

    def fake_run_tui_request(
        *,
        request: TUIRunRequest,
        result_store: TUIResultStore,
        event_sink,
        operation: OperationContext,
    ) -> None:
        del result_store, event_sink, operation
        seen_requests.append(request)

    monkeypatch.setattr("csvql.tui_app.inspect_source_columns", fake_inspect_source_columns)
    _patch_run_tui_request(monkeypatch, fake_run_tui_request)

    async def _inner() -> tuple[
        int | None,
        int | None,
        str | None,
        str,
        str,
        int | None,
        str,
    ]:
        app = CSVQLMenuApp(initial_state=state, start_dir=tmp_path, result_store=store)
        app._transient_preview_only_result = _TransientPreviewOnlyResult(
            sequence=2,
            preview=preview,
            reason="session_spool_limit",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app._show_buffer_result_at_tab(app.state.buffer_result_tabs[0])
            status_after_tab = app.query_one("#status", Static).content
            app.action_show_source_columns()
            await pilot.pause()
            app.state._selected_alias = None
            app.action_insert_source_alias()
            await pilot.pause()
            app._show_non_query_result_table(("field",), (("value",),), message="blocked")
            await pilot.pause()
            app.query_one("#sql", TextArea).load_text("SELECT blocked")
            await pilot.press("f4")
            await pilot.pause()
            return (
                app.state.active_result.sequence,
                app.state.active_result.sequence,
                None
                if app.state.active_query_result_record() is None
                else app.state.active_query_result_record().state,
                app.query_one("#results-message", Static).content,
                status_after_tab,
                app.state.queued_run.request.sequences[0] if app.state.queued_run else None,
                app.query_one("#status", Static).content,
            )

    (
        active_sequence,
        active_sequence_after_insert_error,
        active_record_state,
        message_after_guards,
        status_after_tab,
        queued_sequence,
        final_status,
    ) = asyncio.run(_inner())

    assert active_sequence == 2
    assert active_sequence_after_insert_error == 2
    assert active_record_state == "preview_only"
    assert "Query 2 kept only its active preview" in message_after_guards
    assert "Remove older stored results" in status_after_tab
    assert queued_sequence == 3
    assert status_after_tab in final_status
    assert "Previous result is still available." in final_status
    assert inspect_calls == []
    assert seen_requests == []
