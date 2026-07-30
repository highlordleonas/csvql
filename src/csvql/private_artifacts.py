"""Recognition of LocalQL-owned private result artifacts."""

from __future__ import annotations

import re
from pathlib import Path

TUI_RESULT_SESSION_PREFIX = "localql-tui-v1-"

_TUI_RESULT_DIRECTORY_PATTERN = re.compile(
    rf"{re.escape(TUI_RESULT_SESSION_PREFIX)}(?P<session_id>[0-9a-f]{{32}})"
)
_TUI_RESULT_COMPLETED_SPILL_PATTERN = re.compile(r"(?:query|preview)-[1-9][0-9]*\.result")
_TUI_RESULT_STAGING_SPILL_PATTERN = re.compile(
    r"\.(?:query|preview)-[1-9][0-9]*-[0-9a-f]{16}\.result\.tmp"
)


def private_result_session_id(directory_name: str) -> str | None:
    """Return the session identifier for an exact private-result workspace name."""

    match = _TUI_RESULT_DIRECTORY_PATTERN.fullmatch(directory_name)
    return None if match is None else match.group("session_id")


def is_private_result_spill_name(name: str) -> bool:
    """Return whether a name is reserved for a private result-spill artifact."""

    return (
        _TUI_RESULT_COMPLETED_SPILL_PATTERN.fullmatch(name) is not None
        or _TUI_RESULT_STAGING_SPILL_PATTERN.fullmatch(name) is not None
    )


def is_private_result_artifact(path: Path) -> bool:
    """Return whether a path identifies a LocalQL-owned private result artifact."""

    candidate_paths: tuple[Path, ...] = (path,)
    try:
        resolved_path = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        pass
    else:
        candidate_paths += (resolved_path,)
    return any(
        private_result_session_id(candidate.parent.name) is not None
        and is_private_result_spill_name(candidate.name)
        for candidate in candidate_paths
    )
