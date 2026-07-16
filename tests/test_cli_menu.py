from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

import csvql.tui_launcher as tui_launcher
from csvql import __version__
from csvql.cli import app
from csvql.exceptions import CSVQLError
from csvql.tui_launcher import run_menu_command
from csvql.tui_result_store import TUIResultCleanupSummary

runner = CliRunner()


def test_root_help_is_still_shown_for_no_args() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "Query local CSV files with DuckDB SQL." in result.output


def test_menu_help_lists_startup_arguments() -> None:
    result = runner.invoke(app, ["menu", "--help"], terminal_width=120)

    assert result.exit_code == 0, result.output
    assert "Open the interactive CSVQL terminal menu." in result.output


def test_menu_delegates_startup_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_run_menu_command(
        *, csv_path: str | None, table_mappings: tuple[str, ...], start_dir: Path
    ) -> None:
        captured["csv_path"] = csv_path
        captured["table_mappings"] = table_mappings
        captured["start_dir"] = start_dir

    monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)

    result = runner.invoke(
        app,
        [
            "menu",
            str(tmp_path / "customers.csv"),
            "--table",
            f"customers={tmp_path / 'customers.csv'}",
            "--table",
            f"orders={tmp_path / 'orders.csv'}",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["csv_path"] == str(tmp_path / "customers.csv")
    assert captured["table_mappings"] == (
        f"customers={tmp_path / 'customers.csv'}",
        f"orders={tmp_path / 'orders.csv'}",
    )
    assert captured["start_dir"] == Path.cwd()


def test_menu_without_startup_args_forwards_empty_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_menu_command(
        *, csv_path: str | None, table_mappings: tuple[str, ...], start_dir: Path
    ) -> None:
        captured["csv_path"] = csv_path
        captured["table_mappings"] = table_mappings
        captured["start_dir"] = start_dir

    monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)

    result = runner.invoke(app, ["menu"])

    assert result.exit_code == 0, result.output
    assert captured["csv_path"] is None
    assert captured["table_mappings"] == ()
    assert captured["start_dir"] == Path.cwd()


def test_menu_uses_existing_cli_error_path() -> None:
    def fake_run_menu_command(
        *, csv_path: str | None, table_mappings: tuple[str, ...], start_dir: Path
    ) -> None:
        raise CSVQLError(
            "CSVQL TUI dependency is not installed.",
            suggestion='Install with pip install "localql[tui]".',
        )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)
        result = runner.invoke(app, ["menu"])

    assert result.exit_code == 1, result.output
    assert "CSVQL TUI dependency is not installed." in result.output
    assert 'Install with pip install "localql[tui]".' in result.output


def test_cli_errors_render_control_safe_literal_text() -> None:
    def fake_run_menu_command(
        *, csv_path: str | None, table_mappings: tuple[str, ...], start_dir: Path
    ) -> None:
        raise CSVQLError(
            "\x1b]0;spoof\x07[red]message[/red]\x00",
            suggestion="\x1b[31m[link=https://example.invalid]suggestion[/link]\x9b",
        )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("csvql.cli.run_menu_command", fake_run_menu_command)
        result = runner.invoke(app, ["menu"], terminal_width=200)

    assert result.exit_code == 1, result.output
    assert "\x1b" not in result.output
    assert "\x07" not in result.output
    assert "\x00" not in result.output
    assert "\x9b" not in result.output
    assert r"Error: \x1b]0;spoof\x07[red]message[/red]\x00" in result.output
    assert (
        r"Suggestion: \x1b[31m[link=https://example.invalid]suggestion[/link]\x9b" in result.output
    )


def test_version_flag_reports_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == __version__


def test_menu_launcher_raises_helpful_error_when_textual_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_textual_import(module_name: str) -> object:
        if module_name == "csvql.tui_app":
            raise ModuleNotFoundError(
                "No module named 'textual.widgets'",
                name="textual.widgets",
            )
        return object()

    monkeypatch.setattr("csvql.tui_launcher.import_module", missing_textual_import)

    with pytest.raises(CSVQLError) as exc_info:
        run_menu_command(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert exc_info.value.message == "CSVQL TUI dependency is not installed."
    assert (
        exc_info.value.suggestion
        == 'Install with pip install "localql[tui]" or run uv sync --all-extras.'
    )


def test_launcher_recovers_once_before_constructing_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    captured: dict[str, object] = {}
    recovery_summary = TUIResultCleanupSummary(files_removed=1)
    app_instance = Mock()

    def recover() -> TUIResultCleanupSummary:
        events.append("recover")
        return recovery_summary

    def app_class(**kwargs: object) -> Mock:
        events.append("construct")
        captured.update(kwargs)
        app_instance.run.side_effect = lambda: events.append("run")
        app_instance.cleanup_summary = TUIResultCleanupSummary()
        return app_instance

    module = SimpleNamespace(CSVQLMenuApp=app_class)
    monkeypatch.setattr(tui_launcher, "import_module", lambda name: module)
    monkeypatch.setattr(
        tui_launcher,
        "recover_abandoned_result_workspaces",
        recover,
        raising=False,
    )

    run_menu_command(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert events == ["recover", "construct", "run"]
    assert captured["initial_cleanup_summary"] is recovery_summary


def test_launcher_emits_one_sanitized_cleanup_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive_path = tmp_path / "private-customer-query.csv"
    app_instance = Mock()
    app_instance.cleanup_summary = TUIResultCleanupSummary(
        files_failed=1,
        workspaces_failed=2,
    )
    module = SimpleNamespace(CSVQLMenuApp=Mock(return_value=app_instance))
    monkeypatch.setattr(tui_launcher, "import_module", lambda name: module)
    monkeypatch.setattr(
        tui_launcher,
        "recover_abandoned_result_workspaces",
        lambda: TUIResultCleanupSummary(),
        raising=False,
    )

    run_menu_command(
        csv_path=str(sensitive_path),
        table_mappings=(f"private={sensitive_path}",),
        start_dir=tmp_path,
    )

    assert capsys.readouterr().err == (
        "LocalQL warning: 3 temporary result cleanup item(s) could not be removed; "
        "a later launch or operating-system cleanup may remove them.\n"
    )


def test_launcher_is_silent_when_cleanup_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app_instance = Mock()
    app_instance.cleanup_summary = TUIResultCleanupSummary()
    module = SimpleNamespace(CSVQLMenuApp=Mock(return_value=app_instance))
    monkeypatch.setattr(tui_launcher, "import_module", lambda name: module)
    monkeypatch.setattr(
        tui_launcher,
        "recover_abandoned_result_workspaces",
        lambda: TUIResultCleanupSummary(),
        raising=False,
    )

    run_menu_command(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert capsys.readouterr().err == ""


def test_launcher_does_not_warn_when_app_run_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app_instance = Mock()
    app_instance.run.side_effect = RuntimeError("private failure details")
    app_instance.cleanup_summary = TUIResultCleanupSummary(files_failed=1)
    module = SimpleNamespace(CSVQLMenuApp=Mock(return_value=app_instance))
    monkeypatch.setattr(tui_launcher, "import_module", lambda name: module)
    monkeypatch.setattr(
        tui_launcher,
        "recover_abandoned_result_workspaces",
        lambda: TUIResultCleanupSummary(),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="private failure details"):
        run_menu_command(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert capsys.readouterr().err == ""
