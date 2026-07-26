from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from csvql.bounded_result import PreviewPolicy
from csvql.exceptions import TableMappingError
from csvql.export import ExportFormat
from csvql.models import TableSource
from csvql.tui_query_runner import TUIRunRequest
from csvql.tui_result_store import TUIResultHandle
from csvql.tui_state import (
    TUIActiveResultState,
    TUIBufferResultTab,
    TUIExportIntent,
    TUIExportIntentReplacement,
    TUIQueryHistoryItem,
    TUIQueryRunState,
    TUIQueuedRunReplacement,
    TUIResultCapabilities,
    TUIResultRecord,
    TUIResultViewState,
    TUISessionState,
    TUISource,
    TUISourceColumn,
    derive_result_capabilities,
    transition_result_record,
)


def _handle(sequence: int) -> TUIResultHandle:
    return TUIResultHandle(
        sequence=sequence,
        store_id=f"store-{sequence}",
        nonce=f"nonce-{sequence}",
    )


def _record(
    state: str,
    *,
    handle: TUIResultHandle | None = None,
    reason: str | None = None,
    columns: tuple[str, ...] = (),
    preview_row_count: int = 0,
    full_row_count: int | None = None,
    elapsed_ms: float = 1.5,
) -> TUIResultRecord:
    return TUIResultRecord(
        handle=handle,
        state=state,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        columns=columns,
        preview_row_count=preview_row_count,
        full_row_count=full_row_count,
        elapsed_ms=elapsed_ms,
    )


def _view(sequence: int, rows: tuple[tuple[str, ...], ...]) -> TUIResultViewState:
    return TUIResultViewState(
        columns=("value",),
        display_rows=rows,
        total_row_count=len(rows),
        source_result_sequence=sequence,
    )


def _run_request(*sequences: int, sql_prefix: str = "SELECT") -> TUIRunRequest:
    return TUIRunRequest(
        statements=tuple(f"{sql_prefix} {sequence}" for sequence in sequences),
        sequences=sequences,
        sources=(),
        fallback_sources=(),
        preview_policy=PreviewPolicy(),
        run_mode="buffer" if len(sequences) > 1 else "current",
        submission_order=sequences[0],
    )


def test_tui_source_as_table_source_returns_table_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    source = TUISource(name="orders", path=csv_path, origin="argument")

    assert source.as_table_source() == TableSource(name="orders", path=csv_path)


def test_tui_source_defaults_to_csv_kind(tmp_path: Path) -> None:
    source = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")

    assert source.kind == "csv"


def test_tui_source_uses_csv_kind_for_derived_provenance(tmp_path: Path) -> None:
    source = TUISource(
        name="order_names",
        path=tmp_path / ".csvql" / "results" / "order_names.csv",
        origin="derived",
    )

    assert source.kind == "csv"
    assert source.origin == "derived"


def test_private_result_handle_is_not_convertible_to_a_tui_source() -> None:
    handle = _handle(1)

    assert not isinstance(handle, TUISource)
    assert not hasattr(handle, "as_table_source")


@pytest.mark.parametrize(
    "artifact_name",
    [
        "query-1.result",
        "preview-2.result",
        f".query-3-{'b' * 16}.result.tmp",
        f".preview-4-{'c' * 16}.result.tmp",
    ],
)
def test_tui_source_rejects_private_result_artifacts_before_state_admission(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    private_path = tmp_path / f"localql-tui-v1-{'a' * 32}" / artifact_name

    with pytest.raises(TableMappingError) as error:
        TUISource(name="private_result", path=private_path, origin="session")

    assert str(private_path) not in str(error.value)
    assert error.value.message == "Private TUI result artifacts cannot be used as sources."
    assert error.value.suggestion == "Use Save as source to create a normal CSV source."


def test_session_add_source_preserves_order_and_selects_first_by_default(tmp_path: Path) -> None:
    state = TUISessionState()
    first = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    second = TUISource(name="customers", path=tmp_path / "customers.csv", origin="catalog")

    state.add_source(first)
    state.add_source(second)

    assert state.sources == (first, second)
    assert state.table_sources == (
        TableSource(name="orders", path=tmp_path / "orders.csv"),
        TableSource(name="customers", path=tmp_path / "customers.csv"),
    )
    assert state.selected_source() == first


@pytest.mark.parametrize("alias", ["orders", "ORDERS"])
def test_duplicate_aliases_are_rejected_case_insensitively(tmp_path: Path, alias: str) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    with pytest.raises(TableMappingError):
        state.add_source(TUISource(name=alias, path=tmp_path / "duplicate.csv", origin="session"))


def test_removing_selected_source_advances_selection(tmp_path: Path) -> None:
    state = TUISessionState()
    first = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    second = TUISource(name="customers", path=tmp_path / "customers.csv", origin="catalog")
    state.add_source(first)
    state.add_source(second)

    removed = state.remove_source("orders")

    assert removed == first
    assert state.sources == (second,)
    assert state.selected_source() == second
    assert state.selected_alias == "customers"


def test_removing_unknown_alias_fails(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))

    with pytest.raises(
        TableMappingError,
        match=r"Source alias 'customers' is not loaded in the TUI session\.",
    ):
        state.remove_source("customers")


def test_selecting_and_getting_sources_is_case_insensitive(tmp_path: Path) -> None:
    state = TUISessionState()
    source = TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument")
    state.add_source(source)

    assert state.get_source("ORDERS") == source
    assert state.select_source("ORDERS") == source
    assert state.selected_source() == source

    with pytest.raises(
        TableMappingError,
        match=r"Source alias 'customers' is not loaded in the TUI session\.",
    ):
        state.get_source("customers")
    with pytest.raises(
        TableMappingError,
        match=r"Source alias 'customers' is not loaded in the TUI session\.",
    ):
        state.select_source("customers")


def test_session_source_columns_are_case_insensitive_by_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    columns = (
        TUISourceColumn(name="order_id", duckdb_type="VARCHAR"),
        TUISourceColumn(name="total", duckdb_type="DOUBLE"),
    )

    state.set_source_columns("ORDERS", columns)

    assert state.source_columns("orders") == columns


def test_removing_source_clears_cached_columns_for_that_alias(tmp_path: Path) -> None:
    state = TUISessionState()
    state.add_source(TUISource(name="orders", path=tmp_path / "orders.csv", origin="argument"))
    state.add_source(
        TUISource(name="customers", path=tmp_path / "customers.csv", origin="argument")
    )
    state.set_source_columns("orders", (TUISourceColumn(name="order_id", duckdb_type="VARCHAR"),))
    state.set_source_columns(
        "customers",
        (TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),),
    )

    state.remove_source("ORDERS")

    assert state.source_columns("orders") == ()
    assert state.source_columns("customers") == (
        TUISourceColumn(name="customer_id", duckdb_type="VARCHAR"),
    )


def test_tui_source_column_stores_name_and_duckdb_type() -> None:
    column = TUISourceColumn(name="Customer ID", duckdb_type="VARCHAR")

    assert column.name == "Customer ID"
    assert column.duckdb_type == "VARCHAR"


def test_query_history_item_defaults_to_current_run_mode() -> None:
    item = TUIQueryHistoryItem(sequence=1, sql="SELECT 1", status="success")

    assert item.run_mode == "current"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("executing", TUIResultCapabilities(False, True, False, False, False)),
        ("preserving", TUIResultCapabilities(True, True, False, False, False)),
        ("complete", TUIResultCapabilities(True, False, True, True, True)),
        ("preview_only", TUIResultCapabilities(True, False, False, False, True)),
        ("cancelled", TUIResultCapabilities(False, False, False, False, False)),
        ("failed", TUIResultCapabilities(False, False, False, False, False)),
    ],
)
def test_derive_result_capabilities_matches_state_table(
    state: str,
    expected: TUIResultCapabilities,
) -> None:
    assert derive_result_capabilities(state) == expected  # type: ignore[arg-type]


def test_result_record_rejects_invalid_state_shapes() -> None:
    with pytest.raises(ValueError, match="executing results cannot retain preview metadata"):
        _record("executing", columns=("value",), preview_row_count=1)

    with pytest.raises(
        ValueError,
        match="terminal non-preview results cannot retain preview metadata",
    ):
        _record("failed", columns=("value",), preview_row_count=1)

    with pytest.raises(ValueError, match="complete results require a durable handle"):
        _record("complete", columns=("value",), preview_row_count=1, full_row_count=1)

    with pytest.raises(ValueError, match="preview_only results require a reason"):
        _record("preview_only", columns=("value",), preview_row_count=1)

    with pytest.raises(ValueError, match="preview row count cannot exceed"):
        _record(
            "complete",
            handle=_handle(1),
            columns=("value",),
            preview_row_count=2,
            full_row_count=1,
        )

    with pytest.raises(ValueError, match="unsupported result state"):
        _record("invented", reason="user_cancelled")

    memory_only = _record(
        "preview_only",
        reason="user_cancelled",
        columns=("value",),
        preview_row_count=1,
    )

    assert memory_only.handle is None


def test_transition_result_record_supports_realistic_lifecycle_updates() -> None:
    executing = _record("executing", elapsed_ms=0.1)
    preserving = transition_result_record(
        executing,
        state="preserving",
        columns=("value",),
        preview_row_count=2,
        elapsed_ms=1.2,
    )
    complete = transition_result_record(
        preserving,
        state="complete",
        handle=_handle(1),
        full_row_count=4,
        elapsed_ms=1.7,
    )
    preview_only = transition_result_record(
        preserving,
        state="preview_only",
        reason="user_cancelled",
        elapsed_ms=1.9,
    )

    assert preserving.columns == ("value",)
    assert preserving.preview_row_count == 2
    assert preserving.elapsed_ms == 1.2
    assert complete.full_row_count == 4
    assert complete.elapsed_ms == 1.7
    assert preview_only.handle is None
    assert preview_only.reason == "user_cancelled"

    with pytest.raises(ValueError, match="illegal result transition"):
        transition_result_record(executing, state="complete", handle=_handle(1), full_row_count=1)


def test_record_query_result_validates_handle_sequence() -> None:
    state = TUISessionState()

    with pytest.raises(ValueError, match="result handle sequence must match query sequence"):
        state.record_query_result(
            1,
            "SELECT 1",
            record=_record(
                "complete",
                handle=_handle(2),
                columns=("value",),
                preview_row_count=1,
                full_row_count=1,
            ),
            result_view=_view(1, (("1",),)),
        )


def test_active_preview_identity_must_match_its_result_record() -> None:
    state = TUISessionState()
    state.set_active_result_record(1, _record("executing"))

    with pytest.raises(ValueError, match="preview sequence must match"):
        state.set_active_result_record(
            1,
            _record("preserving", columns=("value",), preview_row_count=1),
            result_view=_view(2, (("1",),)),
        )
    with pytest.raises(ValueError, match="preview columns must match"):
        state.set_active_result_record(
            1,
            _record("preserving", columns=("different",), preview_row_count=1),
            result_view=_view(1, (("1",),)),
        )


def test_set_active_result_record_enforces_legal_transitions() -> None:
    state = TUISessionState()

    with pytest.raises(ValueError, match="lifecycle must begin in executing"):
        state.set_active_result_record(
            1,
            _record(
                "complete",
                handle=_handle(1),
                columns=("value",),
                preview_row_count=1,
                full_row_count=1,
            ),
        )

    state.set_active_result_record(1, _record("executing"))
    state.set_active_result_record(
        1,
        _record("preserving", columns=("value",), preview_row_count=1),
        result_view=_view(1, (("1",),)),
    )

    with pytest.raises(ValueError, match="illegal result transition"):
        state.set_active_result_record(1, _record("executing"))

    state.set_active_result_record(
        1,
        _record(
            "complete",
            handle=_handle(1),
            columns=("value",),
            preview_row_count=1,
            full_row_count=2,
        ),
        result_view=_view(1, (("1",),)),
    )

    with pytest.raises(ValueError, match="illegal result transition"):
        state.set_active_result_record(
            1,
            _record("preserving", columns=("value",), preview_row_count=1),
        )


def test_record_query_success_stores_metadata_without_historical_views() -> None:
    state = TUISessionState()
    view = _view(1, (("1",),))

    state.record_query_success(
        1,
        "SELECT 1",
        handle=_handle(1),
        result_view=view,
        elapsed_ms=1.0,
    )

    stored = state.query_result_record(1)
    assert stored is not None
    assert not hasattr(stored, "view")
    assert state.result_view is view
    assert state.active_result.sequence == 1
    assert state.query_history[-1].row_count == 1


def test_memory_only_preview_only_remains_active_but_is_not_restorable() -> None:
    state = TUISessionState()
    view = _view(1, (("preview",),))

    state.record_query_result(
        1,
        "SELECT 1",
        record=_record(
            "preview_only",
            reason="user_cancelled",
            columns=("value",),
            preview_row_count=1,
        ),
        result_view=view,
    )

    assert state.active_result_record is not None
    assert state.active_result_record.state == "preview_only"
    assert state.query_result_record(1) is None
    assert state.restore_query_result(1) is False
    assert state.result_view is view
    assert state.query_history[-1].row_count is None


def test_record_query_cancelled_clears_active_selection_but_retains_attempt() -> None:
    state = TUISessionState()
    state.set_active_result_record(1, _record("executing"))

    state.record_query_cancelled(1, "SELECT 1", elapsed_ms=2.0)

    assert state.query_history[-1].status == "cancelled"
    assert state.active_result == TUIActiveResultState()


def test_record_query_result_without_activation_preserves_existing_selection() -> None:
    state = TUISessionState()
    prior_view = _view(1, (("prior",),))
    state.record_query_success(
        1,
        "SELECT prior",
        handle=_handle(1),
        result_view=prior_view,
        elapsed_ms=1.0,
    )

    state.record_query_result(
        2,
        "SELECT background",
        record=_record(
            "complete",
            handle=_handle(2),
            columns=("value",),
            preview_row_count=1,
            full_row_count=1,
        ),
        run_mode="current",
        activate_result=False,
    )

    assert state.active_result.sequence == 1
    assert state.result_view is prior_view
    assert state.query_result_record(2) == _record(
        "complete",
        handle=_handle(2),
        columns=("value",),
        preview_row_count=1,
        full_row_count=1,
    )


def test_background_recording_requires_unrelated_active_selection_and_no_view() -> None:
    state = TUISessionState()

    with pytest.raises(ValueError, match="unrelated active selection"):
        state.record_query_result(
            1,
            "SELECT 1",
            record=_record(
                "complete",
                handle=_handle(1),
                columns=("value",),
                preview_row_count=1,
                full_row_count=1,
            ),
            activate_result=False,
        )

    prior_view = _view(1, (("prior",),))
    state.record_query_success(
        1,
        "SELECT prior",
        handle=_handle(1),
        result_view=prior_view,
        elapsed_ms=1.0,
    )
    with pytest.raises(ValueError, match="cannot retain an undisplayed preview"):
        state.record_query_result(
            2,
            "SELECT 2",
            record=_record(
                "complete",
                handle=_handle(2),
                columns=("value",),
                preview_row_count=1,
                full_row_count=1,
            ),
            result_view=_view(2, (("2",),)),
            activate_result=False,
        )


def test_terminal_outcomes_can_preserve_unrelated_active_result() -> None:
    state = TUISessionState()
    prior_view = _view(1, (("prior",),))
    state.record_query_success(
        1,
        "SELECT prior",
        handle=_handle(1),
        result_view=prior_view,
        elapsed_ms=1.0,
    )
    sequence = 2
    state.start_query_request(_run_request(sequence))

    state.record_query_no_result(
        sequence,
        "SELECT 2",
        1.0,
        complete_run=False,
        preserve_active_result=True,
    )
    assert state.active_result.sequence == 1
    assert state.result_view is prior_view
    assert state.last_result_status == "query"
    state.finish_query_run()

    state.start_query_request(_run_request(3))
    sequence = state.query_run.sequence
    assert sequence is not None
    state.record_query_cancelled(
        sequence,
        "SELECT 3",
        complete_run=False,
        preserve_active_result=True,
    )
    assert state.active_result.sequence == 1
    assert state.result_view is prior_view
    state.finish_query_run()

    state.start_query_request(_run_request(4))
    sequence = state.query_run.sequence
    assert sequence is not None
    state.record_query_failed(
        sequence,
        "SELECT 4",
        "failed",
        preserve_active_result=True,
    )

    assert state.active_result.sequence == 1
    assert state.result_view is prior_view
    assert [item.status for item in state.query_history] == [
        "success",
        "no_result",
        "cancelled",
        "error",
    ]


def test_preserved_terminalization_requires_unrelated_active_selection() -> None:
    state = TUISessionState()
    state.set_active_result_record(1, _record("executing"))

    with pytest.raises(ValueError, match="unrelated active selection"):
        state.record_query_no_result(1, "SELECT 1", 1.0, preserve_active_result=True)
    with pytest.raises(ValueError, match="unrelated active selection"):
        state.record_query_cancelled(1, "SELECT 1", preserve_active_result=True)
    with pytest.raises(ValueError, match="unrelated active selection"):
        state.record_query_failed(1, "SELECT 1", "failed", preserve_active_result=True)


def test_non_preview_terminalization_rejects_an_active_preview() -> None:
    state = TUISessionState()
    state.set_active_result_record(1, _record("executing"))
    state.set_active_result_record(
        1,
        _record("preserving", columns=("value",), preview_row_count=1),
        result_view=_view(1, (("preview",),)),
    )

    with pytest.raises(ValueError, match="illegal result transition"):
        state.record_query_cancelled(1, "SELECT 1")
    with pytest.raises(ValueError, match="illegal result transition"):
        state.record_query_failed(1, "SELECT 1", "failed")


def test_active_query_result_record_returns_the_active_memory_record() -> None:
    state = TUISessionState()
    state.set_active_result_record(1, _record("executing"))
    state.set_active_result_record(
        1,
        _record("preserving", columns=("value",), preview_row_count=1),
        result_view=_view(1, (("preview",),)),
    )

    assert state.query_result_record(1) is None
    assert state.active_query_result_record() is state.active_result_record
    assert state.active_query_result_record().state == "preserving"


def test_restore_query_result_clears_stale_view_and_sets_matching_record() -> None:
    state = TUISessionState()
    state.record_query_result(
        1,
        "SELECT 1",
        record=_record(
            "complete",
            handle=_handle(1),
            columns=("value",),
            preview_row_count=1,
            full_row_count=3,
        ),
        result_view=_view(1, (("1",),)),
    )
    state.result_view = _view(99, (("stale",),))

    assert state.restore_query_result(1) is True
    assert state.active_result.kind == "history"
    assert state.active_result_record == state.query_result_record(1)
    assert state.result_view == TUIResultViewState()
    assert state.active_result_capabilities().can_export_full is True


def test_select_buffer_result_clears_stale_view_and_sets_matching_record() -> None:
    state = TUISessionState()
    first = _record(
        "complete",
        handle=_handle(1),
        columns=("value",),
        preview_row_count=1,
        full_row_count=1,
    )
    second = _record(
        "preview_only",
        handle=_handle(2),
        reason="session_spool_limit",
        columns=("value",),
        preview_row_count=1,
    )
    state.record_query_result(1, "SELECT 1", record=first, result_view=_view(1, (("1",),)))
    state.record_query_result(2, "SELECT 2", record=second, result_view=_view(2, (("2",),)))
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(sequence=1, index=1, label="query 1"),
            TUIBufferResultTab(sequence=2, index=2, label="query 2"),
        )
    )
    state.result_view = _view(77, (("stale",),))

    assert state.select_buffer_result(2) is True
    assert state.active_result.kind == "buffer"
    assert state.active_result_record == second
    assert state.result_view == TUIResultViewState()
    assert state.active_result_capabilities().can_remove is True


def test_buffer_result_tabs_reset_stale_active_result_when_cleared_or_replaced() -> None:
    state = TUISessionState()
    state.record_query_result(
        1,
        "SELECT 1",
        record=_record(
            "complete",
            handle=_handle(1),
            columns=("value",),
            preview_row_count=1,
            full_row_count=1,
        ),
        result_view=_view(1, (("1",),)),
        run_mode="buffer",
        buffer_result_index=1,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=1, index=1, label="query 1"),))

    state.clear_buffer_result_tabs()
    assert state.active_result == TUIActiveResultState()
    assert state.result_view == TUIResultViewState()

    state.record_query_result(
        2,
        "SELECT 2",
        record=_record(
            "complete",
            handle=_handle(2),
            columns=("value",),
            preview_row_count=1,
            full_row_count=1,
        ),
        result_view=_view(2, (("2",),)),
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=2, index=2, label="query 2"),))
    state.set_buffer_result_tabs((TUIBufferResultTab(sequence=3, index=1, label="query 3"),))

    assert state.active_result == TUIActiveResultState()
    assert state.active_result_record is None
    assert state.result_view == TUIResultViewState()


def test_storage_error_preserves_active_preview_and_uses_error_history_status() -> None:
    state = TUISessionState()
    view = _view(1, (("1",),))
    state.record_query_success(
        1,
        "SELECT 1",
        handle=_handle(1),
        result_view=view,
        elapsed_ms=1.0,
    )
    sequence = 2
    state.start_query_request(_run_request(sequence))

    state.record_query_storage_error(
        sequence,
        "SELECT * FROM large",
        "Unable to store the query result.",
    )

    assert state.active_result.sequence == 1
    assert state.result_view is view
    assert state.query_history[-1].status == "error"


def test_mark_results_unavailable_drops_durable_record_without_inventing_preview_state() -> None:
    state = TUISessionState()
    view = _view(1, (("1",),))
    state.record_query_success(
        1,
        "SELECT 1",
        handle=_handle(1),
        result_view=view,
        elapsed_ms=1.0,
    )

    state.mark_results_unavailable((1,), "The full result is no longer available.")

    assert state.query_result_record(1) is None
    assert state.active_result == TUIActiveResultState()
    assert state.active_result_record is None
    assert state.result_view == TUIResultViewState()


def test_mark_results_unavailable_does_not_drop_an_existing_memory_only_preview() -> None:
    state = TUISessionState()
    view = _view(1, (("1",),))
    state.set_active_result_record(1, _record("executing"))
    state.set_active_result_record(
        1,
        _record(
            "preserving",
            columns=("value",),
            preview_row_count=1,
        ),
        result_view=view,
    )
    state.set_active_result_record(
        1,
        _record(
            "preview_only",
            reason="session_spool_limit",
            columns=("value",),
            preview_row_count=1,
        ),
        result_view=view,
    )

    state.mark_results_unavailable((1,), "Unrelated durable storage was invalidated.")

    assert state.active_result.sequence == 1
    assert state.active_result_record is not None
    assert state.active_result_record.state == "preview_only"
    assert state.active_result_record.reason == "session_spool_limit"
    assert state.result_view is view


def test_remove_query_result_drops_record_and_handle_but_keeps_attempt() -> None:
    state = TUISessionState()
    state.record_query_result(
        1,
        "SELECT 1",
        record=_record(
            "complete",
            handle=_handle(1),
            columns=("value",),
            preview_row_count=1,
            full_row_count=1,
        ),
        result_view=_view(1, (("1",),)),
    )

    removed = state.remove_query_result(1)

    assert removed == _handle(1)
    assert state.query_result_record(1) is None
    assert [item.sequence for item in state.query_history] == [1]


def test_remove_memory_only_preview_discards_the_active_view() -> None:
    state = TUISessionState()
    state.record_query_result(
        1,
        "SELECT 1",
        record=_record(
            "preview_only",
            reason="session_spool_limit",
            columns=("value",),
            preview_row_count=1,
        ),
        result_view=_view(1, (("preview",),)),
    )

    assert state.remove_query_result(1) is None
    assert state.active_result == TUIActiveResultState()
    assert state.active_result_record is None
    assert state.result_view == TUIResultViewState()
    assert [item.sequence for item in state.query_history] == [1]


def test_start_query_request_prevents_overlapping_runs() -> None:
    state = TUISessionState()
    request = _run_request(*state.reserve_query_sequences(1))
    state.start_query_request(request)

    assert state.query_run.request is request
    assert state.query_run.sequence == 1

    with pytest.raises(RuntimeError, match="query is already running"):
        state.start_query_request(_run_request(*state.reserve_query_sequences(1)))


def test_start_query_request_tracks_contiguous_batch_sequences() -> None:
    state = TUISessionState()
    sequences = state.reserve_query_sequences(3)
    request = _run_request(*sequences)
    state.start_query_request(request)

    assert sequences == (1, 2, 3)
    assert state.query_run.request is request
    assert state.query_run.sequence == 1
    assert state.query_run.sequences == sequences


def test_reserve_query_sequences_does_not_start_run() -> None:
    state = TUISessionState()

    assert state.reserve_query_sequences(2) == (1, 2)
    assert state.query_run.is_running is False
    assert state.reserve_query_sequences(1) == (3,)


def test_start_query_request_tracks_all_sequences_in_active_request() -> None:
    state = TUISessionState()
    reserved = state.reserve_query_sequences(3)
    request = _run_request(*reserved)

    state.start_query_request(request)

    assert state.is_current_query_sequence(1) is True
    assert state.is_current_query_sequence(2) is True
    assert state.is_current_query_sequence(3) is True
    assert state.is_current_query_sequence(4) is False


def test_active_and_queued_requests_reject_reused_sequence_ids() -> None:
    state = TUISessionState()
    active = _run_request(1)
    state.start_query_request(active)

    with pytest.raises(ValueError, match="sequence IDs must not be reused"):
        state.enqueue_run(_run_request(1))

    queued = _run_request(2)
    state.enqueue_run(queued)
    with pytest.raises(ValueError, match="sequence IDs must not be reused"):
        state.enqueue_run(_run_request(2))


def test_query_run_state_derives_all_live_identity_from_the_request() -> None:
    request = _run_request(1, 2)
    run = TUIQueryRunState(request=request)

    assert tuple(TUIQueryRunState.__dataclass_fields__) == ("request",)
    assert run.is_running is True
    assert run.sequence == 1
    assert run.sequences == (1, 2)
    assert run.request is request


def test_batch_outcomes_finish_only_after_batch_completion() -> None:
    state = TUISessionState()
    sequences = state.reserve_query_sequences(2)
    state.start_query_request(_run_request(*sequences))

    state.record_query_success(
        sequences[0],
        "SELECT 1",
        handle=_handle(sequences[0]),
        result_view=_view(sequences[0], (("1",),)),
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
        complete_run=False,
    )
    state.record_query_no_result(
        sequences[1],
        "SELECT 2",
        1.0,
        run_mode="buffer",
        complete_run=False,
    )

    assert state.query_run.is_running is True
    state.finish_query_run()
    assert state.query_run.is_running is False


def test_record_query_success_and_no_result_and_error_preserve_run_modes() -> None:
    state = TUISessionState()
    state.record_query_success(
        1,
        "SELECT 1",
        handle=_handle(1),
        result_view=_view(1, (("1",),)),
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
    )
    state.record_query_no_result(2, "CREATE TABLE t AS SELECT 1", 1.0, run_mode="rerun")
    state.record_query_error(3, "SELECT * FROM missing", "missing", run_mode="rerun")

    assert [item.run_mode for item in state.query_history] == ["buffer", "rerun", "rerun"]
    assert state.query_history[-1].status == "error"


def test_enqueue_run_requires_active_request_and_uses_identity_confirmation() -> None:
    state = TUISessionState()

    with pytest.raises(RuntimeError, match="queued run requires an active query request"):
        state.enqueue_run(_run_request(2))

    active_request = _run_request(*state.reserve_query_sequences(1))
    state.start_query_request(active_request)
    queued_request = _run_request(*state.reserve_query_sequences(1))
    replacement_request = _run_request(*state.reserve_query_sequences(1))
    state.enqueue_run(queued_request)
    replacement = state.enqueue_run(replacement_request)
    assert replacement is not None

    stale = TUIQueuedRunReplacement(
        existing=type(replacement.existing)(request=replacement.existing.request),
        proposed=replacement.proposed,
    )
    with pytest.raises(RuntimeError, match="queued run changed before confirmation"):
        state.replace_queued_run(stale)

    state.replace_queued_run(replacement)
    with pytest.raises(RuntimeError, match="before the active query terminalizes"):
        state.dequeue_run()
    state.finish_query_run()
    assert state.dequeue_run().request is replacement_request
    assert state.dequeue_run() is None


def test_queued_run_snapshot_is_frozen_around_exact_request() -> None:
    state = TUISessionState()
    active_request = _run_request(*state.reserve_query_sequences(1))
    queued_request = _run_request(*state.reserve_query_sequences(1))
    state.start_query_request(active_request)
    state.enqueue_run(queued_request)

    assert state.queued_run is not None
    assert state.queued_run.request is queued_request

    with pytest.raises(FrozenInstanceError):
        state.queued_run.request = _run_request(99)  # type: ignore[misc]


def test_export_intent_uses_real_export_format_and_identity_confirmation() -> None:
    state = TUISessionState()
    state.set_active_result_record(
        5,
        _record("executing"),
    )
    state.set_active_result_record(
        5,
        _record("preserving", columns=("value",), preview_row_count=1),
        result_view=_view(5, (("preview",),)),
    )
    first = TUIExportIntent(
        result_sequence=5,
        destination=Path("/tmp/first.csv"),
        format=ExportFormat.csv,
    )
    second = TUIExportIntent(
        result_sequence=5,
        destination=Path("/tmp/second.txt"),
        format=ExportFormat.text,
    )

    state.attach_export_intent(first)
    replacement = state.attach_export_intent(second)
    assert replacement is not None

    stale = TUIExportIntentReplacement(
        existing=TUIExportIntent(
            result_sequence=5,
            destination=Path("/tmp/first.csv"),
            format=ExportFormat.csv,
        ),
        proposed=replacement.proposed,
    )
    with pytest.raises(RuntimeError, match="export intent changed before confirmation"):
        state.replace_export_intent(stale)

    state.replace_export_intent(replacement)
    assert state.export_intent is second

    with pytest.raises(RuntimeError, match="export intent changed before confirmation"):
        state.clear_export_intent(first)

    state.clear_export_intent(second)
    assert state.export_intent is None


def test_export_intent_rejects_non_preserving_active_result() -> None:
    state = TUISessionState()
    state.set_active_result_record(8, _record("executing"))

    with pytest.raises(RuntimeError, match="export intents require the active preserving result"):
        state.attach_export_intent(
            TUIExportIntent(
                result_sequence=8,
                destination=Path("/tmp/out.csv"),
                format=ExportFormat.csv,
            )
        )
