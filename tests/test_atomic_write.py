import os
from pathlib import Path
from typing import Any

import pytest

from csvql.atomic_write import (
    OperationCancelled,
    OperationToken,
    atomic_text_output,
    write_text_atomic,
)
from csvql.operation import OperationCancelled as SharedOperationCancelled
from csvql.operation import OperationToken as SharedOperationToken


class FaultInjectingTextIO:
    def __init__(
        self,
        wrapped: Any,
        *,
        fail_write: bool = False,
        fail_flush: bool = False,
    ) -> None:
        self._wrapped = wrapped
        self._fail_write = fail_write
        self._fail_flush = fail_flush

    @property
    def closed(self) -> bool:
        return self._wrapped.closed

    def write(self, content: str) -> int:
        if self._fail_write:
            raise RuntimeError("write failed")
        return self._wrapped.write(content)

    def flush(self) -> None:
        if self._fail_flush:
            raise RuntimeError("flush failed")
        self._wrapped.flush()

    def fileno(self) -> int:
        return self._wrapped.fileno()

    def close(self) -> None:
        self._wrapped.close()


def test_atomic_write_reexports_shared_cancellation_types() -> None:
    assert OperationCancelled is SharedOperationCancelled
    assert OperationToken is SharedOperationToken


def test_write_text_atomic_writes_final_content(tmp_path: Path) -> None:
    output_path = tmp_path / "result.txt"

    write_text_atomic(output_path, "hello\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_write_text_atomic_preserves_previous_file_when_cancelled_before_replace(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")
    token = OperationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        write_text_atomic(output_path, "new\n", token=token)

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_write_text_atomic_cleans_up_temp_file_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise RuntimeError("commit failed")

    monkeypatch.setattr("csvql.atomic_write.os.replace", fail_replace)

    with pytest.raises(RuntimeError, match="commit failed"):
        write_text_atomic(output_path, "hello\n")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_write_text_atomic_no_overwrite_preserves_existing_file_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")

    def fail_link(source: Path, target: Path) -> None:
        del source, target
        raise FileExistsError("result.txt")

    monkeypatch.setattr("csvql.atomic_write.os.link", fail_link)

    with pytest.raises(FileExistsError):
        write_text_atomic(output_path, "new\n", overwrite=False)

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_writes_incrementally_and_commits_on_success(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"

    with atomic_text_output(output_path, newline="") as output:
        output.write("hello")
        output.write("\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_cancels_before_open_without_staging_file(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    token = OperationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        with atomic_text_output(output_path, token=token):
            pytest.fail("cancelled token should not yield a writer")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_preserves_previous_file_when_cancelled_before_commit(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")
    token = OperationToken()

    with pytest.raises(OperationCancelled):
        with atomic_text_output(output_path, token=token) as output:
            output.write("new\n")
            token.cancel()

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_rolls_back_when_body_raises_and_only_cleans_its_staging_file(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")
    sibling_temp = tmp_path / ".result.txt.keep.tmp"
    sibling_temp.write_text("keep\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="boom"):
        with atomic_text_output(output_path) as output:
            output.write("new\n")
            raise RuntimeError("boom")

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert sibling_temp.read_text(encoding="utf-8") == "keep\n"
    assert not tuple(path for path in tmp_path.glob(".result.txt.*.tmp") if path != sibling_temp)


def test_atomic_text_output_cleans_up_when_fdopen_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    close_calls: list[int] = []
    real_os_close = __import__("os").close

    def fail_fdopen(fd: int, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("open failed")

    def record_close(fd: int) -> None:
        close_calls.append(fd)
        real_os_close(fd)

    monkeypatch.setattr("csvql.atomic_write.os.fdopen", fail_fdopen)
    monkeypatch.setattr("csvql.atomic_write.os.close", record_close)

    with pytest.raises(RuntimeError, match="open failed"):
        with atomic_text_output(output_path):
            pytest.fail("fdopen failure should prevent yielding a writer")

    assert close_calls
    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_preserves_fdopen_failure_if_close_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    real_os_close = os.close

    def fail_fdopen(fd: int, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("open failed")

    def fail_close_after_closing(fd: int) -> None:
        real_os_close(fd)
        raise OSError("close failed")

    monkeypatch.setattr("csvql.atomic_write.os.fdopen", fail_fdopen)
    monkeypatch.setattr("csvql.atomic_write.os.close", fail_close_after_closing)

    with pytest.raises(RuntimeError, match="open failed"):
        with atomic_text_output(output_path):
            pytest.fail("fdopen failure should prevent yielding a writer")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_propagates_mkstemp_failure_without_creating_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"

    def fail_mkstemp(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("mkstemp failed")

    monkeypatch.setattr("csvql.atomic_write.tempfile.mkstemp", fail_mkstemp)

    with pytest.raises(OSError, match="mkstemp failed"):
        with atomic_text_output(output_path):
            pytest.fail("mkstemp failure should prevent yielding a writer")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_cleans_up_when_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    real_fdopen = os.fdopen

    def fail_write_fdopen(fd: int, *args: Any, **kwargs: Any) -> FaultInjectingTextIO:
        return FaultInjectingTextIO(real_fdopen(fd, *args, **kwargs), fail_write=True)

    monkeypatch.setattr("csvql.atomic_write.os.fdopen", fail_write_fdopen)

    with pytest.raises(RuntimeError, match="write failed"):
        with atomic_text_output(output_path) as output:
            output.write("hello")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_cleans_up_when_flush_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    real_fdopen = os.fdopen

    def fail_flush_fdopen(fd: int, *args: Any, **kwargs: Any) -> FaultInjectingTextIO:
        return FaultInjectingTextIO(real_fdopen(fd, *args, **kwargs), fail_flush=True)

    monkeypatch.setattr("csvql.atomic_write.os.fdopen", fail_flush_fdopen)

    with pytest.raises(RuntimeError, match="flush failed"):
        with atomic_text_output(output_path) as output:
            output.write("hello\n")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_cleans_up_when_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"

    def fail_fsync(_fd: int) -> None:
        raise RuntimeError("fsync failed")

    monkeypatch.setattr("csvql.atomic_write.os.fsync", fail_fsync)

    with pytest.raises(RuntimeError, match="fsync failed"):
        with atomic_text_output(output_path) as output:
            output.write("hello\n")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_cleans_up_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise RuntimeError("commit failed")

    monkeypatch.setattr("csvql.atomic_write.os.replace", fail_replace)

    with pytest.raises(RuntimeError, match="commit failed"):
        with atomic_text_output(output_path) as output:
            output.write("hello\n")

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_no_overwrite_preserves_existing_file_when_commit_races(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")

    def fail_link(source: Path, target: Path) -> None:
        del source, target
        raise FileExistsError("result.txt")

    monkeypatch.setattr("csvql.atomic_write.os.link", fail_link)

    with pytest.raises(FileExistsError):
        with atomic_text_output(output_path, overwrite=False) as output:
            output.write("new\n")

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_no_overwrite_suppresses_temp_cleanup_failure_after_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    linked_temp: Path | None = None
    real_link = os.link
    real_unlink = Path.unlink
    cleanup_attempts = 0

    def record_link(source: Path, target: Path) -> None:
        nonlocal linked_temp
        linked_temp = source
        real_link(source, target)

    def fail_temp_cleanup(self: Path, *, missing_ok: bool = False) -> None:
        nonlocal cleanup_attempts
        if linked_temp is not None and self == linked_temp:
            cleanup_attempts += 1
            if cleanup_attempts == 1:
                raise OSError("cleanup failed")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr("csvql.atomic_write.os.link", record_link)
    monkeypatch.setattr("csvql.atomic_write.Path.unlink", fail_temp_cleanup)

    with atomic_text_output(output_path, overwrite=False) as output:
        output.write("hello\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"
    assert linked_temp is not None
    assert cleanup_attempts == 2
    assert not linked_temp.exists()


def test_atomic_text_output_manual_close_is_idempotent_for_context_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    fsync_calls: list[int] = []
    reopen_flags: list[int] = []
    real_fsync = os.fsync
    real_open = os.open

    def record_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    def record_open(path: str | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        reopen_flags.append(flags)
        return real_open(path, flags, mode)

    monkeypatch.setattr("csvql.atomic_write.os.fsync", record_fsync)
    monkeypatch.setattr("csvql.atomic_write.os.open", record_open)

    with atomic_text_output(output_path) as output:
        output.write("hello\n")
        output.close()

    assert output_path.read_text(encoding="utf-8") == "hello\n"
    assert len(fsync_calls) == 1
    assert reopen_flags[-1] == os.O_RDWR
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_atomic_text_output_manual_close_preserves_fsync_failure_if_sync_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    real_os_close = os.close

    def fail_fsync(_fd: int) -> None:
        raise RuntimeError("fsync failed")

    def fail_close_after_closing(fd: int) -> None:
        real_os_close(fd)
        raise OSError("close failed")

    monkeypatch.setattr("csvql.atomic_write.os.fsync", fail_fsync)
    monkeypatch.setattr("csvql.atomic_write.os.close", fail_close_after_closing)

    with pytest.raises(RuntimeError, match="fsync failed"):
        with atomic_text_output(output_path) as output:
            output.write("hello\n")
            output.close()

    assert not output_path.exists()
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_write_text_atomic_routes_through_atomic_text_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    token = OperationToken()
    events: list[tuple[str, Any]] = []

    class RecordingWriter:
        def write(self, content: str) -> None:
            events.append(("write", content))

    class RecordingContextManager:
        def __enter__(self) -> RecordingWriter:
            events.append(("enter", None))
            return RecordingWriter()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            events.append(("exit", exc_type))
            return False

    def fake_atomic_text_output(
        path: Path,
        *,
        encoding: str = "utf-8",
        newline: str | None = None,
        overwrite: bool = True,
        token: OperationToken | None = None,
    ) -> RecordingContextManager:
        events.append(("args", (path, encoding, newline, overwrite, token)))
        return RecordingContextManager()

    monkeypatch.setattr("csvql.atomic_write.atomic_text_output", fake_atomic_text_output)

    write_text_atomic(output_path, "hello\n", newline="", overwrite=False, token=token)

    assert events == [
        ("args", (output_path, "utf-8", "", False, token)),
        ("enter", None),
        ("write", "hello\n"),
        ("exit", None),
    ]
