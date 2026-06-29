"""Typer command-line interface for CSVQL."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from csvql import __version__
from csvql.checks import run_configured_checks
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, DataQualityCheckFailure
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.output import (
    OutputFormat,
    format_check_result_json,
    format_check_result_table,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
    format_table_result,
)
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    add_project_table,
    build_project_tables_result,
    initialize_project,
    load_project,
)
from csvql.query_workflow import (
    build_inline_query_request,
    build_saved_sql_query_request,
    execute_query_request,
)
from csvql.source_resolver import resolve_path_or_catalog_source
from csvql.sql_file import load_sql_file

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
        source = resolve_path_or_catalog_source(csv_path, base_dir=Path.cwd())
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
        source = resolve_path_or_catalog_source(csv_path, base_dir=Path.cwd())
        result = sample_csv_source(source, limit=limit)
        if output is OutputFormat.json:
            typer.echo(format_sample_result_json(result))
        else:
            typer.echo(format_sample_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def profile(
    csv_path: Annotated[
        str,
        typer.Argument(help="CSV file or project catalog alias to profile."),
    ],
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Profile output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Profile a local CSV file without running user-authored SQL."""

    try:
        source = resolve_path_or_catalog_source(csv_path, base_dir=Path.cwd())
        result = profile_csv_source(source)
        if output is OutputFormat.json:
            typer.echo(format_profile_result_json(result))
        else:
            typer.echo(format_profile_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def check(
    table_name: Annotated[
        str | None,
        typer.Argument(help="Optional project catalog table alias to check."),
    ] = None,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Data-quality check output format.",
        ),
    ] = OutputFormat.table,
    show_failures: Annotated[
        bool,
        typer.Option(
            "--show-failures",
            help="Include sampled failing rows or values in output.",
        ),
    ] = False,
    failure_limit: Annotated[
        int,
        typer.Option(
            "--failure-limit",
            min=1,
            help="Maximum sampled failures per failed check.",
        ),
    ] = 5,
) -> None:
    """Run configured data-quality checks from the project catalog."""

    try:
        context = load_project()
        result = run_configured_checks(
            context,
            table_name=table_name,
            show_failures=show_failures,
            failure_limit=failure_limit,
        )
        if output is OutputFormat.json:
            typer.echo(format_check_result_json(result, include_failures=show_failures))
        else:
            typer.echo(format_check_result_table(result, include_failures=show_failures), nl=False)
        if result.status == "failed":
            raise typer.Exit(DataQualityCheckFailure.exit_code)
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
        request = build_inline_query_request(
            sql_or_csv,
            sql,
            table or [],
            base_dir=Path.cwd(),
        )
        with CSVQLEngine() as engine:
            result = execute_query_request(engine, request)
        if output is OutputFormat.json:
            typer.echo(format_json_result(result))
        else:
            typer.echo(format_table_result(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def run(
    sql_file: Annotated[
        str,
        typer.Argument(help="SQL file to run."),
    ],
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
    """Run SQL from a local file."""

    try:
        loaded_sql = load_sql_file(sql_file, base_dir=Path.cwd())
        request = build_saved_sql_query_request(
            loaded_sql.sql,
            table or [],
            base_dir=Path.cwd(),
        )
        with CSVQLEngine() as engine:
            result = execute_query_request(engine, request)
        if output is OutputFormat.json:
            typer.echo(format_json_result(result))
        else:
            typer.echo(format_table_result(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)


@app.command()
def export(
    sql_file: Annotated[
        str,
        typer.Argument(help="SQL file to run and export."),
    ],
    export_format: Annotated[
        ExportFormat,
        typer.Option(
            "--format",
            case_sensitive=False,
            help="Export output format.",
        ),
    ],
    out: Annotated[
        str,
        typer.Option(
            "--out",
            help="Output file path.",
        ),
    ],
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table",
            "-t",
            help="Table mapping in name=path form. Repeat for multiple CSV files.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing export output file.",
        ),
    ] = False,
) -> None:
    """Run SQL from a local file and write the result to a file."""

    try:
        loaded_sql = load_sql_file(sql_file, base_dir=Path.cwd())
        output_path = resolve_export_path(out, base_dir=Path.cwd(), force=force)
        request = build_saved_sql_query_request(
            loaded_sql.sql,
            table or [],
            base_dir=Path.cwd(),
        )
        with CSVQLEngine() as engine:
            result = execute_query_request(engine, request)
        content = format_query_result_for_export(result, export_format)
        write_export_file(output_path, content)
        typer.echo(f"Wrote export to {output_path}.")
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


def _exit_with_error(error: CSVQLError) -> None:
    console = Console(stderr=True, color_system=None)
    console.print(f"Error: {error.message}")
    if error.suggestion:
        console.print(f"Suggestion: {error.suggestion}")
    raise typer.Exit(error.exit_code)


def main() -> None:
    """Console script entrypoint."""

    app()
