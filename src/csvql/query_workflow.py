"""Shared query workflow orchestration."""

import re
from dataclasses import dataclass
from pathlib import Path

from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError, TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.project_config import discover_project, load_project, resolve_catalog_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv

_DUCKDB_MISSING_TABLE_RE = re.compile(
    r"Table with name (?P<name>[A-Za-z_][A-Za-z0-9_]*) does not exist!"
)


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """SQL text plus registered table sources needed to execute it."""

    sql: str
    table_sources: tuple[TableSource, ...]
    catalog_fallback: bool
    catalog_start_dir: Path | None = None


def build_inline_query_request(
    sql_or_csv: str,
    sql: str | None,
    table_mappings: list[str],
    *,
    base_dir: Path | None = None,
) -> QueryRequest:
    """Build a query request for existing `csvql query` modes."""

    if sql is None:
        explicit_sources = [
            parse_table_mapping(mapping, base_dir=base_dir) for mapping in table_mappings
        ]
        if explicit_sources:
            return QueryRequest(
                sql=sql_or_csv,
                table_sources=tuple(explicit_sources),
                catalog_fallback=True,
                catalog_start_dir=base_dir,
            )
        catalog_sources = _catalog_table_sources(start_dir=base_dir)
        return QueryRequest(
            sql=sql_or_csv,
            table_sources=tuple(catalog_sources),
            catalog_fallback=False,
            catalog_start_dir=base_dir,
        )

    if table_mappings:
        raise TableMappingError(
            "Single-file shortcut mode cannot be combined with --table mappings.",
            suggestion='Use either csvql query data/orders.csv "SELECT ..." or --table mappings.',
        )
    return QueryRequest(
        sql=sql,
        table_sources=(source_from_single_csv(sql_or_csv, base_dir=base_dir),),
        catalog_fallback=False,
        catalog_start_dir=base_dir,
    )


def build_saved_sql_query_request(
    sql: str,
    table_mappings: list[str],
    *,
    base_dir: Path | None = None,
) -> QueryRequest:
    """Build a query request for SQL loaded from a saved file."""

    explicit_sources = [
        parse_table_mapping(mapping, base_dir=base_dir) for mapping in table_mappings
    ]
    if explicit_sources:
        return QueryRequest(
            sql=sql,
            table_sources=tuple(explicit_sources),
            catalog_fallback=True,
            catalog_start_dir=base_dir,
        )
    catalog_sources = _catalog_table_sources(start_dir=base_dir)
    return QueryRequest(
        sql=sql,
        table_sources=tuple(catalog_sources),
        catalog_fallback=False,
        catalog_start_dir=base_dir,
    )


def execute_query_request(engine: CSVQLEngine, request: QueryRequest) -> QueryResult:
    """Register sources and execute a query request."""

    engine.register_tables(request.table_sources)
    if not request.catalog_fallback:
        return engine.query(request.sql)

    registered_names = {source.name.lower() for source in request.table_sources}
    while True:
        try:
            return engine.query(request.sql)
        except QueryExecutionError as exc:
            missing_name = _missing_duckdb_table_name(exc)
            if missing_name is None or missing_name.lower() in registered_names:
                raise

            catalog_source = _catalog_table_source_by_name(
                missing_name,
                excluded_names=registered_names,
                start_dir=request.catalog_start_dir,
            )
            if catalog_source is None:
                raise
            engine.register_tables([catalog_source])
            registered_names.add(catalog_source.name.lower())


def _catalog_table_sources(*, start_dir: Path | None = None) -> list[TableSource]:
    project_root, _ = discover_project(start_dir)
    context = load_project(project_root)
    return [
        TableSource(name=table.name, path=resolve_catalog_path(table, context))
        for table in context.config.tables
    ]


def _missing_duckdb_table_name(error: QueryExecutionError) -> str | None:
    match = _DUCKDB_MISSING_TABLE_RE.search(error.message)
    if match is None:
        return None
    return match.group("name")


def _catalog_table_source_by_name(
    table_name: str,
    *,
    excluded_names: set[str],
    start_dir: Path | None = None,
) -> TableSource | None:
    table_key = table_name.lower()
    if table_key in excluded_names:
        return None

    try:
        context = load_project(start_dir)
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
