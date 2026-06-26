"""Typer command-line interface for CSVQL."""

from typing import Annotated

import typer
from rich.console import Console

from csvql import __version__
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, TableMappingError
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.models import TableSource
from csvql.output import (
    OutputFormat,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_sample_result_json,
    format_sample_result_table,
    format_table_result,
)
from csvql.source import source_from_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv

app = typer.Typer(
    add_completion=False,
    help="Query local CSV files with DuckDB SQL.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            help="Show the CSVQL version.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """CSVQL command group."""


@app.command()
def inspect(
    csv_path: Annotated[
        str,
        typer.Argument(help="CSV file to inspect."),
    ],
    exact: Annotated[
        bool,
        typer.Option(
            "--exact",
            help="Run a full scan to calculate an exact row count.",
        ),
    ] = False,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Inspection output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Inspect a local CSV file without running user-authored SQL."""

    try:
        source = source_from_path(csv_path)
        result = inspect_csv_source(source, exact=exact)
        if output is OutputFormat.json:
            typer.echo(format_inspect_result_json(result))
        else:
            typer.echo(format_inspect_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def sample(
    csv_path: Annotated[
        str,
        typer.Argument(help="CSV file to sample."),
    ],
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            help="Maximum number of rows to sample.",
        ),
    ] = 10,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Sample output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Sample rows from a local CSV file without running user-authored SQL."""

    try:
        source = source_from_path(csv_path)
        result = sample_csv_source(source, limit=limit)
        if output is OutputFormat.json:
            typer.echo(format_sample_result_json(result))
        else:
            typer.echo(format_sample_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def query(
    sql_or_csv: Annotated[
        str,
        typer.Argument(
            help="Inline SQL, or a CSV path when SQL is supplied as the second argument.",
        ),
    ],
    sql: Annotated[
        str | None,
        typer.Argument(help="SQL to run in single-file shortcut mode."),
    ] = None,
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table",
            "-t",
            help="Table mapping in name=path form. Repeat for multiple CSV files.",
        ),
    ] = None,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Result output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Run SQL against one or more local CSV files."""

    try:
        query_sql, table_sources = _build_query_request(sql_or_csv, sql, table or [])
        with CSVQLEngine() as engine:
            engine.register_tables(table_sources)
            result = engine.query(query_sql)
        if output is OutputFormat.json:
            typer.echo(format_json_result(result))
        else:
            typer.echo(format_table_result(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


def _build_query_request(
    sql_or_csv: str,
    sql: str | None,
    table_mappings: list[str],
) -> tuple[str, list[TableSource]]:
    if sql is None:
        if not table_mappings:
            raise TableMappingError(
                "At least one --table mapping is required for inline SQL mode.",
                suggestion="Use --table orders=data/orders.csv before the SQL string.",
            )
        return sql_or_csv, [parse_table_mapping(mapping) for mapping in table_mappings]

    if table_mappings:
        raise TableMappingError(
            "Single-file shortcut mode cannot be combined with --table mappings.",
            suggestion='Use either csvql query data/orders.csv "SELECT ..." or --table mappings.',
        )
    return sql, [source_from_single_csv(sql_or_csv)]


def _exit_with_error(error: CSVQLError) -> None:
    console = Console(stderr=True, color_system=None)
    console.print(f"Error: {error.message}")
    if error.suggestion:
        console.print(f"Suggestion: {error.suggestion}")
    raise typer.Exit(error.exit_code)


def main() -> None:
    """Console script entrypoint."""

    app()
