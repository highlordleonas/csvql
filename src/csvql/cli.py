"""Typer command-line interface for CSVQL."""

import re
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from csvql import __version__
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError, TableMappingError
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.models import QueryResult, TableSource
from csvql.output import (
    OutputFormat,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
    format_table_result,
)
from csvql.project_config import (
    add_project_table,
    build_project_tables_result,
    discover_project,
    initialize_project,
    load_project,
    resolve_catalog_path,
)
from csvql.source import source_from_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv

_DUCKDB_MISSING_TABLE_RE = re.compile(
    r"Table with name (?P<name>[A-Za-z_][A-Za-z0-9_]*) does not exist!"
)

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
        catalog_fallback = sql is None and bool(table)
        with CSVQLEngine() as engine:
            engine.register_tables(table_sources)
            result = _query_with_catalog_fallback(
                engine,
                query_sql,
                table_sources=table_sources,
                catalog_fallback=catalog_fallback,
            )
        if output is OutputFormat.json:
            typer.echo(format_json_result(result))
        else:
            typer.echo(format_table_result(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def init(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Reinitialize an existing project catalog.",
        ),
    ] = False,
) -> None:
    """Create a project catalog in the current working directory."""

    try:
        context = initialize_project(Path.cwd(), force=force)
        typer.echo(f"Created project catalog at {context.config_path}.")
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def add(
    name: Annotated[str, typer.Argument(help="Project catalog table name.")],
    path_value: Annotated[str, typer.Argument(help="CSV file path to add.")],
    replace: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="Replace an existing project catalog table entry.",
        ),
    ] = False,
) -> None:
    """Add a table to the nearest project catalog."""

    try:
        context = load_project()
        updated_context = add_project_table(
            context,
            name,
            path_value,
            replace=replace,
            invocation_dir=Path.cwd(),
        )
        typer.echo(
            f"Added project catalog table '{name.strip()}' to {updated_context.config_path}."
        )
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def tables(
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Project catalog table output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """List tables from the nearest project catalog."""

    try:
        context = load_project()
        result = build_project_tables_result(context)
        if output is OutputFormat.json:
            typer.echo(format_project_tables_json(result))
        else:
            typer.echo(format_project_tables_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


def _build_query_request(
    sql_or_csv: str,
    sql: str | None,
    table_mappings: list[str],
) -> tuple[str, list[TableSource]]:
    if sql is None:
        explicit_sources = [parse_table_mapping(mapping) for mapping in table_mappings]
        if explicit_sources:
            return sql_or_csv, explicit_sources
        catalog_sources = _catalog_table_sources()
        return sql_or_csv, _merge_table_sources(catalog_sources, explicit_sources)

    if table_mappings:
        raise TableMappingError(
            "Single-file shortcut mode cannot be combined with --table mappings.",
            suggestion='Use either csvql query data/orders.csv "SELECT ..." or --table mappings.',
        )
    return sql, [source_from_single_csv(sql_or_csv)]


def _catalog_table_sources() -> list[TableSource]:
    project_root, _ = discover_project()
    context = load_project(project_root)
    return [
        TableSource(name=table.name, path=resolve_catalog_path(table, context))
        for table in context.config.tables
    ]


def _query_with_catalog_fallback(
    engine: CSVQLEngine,
    sql: str,
    *,
    table_sources: list[TableSource],
    catalog_fallback: bool,
) -> QueryResult:
    if not catalog_fallback:
        return engine.query(sql)

    registered_names = {source.name.lower() for source in table_sources}
    while True:
        try:
            return engine.query(sql)
        except QueryExecutionError as exc:
            missing_name = _missing_duckdb_table_name(exc)
            if missing_name is None or missing_name.lower() in registered_names:
                raise

            catalog_source = _catalog_table_source_by_name(
                missing_name,
                excluded_names=registered_names,
            )
            if catalog_source is None:
                raise
            engine.register_tables([catalog_source])
            registered_names.add(catalog_source.name.lower())


def _missing_duckdb_table_name(error: QueryExecutionError) -> str | None:
    match = _DUCKDB_MISSING_TABLE_RE.search(error.message)
    if match is None:
        return None
    return match.group("name")


def _catalog_table_source_by_name(
    table_name: str,
    *,
    excluded_names: set[str],
) -> TableSource | None:
    table_key = table_name.lower()
    if table_key in excluded_names:
        return None

    try:
        context = load_project()
    except CSVQLError:
        return None

    table = next(
        (
            catalog_table
            for catalog_table in context.config.tables
            if catalog_table.name.lower() == table_key
        ),
        None,
    )
    if table is None:
        return None
    return TableSource(name=table.name, path=resolve_catalog_path(table, context))


def _merge_table_sources(
    catalog_sources: list[TableSource],
    explicit_sources: list[TableSource],
) -> list[TableSource]:
    return [*catalog_sources, *explicit_sources]


def _exit_with_error(error: CSVQLError) -> None:
    console = Console(stderr=True, color_system=None)
    console.print(f"Error: {error.message}")
    if error.suggestion:
        console.print(f"Suggestion: {error.suggestion}")
    raise typer.Exit(error.exit_code)


def main() -> None:
    """Console script entrypoint."""

    app()
