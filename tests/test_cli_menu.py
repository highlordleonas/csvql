from pathlib import Path

import pytest
from typer.testing import CliRunner

from csvql import __version__
from csvql.cli import app
from csvql.exceptions import CSVQLError
from csvql.tui_launcher import run_menu_command

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
    assert "--table" in result.output
    assert "CSV file to preload into the TUI session." in result.output


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
