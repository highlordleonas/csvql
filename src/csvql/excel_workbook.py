"""Bounded, dependency-free XLSX workbook metadata resolution."""

from __future__ import annotations

import os
import posixpath
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, cast
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from csvql.operation import OperationContext

MAX_ZIP_ENTRIES = 4_096
MAX_METADATA_ENTRY_BYTES = 1024 * 1024
MAX_METADATA_TOTAL_BYTES = 4 * 1024 * 1024
MAX_METADATA_COMPRESSION_RATIO = 100
MAX_WORKSHEETS = 1_024
MAX_RANGE_CELLS = 10_000_000
MAX_EXCEL_ROW = 1_048_576
MAX_EXCEL_COLUMN = 16_384

_READ_CHUNK_BYTES = 64 * 1024
_UNSAFE_XML_MARKERS = (b"<!DOCTYPE", b"<!ENTITY")
_SPREADSHEET_NAMESPACES = frozenset(
    (
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
    )
)
_PACKAGE_RELATIONSHIP_NAMESPACES = frozenset(
    (
        "http://schemas.openxmlformats.org/package/2006/relationships",
        "http://purl.oclc.org/ooxml/package/relationships",
    )
)
_CONTENT_TYPES_NAMESPACES = frozenset(
    (
        "http://schemas.openxmlformats.org/package/2006/content-types",
        "http://purl.oclc.org/ooxml/package/content-types",
    )
)
_OFFICE_RELATIONSHIP_NAMESPACES = frozenset(
    (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    )
)
_WORKSHEET_RELATIONSHIP_TYPES = frozenset(
    f"{namespace}/worksheet" for namespace in _OFFICE_RELATIONSHIP_NAMESPACES
)
_MAX_RANGE_TEXT_LENGTH = 256
_A1_RANGE = re.compile(
    r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)"
    r"(?::\$?([A-Za-z]{1,3})\$?([1-9][0-9]*))?$"
)
_QUOTED_SHEET_RANGE = re.compile(r"^'((?:[^']|'')+)'!(.+)$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:")


class ExcelWorkbookError(Exception):
    """Sanitized workbook-metadata failure for adapter translation."""

    def __init__(self, code: str, message: str, suggestion: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion


@dataclass(frozen=True, slots=True)
class WorkbookSheet:
    """One declared worksheet with its package relationship."""

    name: str
    relationship_id: str
    relationship_target: str
    worksheet_part: str
    index: int


@dataclass(frozen=True, slots=True)
class _SheetDeclaration:
    name: str
    relationship_id: str
    index: int


@dataclass(frozen=True, slots=True)
class WorkbookSelection:
    """Bounded workbook interpretation used by Excel source resolution."""

    selected_sheet: WorkbookSheet
    resolved_range: str
    sheet_source: str
    range_source: str
    sheet_count: int
    zip_entry_count: int
    metadata_bytes_read: int
    size_bytes: int
    modified_time_ns: int
    device: int
    inode: int


@dataclass(slots=True)
class _MetadataBudget:
    bytes_read: int = 0

    def consume(self, size: int) -> None:
        if self.bytes_read + size > MAX_METADATA_TOTAL_BYTES:
            raise _metadata_limit("Workbook metadata exceeds the combined LocalQL byte limit.")
        self.bytes_read += size


def inspect_excel_workbook(
    path: Path,
    *,
    requested_sheet: str | None,
    requested_range: str | None,
    operation: OperationContext,
    expected_stat: os.stat_result | None = None,
) -> WorkbookSelection:
    """Resolve one exact worksheet and finite range without reading cell rows."""

    operation.checkpoint()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as source_file:
            descriptor = -1
            initial_stat = os.fstat(source_file.fileno())
            if not stat.S_ISREG(initial_stat.st_mode):
                raise OSError("not a regular file")
            if expected_stat is not None and (
                initial_stat.st_dev != expected_stat.st_dev
                or initial_stat.st_ino != expected_stat.st_ino
            ):
                raise OSError("file changed during observation")
            selection = _inspect_open_workbook(
                source_file,
                requested_sheet=requested_sheet,
                requested_range=requested_range,
                operation=operation,
                file_stat=initial_stat,
            )
            final_stat = os.fstat(source_file.fileno())
            if (
                initial_stat.st_dev != final_stat.st_dev
                or initial_stat.st_ino != final_stat.st_ino
                or initial_stat.st_size != final_stat.st_size
                or initial_stat.st_mtime_ns != final_stat.st_mtime_ns
            ):
                raise OSError("file changed during observation")
            return selection
    except ExcelWorkbookError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "Excel source is missing, unreadable, or not a valid XLSX workbook.",
            "Choose a readable local .xlsx workbook.",
        ) from exc
    finally:
        if "descriptor" in locals() and descriptor >= 0:
            os.close(descriptor)


def normalize_excel_range(
    value: str,
    *,
    selected_sheet: str,
    derived_from_dimension: bool = False,
) -> str:
    """Validate and normalize one finite A1 rectangle."""

    code = "source.excel_range_required" if derived_from_dimension else "source.excel_range_invalid"
    suggestion = (
        "Provide one explicit finite A1 range."
        if derived_from_dimension
        else "Use one finite A1 rectangle such as A1:D100."
    )
    if not isinstance(value, str) or not value:
        raise ExcelWorkbookError(
            code,
            "Excel range is missing or invalid.",
            suggestion,
        )
    if value != value.strip() or len(value) > _MAX_RANGE_TEXT_LENGTH:
        raise ExcelWorkbookError(code, "Excel range is missing or invalid.", suggestion)
    range_text = value

    quoted_match = _QUOTED_SHEET_RANGE.fullmatch(range_text)
    if quoted_match is not None:
        prefixed_sheet = quoted_match.group(1).replace("''", "'")
        if prefixed_sheet != selected_sheet:
            raise ExcelWorkbookError(
                code,
                "Excel range sheet prefix does not match the selected sheet.",
                suggestion,
            )
        range_text = quoted_match.group(2)
    elif "!" in range_text:
        raise ExcelWorkbookError(
            code,
            "Excel range sheet prefixes must be quoted and match the selected sheet.",
            suggestion,
        )

    match = _A1_RANGE.fullmatch(range_text)
    if match is None:
        raise ExcelWorkbookError(
            code,
            "Excel range must be one finite A1 rectangle.",
            suggestion,
        )
    start_row_text = match.group(2)
    end_row_text = match.group(4) or start_row_text
    if len(start_row_text) > 7 or len(end_row_text) > 7:
        raise ExcelWorkbookError(
            code,
            "Excel range is outside the supported worksheet bounds.",
            suggestion,
        )
    start_column = _column_number(match.group(1))
    start_row = int(start_row_text)
    end_column = _column_number(match.group(3) or match.group(1))
    end_row = int(end_row_text)
    if (
        start_column > MAX_EXCEL_COLUMN
        or end_column > MAX_EXCEL_COLUMN
        or start_row > MAX_EXCEL_ROW
        or end_row > MAX_EXCEL_ROW
        or start_column > end_column
        or start_row > end_row
    ):
        raise ExcelWorkbookError(
            code,
            "Excel range is outside the supported worksheet bounds.",
            suggestion,
        )
    cell_count = (end_column - start_column + 1) * (end_row - start_row + 1)
    if cell_count > MAX_RANGE_CELLS:
        raise _metadata_limit("Excel range exceeds the LocalQL cell-count limit.")
    return f"{_column_name(start_column)}{start_row}:{_column_name(end_column)}{end_row}"


def _inspect_open_workbook(
    source_file: BinaryIO,
    *,
    requested_sheet: str | None,
    requested_range: str | None,
    operation: OperationContext,
    file_stat: os.stat_result,
) -> WorkbookSelection:
    budget = _MetadataBudget()
    operation.checkpoint()
    if source_file.read(4) != b"PK\x03\x04":
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "Excel source does not begin with an XLSX ZIP signature.",
            "Choose a valid .xlsx workbook.",
        )
    source_file.seek(0)
    with zipfile.ZipFile(source_file) as archive:
        infos = archive.infolist()
        operation.checkpoint()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise _metadata_limit("XLSX archive contains too many ZIP entries.")
        entries = _validated_entries(infos)
        content_types = _required_entry(entries, "[Content_Types].xml")
        workbook_info = _required_entry(entries, "xl/workbook.xml")
        relationships_info = _required_entry(entries, "xl/_rels/workbook.xml.rels")

        content_types_root = _parse_xml_entry(
            archive,
            content_types,
            budget=budget,
            operation=operation,
        )
        if (
            _local_name(content_types_root.tag) != "Types"
            or _namespace(content_types_root.tag) not in _CONTENT_TYPES_NAMESPACES
        ):
            raise ExcelWorkbookError(
                "source.excel_invalid",
                "XLSX content-type metadata uses an unsupported XML namespace.",
                "Repair or recreate the .xlsx workbook.",
            )
        workbook_root = _parse_xml_entry(
            archive,
            workbook_info,
            budget=budget,
            operation=operation,
        )
        relationships_root = _parse_xml_entry(
            archive,
            relationships_info,
            budget=budget,
            operation=operation,
        )
        relationships = _worksheet_relationships(relationships_root)
        declarations = _sheet_declarations(workbook_root)
        selected_declaration, sheet_source = _select_sheet(
            declarations,
            requested_sheet,
        )
        selected_sheet = _resolve_selected_sheet(
            selected_declaration,
            relationships,
            entries,
        )

        if requested_range is None:
            worksheet_info = _required_entry(entries, selected_sheet.worksheet_part)
            dimension = _worksheet_dimension(
                archive,
                worksheet_info,
                budget=budget,
                operation=operation,
            )
            resolved_range = normalize_excel_range(
                dimension,
                selected_sheet=selected_sheet.name,
                derived_from_dimension=True,
            )
            range_source = "worksheet_dimension"
        else:
            resolved_range = normalize_excel_range(
                requested_range,
                selected_sheet=selected_sheet.name,
            )
            range_source = "explicit_option"

    operation.checkpoint()
    return WorkbookSelection(
        selected_sheet=selected_sheet,
        resolved_range=resolved_range,
        sheet_source=sheet_source,
        range_source=range_source,
        sheet_count=len(declarations),
        zip_entry_count=len(infos),
        metadata_bytes_read=budget.bytes_read,
        size_bytes=file_stat.st_size,
        modified_time_ns=file_stat.st_mtime_ns,
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
    )


def _validated_entries(
    infos: list[zipfile.ZipInfo],
) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        name = info.filename
        if info.flag_bits & 0x1:
            raise ExcelWorkbookError(
                "source.excel_invalid",
                "Encrypted XLSX archives are not supported.",
                "Use an unencrypted .xlsx workbook.",
            )
        canonical = _canonical_member_name(name)
        if canonical in entries:
            raise ExcelWorkbookError(
                "source.excel_invalid",
                "XLSX archive contains duplicate canonical member names.",
                "Repair or recreate the workbook before querying it.",
            )
        entries[canonical] = info
    return entries


def _canonical_member_name(name: str) -> str:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or _WINDOWS_ABSOLUTE.match(name)
    ):
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX archive contains an unsafe member path.",
            "Repair or recreate the workbook before querying it.",
        )
    path = PurePosixPath(name)
    if any(part == ".." for part in path.parts):
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX archive contains a parent-traversing member path.",
            "Repair or recreate the workbook before querying it.",
        )
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if not parts:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX archive contains an invalid member path.",
            "Repair or recreate the workbook before querying it.",
        )
    return unicodedata.normalize("NFC", "/".join(parts))


def _required_entry(
    entries: dict[str, zipfile.ZipInfo],
    name: str,
) -> zipfile.ZipInfo:
    try:
        return entries[name]
    except KeyError as exc:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook metadata is incomplete.",
            "Repair or recreate the .xlsx workbook.",
        ) from exc


def _read_xml_entry(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    budget: _MetadataBudget,
    operation: OperationContext,
) -> bytes:
    _validate_metadata_info(info)
    content = _read_member_prefix(
        archive,
        info,
        limit=MAX_METADATA_ENTRY_BYTES,
        require_complete=True,
        budget=budget,
        operation=operation,
    )
    _reject_unsafe_xml(content)
    return content


def _parse_xml_entry(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    budget: _MetadataBudget,
    operation: OperationContext,
) -> ElementTree.Element:
    content = _read_xml_entry(
        archive,
        info,
        budget=budget,
        operation=operation,
    )
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook metadata contains invalid XML.",
            "Repair or recreate the .xlsx workbook.",
        ) from exc


def _validate_metadata_info(info: zipfile.ZipInfo) -> None:
    if info.file_size > MAX_METADATA_ENTRY_BYTES:
        raise _metadata_limit("An XLSX metadata entry exceeds the byte limit.")
    _validate_compression_ratio(info)


def _validate_compression_ratio(info: zipfile.ZipInfo) -> None:
    if info.file_size and (
        info.compress_size == 0
        or info.file_size > info.compress_size * MAX_METADATA_COMPRESSION_RATIO
    ):
        raise _metadata_limit("An XLSX metadata entry exceeds the compression-ratio limit.")


def _read_member_prefix(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    limit: int,
    require_complete: bool,
    budget: _MetadataBudget,
    operation: OperationContext,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        with archive.open(info, "r") as member:
            while total < limit:
                operation.checkpoint()
                chunk = member.read(min(_READ_CHUNK_BYTES, limit - total))
                if not chunk:
                    break
                budget.consume(len(chunk))
                chunks.append(chunk)
                total += len(chunk)
            if require_complete:
                operation.checkpoint()
                excess = member.read(1)
                if excess:
                    budget.consume(len(excess))
                    raise _metadata_limit("An XLSX metadata entry exceeds the byte limit.")
    except ExcelWorkbookError:
        raise
    except (NotImplementedError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook metadata could not be read safely.",
            "Repair or recreate the .xlsx workbook.",
        ) from exc
    operation.checkpoint()
    return b"".join(chunks)


def _reject_unsafe_xml(content: bytes) -> None:
    upper_content = content.upper()
    if any(marker in upper_content for marker in _UNSAFE_XML_MARKERS):
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook metadata contains a forbidden XML declaration.",
            "Remove DTD or entity declarations and recreate the workbook.",
        )


def _worksheet_relationships(
    root: ElementTree.Element,
) -> dict[str, tuple[str, str, str | None]]:
    if (
        _local_name(root.tag) != "Relationships"
        or _namespace(root.tag) not in _PACKAGE_RELATIONSHIP_NAMESPACES
    ):
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook relationships use an unsupported XML namespace.",
            "Repair or recreate the .xlsx workbook.",
        )
    relationships: dict[str, tuple[str, str, str | None]] = {}
    for element in root.iter():
        if (
            _local_name(element.tag) != "Relationship"
            or _namespace(element.tag) not in _PACKAGE_RELATIONSHIP_NAMESPACES
        ):
            continue
        relationship_id = element.attrib.get("Id")
        relationship_type = element.attrib.get("Type")
        target = element.attrib.get("Target")
        target_mode = element.attrib.get("TargetMode")
        if (
            not relationship_id
            or not relationship_type
            or not target
            or relationship_id in relationships
        ):
            raise ExcelWorkbookError(
                "source.excel_invalid",
                "XLSX workbook relationships are invalid or ambiguous.",
                "Repair or recreate the .xlsx workbook.",
            )
        relationships[relationship_id] = (relationship_type, target, target_mode)
    return relationships


def _sheet_declarations(
    root: ElementTree.Element,
) -> tuple[_SheetDeclaration, ...]:
    if _local_name(root.tag) != "workbook" or _namespace(root.tag) not in _SPREADSHEET_NAMESPACES:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook metadata uses an unsupported XML namespace.",
            "Repair or recreate the .xlsx workbook.",
        )
    declarations: list[_SheetDeclaration] = []
    for element in root.iter():
        if (
            _local_name(element.tag) != "sheet"
            or _namespace(element.tag) not in _SPREADSHEET_NAMESPACES
        ):
            continue
        name = element.attrib.get("name")
        relationship_id = next(
            (
                value
                for key, value in element.attrib.items()
                if _local_name(key) == "id" and _namespace(key) in _OFFICE_RELATIONSHIP_NAMESPACES
            ),
            None,
        )
        if not name or not relationship_id:
            raise ExcelWorkbookError(
                "source.excel_invalid",
                "XLSX workbook contains an invalid worksheet declaration.",
                "Repair or recreate the .xlsx workbook.",
            )
        declarations.append(
            _SheetDeclaration(
                name=name,
                relationship_id=relationship_id,
                index=len(declarations),
            )
        )
    if not declarations:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX workbook does not declare a worksheet.",
            "Choose a workbook containing at least one worksheet.",
        )
    if len(declarations) > MAX_WORKSHEETS:
        raise _metadata_limit("XLSX workbook declares too many worksheets.")

    collision_keys = [
        unicodedata.normalize("NFC", declaration.name).casefold() for declaration in declarations
    ]
    if len(collision_keys) != len(set(collision_keys)):
        raise ExcelWorkbookError(
            "source.excel_sheet_ambiguous",
            "XLSX workbook contains case-insensitively colliding sheet names.",
            "Rename the colliding worksheets before querying the workbook.",
        )

    return tuple(declarations)


def _resolve_selected_sheet(
    declaration: _SheetDeclaration,
    relationships: dict[str, tuple[str, str, str | None]],
    entries: dict[str, zipfile.ZipInfo],
) -> WorkbookSheet:
    relationship = relationships.get(declaration.relationship_id)
    if relationship is None:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX worksheet relationship is missing.",
            "Repair or recreate the .xlsx workbook.",
        )
    relationship_type, target, target_mode = relationship
    if (
        target_mode is not None and target_mode.casefold() == "external"
    ) or relationship_type not in _WORKSHEET_RELATIONSHIP_TYPES:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX worksheet relationship is external or has an invalid type.",
            "Use a workbook with internal worksheet relationships.",
        )
    worksheet_part = _resolve_relationship_target(target)
    worksheet_info = _required_entry(entries, worksheet_part)
    _validate_compression_ratio(worksheet_info)
    return WorkbookSheet(
        name=declaration.name,
        relationship_id=declaration.relationship_id,
        relationship_target=target,
        worksheet_part=worksheet_part,
        index=declaration.index,
    )


def _resolve_relationship_target(target: str) -> str:
    split = urlsplit(target)
    if split.scheme or split.netloc or split.query or split.fragment or "\\" in target:
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX worksheet relationship target is unsafe.",
            "Repair or recreate the .xlsx workbook.",
        )
    decoded = unquote(split.path)
    if any(part == ".." for part in PurePosixPath(decoded).parts):
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX worksheet relationship target contains parent traversal.",
            "Repair or recreate the .xlsx workbook.",
        )
    if decoded.startswith("/"):
        candidate = decoded.lstrip("/")
    else:
        candidate = posixpath.join("xl", decoded)
    normalized = posixpath.normpath(candidate)
    if not normalized or normalized == "." or normalized.startswith("../") or normalized == "..":
        raise ExcelWorkbookError(
            "source.excel_invalid",
            "XLSX worksheet relationship target escapes the workbook package.",
            "Repair or recreate the .xlsx workbook.",
        )
    return _canonical_member_name(normalized)


def _select_sheet(
    sheets: tuple[_SheetDeclaration, ...],
    requested_sheet: str | None,
) -> tuple[_SheetDeclaration, str]:
    if requested_sheet is None:
        return sheets[0], "workbook_order"
    if not isinstance(requested_sheet, str) or not requested_sheet:
        raise ExcelWorkbookError(
            "source.excel_sheet_missing",
            "Excel sheet name must be a non-empty exact worksheet name.",
            "Choose one worksheet name exactly as declared by the workbook.",
        )
    selected = next((sheet for sheet in sheets if sheet.name == requested_sheet), None)
    if selected is None:
        raise ExcelWorkbookError(
            "source.excel_sheet_missing",
            "The requested Excel worksheet does not exist.",
            "Choose one worksheet name exactly as declared by the workbook.",
        )
    return selected, "explicit_option"


def _worksheet_dimension(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    budget: _MetadataBudget,
    operation: OperationContext,
) -> str:
    _validate_compression_ratio(info)
    prefix = _read_member_prefix(
        archive,
        info,
        limit=MAX_METADATA_ENTRY_BYTES,
        require_complete=False,
        budget=budget,
        operation=operation,
    )
    _reject_unsafe_xml(prefix)
    parser = ElementTree.XMLPullParser(events=("start",))
    try:
        parser.feed(prefix)
        for raw_event in parser.read_events():
            _event, element = cast(
                tuple[str, ElementTree.Element],
                raw_event,
            )
            if (
                _local_name(element.tag) == "dimension"
                and _namespace(element.tag) in _SPREADSHEET_NAMESPACES
            ):
                reference = element.attrib.get("ref")
                if reference:
                    return reference
                break
    except ElementTree.ParseError:
        pass
    raise ExcelWorkbookError(
        "source.excel_range_required",
        "A finite worksheet dimension was not found within the metadata limit.",
        "Provide one explicit finite A1 range.",
    )


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _namespace(name: str) -> str:
    if not name.startswith("{") or "}" not in name:
        return ""
    return name[1:].split("}", 1)[0]


def _column_number(value: str) -> int:
    result = 0
    for character in value.upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _column_name(value: int) -> str:
    characters: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        characters.append(chr(ord("A") + remainder))
    return "".join(reversed(characters))


def _metadata_limit(message: str) -> ExcelWorkbookError:
    return ExcelWorkbookError(
        "source.excel_metadata_limit",
        message,
        "Reduce the workbook metadata or selected range before retrying.",
    )
