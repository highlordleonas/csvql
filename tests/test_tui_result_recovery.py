import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import csvql.tui_result_store as result_store
from csvql.tui_result_store import (
    TUI_RESULT_LEASE_NAME,
    TUI_RESULT_MARKER_NAME,
    TUI_RESULT_SESSION_PREFIX,
    recover_abandoned_result_workspaces,
)

_NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
_OLD_CREATED_AT = _NOW - timedelta(hours=25)


def _write_candidate(
    temp_root: Path,
    *,
    session_id: str = "1" * 32,
    created_at: datetime,
) -> Path:
    workspace = temp_root / f"{TUI_RESULT_SESSION_PREFIX}{session_id}"
    workspace.mkdir(mode=0o700)
    marker = {
        "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        "format_version": 1,
        "session_id": session_id,
    }
    (workspace / TUI_RESULT_MARKER_NAME).write_text(
        json.dumps(marker, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    (workspace / TUI_RESULT_LEASE_NAME).write_bytes(b"0")
    (workspace / "query-1.pickle").write_bytes(b"disposable")
    if os.name != "nt":
        os.chmod(workspace / TUI_RESULT_MARKER_NAME, 0o600)
        os.chmod(workspace / TUI_RESULT_LEASE_NAME, 0o600)
        os.chmod(workspace / "query-1.pickle", 0o600)
    _age_workspace(workspace, created_at)
    return workspace


def _age_workspace(workspace: Path, created_at: datetime = _OLD_CREATED_AT) -> None:
    old_epoch = created_at.timestamp()
    os.utime(workspace, (old_epoch, old_epoch))


def _replace_candidate_lease(workspace: Path) -> None:
    lease_path = workspace / TUI_RESULT_LEASE_NAME
    lease_path.unlink()
    lease_path.write_bytes(b"0")
    if os.name != "nt":
        os.chmod(lease_path, 0o600)


def _remove_candidate_direct_entries(workspace: Path) -> None:
    for name in os.listdir(workspace):
        (workspace / name).unlink()
    workspace.rmdir()


def _write_marker(workspace: Path, marker: object) -> None:
    (workspace / TUI_RESULT_MARKER_NAME).write_text(
        json.dumps(marker, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    if os.name != "nt":
        os.chmod(workspace / TUI_RESULT_MARKER_NAME, 0o600)


def _marker_payload(workspace: Path) -> dict[str, object]:
    marker = json.loads((workspace / TUI_RESULT_MARKER_NAME).read_text(encoding="utf-8"))
    assert isinstance(marker, dict)
    return marker


def _assert_rejected(workspace: Path, *, now: datetime = _NOW) -> None:
    names_before = tuple(sorted(os.listdir(workspace)))

    summary = recover_abandoned_result_workspaces(
        temp_root=workspace.parent,
        now=now,
    )

    assert summary.workspaces_removed == 0
    assert workspace.is_dir()
    assert tuple(sorted(os.listdir(workspace))) == names_before


def _remove_marker_key(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    del marker["created_at_utc"]
    _write_marker(workspace, marker)


def _add_marker_key(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["unexpected"] = "value"
    _write_marker(workspace, marker)


def _duplicate_marker_key(workspace: Path) -> None:
    session_id = "1" * 32
    (workspace / TUI_RESULT_MARKER_NAME).write_text(
        "{"
        f'"created_at_utc":"{_OLD_CREATED_AT.isoformat().replace("+00:00", "Z")}",'
        '"format_version":1,"format_version":1,'
        f'"session_id":"{session_id}"'
        "}",
        encoding="utf-8",
    )


def _unsupported_marker_version(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["format_version"] = 2
    _write_marker(workspace, marker)


def _boolean_marker_version(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["format_version"] = True
    _write_marker(workspace, marker)


def _string_marker_version(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["format_version"] = "1"
    _write_marker(workspace, marker)


def _mismatched_marker_session(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["session_id"] = "2" * 32
    _write_marker(workspace, marker)


def _non_string_marker_session(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["session_id"] = 1
    _write_marker(workspace, marker)


def _offset_marker_timestamp(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["created_at_utc"] = "2026-07-12T05:00:00-06:00"
    _write_marker(workspace, marker)


def _lowercase_z_marker_timestamp(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["created_at_utc"] = "2026-07-12T11:00:00z"
    _write_marker(workspace, marker)


def _invalid_marker_timestamp(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["created_at_utc"] = "2026-02-30T11:00:00Z"
    _write_marker(workspace, marker)


def _future_marker_timestamp(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["created_at_utc"] = (_NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    _write_marker(workspace, marker)


def _non_string_marker_timestamp(workspace: Path) -> None:
    marker = _marker_payload(workspace)
    marker["created_at_utc"] = 0
    _write_marker(workspace, marker)


@pytest.mark.parametrize(
    "corrupt_marker",
    [
        _remove_marker_key,
        _add_marker_key,
        _duplicate_marker_key,
        _unsupported_marker_version,
        _boolean_marker_version,
        _string_marker_version,
        _mismatched_marker_session,
        _non_string_marker_session,
        _offset_marker_timestamp,
        _lowercase_z_marker_timestamp,
        _invalid_marker_timestamp,
        _future_marker_timestamp,
        _non_string_marker_timestamp,
    ],
    ids=lambda corrupt_marker: corrupt_marker.__name__,
)
def test_recovery_rejects_malformed_marker(
    tmp_path: Path,
    corrupt_marker: Callable[[Path], None],
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    corrupt_marker(workspace)

    _assert_rejected(workspace)


@pytest.mark.parametrize("session_id", ["1" * 31, "1" * 33, "A" * 32])
def test_recovery_rejects_invalid_session_directory_suffix(
    tmp_path: Path,
    session_id: str,
) -> None:
    workspace = _write_candidate(
        tmp_path,
        session_id=session_id,
        created_at=_OLD_CREATED_AT,
    )

    _assert_rejected(workspace)


def test_recovery_rejects_marker_larger_than_four_kibibytes(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    (workspace / TUI_RESULT_MARKER_NAME).write_bytes(b"x" * 4_097)

    _assert_rejected(workspace)


@pytest.mark.parametrize("lease_content", [b"", b"00"])
def test_recovery_rejects_lease_that_is_not_exactly_one_byte(
    tmp_path: Path,
    lease_content: bytes,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    (workspace / TUI_RESULT_LEASE_NAME).write_bytes(lease_content)

    _assert_rejected(workspace)


@pytest.mark.parametrize(
    "unexpected_name",
    [
        "notes.txt",
        "query-0.pickle",
        "query-01.pickle",
        "query-1.PICKLE",
        ".query-0-abcdef0123456789.tmp",
        ".query-1-ABCDEF0123456789.tmp",
        ".query-1-abcdef012345678.tmp",
    ],
)
def test_recovery_rejects_unexpected_entry_name(
    tmp_path: Path,
    unexpected_name: str,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    if unexpected_name == "query-1.PICKLE":
        (workspace / "query-1.pickle").unlink()
    unexpected_path = workspace / unexpected_name
    unexpected_path.write_bytes(b"unexpected")
    if os.name != "nt":
        os.chmod(unexpected_path, 0o600)
    _age_workspace(workspace)

    _assert_rejected(workspace)


def test_recovery_rejects_nested_directory(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    (workspace / "query-2.pickle").mkdir()
    _age_workspace(workspace)

    _assert_rejected(workspace)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation is portable")
def test_recovery_rejects_linked_candidate_entry(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    foreign_file = tmp_path / "foreign.pickle"
    foreign_file.write_bytes(b"retain")
    linked_spill = workspace / "query-2.pickle"
    linked_spill.symlink_to(foreign_file)
    _age_workspace(workspace)

    _assert_rejected(workspace)
    assert foreign_file.read_bytes() == b"retain"
    assert linked_spill.is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation is portable")
def test_recovery_rejects_candidate_directory_symlink(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    target = _write_candidate(
        target_root,
        session_id="2" * 32,
        created_at=_OLD_CREATED_AT,
    )
    candidate_link = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'2' * 32}"
    candidate_link.symlink_to(target, target_is_directory=True)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert candidate_link.is_symlink()
    assert target.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow lease-open regression")
def test_recovery_never_follows_lease_replaced_by_symlink_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    lease_path = workspace / TUI_RESULT_LEASE_NAME
    foreign_lease = tmp_path / "foreign-lease"
    foreign_lease.write_bytes(b"0")
    os.chmod(foreign_lease, 0o600)
    foreign_identity = (foreign_lease.stat().st_dev, foreign_lease.stat().st_ino)
    real_path_open = Path.open
    real_os_open = os.open
    swapped = False
    followed_foreign_lease = False

    def swap_lease_once() -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        lease_path.unlink()
        lease_path.symlink_to(foreign_lease)

    def guarded_path_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):  # type: ignore[no-untyped-def]
        nonlocal followed_foreign_lease
        if path == lease_path:
            swap_lease_once()
        opened = real_path_open(path, mode, buffering, encoding, errors, newline)
        if path == lease_path:
            opened_stat = os.fstat(opened.fileno())
            followed_foreign_lease = (opened_stat.st_dev, opened_stat.st_ino) == foreign_identity
        return opened

    def guarded_os_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal followed_foreign_lease
        requested_path = Path(path)
        if requested_path == lease_path:
            swap_lease_once()
        if dir_fd is None:
            file_descriptor = real_os_open(path, flags, mode)
        else:
            file_descriptor = real_os_open(path, flags, mode, dir_fd=dir_fd)
        if requested_path == lease_path:
            opened_stat = os.fstat(file_descriptor)
            followed_foreign_lease = (opened_stat.st_dev, opened_stat.st_ino) == foreign_identity
        return file_descriptor

    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(result_store.os, "open", guarded_os_open)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert not followed_foreign_lease
    assert lease_path.is_symlink()
    assert foreign_lease.read_bytes() == b"0"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits replacing an open lease path")
def test_recovery_rejects_lease_path_replaced_after_lock_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    lease_path = workspace / TUI_RESULT_LEASE_NAME
    real_acquire = result_store._PlatformLease.acquire_nonblocking

    def acquire_then_replace_lease(lease: result_store._PlatformLease) -> bool:
        acquired = real_acquire(lease)
        if acquired:
            lease_path.unlink()
            lease_path.write_bytes(b"0")
            os.chmod(lease_path, 0o600)
            _age_workspace(workspace)
        return acquired

    monkeypatch.setattr(
        result_store._PlatformLease,
        "acquire_nonblocking",
        acquire_then_replace_lease,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert workspace.is_dir()
    assert sorted(os.listdir(workspace)) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
        "query-1.pickle",
    ]


def test_recovery_revalidates_complete_candidate_content_after_lock_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    unexpected_path = workspace / "unexpected.txt"
    real_acquire = result_store._PlatformLease.acquire_nonblocking

    def acquire_then_add_entry(lease: result_store._PlatformLease) -> bool:
        acquired = real_acquire(lease)
        if acquired:
            unexpected_path.write_bytes(b"retain")
            if os.name != "nt":
                os.chmod(unexpected_path, 0o600)
            _age_workspace(workspace)
        return acquired

    monkeypatch.setattr(
        result_store._PlatformLease,
        "acquire_nonblocking",
        acquire_then_add_entry,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert unexpected_path.read_bytes() == b"retain"
    assert (workspace / "query-1.pickle").read_bytes() == b"disposable"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits renaming a locked workspace")
def test_recovery_revalidates_candidate_identity_after_lock_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    moved_workspace = tmp_path / "moved-original-workspace"
    real_acquire = result_store._PlatformLease.acquire_nonblocking

    def acquire_then_replace_workspace(lease: result_store._PlatformLease) -> bool:
        acquired = real_acquire(lease)
        if acquired:
            workspace.rename(moved_workspace)
            _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
        return acquired

    monkeypatch.setattr(
        result_store._PlatformLease,
        "acquire_nonblocking",
        acquire_then_replace_workspace,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert workspace.is_dir()
    assert moved_workspace.is_dir()
    assert (workspace / "query-1.pickle").read_bytes() == b"disposable"
    assert (moved_workspace / "query-1.pickle").read_bytes() == b"disposable"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits replacing a locked lease path")
@pytest.mark.parametrize("replacement_seam", ["first_spill", "between_spills", "marker"])
def test_recovery_checks_locked_lease_immediately_before_each_content_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_seam: str,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    second_spill = workspace / "query-2.pickle"
    if replacement_seam == "between_spills":
        second_spill.write_bytes(b"disposable-2")
        os.chmod(second_spill, 0o600)
        _age_workspace(workspace)
    real_unlink = result_store._unlink_recovery_entry
    replaced = False

    def replace_lease_at_seam(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal replaced
        path = args[1]
        should_replace = (
            (replacement_seam == "first_spill" and path.name == "query-1.pickle")
            or (replacement_seam == "between_spills" and path.name == "query-2.pickle")
            or (replacement_seam == "marker" and path.name == TUI_RESULT_MARKER_NAME)
        )
        if should_replace and not replaced:
            replaced = True
            _replace_candidate_lease(workspace)
        return real_unlink(*args, **kwargs)

    monkeypatch.setattr(result_store, "_unlink_recovery_entry", replace_lease_at_seam)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert replaced
    assert (workspace / TUI_RESULT_MARKER_NAME).exists()
    if replacement_seam == "first_spill":
        assert (workspace / "query-1.pickle").read_bytes() == b"disposable"
        assert summary.files_removed == 0
    elif replacement_seam == "between_spills":
        assert not (workspace / "query-1.pickle").exists()
        assert second_spill.read_bytes() == b"disposable-2"
        assert summary.files_removed == 1
    else:
        assert not (workspace / "query-1.pickle").exists()
        assert summary.files_removed == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_recovery_rejects_fifo_entry(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    os.mkfifo(workspace / "query-2.pickle", mode=0o600)
    _age_workspace(workspace)

    _assert_rejected(workspace)


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(socket, "AF_UNIX"),
    reason="POSIX Unix sockets are unavailable",
)
def test_recovery_rejects_socket_entry() -> None:
    with tempfile.TemporaryDirectory(prefix="lq-", dir="/tmp") as short_temp_root:
        temp_root = Path(short_temp_root)
        workspace = _write_candidate(temp_root, created_at=_OLD_CREATED_AT)
        socket_path = workspace / "query-2.pickle"
        unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            try:
                unix_socket.bind(str(socket_path))
            except OSError as exc:
                pytest.skip(f"Unix socket fixture creation is unavailable: errno={exc.errno}")
            _age_workspace(workspace)

            _assert_rejected(workspace)
        finally:
            unix_socket.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership and mode checks only")
@pytest.mark.parametrize(
    ("relative_path", "mode"),
    [
        (Path("."), 0o755),
        (Path(TUI_RESULT_MARKER_NAME), 0o640),
        (Path(TUI_RESULT_LEASE_NAME), 0o604),
        (Path("query-1.pickle"), 0o606),
    ],
)
def test_recovery_rejects_insecure_posix_mode(
    tmp_path: Path,
    relative_path: Path,
    mode: int,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    os.chmod(workspace / relative_path, mode)

    _assert_rejected(workspace)


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="changing a candidate to a foreign POSIX owner requires root",
)
def test_recovery_rejects_foreign_posix_owner(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    original_uid = os.getuid()
    original_gid = os.getgid()
    foreign_uid = 65_534 if original_uid != 65_534 else 65_533
    os.chown(workspace, foreign_uid, -1)
    try:
        _assert_rejected(workspace)
    finally:
        os.chown(workspace, original_uid, original_gid)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction/reparse contract")
def test_recovery_rejects_windows_candidate_junction(tmp_path: Path) -> None:
    target_root = tmp_path / "junction-target"
    target_root.mkdir()
    target = _write_candidate(
        target_root,
        session_id="3" * 32,
        created_at=_OLD_CREATED_AT,
    )
    junction = tmp_path / f"{TUI_RESULT_SESSION_PREFIX}{'3' * 32}"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        pytest.skip("Windows junction creation is unavailable in this environment")
    try:
        summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

        assert summary.workspaces_removed == 0
        assert junction.exists()
        assert target.is_dir()
    finally:
        junction.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction/reparse contract")
def test_recovery_rejects_windows_entry_junction(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    target = tmp_path / "entry-junction-target"
    target.mkdir()
    junction = workspace / "query-2.pickle"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        pytest.skip("Windows junction creation is unavailable in this environment")
    try:
        _age_workspace(workspace)

        _assert_rejected(workspace)
        assert junction.exists()
        assert target.is_dir()
    finally:
        junction.rmdir()


def test_recovery_rejects_recent_marker_or_directory_timestamp(tmp_path: Path) -> None:
    recent_marker = _write_candidate(
        tmp_path,
        session_id="4" * 32,
        created_at=_NOW - timedelta(hours=23),
    )
    old_marker_recent_directory = _write_candidate(
        tmp_path,
        session_id="5" * 32,
        created_at=_OLD_CREATED_AT,
    )
    os.utime(
        old_marker_recent_directory,
        ((_NOW - timedelta(hours=23)).timestamp(),) * 2,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert recent_marker.is_dir()
    assert old_marker_recent_directory.is_dir()


def test_recovery_accepts_exact_twenty_four_hour_boundary(tmp_path: Path) -> None:
    boundary = _NOW - timedelta(hours=24)
    workspace = _write_candidate(tmp_path, created_at=boundary)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 1
    assert not workspace.exists()


def test_recovery_rejects_future_directory_timestamp(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    future_epoch = (_NOW + timedelta(seconds=1)).timestamp()
    os.utime(workspace, (future_epoch, future_epoch))

    _assert_rejected(workspace)


def test_recovery_rejects_directory_timestamp_before_marker(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    earlier_epoch = (_OLD_CREATED_AT - timedelta(seconds=1)).timestamp()
    os.utime(workspace, (earlier_epoch, earlier_epoch))

    _assert_rejected(workspace)


def test_recovery_removes_only_exact_files_from_valid_old_candidate(tmp_path: Path) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    staging_path = workspace / ".query-2-abcdef0123456789.tmp"
    staging_path.write_bytes(b"partial")
    if os.name != "nt":
        os.chmod(staging_path, 0o600)
    _age_workspace(workspace)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("retain", encoding="utf-8")

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert not workspace.exists()
    assert unrelated.read_text(encoding="utf-8") == "retain"
    assert summary.files_removed == 4
    assert summary.files_failed == 0
    assert summary.workspaces_removed == 1
    assert summary.workspaces_failed == 0


def test_recovery_stops_at_temporary_root_entry_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(5):
        (tmp_path / f"unrelated-{index}").write_text("retain", encoding="utf-8")
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_TEMP_ENTRIES", 2)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.temp_entries_inspected == 2
    assert len(tuple(tmp_path.iterdir())) == 5


def test_recovery_stops_at_prefix_candidate_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for digit in ("1", "2", "3"):
        _write_candidate(
            tmp_path,
            session_id=digit * 32,
            created_at=_OLD_CREATED_AT,
        )
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_CANDIDATES", 2)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.candidates_validated == 2
    assert summary.workspaces_removed == 2
    assert len(tuple(tmp_path.iterdir())) == 1


def test_recovery_rejects_candidate_not_fully_enumerated_within_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    extra_spill = workspace / "query-2.pickle"
    extra_spill.write_bytes(b"disposable")
    if os.name != "nt":
        os.chmod(extra_spill, 0o600)
    _age_workspace(workspace)
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_CANDIDATE_ENTRIES", 3)

    _assert_rejected(workspace)


def test_recovery_accepts_candidate_with_exact_entry_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_CANDIDATE_ENTRIES", 3)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 1
    assert not workspace.exists()


def test_recovery_rejects_limit_plus_one_without_lstat_on_extra_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    extra_spill = workspace / "query-2.pickle"
    extra_spill.write_bytes(b"disposable")
    if os.name != "nt":
        os.chmod(extra_spill, 0o600)
    _age_workspace(workspace)
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_CANDIDATE_ENTRIES", 3)

    real_scandir = os.scandir
    real_lstat = Path.lstat
    extra_lstat_calls = 0
    candidate_order = (
        TUI_RESULT_MARKER_NAME,
        TUI_RESULT_LEASE_NAME,
        "query-1.pickle",
        extra_spill.name,
    )

    def ordered_scandir(path: os.PathLike[str] | str):
        if Path(path) != workspace:
            return real_scandir(path)
        with real_scandir(path) as entries:
            entries_by_name = {entry.name: entry for entry in entries}
        return nullcontext(iter(entries_by_name[name] for name in candidate_order))

    def track_extra_lstat(path: Path) -> os.stat_result:
        nonlocal extra_lstat_calls
        if path == extra_spill:
            extra_lstat_calls += 1
        return real_lstat(path)

    monkeypatch.setattr(os, "scandir", ordered_scandir)
    monkeypatch.setattr(Path, "lstat", track_extra_lstat)

    _assert_rejected(workspace)

    assert extra_lstat_calls == 0


def test_recovery_does_not_read_marker_over_configured_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    marker_size = (workspace / TUI_RESULT_MARKER_NAME).stat().st_size
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_MARKER_BYTES", marker_size - 1)

    _assert_rejected(workspace)


def test_recovery_stops_at_workspace_removal_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for digit in ("1", "2", "3"):
        _write_candidate(
            tmp_path,
            session_id=digit * 32,
            created_at=_OLD_CREATED_AT,
        )
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_RECOVERED_WORKSPACES", 1)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 1
    assert len(tuple(tmp_path.iterdir())) == 2


@pytest.mark.parametrize("failure_stage", ["lease_unlink", "rmdir"])
def test_recovery_attempt_budget_bounds_partial_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    workspaces = [
        _write_candidate(
            tmp_path,
            session_id=digit * 32,
            created_at=_OLD_CREATED_AT,
        )
        for digit in ("1", "2", "3")
    ]
    monkeypatch.setattr(result_store, "TUI_RESULT_MAX_RECOVERED_WORKSPACES", 1)
    real_unlink = Path.unlink
    real_rmdir = Path.rmdir

    def fail_lease_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.name == TUI_RESULT_LEASE_NAME:
            raise PermissionError("injected lease unlink failure")
        real_unlink(path, missing_ok=missing_ok)

    def fail_workspace_rmdir(path: Path) -> None:
        if path.name.startswith(TUI_RESULT_SESSION_PREFIX):
            raise PermissionError("injected workspace rmdir failure")
        real_rmdir(path)

    if failure_stage == "lease_unlink":
        monkeypatch.setattr(Path, "unlink", fail_lease_unlink)
    else:
        monkeypatch.setattr(Path, "rmdir", fail_workspace_rmdir)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    entered_destructive_recovery = sum(
        not (workspace / TUI_RESULT_MARKER_NAME).exists() for workspace in workspaces
    )
    assert entered_destructive_recovery == 1
    assert summary.workspaces_removed == 0
    untouched = [
        workspace for workspace in workspaces if (workspace / TUI_RESULT_MARKER_NAME).exists()
    ]
    assert len(untouched) == 2
    for workspace in untouched:
        assert sorted(os.listdir(workspace)) == [
            TUI_RESULT_LEASE_NAME,
            TUI_RESULT_MARKER_NAME,
            "query-1.pickle",
        ]


def test_recovery_fails_closed_when_locked_file_identity_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    monkeypatch.setattr(result_store, "_usable_stat_identity", lambda result: None)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert sorted(os.listdir(workspace)) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
        "query-1.pickle",
    ]


def test_recovery_rejects_arbitrary_windows_temp_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_user_root = tmp_path / "current-user-temp"
    current_user_root.mkdir(mode=0o700)
    arbitrary_root = tmp_path / "arbitrary-temp"
    arbitrary_root.mkdir(mode=0o700)
    workspace = _write_candidate(arbitrary_root, created_at=_OLD_CREATED_AT)
    monkeypatch.setattr(
        result_store,
        "_is_windows_platform",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        result_store.tempfile,
        "gettempdir",
        lambda: str(current_user_root),
    )

    summary = recover_abandoned_result_workspaces(temp_root=arbitrary_root, now=_NOW)

    assert summary.temp_entries_inspected == 0
    assert summary.workspaces_removed == 0
    assert workspace.is_dir()


def test_recovery_accepts_resolved_current_user_windows_temp_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    monkeypatch.setattr(result_store, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(result_store.tempfile, "gettempdir", lambda: str(tmp_path))

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 1
    assert not workspace.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
def test_recovery_rejects_reparse_current_user_windows_temp_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_root = tmp_path / "real-temp"
    real_root.mkdir(mode=0o700)
    workspace = _write_candidate(real_root, created_at=_OLD_CREATED_AT)
    linked_root = tmp_path / "linked-temp"
    linked_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setattr(result_store, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(
        result_store.tempfile,
        "gettempdir",
        lambda: str(linked_root),
    )

    summary = recover_abandoned_result_workspaces(temp_root=linked_root, now=_NOW)

    assert summary.temp_entries_inspected == 0
    assert summary.workspaces_removed == 0
    assert workspace.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX inode replacement fixture")
@pytest.mark.parametrize(
    "replacement",
    ["marker_same_content", "marker_changed_content", "spill_same_content"],
)
def test_recovery_revalidates_entry_identity_and_marker_content_after_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    marker_path = workspace / TUI_RESULT_MARKER_NAME
    spill_path = workspace / "query-1.pickle"
    marker_content = marker_path.read_bytes()
    marker_stat = marker_path.stat()
    spill_stat = spill_path.stat()
    real_acquire = result_store._PlatformLease.acquire_nonblocking

    def acquire_then_replace(lease: result_store._PlatformLease) -> bool:
        acquired = real_acquire(lease)
        assert acquired
        if replacement == "marker_same_content":
            marker_path.rename(tmp_path / "preserved-marker")
            marker_path.write_bytes(marker_content)
            os.chmod(marker_path, 0o600)
            os.utime(
                marker_path,
                ns=(marker_stat.st_atime_ns, marker_stat.st_mtime_ns),
            )
        elif replacement == "marker_changed_content":
            marker_path.write_bytes(marker_content.replace(b"T11:00:00Z", b"T10:00:00Z"))
            os.chmod(marker_path, 0o600)
            os.utime(
                marker_path,
                ns=(marker_stat.st_atime_ns, marker_stat.st_mtime_ns),
            )
        else:
            spill_path.rename(tmp_path / "preserved-spill")
            spill_path.write_bytes(b"disposable")
            os.chmod(spill_path, 0o600)
            os.utime(
                spill_path,
                ns=(spill_stat.st_atime_ns, spill_stat.st_mtime_ns),
            )
        _age_workspace(workspace)
        return acquired

    monkeypatch.setattr(
        result_store._PlatformLease,
        "acquire_nonblocking",
        acquire_then_replace,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert summary.workspaces_removed == 0
    assert sorted(os.listdir(workspace)) == [
        TUI_RESULT_LEASE_NAME,
        TUI_RESULT_MARKER_NAME,
        "query-1.pickle",
    ]
    assert (workspace / TUI_RESULT_LEASE_NAME).read_bytes() == b"0"
    expected_marker = (
        marker_content.replace(b"T11:00:00Z", b"T10:00:00Z")
        if replacement == "marker_changed_content"
        else marker_content
    )
    assert marker_path.read_bytes() == expected_marker
    assert spill_path.read_bytes() == b"disposable"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits removing a locked lease path")
@pytest.mark.parametrize(
    "disappearance_seam",
    ["spill", "marker", "lease", "after_lease_unlink", "before_rmdir"],
)
def test_recovery_treats_exact_concurrent_disappearance_as_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disappearance_seam: str,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    real_unlink = result_store._unlink_recovery_entry
    real_rmdir = result_store._rmdir_recovery_workspace
    disappeared = False

    def disappear_at_unlink(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal disappeared
        path = args[1]
        before_target = (
            (disappearance_seam == "spill" and path.name == "query-1.pickle")
            or (disappearance_seam == "marker" and path.name == TUI_RESULT_MARKER_NAME)
            or (disappearance_seam == "lease" and path.name == TUI_RESULT_LEASE_NAME)
        )
        if before_target and not disappeared:
            disappeared = True
            _remove_candidate_direct_entries(workspace)
            return real_unlink(*args, **kwargs)
        outcome = real_unlink(*args, **kwargs)
        if (
            disappearance_seam == "after_lease_unlink"
            and path.name == TUI_RESULT_LEASE_NAME
            and not disappeared
        ):
            disappeared = True
            workspace.rmdir()
        return outcome

    def disappear_before_rmdir(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal disappeared
        if disappearance_seam == "before_rmdir" and not disappeared:
            disappeared = True
            workspace.rmdir()
        return real_rmdir(*args, **kwargs)

    monkeypatch.setattr(result_store, "_unlink_recovery_entry", disappear_at_unlink)
    monkeypatch.setattr(result_store, "_rmdir_recovery_workspace", disappear_before_rmdir)

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert disappeared
    assert not workspace.exists()
    assert summary.warning_count == 0
    assert summary.workspaces_removed == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits removing a locked lease path")
def test_recovery_treats_disappearance_after_post_marker_check_as_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    real_disappeared = result_store._recovery_candidate_disappeared
    disappeared = False

    def disappear_after_post_marker_check(
        candidate: result_store._ValidatedRecoveryCandidate,
    ) -> bool:
        nonlocal disappeared
        outcome = real_disappeared(candidate)
        marker_path = workspace / TUI_RESULT_MARKER_NAME
        if not outcome and not marker_path.exists() and not disappeared:
            disappeared = True
            _remove_candidate_direct_entries(workspace)
        return outcome

    monkeypatch.setattr(
        result_store,
        "_recovery_candidate_disappeared",
        disappear_after_post_marker_check,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert disappeared
    assert not workspace.exists()
    assert summary.warning_count == 0
    assert summary.workspaces_removed == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits removing a locked lease path")
def test_recovery_reports_missing_lease_with_late_workspace_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    late_entry = workspace / "late-entry"
    real_disappeared = result_store._recovery_candidate_disappeared
    lease_removed = False

    def remove_lease_and_add_entry_after_marker(
        candidate: result_store._ValidatedRecoveryCandidate,
    ) -> bool:
        nonlocal lease_removed
        outcome = real_disappeared(candidate)
        marker_path = workspace / TUI_RESULT_MARKER_NAME
        if not outcome and not marker_path.exists() and not lease_removed:
            lease_removed = True
            (workspace / TUI_RESULT_LEASE_NAME).unlink()
            late_entry.write_bytes(b"retain")
        return outcome

    monkeypatch.setattr(
        result_store,
        "_recovery_candidate_disappeared",
        remove_lease_and_add_entry_after_marker,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert lease_removed
    assert workspace.is_dir()
    assert sorted(os.listdir(workspace)) == [late_entry.name]
    assert late_entry.read_bytes() == b"retain"
    assert summary.files_failed == 1
    assert summary.workspaces_failed == 0
    assert summary.warning_count == 1
    assert summary.workspaces_removed == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits removing a locked lease path")
def test_recovery_accepts_missing_lease_with_empty_exact_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    real_disappeared = result_store._recovery_candidate_disappeared
    lease_removed = False

    def remove_lease_after_marker(
        candidate: result_store._ValidatedRecoveryCandidate,
    ) -> bool:
        nonlocal lease_removed
        outcome = real_disappeared(candidate)
        marker_path = workspace / TUI_RESULT_MARKER_NAME
        if not outcome and not marker_path.exists() and not lease_removed:
            lease_removed = True
            (workspace / TUI_RESULT_LEASE_NAME).unlink()
        return outcome

    monkeypatch.setattr(
        result_store,
        "_recovery_candidate_disappeared",
        remove_lease_after_marker,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert lease_removed
    assert workspace.is_dir()
    assert os.listdir(workspace) == []
    assert summary.warning_count == 0
    assert summary.workspaces_removed == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits removing a locked lease path")
def test_recovery_treats_disappearance_between_missing_entry_checks_as_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _write_candidate(tmp_path, created_at=_OLD_CREATED_AT)
    real_unlink = result_store._unlink_recovery_entry
    real_disappeared = result_store._recovery_candidate_disappeared
    entry_removed = False
    disappeared = False

    def remove_spill_before_entry_check(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal entry_removed
        path = args[1]
        if path.name == "query-1.pickle" and not entry_removed:
            path.unlink()
            entry_removed = True
        return real_unlink(*args, **kwargs)

    def disappear_after_missing_entry_check(
        candidate: result_store._ValidatedRecoveryCandidate,
    ) -> bool:
        nonlocal disappeared
        outcome = real_disappeared(candidate)
        if entry_removed and not outcome and not disappeared:
            disappeared = True
            _remove_candidate_direct_entries(workspace)
        return outcome

    monkeypatch.setattr(result_store, "_unlink_recovery_entry", remove_spill_before_entry_check)
    monkeypatch.setattr(
        result_store,
        "_recovery_candidate_disappeared",
        disappear_after_missing_entry_check,
    )

    summary = recover_abandoned_result_workspaces(temp_root=tmp_path, now=_NOW)

    assert entry_removed
    assert disappeared
    assert not workspace.exists()
    assert summary.warning_count == 0
    assert summary.workspaces_removed == 0


def test_recovery_keeps_active_workspace_then_removes_it_after_owner_exits(
    tmp_path: Path,
) -> None:
    ready_path = tmp_path / "ready.txt"
    child_code = """
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from csvql.models import QueryResult
from csvql.tui_result_store import TUIResultStore

temp_root = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
old_now = datetime.now(timezone.utc) - timedelta(hours=25)
store = TUIResultStore(temp_root=temp_root, now=old_now)
rows = tuple((index,) for index in range(10_001))
store.put(QueryResult(columns=("id",), rows=rows, elapsed_ms=1.0), sequence=1)
assert store.workspace_path is not None
ready_path.write_text(str(store.workspace_path), encoding="utf-8")
while True:
    time.sleep(0.1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(tmp_path), str(ready_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not ready_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready_path.exists():
            stdout, stderr = process.communicate(timeout=2.0)
            raise AssertionError(
                f"child did not create a workspace; stdout={stdout!r}, stderr={stderr!r}"
            )
        workspace = Path(ready_path.read_text(encoding="utf-8"))
        _age_workspace(workspace, datetime.now(UTC) - timedelta(hours=25))

        active_summary = recover_abandoned_result_workspaces(
            temp_root=tmp_path,
            now=datetime.now(UTC),
        )

        assert active_summary.workspaces_removed == 0
        assert workspace.is_dir()

        process.terminate()
        process.communicate(timeout=5.0)
        _age_workspace(workspace, datetime.now(UTC) - timedelta(hours=25))

        abandoned_summary = recover_abandoned_result_workspaces(
            temp_root=tmp_path,
            now=datetime.now(UTC),
        )

        assert abandoned_summary.workspaces_removed == 1
        assert not workspace.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5.0)
