"""Private framed result spool for LocalQL-managed TUI storage."""

from __future__ import annotations

import errno
import os
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from csvql.result_codec import RowPayloadCodecError, decode_row_payload

SPOOL_MAGIC = b"LQLRS"
SPOOL_VERSION = 1
ROW_FRAME = 1
FOOTER_FRAME = 2

_HEADER = struct.Struct(">5sBQ")
_FRAME = struct.Struct(">BQ")
_FOOTER = struct.Struct(">BQ")
_COUNT = struct.Struct(">Q")


class ResultSpoolError(ValueError):
    """Raised when a framed result spool cannot be validated safely."""


@dataclass(frozen=True, slots=True)
class ResultSpoolMetadata:
    columns: tuple[str, ...]
    row_count: int
    logical_bytes: int


class ResultSpoolReader:
    """Read a validated framed result spool from a registered regular file."""

    def __init__(
        self,
        file: BinaryIO,
        *,
        columns: tuple[str, ...],
        data_offset: int,
        logical_bytes: int,
    ) -> None:
        self._file = file
        self._columns = columns
        self._data_offset = data_offset
        self._logical_bytes = logical_bytes
        self._closed = False

    @classmethod
    def from_file(cls, file: BinaryIO) -> ResultSpoolReader:
        logical_bytes = os.fstat(file.fileno()).st_size
        header = _read_exact(file, _HEADER.size, "truncated header")
        magic, version, schema_length = _HEADER.unpack(header)
        if magic != SPOOL_MAGIC:
            raise ResultSpoolError("unsupported spool magic")
        if version != SPOOL_VERSION:
            raise ResultSpoolError("unsupported spool version")
        remaining = logical_bytes - file.tell()
        if schema_length > remaining - _FOOTER.size:
            raise ResultSpoolError("invalid schema length")
        schema = _read_exact(file, schema_length, "truncated schema metadata")
        columns = _decode_schema(schema)
        return cls(
            file,
            columns=columns,
            data_offset=file.tell(),
            logical_bytes=logical_bytes,
        )

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._file.close()

    def iter_rows(self) -> Iterator[tuple[object, ...]]:
        if self._closed:
            raise ResultSpoolError("spool reader is closed")
        self._file.seek(self._data_offset)
        row_count = 0
        while True:
            if self._logical_bytes - self._file.tell() < _FOOTER.size:
                raise ResultSpoolError("truncated footer")
            frame_type = _read_exact(self._file, 1, "truncated frame type")[0]
            if frame_type == FOOTER_FRAME:
                footer_row_count = _COUNT.unpack(
                    _read_exact(self._file, _COUNT.size, "truncated footer")
                )[0]
                if self._file.tell() != self._logical_bytes:
                    raise ResultSpoolError("trailing bytes")
                if footer_row_count != row_count:
                    raise ResultSpoolError("footer row count mismatch")
                return
            if frame_type != ROW_FRAME:
                raise ResultSpoolError("unsupported frame type")
            payload_length = _COUNT.unpack(
                _read_exact(self._file, _COUNT.size, "truncated row frame")
            )[0]
            remaining = self._logical_bytes - self._file.tell()
            if payload_length > remaining - _FOOTER.size:
                raise ResultSpoolError("invalid row frame length")
            payload = _read_exact(self._file, payload_length, "truncated row payload")
            if self._logical_bytes - self._file.tell() < _FOOTER.size:
                raise ResultSpoolError("truncated footer")
            try:
                row = decode_row_payload(payload)
            except RowPayloadCodecError as exc:
                raise ResultSpoolError("malformed row payload") from exc
            if len(row) != len(self._columns):
                raise ResultSpoolError("malformed row payload")
            row_count += 1
            yield row


class ResultSpoolWriter:
    """Write a framed result spool to an exclusive staging file."""

    def __init__(
        self,
        *,
        staging_path: Path,
        final_path: Path,
        columns: tuple[str, ...],
        workspace_identity: tuple[int, int] | None = None,
    ) -> None:
        self._staging_path = staging_path
        self._final_path = final_path
        self._columns = columns
        self._workspace_identity = workspace_identity
        self._row_count = 0
        self._logical_bytes = 0
        self._committed = False
        self._closed = False
        self._owns_staging = False
        self._staging_identity: tuple[int, int] | None = None
        self._cleanup_pending = False
        self._file: BinaryIO | None = None
        try:
            staging_fd = os.open(staging_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self._file = os.fdopen(staging_fd, "wb")
            if os.name != "nt":
                os.fchmod(self._file.fileno(), 0o600)
            self._owns_staging = True
            self._staging_identity = _stat_identity(os.fstat(self._file.fileno()))
            if self._workspace_identity is not None and self._staging_identity is None:
                raise OSError(errno.ENOENT, "Temporary result storage disappeared before commit.")
            self._write_header()
        except Exception:
            self.rollback()
            raise

    def append_payload(self, payload: bytes) -> None:
        if self._committed or self._closed or self._file is None:
            raise ResultSpoolError("spool writer is closed")
        self._file.write(_FRAME.pack(ROW_FRAME, len(payload)))
        self._file.write(payload)
        self._row_count += 1

    def commit(self) -> ResultSpoolMetadata:
        if self._committed:
            return ResultSpoolMetadata(
                columns=self._columns,
                row_count=self._row_count,
                logical_bytes=self._logical_bytes,
            )
        if self._closed or self._file is None:
            raise ResultSpoolError("spool writer is closed")
        self._assert_active_workspace()
        try:
            self._file.write(_FOOTER.pack(FOOTER_FRAME, self._row_count))
            self._file.flush()
            os.fsync(self._file.fileno())
            self._logical_bytes = os.fstat(self._file.fileno()).st_size
            self._file.close()
            self._closed = True
            self._assert_active_workspace()
            self._assert_original_staging_path()
            self._publish_staging_file()
        except Exception:
            self.rollback()
            raise
        self._committed = True
        return ResultSpoolMetadata(
            columns=self._columns,
            row_count=self._row_count,
            logical_bytes=self._logical_bytes,
        )

    @property
    def staging_identity(self) -> tuple[int, int] | None:
        return self._staging_identity

    @property
    def staging_cleanup_pending(self) -> bool:
        return self._cleanup_pending

    def rollback(self) -> None:
        if self._committed:
            return
        if not self._closed and self._file is not None:
            try:
                self._file.close()
            finally:
                self._closed = True
        if not self._owns_staging:
            return
        if not self._path_matches_original(self._staging_path, self._staging_identity):
            return
        try:
            self._staging_path.unlink()
        except FileNotFoundError:
            pass

    def _write_header(self) -> None:
        if self._file is None:
            raise ResultSpoolError("spool writer is closed")
        self._assert_active_workspace()
        schema = _encode_schema(self._columns)
        self._file.write(_HEADER.pack(SPOOL_MAGIC, SPOOL_VERSION, len(schema)))
        self._file.write(schema)

    def _assert_active_workspace(self) -> None:
        if self._workspace_identity is None:
            return
        if not self._path_matches_original(self._staging_path.parent, self._workspace_identity):
            raise OSError(errno.ENOENT, "Temporary result storage disappeared before commit.")
        if not self._path_matches_original(self._final_path.parent, self._workspace_identity):
            raise OSError(errno.ENOENT, "Temporary result storage disappeared before commit.")

    def _assert_original_staging_path(self) -> None:
        if not self._path_matches_original(self._staging_path, self._staging_identity):
            raise OSError(errno.ENOENT, "Temporary result storage disappeared before commit.")

    def _publish_staging_file(self) -> None:
        if os.link in os.supports_follow_symlinks:
            os.link(self._staging_path, self._final_path, follow_symlinks=False)
        else:
            os.link(self._staging_path, self._final_path)
        if not self._path_matches_original(self._final_path, self._staging_identity):
            raise OSError(errno.EIO, "Temporary result storage committed with unexpected identity.")
        if not self._path_matches_original(self._staging_path, self._staging_identity):
            self._cleanup_pending = True
            return
        try:
            self._staging_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            self._cleanup_pending = True

    @staticmethod
    def _path_matches_original(
        path: Path,
        expected_identity: tuple[int, int] | None,
    ) -> bool:
        if expected_identity is None:
            return True
        try:
            result = path.lstat()
        except OSError:
            return False
        return _stat_identity(result) == expected_identity


def _encode_schema(columns: tuple[str, ...]) -> bytes:
    pieces = bytearray()
    pieces.extend(_COUNT.pack(len(columns)))
    for column in columns:
        encoded = column.encode("utf-8")
        pieces.extend(_COUNT.pack(len(encoded)))
        pieces.extend(encoded)
    return bytes(pieces)


def _decode_schema(schema: bytes) -> tuple[str, ...]:
    offset = 0
    if len(schema) < _COUNT.size:
        raise ResultSpoolError("truncated schema metadata")
    column_count = _COUNT.unpack_from(schema, offset)[0]
    offset += _COUNT.size
    columns: list[str] = []
    for _index in range(column_count):
        if len(schema) - offset < _COUNT.size:
            raise ResultSpoolError("truncated schema metadata")
        name_length = _COUNT.unpack_from(schema, offset)[0]
        offset += _COUNT.size
        if len(schema) - offset < name_length:
            raise ResultSpoolError("truncated schema metadata")
        try:
            name = schema[offset : offset + name_length].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResultSpoolError("malformed schema metadata") from exc
        offset += name_length
        columns.append(name)
    if offset != len(schema):
        raise ResultSpoolError("malformed schema metadata")
    return tuple(columns)


def _read_exact(file: BinaryIO, size: int, message: str) -> bytes:
    payload = file.read(size)
    if len(payload) != size:
        raise ResultSpoolError(message)
    return payload


def _stat_identity(result: os.stat_result) -> tuple[int, int] | None:
    device = getattr(result, "st_dev", None)
    inode = getattr(result, "st_ino", None)
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
