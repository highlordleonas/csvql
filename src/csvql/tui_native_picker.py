"""Native local-source picker integration for the CSVQL TUI."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence

from csvql.exceptions import CSVQLError

NativePickerCommand = Callable[..., subprocess.CompletedProcess[str]]


def choose_csv_paths_with_native_picker(
    *,
    platform: str = sys.platform,
    run_command: NativePickerCommand = subprocess.run,
) -> tuple[str, ...]:
    """Return local-source paths selected through the macOS file picker.

    The compatibility name is retained for callers from the CSV-only TUI.
    Selection and provider detection happen after this transport boundary.
    """

    if platform != "darwin":
        raise CSVQLError(
            "Native source picker is only available on macOS.",
            suggestion="Use Add source and enter a local path instead.",
        )

    script_lines = _macos_picker_script_lines()

    try:
        # No timeout: this command owns an interactive OS file picker and may
        # legitimately wait while the user chooses files. It stays shell-free.
        result = run_command(
            ["osascript", *(argument for line in script_lines for argument in ("-e", line))],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CSVQLError(
            "Native source picker is unavailable.",
            suggestion="Use Add source and enter a local path instead.",
        ) from exc

    if result.returncode != 0:
        error_text = result.stderr.strip()
        if "User canceled" in error_text:
            return ()
        raise CSVQLError(
            "Native source picker failed.",
            suggestion="Use Add source and enter a local path instead.",
        )

    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _macos_picker_script_lines() -> Sequence[str]:
    return (
        'set chosenFiles to choose file with prompt "Choose local source file(s) to add." '
        "with multiple selections allowed",
        "set outputPaths to {}",
        "repeat with chosenFile in chosenFiles",
        "set end of outputPaths to POSIX path of chosenFile",
        "end repeat",
        "set AppleScript's text item delimiters to linefeed",
        "return outputPaths as text",
    )
