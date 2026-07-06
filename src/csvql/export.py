"""Export query results to local text files."""

import csv
from enum import StrEnum
from io import StringIO
from pathlib import Path

from csvql.atomic_write import write_text_atomic
from csvql.exceptions import ExportError
from csvql.models import QueryResult
from csvql.output import format_json_result, format_table_result


class ExportFormat(StrEnum):
    """Supported export file formats."""

    csv = "csv"
    json = "json"
    markdown = "markdown"
    text = "text"


def resolve_export_path(
    path_value: str,
    *,
    base_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Resolve and validate an export output path."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)

    if resolved_path.parent.is_dir() is False:
        raise ExportError(
            f"Export output directory does not exist: {resolved_path.parent}",
            suggestion="Create the directory or choose an existing output directory.",
        )
    if resolved_path.is_dir():
        raise ExportError(
            f"Export output path is a directory: {resolved_path}",
            suggestion="Choose a file path for the export output.",
        )
    if resolved_path.exists() and not force:
        raise ExportError(
            f"Export output already exists: {resolved_path}",
            suggestion="Pass --force to overwrite it or choose a different output path.",
        )
    return resolved_path


def format_query_result_for_export(result: QueryResult, export_format: ExportFormat) -> str:
    """Serialize a query result for an export format."""

    if export_format is ExportFormat.csv:
        return _format_csv(result)
    if export_format is ExportFormat.json:
        return format_json_result(result) + "\n"
    if export_format is ExportFormat.markdown:
        return _format_markdown(result)
    if export_format is ExportFormat.text:
        return format_table_result(result)
    raise ExportError(
        f"Unsupported export format: {export_format}",
        suggestion="Use csv, json, markdown, or text.",
    )


def write_export_file(path: Path, content: str) -> None:
    """Write export content as UTF-8 text."""

    try:
        write_text_atomic(path, content)
    except OSError as exc:
        raise ExportError(
            f"Failed to write export output: {path}",
            suggestion="Check that the output path is writable.",
        ) from exc


def _format_csv(result: QueryResult) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return buffer.getvalue()


def _format_markdown(result: QueryResult) -> str:
    header = "| " + " | ".join(_format_markdown_cell(column) for column in result.columns) + " |"
    separator = "| " + " | ".join("---" for _ in result.columns) + " |"
    rows = [
        "| " + " | ".join(_format_markdown_cell(value) for value in row) + " |"
        for row in result.rows
    ]
    return "\n".join([header, separator, *rows]) + "\n"


def _format_markdown_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
    return text.replace("|", "\\|")
