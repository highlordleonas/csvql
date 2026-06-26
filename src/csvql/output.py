"""Human and automation output formatting."""

import json
from enum import StrEnum

from rich.console import Console
from rich.table import Table

from csvql.models import InspectResult, QueryResult, RowCountInfo, SampleResult


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


def format_table_result(result: QueryResult) -> str:
    """Format a query result as a Rich table exported to plain text."""

    console = Console(color_system=None, force_terminal=False, record=True, width=120)
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

    console = Console(color_system=None, force_terminal=False, record=True, width=120)
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

    console = Console(color_system=None, force_terminal=False, record=True, width=120)
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


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _format_row_count(row_count: RowCountInfo) -> str:
    if row_count.value is not None:
        return str(row_count.value)
    return row_count.mode
