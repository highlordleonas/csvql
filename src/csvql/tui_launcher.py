"""Lazy launcher for the CSVQL menu TUI."""

import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path

from csvql.exceptions import CSVQLError
from csvql.tui_result_store import recover_abandoned_result_workspaces

_TUI_DEPENDENCY_MESSAGE = 'Install with pip install "localql[tui]" or run uv sync --all-extras.'


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
    recovery_summary = recover_abandoned_result_workspaces()
    app = app_class(
        csv_path=csv_path,
        table_mappings=table_mappings,
        start_dir=start_dir,
        initial_cleanup_summary=recovery_summary,
    )
    app.run()
    warning_count = app.cleanup_summary.warning_count
    if warning_count:
        print(
            "LocalQL warning: "
            f"{warning_count} temporary result cleanup item(s) could not be removed; "
            "a later launch or operating-system cleanup may remove them.",
            file=sys.stderr,
        )
