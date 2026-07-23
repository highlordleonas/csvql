"""Session-local result storage for the CSVQL TUI."""

from __future__ import annotations

import errno
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Literal

from csvql.bounded_result import (
    BoundedQueryResult,
    PreviewAccumulator,
    PreviewPolicy,
    TruncationReason,
)
from csvql.result_codec import encode_row_payload
from csvql.result_spool import ResultSpoolError, ResultSpoolReader, ResultSpoolWriter
from csvql.streaming_export import ExportRowSource

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
DEFAULT_TUI_RESULT_CAPACITY_BYTES = 1_073_741_824

_TUI_RESULT_DIRECTORY_PATTERN = re.compile(
    rf"{re.escape(TUI_RESULT_SESSION_PREFIX)}(?P<session_id>[0-9a-f]{{32}})"
)
_TUI_RESULT_COMPLETED_SPILL_PATTERN = re.compile(r"(?:query|preview)-[1-9][0-9]*\.result")
_TUI_RESULT_STAGING_SPILL_PATTERN = re.compile(
    r"\.(?:query|preview)-[1-9][0-9]*-[0-9a-f]{16}\.result\.tmp"
)
_TUI_RESULT_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?Z"
)
_TUI_RESULT_MARKER_KEYS = {
    "created_at_utc",
    "format_version",
    "session_id",
}
_SPOOL_HEADER_PREFIX_BYTES = 14
_SPOOL_LENGTH_BYTES = 8
_SPOOL_FRAME_PREFIX_BYTES = 9
_SPOOL_FOOTER_BYTES = 9
_TUI_RESULT_REASONS: frozenset[str] = frozenset(
    {"user_cancelled", "session_spool_limit", "preservation_failed"}
)

TUIResultStorageFailureKind = Literal[
    "workspace_unavailable",
    "capacity",
    "permission",
    "serialization",
    "io",
    "result_unavailable",
]
TUIResultKind = Literal["complete", "preview_only"]
TUIResultReason = Literal[
    "user_cancelled",
    "session_spool_limit",
    "preservation_failed",
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
    store_id: str
    nonce: str


@dataclass(frozen=True, slots=True)
class TUIStoredResult:
    """Durable metadata for one registered TUI result artifact."""

    handle: TUIResultHandle
    kind: TUIResultKind
    reason: TUIResultReason | None
    columns: tuple[str, ...]
    stored_row_count: int
    elapsed_ms: float
    logical_bytes: int


@dataclass(frozen=True, slots=True)
class TUIResultStoreProgress:
    """Capacity-aware progress for the one active TUI result writer."""

    rows_written: int
    logical_bytes_written: int
    remaining_capacity_bytes: int


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


@dataclass(slots=True)
class _StoredResultRecord:
    stored: TUIStoredResult
    path: Path
    identity: tuple[int, int]
    staging_alias: Path | None
    preview_payload_bytes: int
    preview_has_more_rows: bool
    preview_truncation_reason: TruncationReason | None


class _TUIResultRowSource:
    """One-shot export row source backed by one validated result spool."""

    def __init__(
        self,
        *,
        reader: ResultSpoolReader,
        elapsed_ms: float,
        invalidate: Callable[[], None],
        sequence: int,
    ) -> None:
        self._reader = reader
        self._elapsed_ms = elapsed_ms
        self._invalidate = invalidate
        self._sequence = sequence
        self._used = False

    @property
    def columns(self) -> tuple[str, ...]:
        return self._reader.columns

    @property
    def elapsed_ms(self) -> float:
        return self._elapsed_ms

    def iter_rows(self) -> Iterator[tuple[object, ...]]:
        if self._used:
            raise _result_unavailable_error(self._sequence)
        self._used = True
        return self._iter_rows()

    def _iter_rows(self) -> Iterator[tuple[object, ...]]:
        try:
            yield from self._reader.iter_rows()
        except Exception as exc:
            self._invalidate()
            raise _result_unavailable_error(self._sequence) from exc
        finally:
            self._reader.close()


class TUIResultWriter:
    """Write one complete TUI result under the store's aggregate capacity."""

    def __init__(
        self,
        *,
        store: TUIResultStore,
        spool_writer: ResultSpoolWriter,
        sequence: int,
        columns: tuple[str, ...],
        staging_path: Path,
        final_path: Path,
        kind: TUIResultKind,
        reason: TUIResultReason | None,
        initial_reserved_bytes: int,
        initial_written_bytes: int,
        preview_payload_bytes: int = 0,
        preview_has_more_rows: bool = False,
        preview_truncation_reason: TruncationReason | None = None,
    ) -> None:
        self._store = store
        self._spool_writer = spool_writer
        self._sequence = sequence
        self._columns = columns
        self._staging_path = staging_path
        self._final_path = final_path
        self._kind = kind
        self._reason = reason
        self._reserved_bytes = initial_reserved_bytes
        self._written_bytes = initial_written_bytes
        self._rows_written = 0
        self._preview_payload_bytes = preview_payload_bytes
        self._preview_has_more_rows = preview_has_more_rows
        self._preview_truncation_reason = preview_truncation_reason
        self._failed = False
        self._closed = False
        self._stored_result: TUIStoredResult | None = None

    def append_payload(self, payload: bytes) -> None:
        """Append one already encoded row payload."""

        self._store._append_writer_payload(self, payload)

    @property
    def progress(self) -> TUIResultStoreProgress:
        """Return written rows/bytes and capacity remaining after footer reservation."""

        return self._store._writer_progress(self)

    def commit(self, *, elapsed_ms: float) -> TUIStoredResult:
        """Commit the complete artifact and return its opaque durable metadata."""

        return self._store._commit_writer(self, elapsed_ms=elapsed_ms)

    def rollback(self) -> None:
        """Delete incomplete staging and release its reserved capacity."""

        self._store._rollback_writer(self)


class TUIResultStore:
    """Own same-session TUI result artifacts under one aggregate capacity."""

    def __init__(
        self,
        *,
        temp_root: Path | None = None,
        session_id: str | None = None,
        now: datetime | None = None,
        capacity_bytes: int = DEFAULT_TUI_RESULT_CAPACITY_BYTES,
    ) -> None:
        if session_id is not None and re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
            raise ValueError("session_id must be 32 lowercase hexadecimal characters.")
        if not _is_positive_integer(capacity_bytes):
            raise ValueError("capacity_bytes must be a positive integer.")
        self._temp_root = temp_root
        self._requested_session_id = session_id
        self._session_id: str | None = None
        self._store_id = secrets.token_hex(16)
        self._created_at = now or datetime.now(UTC)
        self._capacity_bytes = capacity_bytes
        self._allocated_bytes = 0
        self._records_by_nonce: dict[str, _StoredResultRecord] = {}
        self._record_nonce_by_sequence: dict[int, str] = {}
        self._issued_handles: dict[str, TUIResultHandle] = {}
        self._invalidated_sequences: set[int] = set()
        self._active_writer: TUIResultWriter | None = None
        self._workspace_path: Path | None = None
        self._workspace_identity: tuple[int, int] | None = None
        self._pending_cleanup_paths: set[Path] = set()
        self._pending_cleanup_identities: dict[Path, tuple[int, int]] = {}
        self._pending_cleanup_bytes: dict[Path, int] = {}
        self._pending_cleanup_workspaces: dict[Path, _PendingWorkspaceCleanup] = {}
        self._lease: _PlatformLease | None = None
        self._cleanup_uncertainties = 0
        self._cleanup_attempted = False
        self._lock = threading.RLock()

    @property
    def workspace_path(self) -> Path | None:
        """Return the active private workspace without creating it."""

        with self._lock:
            return self._workspace_path

    def begin_complete(
        self,
        *,
        sequence: int,
        columns: tuple[str, ...],
    ) -> TUIResultWriter:
        """Start the session's sole complete-result writer."""

        return self._begin_writer(
            sequence=sequence,
            columns=columns,
            kind="complete",
            reason=None,
        )

    def persist_preview(
        self,
        *,
        sequence: int,
        preview: BoundedQueryResult,
        reason: TUIResultReason,
        elapsed_ms: float,
    ) -> TUIStoredResult | None:
        """Persist only retained preview rows, returning ``None`` on capacity."""

        if reason not in _TUI_RESULT_REASONS:
            raise ValueError("reason must be a supported preview-only reason.")
        if preview.columns != tuple(preview.columns):
            raise ValueError("preview columns must be an immutable tuple.")
        payloads: list[bytes] = []
        try:
            for row in preview.rows:
                if len(row) != len(preview.columns):
                    raise ValueError("preview row does not match its columns.")
                payloads.append(encode_row_payload(row))
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("preview row"):
                raise
            raise TUIResultStorageError(
                "Unable to serialize the query result for temporary storage.",
                kind="serialization",
            ) from exc

        try:
            writer = self._begin_writer(
                sequence=sequence,
                columns=preview.columns,
                kind="preview_only",
                reason=reason,
                preview_payload_bytes=sum(len(payload) for payload in payloads),
                preview_has_more_rows=preview.has_more_rows,
                preview_truncation_reason=preview.truncation_reason,
            )
            try:
                for payload in payloads:
                    writer.append_payload(payload)
                return writer.commit(elapsed_ms=elapsed_ms)
            except TUIResultStorageError as exc:
                writer.rollback()
                if exc.kind == "capacity":
                    return None
                raise
            except BaseException:
                writer.rollback()
                raise
        except TUIResultStorageError as exc:
            if exc.kind == "capacity":
                return None
            raise

    def open_rows(self, handle: TUIResultHandle) -> ExportRowSource:
        """Open one complete registered result as a one-shot row source."""

        with self._lock:
            record = self._record_for_handle(handle)
            if record.stored.kind != "complete":
                raise _result_unavailable_error(handle.sequence)
            reader = self._open_record_reader(record)
            return _TUIResultRowSource(
                reader=reader,
                elapsed_ms=record.stored.elapsed_ms,
                sequence=handle.sequence,
                invalidate=lambda: self._invalidate_record(record),
            )

    def load_preview(
        self,
        handle: TUIResultHandle,
        policy: PreviewPolicy,
    ) -> BoundedQueryResult:
        """Stream a bounded historical preview from one registered artifact."""

        with self._lock:
            record = self._record_for_handle(handle)
            reader = self._open_record_reader(record)
        accumulator = PreviewAccumulator(
            columns=record.stored.columns,
            elapsed_ms=record.stored.elapsed_ms,
            policy=policy,
        )
        iterator = reader.iter_rows()
        try:
            for row in iterator:
                payload = encode_row_payload(row)
                if not accumulator.consider(row, payload):
                    break
        except Exception as exc:
            self._invalidate_record(record)
            raise _result_unavailable_error(handle.sequence) from exc
        finally:
            reader.close()
        result = accumulator.finish()
        if (
            record.stored.kind == "preview_only"
            and not result.has_more_rows
            and record.preview_has_more_rows
        ):
            return BoundedQueryResult(
                columns=result.columns,
                rows=result.rows,
                elapsed_ms=result.elapsed_ms,
                preview_payload_bytes=result.preview_payload_bytes,
                has_more_rows=True,
                truncation_reason=record.preview_truncation_reason,
            )
        return result

    def remove(self, handle: TUIResultHandle) -> None:
        """Remove one exact registered artifact and release only its capacity."""

        with self._lock:
            record = self._record_for_handle(handle)
            self._ensure_registered_workspace(handle.sequence)
            path_state = self._registered_path_state(record)
            if path_state != "matching":
                self._drop_record(record, release_bytes=True)
                raise _result_unavailable_error(handle.sequence)
            try:
                record.path.unlink()
            except FileNotFoundError as exc:
                self._drop_record(record, release_bytes=True)
                raise _result_unavailable_error(handle.sequence) from exc
            except OSError as exc:
                raise self._storage_error_from_os_error(exc) from exc
            release_bytes = True
            if record.staging_alias is not None and not self._remove_staging_file(
                record.staging_alias
            ):
                self._pending_cleanup_bytes[record.staging_alias] = record.stored.logical_bytes
                release_bytes = False
            self._drop_record(record, release_bytes=release_bytes)

    def cleanup(self) -> TUIResultCleanupSummary:
        """Remove exact registered artifacts and terminalize the result store."""

        with self._lock:
            if self._cleanup_attempted:
                return TUIResultCleanupSummary()
            if self._active_writer is not None:
                self._rollback_writer(self._active_writer)
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
            identity = self._workspace_identity
            if workspace is not None:
                if identity is not None and _is_owned_workspace(workspace, identity=identity):
                    cleanup_entries: dict[Path, tuple[int, int] | None] = {
                        path: self._pending_cleanup_identities.get(path)
                        for path in self._pending_cleanup_paths
                    }
                    for record in self._records_by_nonce.values():
                        cleanup_entries[record.path] = record.identity
                    for path, expected_identity in cleanup_entries.items():
                        path_removed, path_failed = _unlink_owned_workspace_entry(
                            workspace,
                            identity=identity,
                            path=path,
                            expected_identity=expected_identity,
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

                    if self._close_active_lease():
                        path_removed, path_failed = _unlink_owned_workspace_entry(
                            workspace,
                            identity=identity,
                            path=lease_path,
                        )
                        removed += path_removed
                        failed += path_failed
                    else:
                        failed += 1

                    path_removed, path_failed = _rmdir_owned_workspace(
                        workspace,
                        identity=identity,
                    )
                    workspace_removed += path_removed
                    workspace_failed += path_failed
                else:
                    workspace_failed += 1
                    if not self._close_active_lease():
                        failed += 1
            elif not self._close_active_lease():
                failed += 1

            self._records_by_nonce.clear()
            self._record_nonce_by_sequence.clear()
            self._issued_handles.clear()
            self._pending_cleanup_paths.clear()
            self._pending_cleanup_identities.clear()
            self._pending_cleanup_bytes.clear()
            self._pending_cleanup_workspaces.clear()
            self._workspace_path = None
            self._workspace_identity = None
            self._session_id = None
            self._allocated_bytes = 0
            self._cleanup_uncertainties = 0
            return TUIResultCleanupSummary(
                files_removed=removed,
                files_failed=failed,
                workspaces_removed=workspace_removed,
                workspaces_failed=workspace_failed,
            )

    def _begin_writer(
        self,
        *,
        sequence: int,
        columns: tuple[str, ...],
        kind: TUIResultKind,
        reason: TUIResultReason | None,
        preview_payload_bytes: int = 0,
        preview_has_more_rows: bool = False,
        preview_truncation_reason: TruncationReason | None = None,
    ) -> TUIResultWriter:
        with self._lock:
            self._require_available()
            if not _is_positive_sequence(sequence):
                raise ValueError("sequence must be a positive integer.")
            if not isinstance(columns, tuple) or not all(
                isinstance(column, str) for column in columns
            ):
                raise ValueError("columns must be an immutable tuple of strings.")
            if self._active_writer is not None:
                raise RuntimeError("A TUI result writer is already active.")
            if sequence in self._record_nonce_by_sequence:
                raise ValueError(f"result sequence {sequence} is already stored.")

            header_bytes = _spool_header_bytes(columns)
            initial_reserved_bytes = header_bytes + _SPOOL_FOOTER_BYTES
            capacity_reserved = False
            spool_writer: ResultSpoolWriter | None = None
            staging_path: Path | None = None
            try:
                workspace = self._workspace_for_new_writer()
                self._reserve_bytes(initial_reserved_bytes)
                capacity_reserved = True
                token = secrets.token_hex(8)
                prefix = "query" if kind == "complete" else "preview"
                staging_path = workspace / f".{prefix}-{sequence}-{token}.result.tmp"
                final_path = workspace / f"{prefix}-{sequence}.result"
                spool_writer = ResultSpoolWriter(
                    staging_path=staging_path,
                    final_path=final_path,
                    columns=columns,
                    workspace_identity=self._workspace_identity,
                )
                self._pending_cleanup_paths.add(staging_path)
                if spool_writer.staging_identity is not None:
                    self._pending_cleanup_identities[staging_path] = spool_writer.staging_identity
                _set_and_verify_posix_mode(staging_path, 0o600)
            except OSError as exc:
                if spool_writer is not None and staging_path is not None:
                    self._release_failed_begin(
                        spool_writer=spool_writer,
                        staging_path=staging_path,
                        reserved_bytes=initial_reserved_bytes,
                    )
                elif capacity_reserved:
                    self._allocated_bytes -= initial_reserved_bytes
                raise self._storage_error_from_os_error(exc) from exc
            except Exception as exc:
                if spool_writer is not None and staging_path is not None:
                    self._release_failed_begin(
                        spool_writer=spool_writer,
                        staging_path=staging_path,
                        reserved_bytes=initial_reserved_bytes,
                    )
                elif capacity_reserved:
                    self._allocated_bytes -= initial_reserved_bytes
                if isinstance(exc, TUIResultStorageError):
                    raise
                raise TUIResultStorageError(
                    "Unable to serialize the query result for temporary storage.",
                    kind="serialization",
                ) from exc

            assert spool_writer is not None
            assert staging_path is not None
            writer = TUIResultWriter(
                store=self,
                spool_writer=spool_writer,
                sequence=sequence,
                columns=columns,
                staging_path=staging_path,
                final_path=final_path,
                kind=kind,
                reason=reason,
                initial_reserved_bytes=initial_reserved_bytes,
                initial_written_bytes=header_bytes,
                preview_payload_bytes=preview_payload_bytes,
                preview_has_more_rows=preview_has_more_rows,
                preview_truncation_reason=preview_truncation_reason,
            )
            self._active_writer = writer
            return writer

    def _append_writer_payload(self, writer: TUIResultWriter, payload: bytes) -> None:
        with self._lock:
            self._require_active_writer(writer)
            if writer._failed:
                raise TUIResultStorageError(
                    "The result writer cannot continue after a storage failure.",
                    kind="result_unavailable",
                )
            if not isinstance(payload, bytes):
                raise TypeError("payload must be bytes.")
            additional_bytes = _SPOOL_FRAME_PREFIX_BYTES + len(payload)
            try:
                self._reserve_bytes(additional_bytes)
            except TUIResultStorageError:
                writer._failed = True
                raise
            writer._reserved_bytes += additional_bytes
            try:
                writer._spool_writer.append_payload(payload)
            except OSError as exc:
                writer._failed = True
                raise self._storage_error_from_os_error(exc) from exc
            except Exception as exc:
                writer._failed = True
                raise TUIResultStorageError(
                    "Unable to serialize the query result for temporary storage.",
                    kind="serialization",
                ) from exc
            writer._written_bytes += additional_bytes
            writer._rows_written += 1

    def _writer_progress(self, writer: TUIResultWriter) -> TUIResultStoreProgress:
        with self._lock:
            if writer._stored_result is not None:
                return TUIResultStoreProgress(
                    rows_written=writer._rows_written,
                    logical_bytes_written=writer._written_bytes,
                    remaining_capacity_bytes=self._capacity_bytes - self._allocated_bytes,
                )
            if writer._closed and self._active_writer is not writer:
                raise TUIResultStorageError(
                    "The result writer is no longer available.",
                    kind="result_unavailable",
                )
            return TUIResultStoreProgress(
                rows_written=writer._rows_written,
                logical_bytes_written=writer._written_bytes,
                remaining_capacity_bytes=self._capacity_bytes - self._allocated_bytes,
            )

    def _commit_writer(
        self,
        writer: TUIResultWriter,
        *,
        elapsed_ms: float,
    ) -> TUIStoredResult:
        with self._lock:
            if writer._stored_result is not None:
                return writer._stored_result
            self._require_active_writer(writer)
            if writer._failed:
                raise TUIResultStorageError(
                    "The result writer cannot commit after a storage failure.",
                    kind="result_unavailable",
                )
            if (
                writer._reserved_bytes - writer._written_bytes != _SPOOL_FOOTER_BYTES
                or self._allocated_bytes > self._capacity_bytes
            ):
                self._rollback_writer(writer)
                raise TUIResultStorageError(
                    "Unable to serialize the query result for temporary storage.",
                    kind="serialization",
                )
            try:
                nonce = self._new_handle_nonce()
            except BaseException:
                self._rollback_writer(writer)
                raise
            try:
                metadata = writer._spool_writer.commit()
            except OSError as exc:
                storage_error = self._storage_error_from_os_error(exc)
                self._rollback_writer(writer)
                if storage_error.kind == "workspace_unavailable":
                    self._abandon_lost_workspace()
                raise storage_error from exc
            except Exception as exc:
                self._rollback_writer(writer)
                raise TUIResultStorageError(
                    "Unable to serialize the query result for temporary storage.",
                    kind="serialization",
                ) from exc

            expected_logical_bytes = writer._reserved_bytes
            if (
                metadata.logical_bytes != expected_logical_bytes
                or metadata.row_count != writer._rows_written
                or metadata.columns != writer._columns
                or writer._spool_writer.staging_identity is None
            ):
                self._discard_unregistered_commit(writer)
                raise TUIResultStorageError(
                    "Unable to serialize the query result for temporary storage.",
                    kind="serialization",
                )

            if not writer._spool_writer.staging_cleanup_pending:
                self._pending_cleanup_paths.discard(writer._staging_path)
                self._pending_cleanup_identities.pop(writer._staging_path, None)
            handle = TUIResultHandle(
                sequence=writer._sequence,
                store_id=self._store_id,
                nonce=nonce,
            )
            stored = TUIStoredResult(
                handle=handle,
                kind=writer._kind,
                reason=writer._reason,
                columns=writer._columns,
                stored_row_count=writer._rows_written,
                elapsed_ms=elapsed_ms,
                logical_bytes=expected_logical_bytes,
            )
            record = _StoredResultRecord(
                stored=stored,
                path=writer._final_path,
                identity=writer._spool_writer.staging_identity,
                staging_alias=(
                    writer._staging_path if writer._spool_writer.staging_cleanup_pending else None
                ),
                preview_payload_bytes=writer._preview_payload_bytes,
                preview_has_more_rows=writer._preview_has_more_rows,
                preview_truncation_reason=writer._preview_truncation_reason,
            )
            self._records_by_nonce[nonce] = record
            self._record_nonce_by_sequence[writer._sequence] = nonce
            self._issued_handles[nonce] = handle
            self._active_writer = None
            writer._closed = True
            writer._written_bytes += _SPOOL_FOOTER_BYTES
            writer._stored_result = stored
            return stored

    def _rollback_writer(self, writer: TUIResultWriter) -> None:
        with self._lock:
            if writer._stored_result is not None or writer._closed:
                return
            if self._active_writer is not writer:
                writer._closed = True
                return
            cleanup_failed = False
            try:
                writer._spool_writer.rollback()
            except OSError:
                cleanup_failed = True
            staging_removed = self._remove_staging_file(writer._staging_path)
            if not staging_removed:
                cleanup_failed = True
                self._pending_cleanup_bytes[writer._staging_path] = writer._reserved_bytes
            else:
                self._allocated_bytes -= writer._reserved_bytes
            if cleanup_failed:
                self._cleanup_uncertainties += 1
            self._active_writer = None
            writer._closed = True

    def _reserve_bytes(self, amount: int) -> None:
        if self._allocated_bytes + amount > self._capacity_bytes:
            raise TUIResultStorageError(
                "Unable to store the query result because session result storage is full.",
                kind="capacity",
            )
        self._allocated_bytes += amount

    def _record_for_handle(self, handle: TUIResultHandle) -> _StoredResultRecord:
        if (
            type(handle) is not TUIResultHandle
            or not _is_positive_sequence(handle.sequence)
            or handle.store_id != self._store_id
            or self._issued_handles.get(handle.nonce) is not handle
        ):
            raise _result_unavailable_error(getattr(handle, "sequence", 0))
        record = self._records_by_nonce.get(handle.nonce)
        if (
            record is None
            or record.stored.handle is not handle
            or record.stored.handle.sequence != handle.sequence
        ):
            raise _result_unavailable_error(handle.sequence)
        return record

    def _open_record_reader(self, record: _StoredResultRecord) -> ResultSpoolReader:
        sequence = record.stored.handle.sequence
        self._ensure_registered_workspace(sequence)
        try:
            pre_stat = record.path.lstat()
            if not self._stat_matches_record(pre_stat, record):
                raise FileNotFoundError(record.path)
            file = record.path.open("rb")
            try:
                opened_stat = os.fstat(file.fileno())
                if not self._stat_matches_record(opened_stat, record) or not _same_opened_file(
                    pre_stat, opened_stat
                ):
                    raise FileNotFoundError(record.path)
                self._ensure_workspace()
                reader = ResultSpoolReader.from_file(file)
            except BaseException:
                file.close()
                raise
        except TUIResultStorageError:
            raise
        except (OSError, ResultSpoolError, Exception) as exc:
            self._invalidate_record(record)
            raise _result_unavailable_error(sequence) from exc
        if reader.columns != record.stored.columns:
            reader.close()
            self._invalidate_record(record)
            raise _result_unavailable_error(sequence)
        return reader

    def _ensure_registered_workspace(self, sequence: int) -> None:
        try:
            self._ensure_workspace()
        except TUIResultStorageError as exc:
            invalidated = self._abandon_lost_workspace()
            raise _results_unavailable_error(invalidated or (sequence,)) from exc

    def _invalidate_record(self, record: _StoredResultRecord) -> None:
        with self._lock:
            nonce = record.stored.handle.nonce
            if self._records_by_nonce.get(nonce) is not record:
                return
            state = self._registered_path_state(record)
            released = state != "matching"
            if state == "matching":
                try:
                    record.path.unlink()
                except FileNotFoundError:
                    released = True
                except OSError:
                    self._pending_cleanup_paths.add(record.path)
                    self._pending_cleanup_identities[record.path] = record.identity
                    self._pending_cleanup_bytes[record.path] = record.stored.logical_bytes
                else:
                    released = True
            if record.staging_alias is not None and not self._remove_staging_file(
                record.staging_alias
            ):
                self._pending_cleanup_bytes[record.staging_alias] = record.stored.logical_bytes
                released = False
            self._drop_record(record, release_bytes=released)

    def _drop_record(self, record: _StoredResultRecord, *, release_bytes: bool) -> None:
        handle = record.stored.handle
        self._records_by_nonce.pop(handle.nonce, None)
        if self._record_nonce_by_sequence.get(handle.sequence) == handle.nonce:
            self._record_nonce_by_sequence.pop(handle.sequence, None)
        self._issued_handles.pop(handle.nonce, None)
        self._invalidated_sequences.add(handle.sequence)
        if release_bytes:
            self._allocated_bytes = max(
                0,
                self._allocated_bytes - record.stored.logical_bytes,
            )

    def _registered_path_state(self, record: _StoredResultRecord) -> _RecoveryMatchState:
        try:
            result = record.path.lstat()
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "uncertain"
        return "matching" if self._stat_matches_record(result, record) else "uncertain"

    @staticmethod
    def _stat_matches_record(
        result: os.stat_result,
        record: _StoredResultRecord,
    ) -> bool:
        return (
            stat.S_ISREG(result.st_mode)
            and not _is_reparse_point(result)
            and _file_mode_is_private(result)
            and _stat_has_current_owner(result)
            and _usable_stat_identity(result) == record.identity
            and result.st_size == record.stored.logical_bytes
        )

    def _require_available(self) -> None:
        if self._cleanup_attempted:
            raise TUIResultStorageError(
                "Result storage is no longer available.",
                kind="result_unavailable",
            )

    def _require_active_writer(self, writer: TUIResultWriter) -> None:
        self._require_available()
        if self._active_writer is not writer or writer._closed:
            raise TUIResultStorageError(
                "The result writer is no longer available.",
                kind="result_unavailable",
            )

    def _workspace_for_new_writer(self) -> Path:
        if self._workspace_path is None:
            return self._create_workspace()
        try:
            return self._ensure_workspace()
        except TUIResultStorageError:
            self._abandon_lost_workspace()
            return self._create_workspace()

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
                if isinstance(exc, TUIResultStorageError):
                    raise
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
            return temp_root.resolve(strict=True)
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
                *(record.path.name for record in self._records_by_nonce.values()),
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
        invalidated = tuple(
            sorted(record.stored.handle.sequence for record in self._records_by_nonce.values())
        )
        self._invalidated_sequences.update(invalidated)
        active = self._active_writer
        if active is not None:
            try:
                active._spool_writer.rollback()
            except OSError:
                pass
            active._closed = True
        self._active_writer = None
        self._records_by_nonce.clear()
        self._record_nonce_by_sequence.clear()
        self._issued_handles.clear()
        self._pending_cleanup_paths.clear()
        self._pending_cleanup_identities.clear()
        self._pending_cleanup_bytes.clear()
        self._allocated_bytes = 0
        self._workspace_path = None
        self._workspace_identity = None
        self._session_id = None
        if not self._close_active_lease():
            self._cleanup_uncertainties += 1
        return invalidated

    def _discard_unregistered_commit(self, writer: TUIResultWriter) -> None:
        identity = writer._spool_writer.staging_identity
        workspace = self._workspace_path
        workspace_identity = self._workspace_identity
        final_failed = 1
        if workspace is not None and workspace_identity is not None:
            _, final_failed = _unlink_owned_workspace_entry(
                workspace,
                identity=workspace_identity,
                path=writer._final_path,
                expected_identity=identity,
            )
        staging_removed = self._remove_staging_file(writer._staging_path)
        if final_failed:
            self._pending_cleanup_paths.add(writer._final_path)
            if identity is not None:
                self._pending_cleanup_identities[writer._final_path] = identity
            self._pending_cleanup_bytes[writer._final_path] = writer._reserved_bytes
            self._cleanup_uncertainties += 1
        elif not staging_removed:
            self._pending_cleanup_bytes[writer._staging_path] = writer._reserved_bytes
            self._cleanup_uncertainties += 1
        else:
            self._allocated_bytes = max(
                0,
                self._allocated_bytes - writer._reserved_bytes,
            )
        self._active_writer = None
        writer._closed = True

    def _release_failed_begin(
        self,
        *,
        spool_writer: ResultSpoolWriter,
        staging_path: Path,
        reserved_bytes: int,
    ) -> None:
        cleanup_failed = False
        try:
            spool_writer.rollback()
        except OSError:
            cleanup_failed = True
        if not self._remove_staging_file(staging_path):
            cleanup_failed = True
            self._pending_cleanup_bytes[staging_path] = reserved_bytes
        else:
            self._allocated_bytes = max(0, self._allocated_bytes - reserved_bytes)
        if cleanup_failed:
            self._cleanup_uncertainties += 1

    def _new_handle_nonce(self) -> str:
        for _attempt in range(10):
            nonce = secrets.token_hex(16)
            if (
                re.fullmatch(r"[0-9a-f]{32}", nonce) is not None
                and nonce not in self._issued_handles
            ):
                return nonce
        raise TUIResultStorageError(
            "Unable to create a secure result handle.",
            kind="io",
        )

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

    def _remove_staging_file(self, staging_path: Path) -> bool:
        if staging_path not in self._pending_cleanup_paths:
            return True
        workspace = self._workspace_path
        identity = self._workspace_identity
        if workspace is None or identity is None:
            return False
        expected_identity = self._pending_cleanup_identities.get(staging_path)
        _, failed = _unlink_owned_workspace_entry(
            workspace,
            identity=identity,
            path=staging_path,
            expected_identity=expected_identity,
        )
        if failed:
            return False
        self._pending_cleanup_paths.discard(staging_path)
        self._pending_cleanup_identities.pop(staging_path, None)
        pending_bytes = self._pending_cleanup_bytes.pop(staging_path, 0)
        if pending_bytes:
            self._allocated_bytes = max(0, self._allocated_bytes - pending_bytes)
        return True

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
    expected_identity: tuple[int, int] | None = None,
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
    if expected_identity is not None and _usable_stat_identity(result) != expected_identity:
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
            current_user_root = current_user_root.resolve(strict=True)
            if not root.is_relative_to(current_user_root):
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


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _spool_header_bytes(columns: tuple[str, ...]) -> int:
    schema_bytes = _SPOOL_LENGTH_BYTES + sum(
        _SPOOL_LENGTH_BYTES + len(column.encode("utf-8")) for column in columns
    )
    return _SPOOL_HEADER_PREFIX_BYTES + schema_bytes
