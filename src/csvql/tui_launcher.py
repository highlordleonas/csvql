"""Lazy launcher for the CSVQL menu TUI."""

from collections.abc import Sequence
from importlib import import_module
from pathlib import Path

from csvql.exceptions import CSVQLError

_TUI_DEPENDENCY_MESSAGE = 'Install with pip install "csvql[tui]" or run uv sync --all-extras.'


def run_menu_command(
    *, csv_path: str | None, table_mappings: Sequence[str], start_dir: Path
) -> None:
    """Start the menu TUI with optional startup sources."""

    try:
        module = import_module("csvql.tui_app")
    except ModuleNotFoundError as exc:
        if exc.name == "textual" or (exc.name is not None and exc.name.startswith("textual.")):
            raise CSVQLError(
                "CSVQL TUI dependency is not installed.",
                suggestion=_TUI_DEPENDENCY_MESSAGE,
            ) from exc
        raise

    app_class = module.CSVQLMenuApp
    app = app_class(csv_path=csv_path, table_mappings=table_mappings, start_dir=start_dir)
    app.run()
