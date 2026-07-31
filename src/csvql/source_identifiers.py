"""Bounded, dependency-light source identification evidence."""

from __future__ import annotations

import csv
import io
import json
import struct
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Protocol, runtime_checkable

from csvql.exceptions import ConfigurationFailure, ConfigurationFinding
from csvql.operation import OperationContext

MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class IdentificationLimits:
    """Product bounds shared by all identifiers in one detection operation."""

    per_identifier_bytes: int = MIB
    aggregate_bytes: int = 4 * MIB
    container_entries: int = 4_096

    def __post_init__(self) -> None:
        if (
            self.per_identifier_bytes <= 0
            or self.aggregate_bytes <= 0
            or self.container_entries <= 0
        ):
            raise ValueError("Identification limits must be positive.")


class IdentificationBudgetExceeded(Exception):
    """Raised before a bounded identifier would exceed an approved limit."""


class IdentificationStatus(StrEnum):
    """Evidence status returned by one source identifier."""

    RECOGNIZED = "recognized"
    NOT_RECOGNIZED = "not_recognized"
    INDETERMINATE = "indeterminate"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID_LOCATOR = "invalid_locator"


@dataclass(frozen=True, slots=True)
class IdentificationEvidence:
    """Sanitized evidence from one bounded identifier."""

    provider_key: str
    status: IdentificationStatus
    evidence_kind: str
    stable_detail: str
    bytes_read: int
    container_entries: int = 0
    cause_classification: str | None = None


class AggregateIdentificationBudget:
    """One non-resettable byte and entry budget for a detection operation."""

    def __init__(
        self,
        limits: IdentificationLimits | None = None,
        *,
        operation: OperationContext | None = None,
    ) -> None:
        self.limits = limits or IdentificationLimits()
        self.operation = operation
        self._bytes_read = 0
        self._bytes_by_provider: dict[str, int] = {}
        self._container_entries = 0

    @property
    def bytes_read(self) -> int:
        """Return aggregate bytes physically returned by bounded readers."""

        return self._bytes_read

    @property
    def container_entries(self) -> int:
        """Return aggregate container entries inspected."""

        return self._container_entries

    def bytes_read_for(self, provider_key: str) -> int:
        """Return bytes consumed by one provider across every requested scope."""

        return self._bytes_by_provider.get(provider_key, 0)

    def for_identifier(self, provider_key: str) -> IdentifierBudget:
        """Return a view whose usage remains attached to this aggregate."""

        return IdentifierBudget(self, provider_key)

    def _checkpoint(self) -> None:
        if self.operation is not None:
            self.operation.checkpoint()

    def _remaining_for(self, provider_key: str) -> int:
        provider_remaining = self.limits.per_identifier_bytes - self.bytes_read_for(provider_key)
        aggregate_remaining = self.limits.aggregate_bytes - self._bytes_read
        return max(0, min(provider_remaining, aggregate_remaining))

    def _require_bytes(self, provider_key: str, size: int) -> None:
        if size < 0:
            raise ValueError("Bounded reads require an explicit non-negative size.")
        if size > self._remaining_for(provider_key):
            raise IdentificationBudgetExceeded("Identification byte budget exhausted.")

    def _record_bytes(self, provider_key: str, size: int) -> None:
        self._bytes_read += size
        self._bytes_by_provider[provider_key] = self.bytes_read_for(provider_key) + size

    def _record_container_entries(self, count: int) -> None:
        if count < 0:
            raise ValueError("Container entry count must be non-negative.")
        if self._container_entries + count > self.limits.container_entries:
            raise IdentificationBudgetExceeded("Identification container-entry budget exhausted.")
        self._container_entries += count


class IdentifierBudget:
    """Provider-scoped access to one shared aggregate budget."""

    def __init__(self, aggregate: AggregateIdentificationBudget, provider_key: str) -> None:
        self._aggregate = aggregate
        self.provider_key = provider_key

    @property
    def bytes_read(self) -> int:
        """Return cumulative bytes consumed by this provider."""

        return self._aggregate.bytes_read_for(self.provider_key)

    @property
    def remaining_bytes(self) -> int:
        """Return the smaller remaining per-provider and aggregate byte allowance."""

        return self._aggregate._remaining_for(self.provider_key)

    def open(self, path: Path) -> BudgetedBinaryReader:
        """Create a context-managed reader charged to this provider."""

        return BudgetedBinaryReader(path, self)

    def consume_container_entries(self, count: int) -> None:
        """Charge inspected container entries to the aggregate."""

        self._aggregate._record_container_entries(count)

    def checkpoint(self) -> None:
        """Propagate operation cancellation at every I/O checkpoint."""

        self._aggregate._checkpoint()

    def _require_bytes(self, size: int) -> None:
        self._aggregate._require_bytes(self.provider_key, size)

    def _record_bytes(self, size: int) -> None:
        self._aggregate._record_bytes(self.provider_key, size)


class BudgetedBinaryReader:
    """Binary file reader that accounts every returned byte and always closes."""

    def __init__(self, path: Path, budget: IdentifierBudget) -> None:
        self._path = path
        self._budget = budget
        self._handle: BinaryIO | None = None

    def __enter__(self) -> BudgetedBinaryReader:
        self._budget.checkpoint()
        self._handle = self._path.open("rb")
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @property
    def _file(self) -> BinaryIO:
        if self._handle is None:
            raise RuntimeError("Budgeted reader is not open.")
        return self._handle

    @property
    def file_size(self) -> int:
        """Return stream length without reading source bytes."""

        self._budget.checkpoint()
        current = self._file.tell()
        self._file.seek(0, io.SEEK_END)
        size = self._file.tell()
        self._file.seek(current)
        return size

    def read(self, size: int) -> bytes:
        """Read at most size bytes after proving the request fits the budget."""

        self._budget.checkpoint()
        self._budget._require_bytes(size)
        content = self._file.read(size)
        self._budget._record_bytes(len(content))
        self._budget.checkpoint()
        return content

    def read_at(self, offset: int, size: int) -> bytes:
        """Seek to an absolute byte offset and perform one accounted read."""

        if offset < 0:
            raise ValueError("Read offset must be non-negative.")
        self._budget.checkpoint()
        self._file.seek(offset)
        return self.read(size)

    def read_tail(self, size: int) -> tuple[int, bytes]:
        """Read an accounted suffix and return its absolute starting offset."""

        file_size = self.file_size
        start = max(0, file_size - size)
        return start, self.read_at(start, file_size - start)


@runtime_checkable
class SourceIdentifier(Protocol):
    """Dependency-light behavioral contract for evidence-only identification."""

    provider_key: str
    identifier_key: str

    def identify(
        self,
        locator: Path,
        budget: IdentifierBudget,
    ) -> IdentificationEvidence: ...


def _evidence(
    *,
    provider_key: str,
    status: IdentificationStatus,
    evidence_kind: str,
    stable_detail: str,
    budget: IdentifierBudget,
    starting_bytes: int,
    container_entries: int = 0,
    cause_classification: str | None = None,
) -> IdentificationEvidence:
    return IdentificationEvidence(
        provider_key=provider_key,
        status=status,
        evidence_kind=evidence_kind,
        stable_detail=stable_detail,
        bytes_read=budget.bytes_read - starting_bytes,
        container_entries=container_entries,
        cause_classification=cause_classification,
    )


def _invalid_locator(
    provider_key: str,
    budget: IdentifierBudget,
    starting_bytes: int,
) -> IdentificationEvidence:
    return _evidence(
        provider_key=provider_key,
        status=IdentificationStatus.INVALID_LOCATOR,
        evidence_kind="locator_shape",
        stable_detail="regular_file_required",
        budget=budget,
        starting_bytes=starting_bytes,
    )


class ParquetSourceIdentifier:
    """Recognize matching leading and trailing Parquet magic."""

    provider_key = "parquet"
    identifier_key = "parquet.magic"

    def identify(
        self,
        locator: Path,
        budget: IdentifierBudget,
    ) -> IdentificationEvidence:
        starting_bytes = budget.bytes_read
        if not locator.is_file():
            return _invalid_locator(self.provider_key, budget, starting_bytes)
        try:
            with budget.open(locator) as reader:
                leading = reader.read(4)
                if reader.file_size < 8:
                    return _evidence(
                        provider_key=self.provider_key,
                        status=IdentificationStatus.NOT_RECOGNIZED,
                        evidence_kind="parquet_magic",
                        stable_detail="file_too_short",
                        budget=budget,
                        starting_bytes=starting_bytes,
                    )
                _tail_offset, trailing = reader.read_tail(4)
        except IdentificationBudgetExceeded:
            return _evidence(
                provider_key=self.provider_key,
                status=IdentificationStatus.BUDGET_EXHAUSTED,
                evidence_kind="parquet_magic",
                stable_detail="byte_budget_exhausted",
                budget=budget,
                starting_bytes=starting_bytes,
            )
        except OSError:
            return _io_indeterminate(self.provider_key, budget, starting_bytes, "parquet_magic")
        recognized = leading == b"PAR1" and trailing == b"PAR1"
        return _evidence(
            provider_key=self.provider_key,
            status=(
                IdentificationStatus.RECOGNIZED
                if recognized
                else IdentificationStatus.NOT_RECOGNIZED
            ),
            evidence_kind="parquet_magic",
            stable_detail="leading_and_trailing_magic" if recognized else "magic_mismatch",
            budget=budget,
            starting_bytes=starting_bytes,
        )


class ExcelSourceIdentifier:
    """Recognize XLSX using ZIP signatures and bounded central-directory names."""

    provider_key = "excel"
    identifier_key = "excel.xlsx_container"

    def identify(
        self,
        locator: Path,
        budget: IdentifierBudget,
    ) -> IdentificationEvidence:
        starting_bytes = budget.bytes_read
        starting_entries = 0
        if not locator.is_file():
            return _invalid_locator(self.provider_key, budget, starting_bytes)
        try:
            with budget.open(locator) as reader:
                leading = reader.read(4)
                if leading != b"PK\x03\x04":
                    return _evidence(
                        provider_key=self.provider_key,
                        status=IdentificationStatus.NOT_RECOGNIZED,
                        evidence_kind="xlsx_container",
                        stable_detail="zip_signature_missing",
                        budget=budget,
                        starting_bytes=starting_bytes,
                    )
                if budget.remaining_bytes == 0:
                    raise IdentificationBudgetExceeded
                tail_offset, tail = reader.read_tail(budget.remaining_bytes)
                names, entry_count = _zip_central_directory_names(
                    reader,
                    tail_offset=tail_offset,
                    tail=tail,
                    budget=budget,
                )
                starting_entries = entry_count
        except IdentificationBudgetExceeded:
            return _evidence(
                provider_key=self.provider_key,
                status=IdentificationStatus.BUDGET_EXHAUSTED,
                evidence_kind="xlsx_container",
                stable_detail="container_budget_exhausted",
                budget=budget,
                starting_bytes=starting_bytes,
                container_entries=starting_entries,
            )
        except (OSError, struct.error, UnicodeDecodeError):
            return _io_indeterminate(self.provider_key, budget, starting_bytes, "xlsx_container")
        required_names = {"[Content_Types].xml", "xl/workbook.xml"}
        recognized = required_names.issubset(names)
        return _evidence(
            provider_key=self.provider_key,
            status=(
                IdentificationStatus.RECOGNIZED
                if recognized
                else IdentificationStatus.NOT_RECOGNIZED
            ),
            evidence_kind="xlsx_container",
            stable_detail="workbook_metadata" if recognized else "workbook_metadata_missing",
            budget=budget,
            starting_bytes=starting_bytes,
            container_entries=entry_count,
        )


def _zip_central_directory_names(
    reader: BudgetedBinaryReader,
    *,
    tail_offset: int,
    tail: bytes,
    budget: IdentifierBudget,
) -> tuple[set[str], int]:
    end_index = tail.rfind(b"PK\x05\x06")
    if end_index < 0 or len(tail) - end_index < 22:
        raise struct.error("ZIP end-of-central-directory record not found.")
    (
        _signature,
        disk_number,
        central_disk,
        entries_on_disk,
        entry_count,
        central_size,
        central_offset,
        _comment_length,
    ) = struct.unpack_from("<4s4H2LH", tail, end_index)
    if disk_number != 0 or central_disk != 0 or entries_on_disk != entry_count:
        raise struct.error("Multi-disk ZIP containers are not supported.")
    budget.consume_container_entries(entry_count)
    central_end = central_offset + central_size
    tail_end = tail_offset + len(tail)
    if central_offset >= tail_offset and central_end <= tail_end:
        central = tail[central_offset - tail_offset : central_end - tail_offset]
    else:
        central = reader.read_at(central_offset, central_size)

    names: set[str] = set()
    position = 0
    for _entry in range(entry_count):
        if central[position : position + 4] != b"PK\x01\x02":
            raise struct.error("Malformed ZIP central-directory entry.")
        filename_length, extra_length, comment_length = struct.unpack_from(
            "<HHH",
            central,
            position + 28,
        )
        name_start = position + 46
        name_end = name_start + filename_length
        names.add(central[name_start:name_end].decode("utf-8"))
        position = name_end + extra_length + comment_length
    return names, entry_count


class JSONSourceIdentifier:
    """Recognize a complete bounded JSON object or array document."""

    provider_key = "json"
    identifier_key = "json.document"

    def identify(
        self,
        locator: Path,
        budget: IdentifierBudget,
    ) -> IdentificationEvidence:
        return _identify_text(
            self.provider_key,
            "json_document",
            locator,
            budget,
            _recognize_json,
        )


class NDJSONSourceIdentifier:
    """Recognize bounded newline-delimited JSON object records."""

    provider_key = "ndjson"
    identifier_key = "ndjson.records"

    def identify(
        self,
        locator: Path,
        budget: IdentifierBudget,
    ) -> IdentificationEvidence:
        return _identify_text(
            self.provider_key,
            "ndjson_records",
            locator,
            budget,
            _recognize_ndjson,
        )


class CSVSourceIdentifier:
    """Recognize a bounded, consistent delimited record shape."""

    provider_key = "csv"
    identifier_key = "csv.record_shape"

    def identify(
        self,
        locator: Path,
        budget: IdentifierBudget,
    ) -> IdentificationEvidence:
        return _identify_text(
            self.provider_key,
            "csv_record_shape",
            locator,
            budget,
            _recognize_csv,
        )


class TextRecognizer(Protocol):
    """Callable contract for one bounded text recognizer."""

    def __call__(
        self,
        text: str,
        incomplete: bool,
    ) -> tuple[IdentificationStatus, str]: ...


def _identify_text(
    provider_key: str,
    evidence_kind: str,
    locator: Path,
    budget: IdentifierBudget,
    recognizer: TextRecognizer,
) -> IdentificationEvidence:
    starting_bytes = budget.bytes_read
    if not locator.is_file():
        return _invalid_locator(provider_key, budget, starting_bytes)
    try:
        with budget.open(locator) as reader:
            file_size = reader.file_size
            read_size = min(file_size, budget.remaining_bytes)
            if read_size == 0 and file_size:
                raise IdentificationBudgetExceeded
            content = reader.read(read_size)
        incomplete = file_size > len(content)
        text = content.decode("utf-8-sig")
        status, detail = recognizer(text, incomplete)
    except IdentificationBudgetExceeded:
        return _evidence(
            provider_key=provider_key,
            status=IdentificationStatus.BUDGET_EXHAUSTED,
            evidence_kind=evidence_kind,
            stable_detail="byte_budget_exhausted",
            budget=budget,
            starting_bytes=starting_bytes,
        )
    except UnicodeDecodeError:
        status = IdentificationStatus.NOT_RECOGNIZED
        detail = "invalid_utf8"
    except OSError:
        return _io_indeterminate(provider_key, budget, starting_bytes, evidence_kind)
    return _evidence(
        provider_key=provider_key,
        status=status,
        evidence_kind=evidence_kind,
        stable_detail=detail,
        budget=budget,
        starting_bytes=starting_bytes,
    )


def _recognize_json(text: str, incomplete: bool) -> tuple[IdentificationStatus, str]:
    stripped = text.strip()
    if not stripped:
        return IdentificationStatus.NOT_RECOGNIZED, "empty"
    if incomplete:
        if stripped[0] in "[{":
            return IdentificationStatus.INDETERMINATE, "bounded_prefix"
        return IdentificationStatus.NOT_RECOGNIZED, "top_level_shape_mismatch"
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return IdentificationStatus.NOT_RECOGNIZED, "parse_mismatch"
    if not isinstance(value, (dict, list)):
        return IdentificationStatus.NOT_RECOGNIZED, "top_level_shape_mismatch"
    return IdentificationStatus.RECOGNIZED, "complete_object_or_array"


def _recognize_ndjson(text: str, incomplete: bool) -> tuple[IdentificationStatus, str]:
    lines = text.splitlines()
    if incomplete and text and not text.endswith(("\n", "\r")):
        lines = lines[:-1]
    records = [line for line in lines if line.strip()]
    if not records:
        return (
            (IdentificationStatus.INDETERMINATE, "bounded_prefix")
            if incomplete
            else (IdentificationStatus.NOT_RECOGNIZED, "empty")
        )
    try:
        values = [json.loads(line) for line in records]
    except json.JSONDecodeError:
        return IdentificationStatus.NOT_RECOGNIZED, "line_parse_mismatch"
    if not all(isinstance(value, dict) for value in values):
        return IdentificationStatus.NOT_RECOGNIZED, "record_shape_mismatch"
    return IdentificationStatus.RECOGNIZED, "object_records"


def _recognize_csv(text: str, incomplete: bool) -> tuple[IdentificationStatus, str]:
    if not text.strip():
        return IdentificationStatus.NOT_RECOGNIZED, "empty"
    try:
        dialect = csv.Sniffer().sniff(text, delimiters=",\t;|")
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        return IdentificationStatus.NOT_RECOGNIZED, "dialect_mismatch"
    if incomplete and rows:
        rows = rows[:-1]
    nonempty = [row for row in rows if row]
    if len(nonempty) < 2:
        return (
            (IdentificationStatus.INDETERMINATE, "bounded_prefix")
            if incomplete
            else (IdentificationStatus.NOT_RECOGNIZED, "record_count_mismatch")
        )
    width = len(nonempty[0])
    if width < 2 or any(len(row) != width for row in nonempty):
        return IdentificationStatus.NOT_RECOGNIZED, "record_shape_mismatch"
    return IdentificationStatus.RECOGNIZED, "consistent_delimited_records"


def _io_indeterminate(
    provider_key: str,
    budget: IdentifierBudget,
    starting_bytes: int,
    evidence_kind: str,
) -> IdentificationEvidence:
    return _evidence(
        provider_key=provider_key,
        status=IdentificationStatus.INDETERMINATE,
        evidence_kind=evidence_kind,
        stable_detail="io_failure",
        budget=budget,
        starting_bytes=starting_bytes,
        cause_classification="io_error",
    )


class IdentifierTable:
    """Immutable provider-key mapping for bounded identifiers."""

    def __init__(self, identifiers: tuple[SourceIdentifier, ...]) -> None:
        findings: list[ConfigurationFinding] = []
        by_provider: dict[str, SourceIdentifier] = {}
        for index, identifier in enumerate(identifiers):
            if not isinstance(identifier, SourceIdentifier):
                findings.append(
                    ConfigurationFinding(
                        "invalid_identifier_contract",
                        f"identifier[{index}]",
                        "Identifier does not satisfy the evidence-only protocol.",
                    )
                )
                continue
            if identifier.provider_key in by_provider:
                findings.append(
                    ConfigurationFinding(
                        "duplicate_identifier_provider",
                        identifier.provider_key,
                        "Provider has more than one identifier implementation.",
                    )
                )
                continue
            by_provider[identifier.provider_key] = identifier
        if findings:
            raise ConfigurationFailure(tuple(findings))
        self.provider_keys = tuple(sorted(by_provider))
        self.identifiers = MappingProxyType(
            {provider_key: by_provider[provider_key] for provider_key in self.provider_keys}
        )

    def identifier(self, provider_key: str) -> SourceIdentifier:
        """Return the identifier registered for one provider."""

        return self.identifiers[provider_key]


def build_builtin_identifier_table() -> IdentifierTable:
    """Build the dependency-light identifier table in canonical provider order."""

    return IdentifierTable(
        (
            CSVSourceIdentifier(),
            ExcelSourceIdentifier(),
            JSONSourceIdentifier(),
            NDJSONSourceIdentifier(),
            ParquetSourceIdentifier(),
        )
    )
