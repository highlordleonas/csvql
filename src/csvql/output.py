"""Human and automation output formatting."""

import json
from enum import StrEnum
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.table import Table

from csvql.doctor import DoctorProbeResult, DoctorRunResult
from csvql.models import InspectResult, ProfileResult, QueryResult, RowCountInfo, SampleResult
from csvql.project_config import ProjectTablesResult
from csvql.quality import CheckRunResult


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
            }
            for table in result.tables
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def format_table_result(result: QueryResult) -> str:
    """Format a query result as a Rich table exported to plain text."""

    console = _recording_console(width=120)
    table = Table(show_header=True)
    for column in result.columns:
        table.add_column(column)
    for row in result.rows:
        table.add_row(*(_format_cell(value) for value in row))
    console.print(table)
    console.print(f"{result.row_count} row(s) in {result.elapsed_ms:.2f} ms")
    return console.export_text(clear=True)


def format_inspect_result_table(result: InspectResult) -> str:
    """Format an inspect result as Rich table text."""

    console = _recording_console(width=120)
    source = result.source
    console.print(f"Source: {source.get('display_path', '')}")
    console.print(f"Rows: {_format_row_count(result.row_count)}")

    table = Table(show_header=True)
    table.add_column("column")
    table.add_column("type")
    for column in result.columns:
        table.add_row(column.name, column.duckdb_type)
    console.print(table)

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print(f"- {warning}")
    return console.export_text(clear=True)


def format_sample_result_table(result: SampleResult) -> str:
    """Format a sample result as Rich table text."""

    console = _recording_console(width=120)
    table = Table(show_header=True)
    for column in result.columns:
        table.add_column(column)
    for row in result.rows:
        table.add_row(*(_format_cell(value) for value in row))
    console.print(table)
    console.print(f"{len(result.rows)} row(s) sampled with limit {result.limit}")

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print(f"- {warning}")
    return console.export_text(clear=True)


def format_profile_result_table(result: ProfileResult) -> str:
    """Format a profile result as Rich table text."""

    console = _recording_console(width=140)
    source = result.source
    console.print(f"Source: {source.get('display_path', '')}")
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
            column.name,
            column.duckdb_type,
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
            console.print(f"- {warning}")
    return console.export_text(clear=True)


def format_check_result_table(result: CheckRunResult, *, include_failures: bool) -> str:
    """Format a data-quality check result as Rich table text."""

    console = _recording_console(width=140)
    console.print(f"Status: {result.status}")
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
            check.table,
            check.name,
            check.type,
            _format_cell(check.column),
            check.status,
            str(check.failed_count),
        )
    console.print(table)

    if include_failures:
        _print_check_failures(console, result)
    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print(f"- {warning}")
    return console.export_text(clear=True)


def format_doctor_result_table(result: DoctorRunResult) -> str:
    """Format a doctor result as Rich table text."""

    console = _recording_console(width=140)
    console.print(f"Status: {result.status}")
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
            probe.scope,
            probe.name,
            probe.status,
            _format_doctor_target(probe),
            probe.message,
        )
    console.print(table)
    return console.export_text(clear=True)


def format_project_tables_table(result: ProjectTablesResult) -> str:
    """Format a project catalog table listing as Rich table text."""

    console = _recording_console(width=120)
    table = Table(show_header=True)
    table.add_column("name")
    table.add_column("path")
    table.add_column("resolved_path")
    for listing in result.tables:
        table.add_row(listing.name, listing.path, _format_path(listing.resolved_path))
    console.print(table)
    return console.export_text(clear=True)


def _format_path(path: Path) -> str:
    return path.as_posix()


def _recording_console(*, width: int) -> Console:
    """Return a Rich console that records output without writing to stdout."""

    return Console(
        color_system=None, force_terminal=False, record=True, width=width, file=StringIO()
    )


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _format_row_count(row_count: RowCountInfo) -> str:
    if row_count.value is not None:
        return str(row_count.value)
    return row_count.mode


def _print_check_failures(console: Console, result: CheckRunResult) -> None:
    failure_lines: list[str] = []
    for check in result.checks:
        for failure in check.failures:
            details = ", ".join(
                f"{key}={_format_failure_value(value)}" for key, value in failure.as_dict().items()
            )
            failure_lines.append(f"{check.table}.{check.name}: {details}")
    if failure_lines:
        console.print("Failures:")
        for line in failure_lines:
            console.print(f"- {line}")


def _format_failure_value(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return _format_cell(value)


def _format_doctor_target(probe: DoctorProbeResult) -> str:
    if probe.scope == "table":
        return probe.table or ""
    if probe.scope == "check":
        return f"{probe.table}.{probe.check}".strip(".")
    return str(probe.path or ".csvql.yml")
