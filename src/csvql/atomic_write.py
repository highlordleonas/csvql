"""Atomic local text writes for CSVQL user-visible outputs."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path


class OperationCancelled(Exception):
    """Raised when a cancellable local operation is cancelled before commit."""


class OperationToken:
    """Thread-safe cancellation token for local TUI/file operations."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Mark the operation as cancelled."""

        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`OperationCancelled` when the token is cancelled."""

        if self.is_cancelled:
            raise OperationCancelled("Operation cancelled.")


def write_text_atomic(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    token: OperationToken | None = None,
) -> None:
    """Write text through a temp sibling file and atomically replace the target."""

    if token is not None:
        token.raise_if_cancelled()

    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        if token is not None:
            token.raise_if_cancelled()
        os.replace(temp_path, path)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
