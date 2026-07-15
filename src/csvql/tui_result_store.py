"""Session-local result storage for the CSVQL TUI."""

from __future__ import annotations

import errno
import json
import os
import pickle
import re
import secrets
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Literal

from csvql.models import QueryResult

TUI_RESULT_SPILL_ROW_THRESHOLD = 10_000
TUI_RESULT_SPILL_CELL_THRESHOLD = 250_000
TUI_RESULT_SESSION_PREFIX = "localql-tui-v1-"
TUI_RESULT_MARKER_NAME = ".localql-session.json"
TUI_RESULT_LEASE_NAME = ".lease"
TUI_RESULT_MAX_TEMP_ENTRIES = 5_000
TUI_RESULT_MAX_CANDIDATES = 100
TUI_RESULT_MAX_CANDIDATE_ENTRIES = 1_024
TUI_RESULT_MAX_MARKER_BYTES = 4 * 1024
TUI_RESULT_MAX_RECOVERED_WORKSPACES = 20
TUI_RESULT_ABANDONED_AFTER = timedelta(hours=24)

_TUI_RESULT_DIRECTORY_PATTERN = re.compile(
    rf"{re.escape(TUI_RESULT_SESSION_PREFIX)}(?P<session_id>[0-9a-f]{{32}})"
)
_TUI_RESULT_COMPLETED_SPILL_PATTERN = re.compile(r"query-[1-9][0-9]*\.pickle")
_TUI_RESULT_STAGING_SPILL_PATTERN = re.compile(r"\.query-[1-9][0-9]*-[0-9a-f]{16}\.tmp")
_TUI_RESULT_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?Z"
)
_TUI_RESULT_MARKER_KEYS = {
    "created_at_utc",
    "format_version",
    "session_id",
}

TUIResultStorageFailureKind = Literal[
    "workspace_unavailable",
    "capacity",
    "permission",
    "serialization",
    "io",
    "result_unavailable",
]
_RecoveryMatchState = Literal["matching", "missing", "uncertain"]


class TUIResultStorageError(RuntimeError):
    """Sanitized TUI result-storage failure."""

    def __init__(
        self,
        user_message: str,
        *,
        kind: TUIResultStorageFailureKind,
        invalidated_sequences: tuple[int, ...] = (),
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.kind = kind
        self.invalidated_sequences = invalidated_sequences


@dataclass(frozen=True, slots=True)
class TUIResultHandle:
    """Reference to a stored TUI query result."""

    sequence: int
    is_spilled: bool
    temp_path: Path | None = None


@dataclass(frozen=True, slots=True)
class TUIResultPutOutcome:
    """Stored handle plus older results invalidated by workspace replacement."""

    handle: TUIResultHandle
    invalidated_sequences: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TUIResultCleanupSummary:
    """Bounded counts from TUI result cleanup and recovery."""

    temp_entries_inspected: int = 0
    candidates_validated: int = 0
    files_removed: int = 0
    files_failed: int = 0
    workspaces_removed: int = 0
    workspaces_failed: int = 0

    @property
    def warning_count(self) -> int:
        return self.files_failed + self.workspaces_failed

    def merge(self, other: TUIResultCleanupSummary) -> TUIResultCleanupSummary:
        return TUIResultCleanupSummary(
            temp_entries_inspected=self.temp_entries_inspected + other.temp_entries_inspected,
            candidates_validated=self.candidates_validated + other.candidates_validated,
            files_removed=self.files_removed + other.files_removed,
            files_failed=self.files_failed + other.files_failed,
            workspaces_removed=self.workspaces_removed + other.workspaces_removed,
            workspaces_failed=self.workspaces_failed + other.workspaces_failed,
        )


@dataclass(frozen=True, slots=True)
class _PendingWorkspaceCleanup:
    """Owned failed workspace plus the direct entries safe to revisit."""

    identity: tuple[int, int]
    entry_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _ValidatedRecoveryEntry:
    """One direct candidate entry observed without following links."""

    path: Path
    identity: tuple[int, int] | None
    mode: int
    size: int
    mtime_ns: int
    owner: int | None


@dataclass(frozen=True, slots=True)
class _ValidatedRecoveryCandidate:
    """Fully enumerated abandoned-workspace candidate."""

    path: Path
    identity: tuple[int, int] | None
    marker_path: Path
    lease_path: Path
    removable_paths: tuple[Path, ...]
    directory_mode: int
    directory_mtime_ns: int
    directory_owner: int | None
    marker_content: bytes
    entries: tuple[_ValidatedRecoveryEntry, ...]


@dataclass(slots=True)
class _PlatformLease:
    """Exclusive one-byte lease held by one cooperating LocalQL process."""

    file: BinaryIO
    is_locked: bool = False

    @classmethod
    def open(cls, path: Path) -> _PlatformLease:
        return cls(file=path.open("r+b", buffering=0))

    def acquire_nonblocking(self) -> bool:
        self.file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(
                    self.file.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )
            else:
                import fcntl

                fcntl.lockf(
                    self.file.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                    1,
                    0,
                    os.SEEK_SET,
                )
        except OSError as exc:
            contention_errnos = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
            windows_lock_violation = os.name == "nt" and getattr(exc, "winerror", None) == 33
            if exc.errno in contention_errnos or windows_lock_violation:
                return False
            raise
        self.is_locked = True
        return True

    def release(self) -> None:
        if not self.is_locked:
            return
        self.file.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(
                self.file.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )
        else:
            import fcntl

            fcntl.lockf(self.file.fileno(), fcntl.LOCK_UN, 1, 0, os.SEEK_SET)
        self.is_locked = False

    def close(self) -> None:
        try:
            self.release()
        finally:
            try:
                self.file.close()
            finally:
                self.is_locked = False


def recover_abandoned_result_workspaces(
    *,
    temp_root: Path | None = None,
    now: datetime | None = None,
) -> TUIResultCleanupSummary:
    """Remove bounded, validated, abandoned LocalQL TUI result workspaces."""

    recovery_now = now or datetime.now(UTC)
    if recovery_now.tzinfo is None or recovery_now.utcoffset() is None:
        return TUIResultCleanupSummary()
    recovery_now = recovery_now.astimezone(UTC)
    root = _resolve_recovery_root(temp_root)
    if root is None:
        return TUIResultCleanupSummary()

    inspected = 0
    candidates_validated = 0
    destructive_attempts = 0
    cleanup = TUIResultCleanupSummary()
    try:
        with os.scandir(root) as entries:
            while inspected < TUI_RESULT_MAX_TEMP_ENTRIES:
                if destructive_attempts >= TUI_RESULT_MAX_RECOVERED_WORKSPACES:
                    break
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                inspected += 1
                if not entry.name.startswith(TUI_RESULT_SESSION_PREFIX):
                    continue
                if candidates_validated >= TUI_RESULT_MAX_CANDIDATES:
                    continue
                candidates_validated += 1
                candidate = _validate_recovery_candidate(
                    root / entry.name,
                    temp_root=root,
                    now=recovery_now,
                )
                if candidate is None:
                    continue

                lease: _PlatformLease | None = None
                try:
                    lease = _open_recovery_lease(candidate)
                    if lease is None:
                        continue
                    if not lease.acquire_nonblocking():
                        continue
                    revalidated = _validate_recovery_candidate(
                        candidate.path,
                        temp_root=root,
                        now=recovery_now,
                    )
                    if revalidated is None or not _same_recovery_candidate(
                        candidate,
                        revalidated,
                    ):
                        continue
                    if not _locked_lease_matches_candidate(lease, revalidated):
                        continue
                    destructive_attempts += 1
                    cleanup = cleanup.merge(
                        _remove_validated_recovery_candidate(revalidated, lease=lease)
                    )
                except Exception:
                    # Startup recovery is deliberately best-effort. A candidate
                    # that becomes uncertain is retained for a later launch.
                    continue
                finally:
                    if lease is not None:
                        try:
                            lease.close()
                        except Exception:
                            pass
    except OSError:
        pass

    return TUIResultCleanupSummary(
        temp_entries_inspected=inspected,
        candidates_validated=candidates_validated,
        files_removed=cleanup.files_removed,
        files_failed=cleanup.files_failed,
        workspaces_removed=cleanup.workspaces_removed,
        workspaces_failed=cleanup.workspaces_failed,
    )


class TUIResultStore:
    """Own full results in memory or in a lazy, session-local spill workspace."""

    def __init__(
        self,
        *,
        temp_root: Path | None = None,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        if session_id is not None and re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
            raise ValueError("session_id must be 32 lowercase hexadecimal characters.")
        self._temp_root = temp_root
        self._requested_session_id = session_id
        self._session_id: str | None = None
        self._created_at = now or datetime.now(UTC)
        self._memory_results: dict[int, QueryResult] = {}
        self._spill_paths: dict[int, Path] = {}
        self._issued_handles: dict[int, TUIResultHandle] = {}
        self._workspace_path: Path | None = None
        self._workspace_identity: tuple[int, int] | None = None
        self._invalidated_sequences: set[int] = set()
        self._pending_cleanup_paths: set[Path] = set()
        self._pending_cleanup_workspaces: dict[Path, _PendingWorkspaceCleanup] = {}
        self._lease: _PlatformLease | None = None
        self._cleanup_uncertainties = 0
        self._cleanup_attempted = False

    @property
    def workspace_path(self) -> Path | None:
        """Return the active spill workspace without creating one."""

        return self._workspace_path

    def put(self, result: QueryResult, *, sequence: int) -> TUIResultPutOutcome:
        """Store a full result and return its handle plus invalidated sequences."""

        if self._cleanup_attempted:
            raise TUIResultStorageError(
                "Result storage is no longer available.",
                kind="result_unavailable",
            )
        if not _is_positive_sequence(sequence):
            raise ValueError("sequence must be a positive integer.")
        if (
            sequence in self._memory_results
            or sequence in self._spill_paths
            or sequence in self._invalidated_sequences
        ):
            raise ValueError(f"result sequence {sequence} is already stored.")

        if not _should_spill(result):
            self._memory_results[sequence] = result
            handle = TUIResultHandle(sequence=sequence, is_spilled=False)
            self._issued_handles[sequence] = handle
            return TUIResultPutOutcome(handle=handle)

        had_active_workspace = self._workspace_path is not None
        invalidated_sequences: tuple[int, ...] = ()
        for attempt in range(2):
            try:
                handle = self._write_spilled_result(result, sequence=sequence)
                return TUIResultPutOutcome(
                    handle=handle,
                    invalidated_sequences=invalidated_sequences,
                )
            except (TUIResultStorageError, OSError) as exc:
                storage_error = (
                    exc
                    if isinstance(exc, TUIResultStorageError)
                    else self._storage_error_from_os_error(exc)
                )
                can_replace_workspace = (
                    had_active_workspace
                    and storage_error.kind == "workspace_unavailable"
                    and attempt == 0
                )
                if not can_replace_workspace:
                    if invalidated_sequences:
                        raise TUIResultStorageError(
                            storage_error.user_message,
                            kind=storage_error.kind,
                            invalidated_sequences=invalidated_sequences,
                        ) from exc
                    if isinstance(exc, TUIResultStorageError):
                        raise
                    raise storage_error from exc
                invalidated_sequences = self._abandon_lost_workspace()
        raise AssertionError("spill retry loop must return or raise")

    def get(self, handle: TUIResultHandle) -> QueryResult:
        """Load a full result only from this store's registered handle."""

        if not _is_positive_sequence(handle.sequence):
            raise _result_unavailable_error(handle.sequence)
        if self._issued_handles.get(handle.sequence) is not handle:
            raise _result_unavailable_error(handle.sequence)
        if not handle.is_spilled:
            if handle.temp_path is not None:
                raise _result_unavailable_error(handle.sequence)
            try:
                return self._memory_results[handle.sequence]
            except KeyError as exc:
                raise _result_unavailable_error(handle.sequence) from exc

        registered_path = self._spill_paths.get(handle.sequence)
        if (
            handle.sequence in self._invalidated_sequences
            or handle.temp_path is None
            or registered_path is None
            or handle.temp_path != registered_path
        ):
            raise _result_unavailable_error(handle.sequence)

        try:
            self._ensure_workspace()
        except TUIResultStorageError as exc:
            if exc.kind != "workspace_unavailable":
                raise
            invalidated = self._abandon_lost_workspace()
            raise _results_unavailable_error(invalidated or (handle.sequence,)) from exc

        try:
            file = registered_path.open("rb")
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
                invalidated = self._abandon_lost_workspace()
                raise _results_unavailable_error(invalidated or (handle.sequence,)) from exc
            self._invalidate_handle(handle.sequence)
            raise _result_unavailable_error(handle.sequence) from exc

        try:
            with file:
                loaded = pickle.load(file)
        except Exception as exc:
            self._invalidate_handle(handle.sequence)
            raise _result_unavailable_error(handle.sequence) from exc
        if not isinstance(loaded, QueryResult):
            self._invalidate_handle(handle.sequence)
            raise TUIResultStorageError(
                "The stored result has an unexpected format.",
                kind="result_unavailable",
                invalidated_sequences=(handle.sequence,),
            )
        return loaded

    def cleanup(self) -> TUIResultCleanupSummary:
        """Remove registered result files without recursive deletion."""

        if self._cleanup_attempted:
            return TUIResultCleanupSummary()
        self._cleanup_attempted = True
        removed = 0
        failed = self._cleanup_uncertainties

        workspace_removed = 0
        workspace_failed = 0
        for pending_workspace, pending_cleanup in self._pending_cleanup_workspaces.items():
            pending_summary = _cleanup_owned_workspace(
                pending_workspace,
                identity=pending_cleanup.identity,
                entry_paths=pending_cleanup.entry_paths,
            )
            removed += pending_summary.files_removed
            failed += pending_summary.files_failed
            workspace_removed += pending_summary.workspaces_removed
            workspace_failed += pending_summary.workspaces_failed

        workspace = self._workspace_path
        if workspace is not None:
            identity = self._workspace_identity
            if identity is not None and _is_owned_workspace(workspace, identity=identity):
                paths = tuple(self._pending_cleanup_paths) + tuple(self._spill_paths.values())
                for path in paths:
                    path_removed, path_failed = _unlink_owned_workspace_entry(
                        workspace,
                        identity=identity,
                        path=path,
                    )
                    removed += path_removed
                    failed += path_failed

                marker_path, lease_path = self._workspace_metadata_paths(workspace)
                path_removed, path_failed = _unlink_owned_workspace_entry(
                    workspace,
                    identity=identity,
                    path=marker_path,
                )
                removed += path_removed
                failed += path_failed

                lease_closed = self._close_active_lease()
                if lease_closed:
                    path_removed, path_failed = _unlink_owned_workspace_entry(
                        workspace,
                        identity=identity,
                        path=lease_path,
                    )
                    removed += path_removed
                    failed += path_failed
                else:
                    failed += 1

                workspace_path_removed, workspace_path_failed = _rmdir_owned_workspace(
                    workspace,
                    identity=identity,
                )
                workspace_removed += workspace_path_removed
                workspace_failed += workspace_path_failed
            else:
                workspace_failed += 1
                if not self._close_active_lease():
                    failed += 1
        elif not self._close_active_lease():
            failed += 1

        self._memory_results.clear()
        self._spill_paths.clear()
        self._issued_handles.clear()
        self._pending_cleanup_paths.clear()
        self._pending_cleanup_workspaces.clear()
        self._workspace_path = None
        self._workspace_identity = None
        self._session_id = None
        self._cleanup_uncertainties = 0
        return TUIResultCleanupSummary(
            files_removed=removed,
            files_failed=failed,
            workspaces_removed=workspace_removed,
            workspaces_failed=workspace_failed,
        )

    def _create_workspace(self) -> Path:
        temp_root = self._resolve_temp_root()
        for attempt in range(10):
            session_id = self._requested_session_id or secrets.token_hex(16)
            workspace = temp_root / f"{TUI_RESULT_SESSION_PREFIX}{session_id}"
            try:
                workspace.mkdir(mode=0o700)
            except FileExistsError as exc:
                if self._requested_session_id is None and attempt < 9:
                    continue
                raise TUIResultStorageError(
                    "Unable to create secure temporary result storage.",
                    kind="workspace_unavailable",
                ) from exc
            except OSError as exc:
                raise self._storage_error_from_os_error(exc) from exc

            self._session_id = session_id
            self._workspace_path = workspace
            created_metadata_paths: list[Path] = []
            try:
                workspace_identity = _owned_workspace_identity(workspace)
                self._workspace_identity = workspace_identity
                self._write_workspace_metadata(
                    workspace,
                    session_id=session_id,
                    created_paths=created_metadata_paths,
                )
                lease = _PlatformLease.open(workspace / TUI_RESULT_LEASE_NAME)
                try:
                    lease_acquired = lease.acquire_nonblocking()
                except BaseException:
                    lease.close()
                    raise
                if not lease_acquired:
                    try:
                        lease.close()
                    finally:
                        raise TUIResultStorageError(
                            "Unable to create secure temporary result storage.",
                            kind="workspace_unavailable",
                        )
                self._lease = lease
            except Exception as exc:
                metadata_paths = tuple(created_metadata_paths)
                failed_workspace_identity = self._workspace_identity
                if failed_workspace_identity is not None and not self._remove_failed_workspace(
                    workspace,
                    identity=failed_workspace_identity,
                    entry_paths=metadata_paths,
                ):
                    self._pending_cleanup_workspaces[workspace] = _PendingWorkspaceCleanup(
                        identity=failed_workspace_identity,
                        entry_paths=metadata_paths,
                    )
                self._session_id = None
                self._workspace_path = None
                self._workspace_identity = None
                if isinstance(exc, OSError):
                    raise self._storage_error_from_os_error(exc) from exc
                raise TUIResultStorageError(
                    "Unable to create secure temporary result storage.",
                    kind="workspace_unavailable",
                ) from exc
            return workspace
        raise AssertionError("workspace creation loop must return or raise")

    def _resolve_temp_root(self) -> Path:
        try:
            temp_root = (
                self._temp_root if self._temp_root is not None else Path(tempfile.gettempdir())
            )
            return temp_root.resolve()
        except OSError as exc:
            raise self._storage_error_from_os_error(exc) from exc
        except RuntimeError as exc:
            raise TUIResultStorageError(
                "Unable to create secure temporary result storage.",
                kind="workspace_unavailable",
            ) from exc

    def _write_workspace_metadata(
        self,
        workspace: Path,
        *,
        session_id: str,
        created_paths: list[Path],
    ) -> None:
        created_at_utc = self._created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        marker = {
            "created_at_utc": created_at_utc,
            "format_version": 1,
            "session_id": session_id,
        }
        marker_text = json.dumps(marker, separators=(",", ":"), sort_keys=True)
        marker_path = workspace / TUI_RESULT_MARKER_NAME
        lease_path = workspace / TUI_RESULT_LEASE_NAME
        _write_exclusive_bytes(
            marker_path,
            marker_text.encode("utf-8"),
            created_paths=created_paths,
        )
        _write_exclusive_bytes(lease_path, b"0", created_paths=created_paths)
        _set_and_verify_posix_mode(workspace, 0o700)
        _set_and_verify_posix_mode(marker_path, 0o600)
        _set_and_verify_posix_mode(lease_path, 0o600)

    def _write_spilled_result(self, result: QueryResult, *, sequence: int) -> TUIResultHandle:
        workspace = self._ensure_workspace()
        token = secrets.token_hex(8)
        staging_path = workspace / f".query-{sequence}-{token}.tmp"
        final_path = workspace / f"query-{sequence}.pickle"
        try:
            staging_fd = os.open(
                staging_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            self._pending_cleanup_paths.add(staging_path)
            try:
                _set_and_verify_posix_mode(staging_path, 0o600)
            except BaseException:
                _close_file_descriptor(staging_fd)
                raise
            with _open_spill_file(staging_fd) as file:
                pickle.dump(result, file, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(staging_path, final_path)
        except OSError as exc:
            self._remove_staging_file(staging_path)
            raise self._storage_error_from_os_error(exc) from exc
        except Exception as exc:
            self._remove_staging_file(staging_path)
            raise TUIResultStorageError(
                "Unable to serialize the query result for temporary storage.",
                kind="serialization",
            ) from exc
        self._pending_cleanup_paths.discard(staging_path)
        self._spill_paths[sequence] = final_path
        handle = TUIResultHandle(sequence=sequence, is_spilled=True, temp_path=final_path)
        self._issued_handles[sequence] = handle
        return handle

    def _ensure_workspace(self) -> Path:
        if self._workspace_path is None:
            return self._create_workspace()
        workspace = self._workspace_path
        try:
            identity = self._workspace_identity
            if identity is None or not _is_owned_workspace(workspace, identity=identity):
                raise FileNotFoundError(workspace)
            for name in (TUI_RESULT_MARKER_NAME, TUI_RESULT_LEASE_NAME):
                if not stat.S_ISREG((workspace / name).lstat().st_mode):
                    raise FileNotFoundError(workspace / name)
            expected_names = {
                TUI_RESULT_MARKER_NAME,
                TUI_RESULT_LEASE_NAME,
                *(path.name for path in self._spill_paths.values()),
                *(path.name for path in self._pending_cleanup_paths),
            }
            if {path.name for path in workspace.iterdir()} != expected_names:
                raise FileNotFoundError(workspace)
        except OSError as exc:
            raise TUIResultStorageError(
                "Temporary result storage disappeared before the result was saved.",
                kind="workspace_unavailable",
            ) from exc
        return workspace

    def _abandon_lost_workspace(self) -> tuple[int, ...]:
        invalidated = tuple(sorted(self._spill_paths))
        self._invalidated_sequences.update(invalidated)
        for sequence in invalidated:
            self._issued_handles.pop(sequence, None)
        self._spill_paths.clear()
        self._pending_cleanup_paths.clear()
        self._workspace_path = None
        self._workspace_identity = None
        self._session_id = None
        if not self._close_active_lease():
            self._cleanup_uncertainties += 1
        return invalidated

    def _close_active_lease(self) -> bool:
        lease = self._lease
        self._lease = None
        if lease is None:
            return True
        try:
            lease.close()
        except Exception:
            return False
        return True

    def _remove_staging_file(self, staging_path: Path) -> None:
        if staging_path not in self._pending_cleanup_paths:
            return
        workspace = self._workspace_path
        identity = self._workspace_identity
        if workspace is None or identity is None:
            return
        _, failed = _unlink_owned_workspace_entry(
            workspace,
            identity=identity,
            path=staging_path,
        )
        if failed:
            return
        self._pending_cleanup_paths.discard(staging_path)

    def _invalidate_handle(self, sequence: int) -> None:
        self._invalidated_sequences.add(sequence)
        self._issued_handles.pop(sequence, None)

    @staticmethod
    def _workspace_metadata_paths(workspace: Path) -> tuple[Path, Path]:
        return (
            workspace / TUI_RESULT_MARKER_NAME,
            workspace / TUI_RESULT_LEASE_NAME,
        )

    @staticmethod
    def _remove_failed_workspace(
        workspace: Path,
        *,
        identity: tuple[int, int],
        entry_paths: tuple[Path, ...],
    ) -> bool:
        summary = _cleanup_owned_workspace(
            workspace,
            identity=identity,
            entry_paths=entry_paths,
        )
        return summary.workspaces_failed == 0

    @staticmethod
    def _storage_error_from_os_error(exc: OSError) -> TUIResultStorageError:
        capacity_codes = {errno.ENOSPC, getattr(errno, "EDQUOT", -1)}
        if exc.errno in capacity_codes:
            return TUIResultStorageError(
                "Unable to store the query result because temporary storage is full.",
                kind="capacity",
            )
        if isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
            return TUIResultStorageError(
                "Unable to use secure temporary result storage.",
                kind="permission",
            )
        if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
            return TUIResultStorageError(
                "Temporary result storage disappeared before the result was saved.",
                kind="workspace_unavailable",
            )
        return TUIResultStorageError(
            "Unable to write the query result to temporary storage.",
            kind="io",
        )


def _write_exclusive_bytes(
    path: Path,
    content: bytes,
    *,
    created_paths: list[Path],
) -> None:
    file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    created_paths.append(path)
    try:
        file_object = os.fdopen(file_descriptor, "wb")
    except Exception:
        _close_file_descriptor(file_descriptor)
        raise
    with file_object:
        file_object.write(content)


def _open_spill_file(file_descriptor: int) -> BinaryIO:
    try:
        if sys.platform != "win32":
            os.fchmod(file_descriptor, 0o600)
        return os.fdopen(file_descriptor, "wb")
    except Exception:
        _close_file_descriptor(file_descriptor)
        raise


def _close_file_descriptor(file_descriptor: int) -> None:
    try:
        os.close(file_descriptor)
    except OSError:
        pass


def _set_and_verify_posix_mode(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    os.chmod(path, mode)
    if stat.S_IMODE(path.lstat().st_mode) != mode:
        raise PermissionError(errno.EACCES, "Unable to enforce owner-only permissions.")


def _owned_workspace_identity(workspace: Path) -> tuple[int, int]:
    result = workspace.lstat()
    if not stat.S_ISDIR(result.st_mode) or _is_reparse_point(result):
        raise OSError(errno.ENOTDIR, "Temporary result workspace is not a real directory.")
    return (result.st_dev, result.st_ino)


def _is_owned_workspace(workspace: Path, *, identity: tuple[int, int]) -> bool:
    try:
        result = workspace.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(result.st_mode)
        and not _is_reparse_point(result)
        and (result.st_dev, result.st_ino) == identity
    )


def _cleanup_owned_workspace(
    workspace: Path,
    *,
    identity: tuple[int, int],
    entry_paths: tuple[Path, ...],
) -> TUIResultCleanupSummary:
    if not _is_owned_workspace(workspace, identity=identity):
        return TUIResultCleanupSummary(workspaces_failed=1)

    removed = 0
    failed = 0
    for path in entry_paths:
        path_removed, path_failed = _unlink_owned_workspace_entry(
            workspace,
            identity=identity,
            path=path,
        )
        removed += path_removed
        failed += path_failed
    workspace_removed, workspace_failed = _rmdir_owned_workspace(
        workspace,
        identity=identity,
    )
    return TUIResultCleanupSummary(
        files_removed=removed,
        files_failed=failed,
        workspaces_removed=workspace_removed,
        workspaces_failed=workspace_failed,
    )


def _unlink_owned_workspace_entry(
    workspace: Path,
    *,
    identity: tuple[int, int],
    path: Path,
) -> tuple[int, int]:
    if path.parent != workspace or not _is_owned_workspace(workspace, identity=identity):
        return (0, 1)
    try:
        result = path.lstat()
    except FileNotFoundError:
        return (0, 0)
    except OSError:
        return (0, 1)
    if not stat.S_ISREG(result.st_mode) or _is_reparse_point(result):
        return (0, 1)
    if not _is_owned_workspace(workspace, identity=identity):
        return (0, 1)
    try:
        path.unlink()
    except FileNotFoundError:
        return (0, 0)
    except OSError:
        return (0, 1)
    return (1, 0)


def _rmdir_owned_workspace(
    workspace: Path,
    *,
    identity: tuple[int, int],
) -> tuple[int, int]:
    if not _is_owned_workspace(workspace, identity=identity):
        return (0, 1)
    try:
        workspace.rmdir()
    except FileNotFoundError:
        return (0, 0)
    except OSError:
        return (0, 1)
    return (1, 0)


def _is_reparse_point(result: os.stat_result) -> bool:
    file_attributes = getattr(result, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(file_attributes & reparse_flag)


def _is_windows_platform() -> bool:
    return os.name == "nt"


def _resolve_recovery_root(temp_root: Path | None) -> Path | None:
    try:
        requested_root = temp_root if temp_root is not None else Path(tempfile.gettempdir())
        requested_stat = requested_root.lstat()
        if not stat.S_ISDIR(requested_stat.st_mode) or _is_reparse_point(requested_stat):
            return None
        root = requested_root.resolve(strict=True)
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or _is_reparse_point(root_stat):
            return None

        if _is_windows_platform():
            current_user_root = Path(tempfile.gettempdir())
            current_user_stat = current_user_root.lstat()
            if not stat.S_ISDIR(current_user_stat.st_mode) or _is_reparse_point(current_user_stat):
                return None
            if root != current_user_root.resolve(strict=True):
                return None
    except (OSError, RuntimeError):
        return None
    return root


def _validate_recovery_candidate(
    path: Path,
    *,
    temp_root: Path,
    now: datetime,
) -> _ValidatedRecoveryCandidate | None:
    if path.parent != temp_root:
        return None
    directory_match = _TUI_RESULT_DIRECTORY_PATTERN.fullmatch(path.name)
    if directory_match is None:
        return None
    session_id = directory_match.group("session_id")

    try:
        directory_stat = path.lstat()
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or _is_reparse_point(directory_stat)
            or not _stat_has_current_owner(directory_stat)
            or not _directory_mode_is_private(directory_stat)
        ):
            return None
        directory_modified_at = datetime.fromtimestamp(directory_stat.st_mtime, UTC)

        marker_path: Path | None = None
        marker_stat: os.stat_result | None = None
        lease_path: Path | None = None
        removable_paths: list[Path] = []
        validated_entries: list[_ValidatedRecoveryEntry] = []
        with os.scandir(path) as entries:
            enumeration_complete = False
            entries_inspected = 0
            while entries_inspected < TUI_RESULT_MAX_CANDIDATE_ENTRIES:
                try:
                    entry = next(entries)
                except StopIteration:
                    enumeration_complete = True
                    break
                entries_inspected += 1
                entry_path = path / entry.name
                if entry_path.parent != path:
                    return None
                entry_stat = entry_path.lstat()
                if (
                    not stat.S_ISREG(entry_stat.st_mode)
                    or _is_reparse_point(entry_stat)
                    or not _stat_has_current_owner(entry_stat)
                    or not _file_mode_is_private(entry_stat)
                ):
                    return None
                validated_entries.append(_validated_recovery_entry(entry_path, entry_stat))
                if entry.name == TUI_RESULT_MARKER_NAME:
                    marker_path = entry_path
                    marker_stat = entry_stat
                elif entry.name == TUI_RESULT_LEASE_NAME:
                    if entry_stat.st_size != 1:
                        return None
                    lease_path = entry_path
                elif _is_recovery_spill_name(entry.name):
                    removable_paths.append(entry_path)
                else:
                    return None
            if not enumeration_complete:
                try:
                    next(entries)
                except StopIteration:
                    enumeration_complete = True
            if not enumeration_complete:
                return None
    except (OSError, OverflowError, ValueError):
        return None

    if marker_path is None or marker_stat is None or lease_path is None:
        return None
    marker_result = _read_recovery_marker(marker_path, expected_stat=marker_stat)
    if marker_result is None:
        return None
    marker, marker_content = marker_result
    created_at = _parse_recovery_marker(marker, expected_session_id=session_id)
    if created_at is None:
        return None
    if (
        created_at > now
        or directory_modified_at > now
        or directory_modified_at < created_at
        or now - created_at < TUI_RESULT_ABANDONED_AFTER
        or now - directory_modified_at < TUI_RESULT_ABANDONED_AFTER
    ):
        return None

    return _ValidatedRecoveryCandidate(
        path=path,
        identity=_usable_stat_identity(directory_stat),
        marker_path=marker_path,
        lease_path=lease_path,
        removable_paths=tuple(sorted(removable_paths)),
        directory_mode=directory_stat.st_mode,
        directory_mtime_ns=directory_stat.st_mtime_ns,
        directory_owner=_stat_owner(directory_stat),
        marker_content=marker_content,
        entries=tuple(sorted(validated_entries, key=lambda entry: entry.path.name)),
    )


def _read_recovery_marker(
    marker_path: Path,
    *,
    expected_stat: os.stat_result,
) -> tuple[dict[str, object], bytes] | None:
    if expected_stat.st_size > TUI_RESULT_MAX_MARKER_BYTES:
        return None
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        file_descriptor = os.open(marker_path, flags)
    except OSError:
        return None
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not _same_file_observation(expected_stat, opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _is_reparse_point(opened_stat)
            or not _stat_has_current_owner(opened_stat)
            or not _file_mode_is_private(opened_stat)
            or opened_stat.st_size > TUI_RESULT_MAX_MARKER_BYTES
        ):
            return None
        remaining = opened_stat.st_size
        marker_bytes = bytearray()
        while remaining:
            chunk = os.read(file_descriptor, remaining)
            if not chunk:
                return None
            marker_bytes.extend(chunk)
            remaining -= len(chunk)
        final_stat = os.fstat(file_descriptor)
        if (
            not _same_file_observation(opened_stat, final_stat)
            or not stat.S_ISREG(final_stat.st_mode)
            or _is_reparse_point(final_stat)
            or not _stat_has_current_owner(final_stat)
            or not _file_mode_is_private(final_stat)
        ):
            return None
    except OSError:
        return None
    finally:
        try:
            os.close(file_descriptor)
        except OSError:
            pass

    try:
        parsed: object = json.loads(
            marker_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return (parsed, bytes(marker_bytes))


def _open_recovery_lease(
    candidate: _ValidatedRecoveryCandidate,
) -> _PlatformLease | None:
    lease_path = candidate.lease_path
    if lease_path.parent != candidate.path or not _recovery_workspace_matches(candidate):
        return None
    try:
        expected_stat = lease_path.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISREG(expected_stat.st_mode)
        or _is_reparse_point(expected_stat)
        or not _stat_has_current_owner(expected_stat)
        or not _file_mode_is_private(expected_stat)
        or expected_stat.st_size != 1
    ):
        return None

    flags = os.O_RDWR
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        file_descriptor = os.open(lease_path, flags)
    except OSError:
        return None
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not _same_opened_file(expected_stat, opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _is_reparse_point(opened_stat)
            or not _stat_has_current_owner(opened_stat)
            or not _file_mode_is_private(opened_stat)
            or opened_stat.st_size != 1
            or not _recovery_workspace_matches(candidate)
        ):
            _close_file_descriptor(file_descriptor)
            return None
        try:
            file_object = os.fdopen(file_descriptor, "r+b", buffering=0)
        except Exception:
            _close_file_descriptor(file_descriptor)
            return None
    except OSError:
        _close_file_descriptor(file_descriptor)
        return None
    return _PlatformLease(file=file_object)


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_recovery_marker(
    marker: dict[str, object],
    *,
    expected_session_id: str,
) -> datetime | None:
    if set(marker) != _TUI_RESULT_MARKER_KEYS:
        return None
    created_at_text = marker["created_at_utc"]
    format_version = marker["format_version"]
    session_id = marker["session_id"]
    if (
        type(created_at_text) is not str
        or type(format_version) is not int
        or type(session_id) is not str
        or format_version != 1
        or session_id != expected_session_id
        or _TUI_RESULT_TIMESTAMP_PATTERN.fullmatch(created_at_text) is None
    ):
        return None
    try:
        created_at = datetime.fromisoformat(f"{created_at_text[:-1]}+00:00")
    except ValueError:
        return None
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
        return None
    return created_at.astimezone(UTC)


def _same_recovery_candidate(
    first: _ValidatedRecoveryCandidate,
    second: _ValidatedRecoveryCandidate,
) -> bool:
    return (
        first.identity == second.identity
        and first.path == second.path
        and first.marker_path == second.marker_path
        and first.lease_path == second.lease_path
        and first.removable_paths == second.removable_paths
        and first.directory_mode == second.directory_mode
        and first.directory_mtime_ns == second.directory_mtime_ns
        and first.directory_owner == second.directory_owner
        and first.marker_content == second.marker_content
        and first.entries == second.entries
    )


def _remove_validated_recovery_candidate(
    candidate: _ValidatedRecoveryCandidate,
    *,
    lease: _PlatformLease,
) -> TUIResultCleanupSummary:
    files_removed = 0
    files_failed = 0
    if not _locked_lease_matches_candidate(lease, candidate):
        return TUIResultCleanupSummary()
    for removable_path in candidate.removable_paths:
        removed, failed = _unlink_recovery_entry(
            candidate,
            removable_path,
            lease=lease,
        )
        files_removed += removed
        files_failed += failed
        if failed:
            return TUIResultCleanupSummary(
                files_removed=files_removed,
                files_failed=files_failed,
            )
        if _recovery_candidate_disappeared(candidate):
            return TUIResultCleanupSummary(
                files_removed=files_removed,
                files_failed=files_failed,
            )

    removed, failed = _unlink_recovery_entry(
        candidate,
        candidate.marker_path,
        lease=lease,
    )
    files_removed += removed
    files_failed += failed
    if failed:
        return TUIResultCleanupSummary(
            files_removed=files_removed,
            files_failed=files_failed,
        )
    if _recovery_candidate_disappeared(candidate):
        return TUIResultCleanupSummary(
            files_removed=files_removed,
            files_failed=files_failed,
        )

    if not _locked_lease_matches_candidate(lease, candidate):
        if _recovery_candidate_or_lease_disappeared(candidate):
            return TUIResultCleanupSummary(
                files_removed=files_removed,
                files_failed=files_failed,
            )
        return TUIResultCleanupSummary(
            files_removed=files_removed,
            files_failed=files_failed + 1,
        )
    try:
        lease.close()
    except Exception:
        return TUIResultCleanupSummary(
            files_removed=files_removed,
            files_failed=files_failed + 1,
        )

    removed, failed = _unlink_recovery_entry(
        candidate,
        candidate.lease_path,
        lease=None,
    )
    files_removed += removed
    files_failed += failed
    if failed:
        return TUIResultCleanupSummary(
            files_removed=files_removed,
            files_failed=files_failed,
        )

    workspace_removed, workspace_failed = _rmdir_recovery_workspace(candidate)
    return TUIResultCleanupSummary(
        files_removed=files_removed,
        files_failed=files_failed,
        workspaces_removed=workspace_removed,
        workspaces_failed=workspace_failed,
    )


def _unlink_recovery_entry(
    candidate: _ValidatedRecoveryCandidate,
    path: Path,
    *,
    lease: _PlatformLease | None = None,
) -> tuple[int, int]:
    if path.parent != candidate.path:
        return (0, 1)
    try:
        entry_stat = path.lstat()
    except FileNotFoundError:
        if _recovery_candidate_disappeared(candidate):
            return (0, 0)
        workspace_state = _recovery_workspace_state(candidate)
        return (0, 0) if workspace_state != "uncertain" else (0, 1)
    except OSError:
        return (0, 1)
    expected_entry = _recovery_entry_for_path(candidate, path)
    if expected_entry is None:
        return (0, 1)
    require_identity = path == candidate.lease_path
    if (
        not stat.S_ISREG(entry_stat.st_mode)
        or _is_reparse_point(entry_stat)
        or not _stat_has_current_owner(entry_stat)
        or not _file_mode_is_private(entry_stat)
        or not _stat_matches_validated_entry(
            entry_stat,
            expected_entry,
            require_identity=require_identity,
        )
        or not _recovery_workspace_matches(candidate)
    ):
        return (0, 1)
    if path != candidate.lease_path:
        if lease is None or not _locked_lease_matches_candidate(lease, candidate):
            return (0, 1)
    elif lease is not None:
        return (0, 1)
    try:
        path.unlink()
    except FileNotFoundError:
        return (0, 0)
    except OSError:
        return (0, 1)
    return (1, 0)


def _rmdir_recovery_workspace(
    candidate: _ValidatedRecoveryCandidate,
) -> tuple[int, int]:
    try:
        workspace_stat = candidate.path.lstat()
    except FileNotFoundError:
        return (0, 0)
    except OSError:
        return (0, 1)
    if not _workspace_stat_matches_candidate(candidate, workspace_stat):
        return (0, 1)
    try:
        candidate.path.rmdir()
    except FileNotFoundError:
        return (0, 0)
    except OSError:
        return (0, 1)
    return (1, 0)


def _recovery_workspace_matches(candidate: _ValidatedRecoveryCandidate) -> bool:
    return _recovery_workspace_state(candidate) == "matching"


def _recovery_workspace_state(
    candidate: _ValidatedRecoveryCandidate,
) -> _RecoveryMatchState:
    try:
        workspace_stat = candidate.path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "uncertain"
    if _workspace_stat_matches_candidate(candidate, workspace_stat):
        return "matching"
    return "uncertain"


def _workspace_stat_matches_candidate(
    candidate: _ValidatedRecoveryCandidate,
    workspace_stat: os.stat_result,
) -> bool:
    if (
        not stat.S_ISDIR(workspace_stat.st_mode)
        or _is_reparse_point(workspace_stat)
        or not _stat_has_current_owner(workspace_stat)
        or not _directory_mode_is_private(workspace_stat)
    ):
        return False
    current_identity = _usable_stat_identity(workspace_stat)
    if candidate.identity is not None or current_identity is not None:
        return candidate.identity == current_identity
    return (
        workspace_stat.st_mode == candidate.directory_mode
        and _stat_owner(workspace_stat) == candidate.directory_owner
    )


def _recovery_candidate_disappeared(candidate: _ValidatedRecoveryCandidate) -> bool:
    return _recovery_workspace_state(candidate) == "missing"


def _recovery_candidate_or_lease_disappeared(
    candidate: _ValidatedRecoveryCandidate,
) -> bool:
    workspace_state = _recovery_workspace_state(candidate)
    if workspace_state == "missing":
        return True
    if workspace_state != "matching":
        return False
    try:
        candidate.lease_path.lstat()
    except FileNotFoundError:
        return _recovery_workspace_is_missing_or_empty(candidate)
    except OSError:
        return False
    return False


def _recovery_workspace_is_missing_or_empty(
    candidate: _ValidatedRecoveryCandidate,
) -> bool:
    workspace_state = _recovery_workspace_state(candidate)
    if workspace_state == "missing":
        return True
    if workspace_state != "matching":
        return False
    try:
        with os.scandir(candidate.path) as entries:
            try:
                next(entries)
            except StopIteration:
                pass
            else:
                return False
    except FileNotFoundError:
        return _recovery_workspace_state(candidate) == "missing"
    except OSError:
        return False
    return _recovery_workspace_state(candidate) in {"matching", "missing"}


def _locked_lease_matches_candidate(
    lease: _PlatformLease,
    candidate: _ValidatedRecoveryCandidate,
) -> bool:
    if (
        not lease.is_locked
        or candidate.lease_path.parent != candidate.path
        or not _recovery_workspace_matches(candidate)
    ):
        return False
    expected_entry = _recovery_entry_for_path(candidate, candidate.lease_path)
    if expected_entry is None or expected_entry.identity is None:
        return False
    try:
        opened_stat = os.fstat(lease.file.fileno())
        path_stat = candidate.lease_path.lstat()
    except (OSError, ValueError):
        return False
    return (
        _same_opened_file(opened_stat, path_stat)
        and stat.S_ISREG(path_stat.st_mode)
        and not _is_reparse_point(path_stat)
        and _stat_has_current_owner(path_stat)
        and _file_mode_is_private(path_stat)
        and path_stat.st_size == 1
        and _stat_matches_validated_entry(
            path_stat,
            expected_entry,
            require_identity=True,
        )
    )


def _validated_recovery_entry(
    path: Path,
    result: os.stat_result,
) -> _ValidatedRecoveryEntry:
    return _ValidatedRecoveryEntry(
        path=path,
        identity=_usable_stat_identity(result),
        mode=result.st_mode,
        size=result.st_size,
        mtime_ns=result.st_mtime_ns,
        owner=_stat_owner(result),
    )


def _recovery_entry_for_path(
    candidate: _ValidatedRecoveryCandidate,
    path: Path,
) -> _ValidatedRecoveryEntry | None:
    return next((entry for entry in candidate.entries if entry.path == path), None)


def _stat_matches_validated_entry(
    result: os.stat_result,
    expected: _ValidatedRecoveryEntry,
    *,
    require_identity: bool,
) -> bool:
    identity = _usable_stat_identity(result)
    if require_identity and (expected.identity is None or identity is None):
        return False
    if expected.identity is not None or identity is not None:
        if expected.identity != identity:
            return False
    return (
        result.st_mode == expected.mode
        and result.st_size == expected.size
        and result.st_mtime_ns == expected.mtime_ns
        and _stat_owner(result) == expected.owner
    )


def _is_recovery_spill_name(name: str) -> bool:
    return (
        _TUI_RESULT_COMPLETED_SPILL_PATTERN.fullmatch(name) is not None
        or _TUI_RESULT_STAGING_SPILL_PATTERN.fullmatch(name) is not None
    )


def _directory_mode_is_private(result: os.stat_result) -> bool:
    return os.name == "nt" or stat.S_IMODE(result.st_mode) == 0o700


def _file_mode_is_private(result: os.stat_result) -> bool:
    return os.name == "nt" or stat.S_IMODE(result.st_mode) & 0o077 == 0


def _stat_has_current_owner(result: os.stat_result) -> bool:
    if os.name == "nt" or not hasattr(os, "getuid"):
        return True
    stat_uid = getattr(result, "st_uid", None)
    return stat_uid is None or stat_uid == os.getuid()


def _stat_owner(result: os.stat_result) -> int | None:
    if _is_windows_platform():
        return None
    stat_uid = getattr(result, "st_uid", None)
    return stat_uid if isinstance(stat_uid, int) else None


def _usable_stat_identity(result: os.stat_result) -> tuple[int, int] | None:
    device = getattr(result, "st_dev", 0)
    inode = getattr(result, "st_ino", 0)
    if (
        isinstance(device, int)
        and not isinstance(device, bool)
        and device >= 0
        and isinstance(inode, int)
        and not isinstance(inode, bool)
        and inode > 0
    ):
        return (device, inode)
    return None


def _same_opened_file(first: os.stat_result, second: os.stat_result) -> bool:
    first_identity = _usable_stat_identity(first)
    second_identity = _usable_stat_identity(second)
    return (
        first_identity is not None
        and second_identity is not None
        and first_identity == second_identity
    )


def _same_file_observation(first: os.stat_result, second: os.stat_result) -> bool:
    first_identity = _usable_stat_identity(first)
    second_identity = _usable_stat_identity(second)
    if first_identity is not None or second_identity is not None:
        if first_identity != second_identity:
            return False
    return (
        first.st_mode == second.st_mode
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and _stat_owner(first) == _stat_owner(second)
    )


def _result_unavailable_error(sequence: int) -> TUIResultStorageError:
    return _results_unavailable_error((sequence,))


def _results_unavailable_error(sequences: tuple[int, ...]) -> TUIResultStorageError:
    return TUIResultStorageError(
        "The full result is no longer available.",
        kind="result_unavailable",
        invalidated_sequences=sequences,
    )


def _is_positive_sequence(sequence: object) -> bool:
    return isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0


def _should_spill(result: QueryResult) -> bool:
    if result.row_count > TUI_RESULT_SPILL_ROW_THRESHOLD:
        return True
    return result.row_count * len(result.columns) > TUI_RESULT_SPILL_CELL_THRESHOLD
