"""Shared query workflow orchestration."""

import re
from dataclasses import dataclass, replace
from pathlib import Path

from csvql.csv_adapter import DEFAULT_SOURCE_ADAPTER_REGISTRY
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    CSVQLError,
    FileMissingError,
    QueryExecutionError,
    SourceError,
    TableMappingError,
)
from csvql.models import QueryResult
from csvql.operation import OperationContext
from csvql.project_config import (
    ProjectContext,
    load_project,
    project_tables_to_source_specs,
)
from csvql.result_stream import ResultStream
from csvql.source import (
    ResolvedSource,
    SourceFingerprint,
    SourceSpec,
    source_spec_from_cli_mapping,
)
from csvql.table_mapping import derive_alias_from_path, validate_table_alias

_DUCKDB_MISSING_TABLE_RE = re.compile(
    r"Table with name (?P<name>[A-Za-z_][A-Za-z0-9_]*) does not exist!"
)


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    """Immutable dormant source declaration and its submission-time identity."""

    spec: SourceSpec
    expected_fingerprint: SourceFingerprint | None
    submission_error: SourceError | None


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Immutable SQL request with required sources and bounded lazy fallbacks."""

    sql: str
    required_sources: tuple[ResolvedSource, ...]
    fallback_sources: tuple[SourceCandidate, ...]


def build_inline_query_request(
    sql_or_csv: str,
    sql: str | None,
    table_mappings: list[str],
    *,
    base_dir: Path | None = None,
    operation: OperationContext,
) -> QueryRequest:
    """Build a query request for existing `csvql query` modes."""

    if sql is None:
        explicit_specs = tuple(
            _source_spec_from_table_mapping(mapping, base_dir=base_dir)
            for mapping in table_mappings
        )
        if explicit_specs:
            return QueryRequest(
                sql=sql_or_csv,
                required_sources=tuple(
                    _resolve_required_source(
                        spec,
                        display_path=spec.locator,
                        operation=operation,
                    )
                    for spec in explicit_specs
                ),
                fallback_sources=_snapshot_optional_catalog(
                    start_dir=base_dir,
                    operation=operation,
                ),
            )
        context = load_project(base_dir)
        return QueryRequest(
            sql=sql_or_csv,
            required_sources=_resolve_required_catalog(context, operation=operation),
            fallback_sources=(),
        )

    if table_mappings:
        raise TableMappingError(
            "Single-file shortcut mode cannot be combined with --table mappings.",
            suggestion='Use either csvql query data/orders.csv "SELECT ..." or --table mappings.',
        )
    required_source = _resolved_single_csv(
        sql_or_csv,
        base_dir=base_dir,
        operation=operation,
    )
    return QueryRequest(
        sql=sql,
        required_sources=(required_source,),
        fallback_sources=_snapshot_optional_catalog(
            start_dir=base_dir,
            operation=operation,
        ),
    )


def build_saved_sql_query_request(
    sql: str,
    table_mappings: list[str],
    *,
    base_dir: Path | None = None,
    operation: OperationContext,
) -> QueryRequest:
    """Build a query request for SQL loaded from a saved file."""

    explicit_specs = tuple(
        _source_spec_from_table_mapping(mapping, base_dir=base_dir) for mapping in table_mappings
    )
    if explicit_specs:
        return QueryRequest(
            sql=sql,
            required_sources=tuple(
                _resolve_required_source(
                    spec,
                    display_path=spec.locator,
                    operation=operation,
                )
                for spec in explicit_specs
            ),
            fallback_sources=_snapshot_optional_catalog(
                start_dir=base_dir,
                operation=operation,
            ),
        )
    context = load_project(base_dir)
    return QueryRequest(
        sql=sql,
        required_sources=_resolve_required_catalog(context, operation=operation),
        fallback_sources=(),
    )


def execute_query_request(
    engine: CSVQLEngine,
    request: QueryRequest,
    *,
    operation: OperationContext,
) -> QueryResult:
    """Prepare immutable sources, stream the query, and materialize complete rows."""

    stream = execute_query_request_stream(engine, request, operation=operation)
    rows: list[tuple[object, ...]] = []
    primary: BaseException | None = None
    try:
        while True:
            batch = stream.fetch_rows(1000)
            rows.extend(batch.rows)
            if batch.exhausted:
                break
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            stream.close()
        except BaseException:
            if primary is None:
                raise
            primary.add_note("Cleanup uncertainty: the active result cursor could not be closed.")
    return QueryResult(columns=stream.columns, rows=tuple(rows), elapsed_ms=stream.elapsed_ms)


def execute_query_request_stream(
    engine: CSVQLEngine,
    request: QueryRequest,
    *,
    operation: OperationContext,
) -> ResultStream:
    """Prepare immutable sources and execute with bounded lazy fallback."""

    _require_matching_operation_context(engine, operation)
    operation.checkpoint()
    engine.prepare_sources(request.required_sources)
    attempted_aliases = {source.spec.alias.casefold() for source in request.required_sources}
    while True:
        operation.checkpoint()
        try:
            return engine.stream(request.sql)
        except QueryExecutionError as exc:
            missing_name = _missing_duckdb_table_name(exc)
            if missing_name is None:
                raise

            missing_key = missing_name.casefold()
            candidate = next(
                (
                    fallback
                    for fallback in request.fallback_sources
                    if fallback.spec.alias.casefold() == missing_key
                    and missing_key not in attempted_aliases
                ),
                None,
            )
            if candidate is None:
                raise
            attempted_aliases.add(missing_key)
            engine.prepare_sources((_resolve_fallback_candidate(candidate, operation=operation),))


def _missing_duckdb_table_name(error: QueryExecutionError) -> str | None:
    match = _DUCKDB_MISSING_TABLE_RE.search(error.message)
    if match is None:
        return None
    return match.group("name")


def _snapshot_optional_catalog(
    *,
    start_dir: Path | None,
    operation: OperationContext,
) -> tuple[SourceCandidate, ...]:
    try:
        context = load_project(start_dir)
    except (CSVQLError, OSError, UnicodeDecodeError):
        return ()
    return tuple(
        _snapshot_candidate(spec, operation=operation)
        for spec in project_tables_to_source_specs(context)
    )


def _snapshot_candidate(
    spec: SourceSpec,
    *,
    operation: OperationContext,
) -> SourceCandidate:
    try:
        resolved = _resolve_source(spec, operation=operation)
    except SourceError as exc:
        return SourceCandidate(
            spec=spec,
            expected_fingerprint=None,
            submission_error=exc,
        )
    return SourceCandidate(
        spec=spec,
        expected_fingerprint=resolved.fingerprint,
        submission_error=None,
    )


def _resolve_fallback_candidate(
    candidate: SourceCandidate,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    if candidate.submission_error is not None:
        if candidate.submission_error.code != "source_missing":
            raise candidate.submission_error
        raise _build_fallback_catalog_file_missing(candidate) from candidate.submission_error
    try:
        resolved = _resolve_source(candidate.spec, operation=operation)
    except SourceError as exc:
        if exc.code != "source_missing":
            raise
        raise _build_fallback_catalog_file_missing(candidate) from exc
    if resolved.fingerprint != candidate.expected_fingerprint:
        raise SourceError(
            "source_changed",
            "CSV source changed after submission.",
            kind=candidate.spec.kind,
            alias=candidate.spec.alias,
            suggestion="Submit the operation again to capture the current CSV source.",
        )
    return resolved


def _build_fallback_catalog_file_missing(
    candidate: SourceCandidate,
) -> FileMissingError:
    return FileMissingError(
        (
            "CSV file not found for project catalog table "
            f"'{candidate.spec.alias}': {candidate.spec.locator}"
        ),
        suggestion=(
            "Update .csvql.yml, run csvql add "
            f"{candidate.spec.alias} <path> --replace, or restore the CSV file."
        ),
    )


def _resolve_required_catalog(
    context: ProjectContext,
    *,
    operation: OperationContext,
) -> tuple[ResolvedSource, ...]:
    resolved: list[ResolvedSource] = []
    for table, spec in zip(
        context.config.tables,
        project_tables_to_source_specs(context),
        strict=True,
    ):
        try:
            resolved.append(_resolve_source(spec, operation=operation))
        except SourceError as exc:
            if exc.code != "source_missing":
                raise
            raise FileMissingError(
                f"CSV file not found for project catalog table '{table.name}': {table.path}",
                suggestion=(
                    "Update .csvql.yml, run csvql add "
                    f"{table.name} <path> --replace, or restore the CSV file."
                ),
            ) from exc
    return tuple(resolved)


def _resolve_required_source(
    spec: SourceSpec,
    *,
    display_path: str,
    operation: OperationContext,
) -> ResolvedSource:
    try:
        return _resolve_source(spec, operation=operation)
    except SourceError as exc:
        if exc.code != "source_missing":
            raise
        raise FileMissingError(
            f"CSV file not found: {display_path}",
            suggestion="Check the path or run from the directory that contains the CSV file.",
        ) from exc


def _resolve_source(
    spec: SourceSpec,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    adapter = DEFAULT_SOURCE_ADAPTER_REGISTRY.create(spec.kind, capability="query")
    return adapter.resolve(spec, operation)


def _require_matching_operation_context(
    engine: CSVQLEngine,
    operation: OperationContext,
) -> None:
    if getattr(engine, "_operation", None) is operation:
        return
    raise CSVQLError(
        "LocalQL query workflow requires one shared operation context.",
        suggestion=(
            "Create one operation context and pass it to both the request builder and engine."
        ),
    )


def _source_spec_from_table_mapping(
    raw_mapping: str,
    *,
    base_dir: Path | None,
) -> SourceSpec:
    if "=" not in raw_mapping:
        raise TableMappingError(
            f"Invalid table mapping '{raw_mapping}'.",
            suggestion="Use --table name=path, for example --table orders=data/orders.csv.",
        )
    raw_alias, raw_path = raw_mapping.split("=", maxsplit=1)
    alias = validate_table_alias(raw_alias)
    if not raw_path.strip():
        raise TableMappingError(
            f"Missing CSV path for table alias '{alias}'.",
            suggestion="Use --table name=path, for example --table orders=data/orders.csv.",
        )
    return source_spec_from_cli_mapping(
        alias=alias,
        path_value=raw_path,
        anchor=base_dir or Path.cwd(),
    )


def _resolved_single_csv(
    path_value: str,
    *,
    base_dir: Path | None,
    operation: OperationContext,
) -> ResolvedSource:
    placeholder = source_spec_from_cli_mapping(
        alias="csv_source",
        path_value=path_value,
        anchor=base_dir or Path.cwd(),
    )
    resolved = _resolve_required_source(
        placeholder,
        display_path=path_value,
        operation=operation,
    )
    canonical_path = Path(resolved.canonical_locator)
    return replace(
        resolved,
        spec=replace(
            resolved.spec,
            alias=derive_alias_from_path(canonical_path),
            locator=resolved.canonical_locator,
            anchor=canonical_path.parent,
        ),
    )
