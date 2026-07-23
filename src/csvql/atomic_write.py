"""Atomic local text writes for CSVQL user-visible outputs."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from csvql.operation import (
    OperationCancelled as OperationCancelled,
)
from csvql.operation import (
    OperationToken as OperationToken,
)


def write_text_atomic(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    overwrite: bool = True,
    token: OperationToken | None = None,
) -> None:
    """Write text through a temp sibling file and atomically publish the target.

    When ``overwrite`` is ``False``, the final path is only created if it does
    not already exist.
    """

    if token is not None:
        token.raise_if_cancelled()

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
        if overwrite:
            os.replace(temp_path, path)
        else:
            os.link(temp_path, path)
            temp_path.unlink(missing_ok=True)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
