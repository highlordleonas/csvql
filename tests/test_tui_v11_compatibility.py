from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

import csvql.tui_launcher as tui_launcher
from csvql.cli import app
from csvql.exceptions import CSVQLError
from csvql.models import QueryResult
from csvql.tui_launcher import run_menu_command
from csvql.tui_result_store import TUIResultCleanupSummary, TUIResultHandle
from csvql.tui_state import TUIBufferResultTab, TUISessionState, TUISource
from csvql.tui_workflows import (
    build_initial_state,
    inspect_source,
    profile_source,
    sample_source,
    save_derived_result_source,
    save_sources_to_project_catalog,
)

runner = CliRunner()


def _write_csv(path: Path, content: str = "id,value\n1,alpha\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _compat_source(tmp_path: Path) -> TUISource:
    csv_path = _write_csv(tmp_path / "customers.csv", "customer_id,email\nCUST-001,a@example.com\n")
    return TUISource(name="customers", path=csv_path.resolve(), origin="argument")


def _assert_source_preload_and_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    primary = _write_csv(tmp_path / "primary.csv")
    second = _write_csv(tmp_path / "second.csv")
    third = _write_csv(tmp_path / "third.csv")

    state = build_initial_state(
        csv_path=str(primary),
        table_mappings=(f"second={second}", f"third={third}"),
        start_dir=tmp_path,
    )

    assert tuple(source.name for source in state.sources) == ("primary", "second", "third")
    assert tuple(source.origin for source in state.sources) == ("argument", "argument", "argument")
    assert state.selected_alias == "primary"


def _assert_run_modes_and_history_recall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    state = TUISessionState()
    state.add_source(_compat_source(tmp_path))

    sequence = state.begin_query_run("SELECT 1 AS current_value")
    state.record_query_success(
        sequence,
        "SELECT 1 AS current_value",
        handle=TUIResultHandle(sequence=sequence, is_spilled=False),
        result_view=state.result_view,
        elapsed_ms=1.0,
    )
    buffer_sequence = state.begin_query_run("SELECT 2 AS buffered_value")
    state.record_query_no_result(
        buffer_sequence,
        "SELECT 2 AS buffered_value",
        elapsed_ms=2.0,
        run_mode="buffer",
    )
    rerun_sequence = state.begin_query_run("SELECT * FROM missing")
    state.record_query_error(
        rerun_sequence,
        "SELECT * FROM missing",
        "missing table",
        run_mode="rerun",
    )

    assert tuple(item.run_mode for item in state.query_history) == ("current", "buffer", "rerun")
    assert state.restore_query_result(sequence) is True
    assert state.active_result.kind == "history"
    assert state.active_result.sequence == sequence


def _assert_buffer_tabs_order_and_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    state = TUISessionState()
    state.add_source(_compat_source(tmp_path))

    first_sequence = state.begin_query_run("SELECT 1 AS first")
    first_view = state.result_view
    state.record_query_success(
        first_sequence,
        "SELECT 1 AS first",
        handle=TUIResultHandle(sequence=first_sequence, is_spilled=False),
        result_view=first_view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=1,
    )
    second_sequence = state.begin_query_run("SELECT 2 AS second")
    second_view = state.result_view
    state.record_query_success(
        second_sequence,
        "SELECT 2 AS second",
        handle=TUIResultHandle(sequence=second_sequence, is_spilled=False),
        result_view=second_view,
        elapsed_ms=1.0,
        run_mode="buffer",
        buffer_result_index=2,
    )
    state.set_buffer_result_tabs(
        (
            TUIBufferResultTab(
                sequence=first_sequence,
                index=1,
                label="query 1",
            ),
            TUIBufferResultTab(
                sequence=second_sequence,
                index=2,
                label="query 2",
            ),
        ),
        selected_sequence=first_sequence,
    )

    assert tuple(tab.sequence for tab in state.buffer_result_tabs) == (
        first_sequence,
        second_sequence,
    )
    assert state.active_result.sequence == first_sequence
    assert state.active_result.buffer_result_index == 1
    assert state.select_buffer_result(second_sequence) is True
    assert state.active_result.sequence == second_sequence
    assert state.active_result.buffer_result_index == 2
    assert state.result_view is second_view


def _assert_source_introspection_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    source = _compat_source(tmp_path)

    inspect_result = inspect_source(source)
    sample_result = sample_source(source, limit=1)
    profile_result = profile_source(source)

    assert inspect_result.source["display_path"] == "customers"
    assert sample_result.source["display_path"] == "customers"
    assert profile_result.source["display_path"] == "customers"
    assert sample_result.rows == (("CUST-001", "a@example.com"),)


def _assert_derived_csv_and_catalog_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    project_root = tmp_path / "project"
    project_root.mkdir()
    result = QueryResult(columns=("id",), rows=((1,),), elapsed_ms=1.0)

    derived = save_derived_result_source(
        result,
        "derived_ids",
        existing_sources=(),
        start_dir=project_root,
    )
    context = save_sources_to_project_catalog((derived,), start_dir=project_root, replace=False)

    assert derived.origin == "derived"
    assert derived.kind == "csv"
    assert derived.path == (project_root / ".csvql" / "results" / "derived_ids.csv").resolve()
    assert context.config.tables[0].name == "derived_ids"


def _assert_optional_textual_import_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_textual_import(module_name: str) -> object:
        if module_name == "csvql.tui_app":
            raise ModuleNotFoundError("No module named 'textual.widgets'", name="textual.widgets")
        return object()

    monkeypatch.setattr("csvql.tui_launcher.import_module", missing_textual_import)

    with pytest.raises(CSVQLError) as exc_info:
        run_menu_command(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert exc_info.value.message == "CSVQL TUI dependency is not installed."
    assert exc_info.value.suggestion == (
        'Install with pip install "localql[tui]" or run uv sync --all-extras.'
    )


def _assert_terminal_control_safety(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del tmp_path

    def fake_run_menu_command(
        *, csv_path: str | None, table_mappings: tuple[str, ...], start_dir: Path
    ) -> None:
        del csv_path, table_mappings, start_dir
        raise CSVQLError(
            "\x1b]0;spoof\x07[red]message[/red]\x00",
            suggestion="\x1b[31m[link=https://example.invalid]suggestion[/link]\x9b",
        )

    monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)
    result = runner.invoke(app, ["menu"], terminal_width=200)

    assert result.exit_code == 1, result.output
    assert "\x1b" not in result.output
    assert "\x07" not in result.output
    assert "\x00" not in result.output
    assert "\x9b" not in result.output
    assert r"Error: \x1b]0;spoof\x07[red]message[/red]\x00" in result.output


def _assert_final_cleanup_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_instance = Mock()
    app_instance.cleanup_summary = TUIResultCleanupSummary(files_failed=1, workspaces_failed=2)
    module = SimpleNamespace(CSVQLMenuApp=Mock(return_value=app_instance))
    monkeypatch.setattr(tui_launcher, "import_module", lambda name: module)
    monkeypatch.setattr(
        tui_launcher,
        "recover_abandoned_result_workspaces",
        lambda: TUIResultCleanupSummary(),
        raising=False,
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["menu"])

    assert result.exit_code == 0, result.output
    assert result.stderr == (
        "LocalQL warning: 3 temporary result cleanup item(s) could not be removed; "
        "a later launch or operating-system cleanup may remove them.\n"
    )


@pytest.mark.parametrize(
    "case",
    [
        _assert_source_preload_and_order,
        _assert_run_modes_and_history_recall,
        _assert_buffer_tabs_order_and_selection,
        _assert_source_introspection_surface,
        _assert_derived_csv_and_catalog_save,
        _assert_optional_textual_import_behavior,
        _assert_terminal_control_safety,
        _assert_final_cleanup_summary,
    ],
    ids=[
        "source-preload-order",
        "run-modes-and-history-recall",
        "buffer-tabs-order-selection",
        "source-inspect-sample-profile",
        "derived-csv-and-project-catalog",
        "optional-textual-import",
        "terminal-control-safety",
        "final-cleanup-summary",
    ],
)
def test_tui_v11_compatibility_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: Callable[[Path, pytest.MonkeyPatch], None],
) -> None:
    case(tmp_path, monkeypatch)
