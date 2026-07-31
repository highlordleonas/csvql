"""Human and automation output formatting."""

import json
from enum import StrEnum
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from csvql.bounded_result import MAX_PREVIEW_PAYLOAD_BYTES, BoundedQueryResult
from csvql.doctor import DoctorProbeResult, DoctorRunResult
from csvql.exceptions import CSVQLError
from csvql.models import (
    InspectResult,
    ProfileResult,
    QueryResult,
    RowCountInfo,
    SampleResult,
)
from csvql.project_config import ProjectTablesResult
from csvql.quality import CheckRunResult
from csvql.source import SourceDiagnostic, source_options_as_python
from csvql.terminal_text import literal_terminal_text, terminal_safe_text


class OutputFormat(StrEnum):
    """Supported stdout formats for query results."""

    table = "table"
    json = "json"


def format_json_result(result: QueryResult) -> str:
    """Format a query result as deterministic JSON."""

    payload = {
        "columns": list(result.columns),
        "rows": result.as_records(),
        "row_count": result.row_count,
        "elapsed_ms": round(result.elapsed_ms, 3),
    }
    return json.dumps(payload, default=str, indent=2, sort_keys=True)


def format_inspect_result_json(result: InspectResult) -> str:
    """Format an inspect result as deterministic JSON."""

    return json.dumps(result.as_dict(), default=str, indent=2, sort_keys=True)


def format_sample_result_json(result: SampleResult) -> str:
    """Format a sample result as deterministic JSON."""

    return json.dumps(result.as_dict(), default=str, indent=2, sort_keys=True)


def format_profile_result_json(result: ProfileResult) -> str:
    """Format a profile result as deterministic JSON."""

    return json.dumps(result.as_dict(), default=str, indent=2, sort_keys=True)


def format_check_result_json(result: CheckRunResult, *, include_failures: bool) -> str:
    """Format a data-quality check result as deterministic JSON."""

    return json.dumps(
        result.as_dict(include_failures=include_failures),
        default=str,
        indent=2,
        sort_keys=True,
    )


def format_doctor_result_json(result: DoctorRunResult) -> str:
    """Format a doctor result as deterministic JSON."""

    return json.dumps(result.as_dict(), indent=2, sort_keys=True)


def format_project_tables_json(result: ProjectTablesResult) -> str:
    """Format a project catalog table listing as deterministic JSON."""

    payload = {
        "config_path": _format_path(result.config_path),
        "project_root": _format_path(result.project_root),
        "tables": [
            {
                "name": table.name,
                "path": table.path,
                "resolved_path": _format_path(table.resolved_path),
                "source_type": table.source_type,
                "options": source_options_as_python(table.options),
            }
            for table in result.tables
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def format_error_json(error: CSVQLError) -> str:
    """Format one public application failure without raw exception details."""

    return json.dumps(
        error.as_dict(redaction="safe"),
        default=str,
        indent=2,
        sort_keys=True,
    )


def format_source_diagnostic_table(diagnostic: SourceDiagnostic) -> str:
    """Format shared source evidence and required action for a human surface."""

    console = _recording_console(width=120)
    console.print("Code: ", _format_cell(diagnostic.code.value), sep="")
    console.print("Stage: ", _format_cell(diagnostic.stage.value), sep="")
    if diagnostic.safe_source_reference:
        console.print(
            "Source: ",
            _format_cell(diagnostic.safe_source_reference),
            sep="",
        )
    if diagnostic.evidence:
        console.print("Evidence:")
        for evidence in diagnostic.evidence:
            provider = f"{evidence.provider_key}: " if evidence.provider_key else ""
            console.print(
                "- ",
                _format_cell(f"{provider}{evidence.evidence_kind}={evidence.stable_detail}"),
                sep="",
            )
    if diagnostic.required_action is not None:
        providers = (
            f" ({', '.join(diagnostic.required_action.provider_keys)})"
            if diagnostic.required_action.provider_keys
            else ""
        )
        console.print(
            "Required action: ",
            _format_cell(f"{diagnostic.required_action.kind}{providers}"),
            sep="",
        )
    return console.export_text(clear=True)


def format_table_result(result: QueryResult) -> str:
    """Format a query result as a Rich table exported to plain text."""

    console = _recording_console(width=120)
    _print_result_table(console, columns=result.columns, rows=result.rows)
    console.print(f"{result.row_count} row(s) in {result.elapsed_ms:.2f} ms")
    return console.export_text(clear=True)


def format_bounded_table_result(result: BoundedQueryResult) -> str:
    """Format a bounded query preview as a Rich table exported to plain text."""

    console = _recording_console(width=120)
    _print_result_table(console, columns=result.columns, rows=result.rows)
    console.print(_format_bounded_footer(result))
    return console.export_text(clear=True)


def format_inspect_result_table(result: InspectResult) -> str:
    """Format an inspect result as Rich table text."""

    console = _recording_console(width=120)
    source = result.source
    console.print("Source: ", _format_cell(source.get("display_path", "")), sep="")
    console.print(f"Rows: {_format_row_count(result.row_count)}")

    table = Table(show_header=True)
    table.add_column("column")
    table.add_column("type")
    for column in result.columns:
        table.add_row(_format_cell(column.name), _format_cell(column.duckdb_type))
    console.print(table)

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print("- ", _format_cell(warning), sep="")
    return console.export_text(clear=True)


def format_sample_result_table(result: SampleResult) -> str:
    """Format a sample result as Rich table text."""

    console = _recording_console(width=120)
    table = Table(show_header=True)
    for column in result.columns:
        table.add_column(_format_cell(column))
    for row in result.rows:
        table.add_row(*(_format_cell(value) for value in row))
    console.print(table)
    console.print(f"{len(result.rows)} row(s) sampled with limit {result.limit}")

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print("- ", _format_cell(warning), sep="")
    return console.export_text(clear=True)


def format_profile_result_table(result: ProfileResult) -> str:
    """Format a profile result as Rich table text."""

    console = _recording_console(width=140)
    source = result.source
    console.print("Source: ", _format_cell(source.get("display_path", "")), sep="")
    console.print(f"Rows: {result.row_count}")
    console.print(f"Columns: {result.column_count}")
    console.print(f"Duplicate rows: {result.duplicate_row_count}")

    table = Table(show_header=True)
    table.add_column("column")
    table.add_column("type")
    table.add_column("non_null")
    table.add_column("null")
    table.add_column("null_%")
    table.add_column("distinct")
    table.add_column("min")
    table.add_column("max")
    for column in result.columns:
        table.add_row(
            _format_cell(column.name),
            _format_cell(column.duckdb_type),
            str(column.non_null_count),
            str(column.null_count),
            f"{column.null_percentage:.3f}",
            str(column.distinct_count),
            _format_cell(column.min),
            _format_cell(column.max),
        )
    console.print(table)

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print("- ", _format_cell(warning), sep="")
    return console.export_text(clear=True)


def format_check_result_table(result: CheckRunResult, *, include_failures: bool) -> str:
    """Format a data-quality check result as Rich table text."""

    console = _recording_console(width=140)
    console.print("Status: ", _format_cell(result.status), sep="")
    console.print(
        "Checks: "
        f"{result.check_count} | Passed: {result.passed_count} | Failed: {result.failed_count}"
    )

    table = Table(show_header=True)
    table.add_column("table")
    table.add_column("check")
    table.add_column("type")
    table.add_column("column")
    table.add_column("status")
    table.add_column("failed")
    for check in result.checks:
        table.add_row(
            _format_cell(check.table),
            _format_cell(check.name),
            _format_cell(check.type),
            _format_cell(check.column),
            _format_cell(check.status),
            str(check.failed_count),
        )
    console.print(table)

    if include_failures:
        _print_check_failures(console, result)
    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print("- ", _format_cell(warning), sep="")
    return console.export_text(clear=True)


def format_doctor_result_table(result: DoctorRunResult) -> str:
    """Format a doctor result as Rich table text."""

    console = _recording_console(width=140)
    console.print("Status: ", _format_cell(result.status), sep="")
    console.print(
        "Probes: "
        f"{result.probe_count} | Passed: {result.passed_count} | "
        f"Warnings: {result.warning_count} | Failed: {result.failed_count}"
    )

    table = Table(show_header=True)
    table.add_column("scope")
    table.add_column("name")
    table.add_column("status")
    table.add_column("target")
    table.add_column("message")
    for probe in result.probes:
        table.add_row(
            _format_cell(probe.scope),
            _format_cell(probe.name),
            _format_cell(probe.status),
            _format_cell(_format_doctor_target(probe)),
            _format_cell(probe.message),
        )
    console.print(table)
    return console.export_text(clear=True)


def format_project_tables_table(result: ProjectTablesResult) -> str:
    """Format a project catalog table listing as Rich table text."""

    console = _recording_console(width=120)
    table = Table(show_header=True)
    table.add_column("name")
    table.add_column("kind")
    table.add_column("path")
    table.add_column("resolved_path")
    table.add_column("options")
    for listing in result.tables:
        table.add_row(
            _format_cell(listing.name),
            _format_cell(listing.source_type),
            _format_cell(listing.path),
            _format_cell(_format_path(listing.resolved_path)),
            _format_cell(
                json.dumps(
                    source_options_as_python(listing.options),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            ),
        )
    console.print(table)
    return console.export_text(clear=True)


def _format_path(path: Path) -> str:
    return path.as_posix()


def _recording_console(*, width: int) -> Console:
    """Return a Rich console that records output without writing to stdout."""

    return Console(
        color_system=None,
        force_terminal=False,
        markup=False,
        record=True,
        width=width,
        file=StringIO(),
    )


def _print_result_table(
    console: Console,
    *,
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
) -> None:
    table = Table(show_header=True)
    for column in columns:
        table.add_column(_format_cell(column))
    for row in rows:
        table.add_row(*(_format_cell(value) for value in row))
    console.print(table)


def _format_cell(value: object) -> Text:
    return literal_terminal_text(value)


def _format_bounded_footer(result: BoundedQueryResult) -> str:
    row_count = len(result.rows)
    elapsed = f"{result.elapsed_ms:.2f} ms"
    if not result.has_more_rows or result.truncation_reason is None:
        return f"{row_count} row(s) in {elapsed}"
    if result.truncation_reason == "row_limit":
        return (
            f"{row_count} row(s) shown in {elapsed}; more rows exist beyond the "
            f"{row_count}-row limit."
        )
    ceiling_mib = MAX_PREVIEW_PAYLOAD_BYTES // (1024 * 1024)
    return (
        f"{row_count} row(s) shown in {elapsed}; more rows exist beyond the "
        f"{ceiling_mib} MiB preview payload ceiling."
    )


def _format_row_count(row_count: RowCountInfo) -> str:
    if row_count.value is not None:
        return str(row_count.value)
    return row_count.mode


def _print_check_failures(console: Console, result: CheckRunResult) -> None:
    failure_lines: list[Text] = []
    for check in result.checks:
        for failure in check.failures:
            details = ", ".join(
                f"{key}={_format_failure_value(value)}" for key, value in failure.as_dict().items()
            )
            failure_lines.append(_format_cell(f"{check.table}.{check.name}: {details}"))
    if failure_lines:
        console.print("Failures:")
        for line in failure_lines:
            console.print("- ", line, sep="")


def _format_failure_value(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return terminal_safe_text(value)


def _format_doctor_target(probe: DoctorProbeResult) -> str:
    if probe.scope == "table":
        return probe.table or ""
    if probe.scope == "check":
        return f"{probe.table}.{probe.check}".strip(".")
    return str(probe.path or ".csvql.yml")
