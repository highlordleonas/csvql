"""Shared file-export orchestration for query and preserved result pipelines."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import duckdb

from csvql.atomic_write import atomic_output_path
from csvql.engine import CSVQLEngine, RegistrationToken
from csvql.exceptions import CSVQLError, ExportError
from csvql.export import (
    NATIVE_EXPORT_FORMATS,
    STREAMING_EXPORT_FORMATS,
    ExportFormat,
)
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.query_workflow import (
    QueryRequest,
    _adapt_result_stream_for_export,
    _execute_query_request_with_fallback,
    execute_query_request_stream,
)
from csvql.streaming_export import ExportRowSource, ExportSummary, write_streaming_export

_EXCEL_DEPENDENCY_KEY = "duckdb.extension.excel"
_EXCEL_DEPENDENCY_KIND = "duckdb_extension"
_EXPORT_INSERT_BATCH_SIZE = 256
_ROW_EXPORT_ALIAS = "localql_result_export"


def write_query_request_export(
    engine: CSVQLEngine,
    request: QueryRequest,
    path: Path,
    *,
    export_format: ExportFormat,
    overwrite: bool,
    operation: OperationContext,
) -> ExportSummary:
    """Export one query request without changing its source or fallback semantics."""

    if export_format in STREAMING_EXPORT_FORMATS:
        stream = execute_query_request_stream(engine, request, operation=operation)
        return write_streaming_export(
            _adapt_result_stream_for_export(stream),
            path,
            export_format=export_format,
            overwrite=overwrite,
            token=operation.token,
        )
    if export_format not in NATIVE_EXPORT_FORMATS:
        raise _unsupported_export_format(export_format)

    _ensure_native_dependency(
        engine,
        export_format=export_format,
        operation=operation,
    )
    with _native_destination(path, overwrite=overwrite, token=operation.token) as stage_path:
        return _execute_query_request_with_fallback(
            engine,
            request,
            operation=operation,
            execute_attempt=lambda _prepared_scopes: _copy_query_to_path(
                engine,
                request.sql,
                stage_path,
                export_format=export_format,
            ),
            release_on_success=True,
        )


def write_row_source_export(
    source: ExportRowSource,
    path: Path,
    *,
    export_format: ExportFormat,
    overwrite: bool,
    token: OperationToken | None = None,
    operation: OperationContext | None = None,
) -> ExportSummary:
    """Export a preserved one-shot row source through the same format contract."""

    if export_format in STREAMING_EXPORT_FORMATS:
        return write_streaming_export(
            source,
            path,
            export_format=export_format,
            overwrite=overwrite,
            token=token if operation is None else operation.token,
        )
    if export_format not in NATIVE_EXPORT_FORMATS:
        raise _unsupported_export_format(export_format)

    active_operation = operation or OperationContext(token or OperationToken())
    if token is not None and operation is not None and token is not operation.token:
        raise ValueError("token must belong to the supplied operation context")

    with CSVQLEngine(operation=active_operation) as engine:
        _ensure_native_dependency(
            engine,
            export_format=export_format,
            operation=active_operation,
        )
        with _native_destination(
            path,
            overwrite=overwrite,
            token=active_operation.token,
        ) as stage_path:
            registration: RegistrationToken | None = None
            primary: BaseException | None = None
            try:
                registration = _register_export_rows(
                    engine,
                    source,
                    operation=active_operation,
                )
                select_sql = _export_relation_select(source.columns)
                return _copy_query_to_path(
                    engine,
                    select_sql,
                    stage_path,
                    export_format=export_format,
                )
            except BaseException as exc:
                primary = exc
                raise
            finally:
                if registration is not None:
                    _release_export_rows(engine, registration, primary=primary)


def _register_export_rows(
    engine: CSVQLEngine,
    source: ExportRowSource,
    *,
    operation: OperationContext,
) -> RegistrationToken:
    if not source.columns:
        raise ExportError(
            "A result without columns cannot be exported to this format.",
            suggestion="Export a SELECT query that returns at least one column.",
        )
    raw_column_types = getattr(source, "column_types", ())
    column_types = _validated_column_types(source.columns, raw_column_types)
    internal_columns = tuple(f"c{index}" for index in range(len(source.columns)))
    schema_sql = ", ".join(
        f"{_quote_identifier(column)} {column_type}"
        for column, column_type in zip(internal_columns, column_types, strict=True)
    )
    placeholders = ", ".join("?" for _column in internal_columns)
    create_sql = f"CREATE TABLE {_quote_identifier(_ROW_EXPORT_ALIAS)} ({schema_sql})"
    insert_sql = f"INSERT INTO {_quote_identifier(_ROW_EXPORT_ALIAS)} VALUES ({placeholders})"

    def register(connection_value: object) -> None:
        connection = cast(duckdb.DuckDBPyConnection, connection_value)
        created = False
        try:
            connection.execute(create_sql)
            created = True
            with _owned_source_iterator(source) as iterator:
                for rows in _row_batches(iterator, operation=operation):
                    connection.executemany(insert_sql, rows)
                    operation.checkpoint()
        except BaseException:
            if created:
                try:
                    connection.execute(
                        f"DROP TABLE IF EXISTS {_quote_identifier(_ROW_EXPORT_ALIAS)}"
                    )
                except duckdb.Error:
                    pass
            raise

    def unregister(connection_value: object) -> None:
        connection = cast(duckdb.DuckDBPyConnection, connection_value)
        connection.execute(f"DROP TABLE IF EXISTS {_quote_identifier(_ROW_EXPORT_ALIAS)}")

    try:
        return engine.register_relation(
            alias=_ROW_EXPORT_ALIAS,
            register=register,
            unregister=unregister,
            operation=operation,
        )
    except OperationCancelled:
        raise
    except duckdb.Error as exc:
        raise ExportError(
            "The preserved result could not be prepared for structured export.",
            suggestion="Rerun the query and retry the export.",
        ) from exc


def _release_export_rows(
    engine: CSVQLEngine,
    registration: RegistrationToken,
    *,
    primary: BaseException | None,
) -> None:
    cleanup_operation = OperationContext(OperationToken())
    try:
        engine.unregister_relation(registration, operation=cleanup_operation)
    except BaseException as exc:
        if primary is not None:
            primary.add_note("Cleanup uncertainty: the temporary export relation was not removed.")
            return
        raise ExportError(
            "Temporary structured-export cleanup did not complete.",
            suggestion="Start a new LocalQL operation before retrying.",
        ) from exc


def _copy_query_to_path(
    engine: CSVQLEngine,
    sql: str,
    path: Path,
    *,
    export_format: ExportFormat,
) -> ExportSummary:
    query_sql = _copy_query_sql(sql)
    if export_format is ExportFormat.parquet:
        copy_sql = f"COPY ({query_sql}) TO ? (FORMAT PARQUET)"
    elif export_format is ExportFormat.excel:
        copy_sql = f"COPY ({query_sql}) TO ? (FORMAT XLSX, HEADER true)"
    else:
        raise _unsupported_export_format(export_format)
    result = engine.query(copy_sql, [str(path)])
    row_count = _copy_row_count(result.rows)
    return ExportSummary(row_count=row_count, elapsed_ms=result.elapsed_ms)


def _ensure_native_dependency(
    engine: CSVQLEngine,
    *,
    export_format: ExportFormat,
    operation: OperationContext,
) -> None:
    if export_format is ExportFormat.parquet:
        return
    if export_format is not ExportFormat.excel:
        raise _unsupported_export_format(export_format)
    try:
        state = engine.inspect_dependency(
            _EXCEL_DEPENDENCY_KEY,
            _EXCEL_DEPENDENCY_KIND,
            operation=operation,
        )
    except CSVQLError as exc:
        raise ExportError(
            "Excel export dependency availability could not be inspected.",
            suggestion="Start a new LocalQL operation and retry.",
        ) from exc
    if not state.available:
        raise ExportError(
            "Excel export requires a provisioned DuckDB excel extension.",
            suggestion=(
                "Provision the excel extension for this DuckDB version before starting "
                "LocalQL. LocalQL never installs extensions automatically."
            ),
        )
    try:
        engine.load_installed_extension(
            _EXCEL_DEPENDENCY_KEY,
            operation=operation,
        )
    except CSVQLError as exc:
        raise ExportError(
            "The provisioned DuckDB excel extension could not be loaded for export.",
            suggestion="Verify that the extension matches this DuckDB runtime.",
        ) from exc


def _validated_column_types(
    columns: tuple[str, ...],
    raw_column_types: object,
) -> tuple[str, ...]:
    if not isinstance(raw_column_types, tuple) or not raw_column_types:
        raise ExportError(
            "The preserved result does not include its DuckDB column types.",
            suggestion="Rerun the query before exporting it as Parquet or Excel.",
        )
    if len(raw_column_types) != len(columns) or not all(
        isinstance(column_type, str) and bool(column_type) for column_type in raw_column_types
    ):
        raise ExportError(
            "The preserved result schema is invalid.",
            suggestion="Rerun the query before exporting it.",
        )
    try:
        return tuple(str(duckdb.sqltype(column_type)) for column_type in raw_column_types)
    except duckdb.Error as exc:
        raise ExportError(
            "The preserved result contains an unsupported column type.",
            suggestion="Export as NDJSON or CSV, or cast the column in SQL before exporting.",
        ) from exc


def _export_relation_select(columns: tuple[str, ...]) -> str:
    projections = ", ".join(
        f"{_quote_identifier(f'c{index}')} AS {_quote_identifier(column)}"
        for index, column in enumerate(columns)
    )
    return f"SELECT {projections} FROM {_quote_identifier(_ROW_EXPORT_ALIAS)}"


def _copy_query_sql(sql: str) -> str:
    normalized = sql.strip()
    while normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    if not normalized:
        raise ExportError(
            "Export SQL is empty.",
            suggestion="Provide a SELECT query to export.",
        )
    return normalized


def _copy_row_count(rows: tuple[tuple[object, ...], ...]) -> int:
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ExportError(
            "DuckDB returned an unexpected export completion result.",
            suggestion="Retry the export with a new LocalQL operation.",
        )
    value = rows[0][0]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExportError(
            "DuckDB returned an invalid exported row count.",
            suggestion="Retry the export with a new LocalQL operation.",
        )
    return value


@contextmanager
def _native_destination(
    path: Path,
    *,
    overwrite: bool,
    token: OperationToken,
) -> Iterator[Path]:
    try:
        with atomic_output_path(
            path,
            overwrite=overwrite,
            token=token,
        ) as stage_path:
            yield stage_path
    except OperationCancelled:
        raise
    except FileExistsError as exc:
        raise ExportError(
            f"Export output already exists: {path}",
            suggestion="Pass --force to overwrite it or choose a different output path.",
        ) from exc
    except OSError as exc:
        raise ExportError(
            f"Failed to write export output: {path}",
            suggestion="Check that the output path is writable.",
        ) from exc


@contextmanager
def _owned_source_iterator(
    source: ExportRowSource,
) -> Iterator[Iterator[tuple[object, ...]]]:
    iterator = source.iter_rows()
    primary: BaseException | None = None
    try:
        yield iterator
    except BaseException as exc:
        primary = exc
        raise
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            try:
                close()
            except BaseException:
                if primary is None:
                    raise


def _row_batches(
    iterator: Iterator[tuple[object, ...]],
    *,
    operation: OperationContext,
) -> Iterator[Sequence[tuple[object, ...]]]:
    while True:
        operation.checkpoint()
        rows: list[tuple[object, ...]] = []
        try:
            for _index in range(_EXPORT_INSERT_BATCH_SIZE):
                row = next(iterator)
                rows.append(row)
        except StopIteration:
            if rows:
                yield rows
            return
        yield rows


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _unsupported_export_format(export_format: ExportFormat) -> ExportError:
    return ExportError(
        f"Unsupported export format: {export_format}",
        suggestion="Use csv, json, ndjson, parquet, excel, markdown, or text.",
    )
