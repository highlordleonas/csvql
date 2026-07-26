"""Typer command-line interface for CSVQL."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from csvql import __version__
from csvql.bounded_result import (
    DEFAULT_INTERACTIVE_ROW_LIMIT,
    MAX_PREVIEW_PAYLOAD_BYTES,
    PreviewPolicy,
    collect_bounded_preview,
)
from csvql.checks import run_configured_checks
from csvql.doctor import run_doctor
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, DataQualityCheckFailure, DoctorFailure
from csvql.export import (
    ExportFormat,
    resolve_export_path,
)
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.operation import OperationContext, OperationToken
from csvql.output import (
    OutputFormat,
    format_bounded_table_result,
    format_check_result_json,
    format_check_result_table,
    format_doctor_result_json,
    format_doctor_result_table,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
)
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    add_project_table,
    build_project_tables_result,
    initialize_project,
    load_project,
)
from csvql.query_workflow import (
    QueryRequest,
    _adapt_result_stream_for_export,
    build_inline_query_request,
    build_saved_sql_query_request,
    execute_query_request,
    execute_query_request_stream,
)
from csvql.source_resolver import resolve_path_or_catalog_source
from csvql.sql_file import load_sql_file
from csvql.streaming_export import write_streaming_export
from csvql.terminal_text import literal_terminal_text, terminal_safe_text
from csvql.tui_launcher import run_menu_command
from csvql.tui_result_store import DEFAULT_TUI_RESULT_CAPACITY_BYTES

app = typer.Typer(
    add_completion=False,
    help="Query local CSV files with DuckDB SQL.",
)

_JSON_LIMIT_MESSAGE = (
    "The --limit option only applies to table output. JSON output remains complete in v1.1."
)
_JSON_LIMIT_SUGGESTION = "Remove --limit or use --output table."
_INTERRUPTED_QUERY_MESSAGE = "Query interrupted."
_INTERRUPTED_QUERY_SUGGESTION = "Retry the query when ready."
_MEBIBYTE = 1024 * 1024
_MAX_TUI_RESULT_CAPACITY_BYTES = (2**63) - 1
_MAX_TUI_RESULT_CAPACITY_MIB = _MAX_TUI_RESULT_CAPACITY_BYTES // _MEBIBYTE


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _capacity_bytes_from_mib(capacity_mib: int) -> int:
    if type(capacity_mib) is not int:
        raise typer.BadParameter("must be a valid integer.")
    if capacity_mib <= 0:
        raise typer.BadParameter("must be at least 1.")
    if capacity_mib > _MAX_TUI_RESULT_CAPACITY_MIB:
        raise typer.BadParameter(f"must be at most {_MAX_TUI_RESULT_CAPACITY_MIB}.")
    return capacity_mib * _MEBIBYTE


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
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

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


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
def menu(
    csv_path: Annotated[
        str | None,
        typer.Argument(help="CSV file to preload into the TUI session."),
    ] = None,
    table: Annotated[
        list[str] | None,
        typer.Option(
            "--table",
            "-t",
            help="Table mapping in name=path form. Repeat for multiple CSV files.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            help="Maximum number of preview rows to retain in the session.",
        ),
    ] = DEFAULT_INTERACTIVE_ROW_LIMIT,
    spool_capacity_mib: Annotated[
        int,
        typer.Option(
            "--spool-capacity-mib",
            min=1,
            help="Per-session TUI result capacity in MiB.",
        ),
    ] = DEFAULT_TUI_RESULT_CAPACITY_BYTES // _MEBIBYTE,
) -> None:
    """Open the interactive CSVQL terminal menu."""

    try:
        result_store_capacity_bytes = _capacity_bytes_from_mib(spool_capacity_mib)
        run_menu_command(
            csv_path=csv_path,
            table_mappings=tuple(table or ()),
            start_dir=Path.cwd(),
            preview_policy=PreviewPolicy(
                row_limit=limit,
                payload_limit_bytes=MAX_PREVIEW_PAYLOAD_BYTES,
            ),
            result_store_capacity_bytes=result_store_capacity_bytes,
        )
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
def doctor(
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Doctor output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Check local CSVQL project health without running user-authored SQL."""

    result = run_doctor(start_dir=Path.cwd())
    if output is OutputFormat.json:
        typer.echo(format_doctor_result_json(result))
    else:
        typer.echo(format_doctor_result_table(result), nl=False)
    if result.status == "failed":
        raise typer.Exit(DoctorFailure.exit_code)


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
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            min=1,
            help="Maximum rows to display in table output.",
        ),
    ] = None,
) -> None:
    """Run SQL against one or more local CSV files."""

    try:
        _reject_json_limit(limit=limit, output=output)
        operation = OperationContext(token=OperationToken())
        request = build_inline_query_request(
            sql_or_csv,
            sql,
            table or [],
            base_dir=Path.cwd(),
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            if output is OutputFormat.json:
                result = execute_query_request(engine, request, operation=operation)
                typer.echo(format_json_result(result))
            else:
                typer.echo(
                    _format_bounded_query_preview(
                        engine,
                        request,
                        operation=operation,
                        limit=limit,
                    ),
                    nl=False,
                )
    except KeyboardInterrupt:
        _exit_with_error(_interrupted_query_error())
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
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            min=1,
            help="Maximum rows to display in table output.",
        ),
    ] = None,
) -> None:
    """Run SQL from a local file."""

    try:
        _reject_json_limit(limit=limit, output=output)
        loaded_sql = load_sql_file(sql_file, base_dir=Path.cwd())
        operation = OperationContext(token=OperationToken())
        request = build_saved_sql_query_request(
            loaded_sql.sql,
            table or [],
            base_dir=Path.cwd(),
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            if output is OutputFormat.json:
                result = execute_query_request(engine, request, operation=operation)
                typer.echo(format_json_result(result))
            else:
                typer.echo(
                    _format_bounded_query_preview(
                        engine,
                        request,
                        operation=operation,
                        limit=limit,
                    ),
                    nl=False,
                )
    except KeyboardInterrupt:
        _exit_with_error(_interrupted_query_error())
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
        operation = OperationContext(token=OperationToken())
        request = build_saved_sql_query_request(
            loaded_sql.sql,
            table or [],
            base_dir=Path.cwd(),
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            stream = execute_query_request_stream(engine, request, operation=operation)
            write_streaming_export(
                _adapt_result_stream_for_export(stream),
                output_path,
                export_format=export_format,
                overwrite=force,
                token=operation.token,
            )
        _echo_human_message(f"Wrote export to {output_path}.")
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
        _echo_human_message(f"Created project catalog at {context.config_path}.")
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
        _echo_human_message(
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


def _echo_human_message(message: str) -> None:
    typer.echo(terminal_safe_text(message))


def _reject_json_limit(*, limit: int | None, output: OutputFormat) -> None:
    if output is OutputFormat.json and limit is not None:
        raise CSVQLError(
            _JSON_LIMIT_MESSAGE,
            suggestion=_JSON_LIMIT_SUGGESTION,
        )


def _format_bounded_query_preview(
    engine: CSVQLEngine,
    request: QueryRequest,
    *,
    operation: OperationContext,
    limit: int | None,
) -> str:
    stream = execute_query_request_stream(engine, request, operation=operation)
    result = collect_bounded_preview(
        stream,
        policy=PreviewPolicy(row_limit=limit or DEFAULT_INTERACTIVE_ROW_LIMIT),
    )
    return format_bounded_table_result(result)


def _interrupted_query_error() -> CSVQLError:
    return CSVQLError(
        _INTERRUPTED_QUERY_MESSAGE,
        suggestion=_INTERRUPTED_QUERY_SUGGESTION,
    )


def _exit_with_error(error: CSVQLError) -> None:
    console = Console(stderr=True, color_system=None, markup=False)
    console.print("Error: ", literal_terminal_text(error.message), sep="")
    if error.suggestion:
        console.print("Suggestion: ", literal_terminal_text(error.suggestion), sep="")
    raise typer.Exit(error.exit_code)


def main() -> None:
    """Console script entrypoint."""

    app()
