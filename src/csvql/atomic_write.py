"""Atomic local writes for CSVQL user-visible outputs."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from csvql.operation import (
    OperationCancelled as OperationCancelled,
)
from csvql.operation import (
    OperationToken as OperationToken,
)


@contextmanager
def atomic_text_output(
    path: Path,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    overwrite: bool = True,
    token: OperationToken | None = None,
) -> Iterator[TextIO]:
    """Yield a staging text writer and atomically publish it on success."""

    if token is not None:
        token.raise_if_cancelled()

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    file: TextIO | None = None
    committed = False
    needs_post_publish_cleanup = False
    try:
        try:
            file = os.fdopen(fd, "w", encoding=encoding, newline=newline)
        except BaseException:
            try:
                os.close(fd)
            except Exception:
                pass
            raise

        try:
            yield file
        except BaseException:
            raise
        else:
            if file.closed:
                # Windows rejects fsync on a descriptor reopened read-only after
                # the caller manually closed the staging file.
                sync_fd = os.open(temp_path, os.O_RDWR)
                try:
                    os.fsync(sync_fd)
                finally:
                    try:
                        os.close(sync_fd)
                    except Exception:
                        pass
            else:
                file.flush()
                os.fsync(file.fileno())
                file.close()

            if token is not None:
                token.raise_if_cancelled()

            if overwrite:
                os.replace(temp_path, path)
                committed = True
            else:
                os.link(temp_path, path)
                committed = True
                needs_post_publish_cleanup = True
                try:
                    temp_path.unlink(missing_ok=True)
                    needs_post_publish_cleanup = False
                except OSError:
                    pass
    except BaseException:
        raise
    finally:
        if file is not None and not file.closed:
            try:
                file.close()
            except Exception:
                pass
        if not committed or needs_post_publish_cleanup:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


@contextmanager
def atomic_output_path(
    path: Path,
    *,
    overwrite: bool = True,
    token: OperationToken | None = None,
) -> Iterator[Path]:
    """Yield a private sibling path and atomically publish its file on success."""

    if token is not None:
        token.raise_if_cancelled()

    stage_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
    )
    stage_path = stage_dir / path.name
    committed = False
    needs_post_publish_cleanup = False
    try:
        yield stage_path
        if not stage_path.is_file():
            raise OSError(f"Export writer did not create the staged file: {stage_path}")

        # Windows rejects fsync on a descriptor opened read-only.
        sync_fd = os.open(stage_path, os.O_RDWR)
        try:
            os.fsync(sync_fd)
        finally:
            os.close(sync_fd)

        if token is not None:
            token.raise_if_cancelled()

        if overwrite:
            os.replace(stage_path, path)
            committed = True
        else:
            os.link(stage_path, path)
            committed = True
            needs_post_publish_cleanup = True
            try:
                stage_path.unlink(missing_ok=True)
                needs_post_publish_cleanup = False
            except OSError:
                pass
    finally:
        if not committed or needs_post_publish_cleanup:
            try:
                stage_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            stage_dir.rmdir()
        except OSError:
            pass


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

    with atomic_text_output(
        path,
        encoding=encoding,
        newline=newline,
        overwrite=overwrite,
        token=token,
    ) as file:
        file.write(content)
