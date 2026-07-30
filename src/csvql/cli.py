"""Typer command-line interface for CSVQL."""

from dataclasses import replace
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
from csvql.operation import OperationContext, OperationToken
from csvql.output import (
    OutputFormat,
    format_bounded_table_result,
    format_check_result_json,
    format_check_result_table,
    format_doctor_result_json,
    format_doctor_result_table,
    format_error_json,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
    format_source_diagnostic_table,
)
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
from csvql.source_operations import SourceOperations
from csvql.source_resolver import resolve_operation_source
from csvql.sql_file import load_sql_file
from csvql.streaming_export import write_streaming_export
from csvql.table_mapping import parse_source_options
from csvql.terminal_text import literal_terminal_text, terminal_safe_text
from csvql.tui_launcher import run_menu_command
from csvql.tui_result_store import DEFAULT_TUI_RESULT_CAPACITY_BYTES

app = typer.Typer(
    add_completion=False,
    help="Query local structured data with DuckDB SQL.",
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
    source: Annotated[
        str,
        typer.Argument(help="Source locator or project catalog alias to inspect."),
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
    source_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Explicit source type (csv, parquet, json, ndjson, or excel).",
        ),
    ] = None,
    option: Annotated[
        list[str] | None,
        typer.Option(
            "--option",
            help="Source option in KEY=VALUE form. Repeat for multiple options.",
        ),
    ] = None,
) -> None:
    """Inspect a local source without running user-authored SQL."""

    try:
        operation = OperationContext(OperationToken())
        resolved = resolve_operation_source(
            source,
            source_type=source_type,
            options=parse_source_options(option or ()),
            base_dir=Path.cwd(),
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            result = SourceOperations(engine, resolved).inspect(exact=exact)
        result = replace(result, source={**result.source, "display_path": source})
        if output is OutputFormat.json:
            typer.echo(format_inspect_result_json(result))
        else:
            typer.echo(format_inspect_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc, output=output)


@app.command()
def sample(
    source: Annotated[
        str,
        typer.Argument(help="Source locator or project catalog alias to sample."),
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
    source_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Explicit source type (csv, parquet, json, ndjson, or excel).",
        ),
    ] = None,
    option: Annotated[
        list[str] | None,
        typer.Option(
            "--option",
            help="Source option in KEY=VALUE form. Repeat for multiple options.",
        ),
    ] = None,
) -> None:
    """Sample rows from a local source without running user-authored SQL."""

    try:
        operation = OperationContext(OperationToken())
        resolved = resolve_operation_source(
            source,
            source_type=source_type,
            options=parse_source_options(option or ()),
            base_dir=Path.cwd(),
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            result = SourceOperations(engine, resolved).sample(limit=limit)
        result = replace(result, source={**result.source, "display_path": source})
        if output is OutputFormat.json:
            typer.echo(format_sample_result_json(result))
        else:
            typer.echo(format_sample_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc, output=output)


@app.command()
def profile(
    source: Annotated[
        str,
        typer.Argument(help="Source locator or project catalog alias to profile."),
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
    source_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Explicit source type (csv, parquet, json, ndjson, or excel).",
        ),
    ] = None,
    option: Annotated[
        list[str] | None,
        typer.Option(
            "--option",
            help="Source option in KEY=VALUE form. Repeat for multiple options.",
        ),
    ] = None,
) -> None:
    """Profile a local source without running user-authored SQL."""

    try:
        operation = OperationContext(OperationToken())
        resolved = resolve_operation_source(
            source,
            source_type=source_type,
            options=parse_source_options(option or ()),
            base_dir=Path.cwd(),
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            result = SourceOperations(engine, resolved).profile()
        result = replace(result, source={**result.source, "display_path": source})
        if output is OutputFormat.json:
            typer.echo(format_profile_result_json(result))
        else:
            typer.echo(format_profile_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc, output=output)


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
    source: Annotated[
        list[str] | None,
        typer.Option(
            "--source",
            help="Source mapping in NAME=LOCATOR form. Repeat for multiple sources.",
        ),
    ] = None,
    source_types: Annotated[
        list[str] | None,
        typer.Option(
            "--source-type",
            help="Source type mapping in NAME=TYPE form.",
        ),
    ] = None,
    source_options: Annotated[
        list[str] | None,
        typer.Option(
            "--source-option",
            help="Source option mapping in NAME.KEY=VALUE form.",
        ),
    ] = None,
    single_source_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Explicit type for single-source shortcut mode.",
        ),
    ] = None,
    option: Annotated[
        list[str] | None,
        typer.Option(
            "--option",
            help="Single-source option in KEY=VALUE form.",
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
            help="Maximum rows to display; display in table output only.",
        ),
    ] = None,
) -> None:
    """Run SQL against one or more local structured sources."""

    try:
        _reject_json_limit(limit=limit, output=output)
        operation = OperationContext(token=OperationToken())
        if source or source_types or source_options or single_source_type or option:
            request = build_inline_query_request(
                sql_or_csv,
                sql,
                table or [],
                source_mappings=source or (),
                source_type_mappings=source_types or (),
                source_option_mappings=source_options or (),
                source_type=single_source_type,
                source_options=option or (),
                base_dir=Path.cwd(),
                operation=operation,
            )
        else:
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
        _exit_with_error(exc, output=output)


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
    source: Annotated[
        list[str] | None,
        typer.Option(
            "--source",
            help="Source mapping in NAME=LOCATOR form. Repeat for multiple sources.",
        ),
    ] = None,
    source_types: Annotated[
        list[str] | None,
        typer.Option(
            "--source-type",
            help="Source type mapping in NAME=TYPE form.",
        ),
    ] = None,
    source_options: Annotated[
        list[str] | None,
        typer.Option(
            "--source-option",
            help="Source option mapping in NAME.KEY=VALUE form.",
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
            help="Maximum rows to display; display in table output only.",
        ),
    ] = None,
) -> None:
    """Run SQL from a local file."""

    try:
        _reject_json_limit(limit=limit, output=output)
        loaded_sql = load_sql_file(sql_file, base_dir=Path.cwd())
        operation = OperationContext(token=OperationToken())
        if source or source_types or source_options:
            request = build_saved_sql_query_request(
                loaded_sql.sql,
                table or [],
                source_mappings=source or (),
                source_type_mappings=source_types or (),
                source_option_mappings=source_options or (),
                base_dir=Path.cwd(),
                operation=operation,
            )
        else:
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
        _exit_with_error(exc, output=output)


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
    source: Annotated[
        list[str] | None,
        typer.Option(
            "--source",
            help="Source mapping in NAME=LOCATOR form. Repeat for multiple sources.",
        ),
    ] = None,
    source_types: Annotated[
        list[str] | None,
        typer.Option(
            "--source-type",
            help="Source type mapping in NAME=TYPE form.",
        ),
    ] = None,
    source_options: Annotated[
        list[str] | None,
        typer.Option(
            "--source-option",
            help="Source option mapping in NAME.KEY=VALUE form.",
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
        if source or source_types or source_options:
            request = build_saved_sql_query_request(
                loaded_sql.sql,
                table or [],
                source_mappings=source or (),
                source_type_mappings=source_types or (),
                source_option_mappings=source_options or (),
                base_dir=Path.cwd(),
                operation=operation,
            )
        else:
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
    path_value: Annotated[str, typer.Argument(help="Source locator to add.")],
    replace: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="Replace an existing project catalog table entry.",
        ),
    ] = False,
    source_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Explicit source type (csv, parquet, json, ndjson, or excel).",
        ),
    ] = None,
    option: Annotated[
        list[str] | None,
        typer.Option(
            "--option",
            help="Source option in KEY=VALUE form. Repeat for multiple options.",
        ),
    ] = None,
) -> None:
    """Add a table to the nearest project catalog."""

    try:
        context = load_project()
        if source_type is not None or option:
            updated_context = add_project_table(
                context,
                name,
                path_value,
                source_type=source_type,
                options=parse_source_options(option or ()),
                replace=replace,
                invocation_dir=Path.cwd(),
            )
        else:
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


def _exit_with_error(
    error: CSVQLError,
    *,
    output: OutputFormat | None = None,
) -> None:
    if output is OutputFormat.json:
        typer.echo(format_error_json(error), err=True)
        raise typer.Exit(error.exit_code)
    console = Console(stderr=True, color_system=None, markup=False)
    console.print("Error: ", literal_terminal_text(error.message), sep="")
    if error.diagnostic is not None:
        console.print(
            format_source_diagnostic_table(error.diagnostic),
            end="",
            soft_wrap=True,
        )
    if error.suggestion:
        console.print("Suggestion: ", literal_terminal_text(error.suggestion), sep="")
    raise typer.Exit(error.exit_code)


def main() -> None:
    """Console script entrypoint."""

    app()
