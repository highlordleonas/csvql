"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from csvql.checks import run_configured_checks
from csvql.csv_adapter import DEFAULT_SOURCE_ADAPTER_REGISTRY
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    CSVInspectionError,
    CSVQLError,
    ExportError,
    FileMissingError,
    ProjectConfigError,
    SourceError,
)
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.operation import OperationContext, OperationToken
from csvql.project_config import (
    ProjectContext,
    ProjectTable,
    ProjectTablesResult,
    build_project_tables_result,
    load_project,
)
from csvql.quality import CheckRunResult
from csvql.source import ResolvedSource, source_spec_from_catalog_table
from csvql.source_operations import SourceOperations
from csvql.sql_file import load_sql_file


@dataclass(frozen=True, slots=True)
class CSVQLSession:
    """Thin project-backed API over existing CSVQL services."""

    _context: ProjectContext

    @classmethod
    def from_config(cls, start_dir: str | Path = ".") -> CSVQLSession:
        """Create a session from the nearest project config at or above ``start_dir``."""

        return cls(load_project(Path(start_dir)))

    def tables(self) -> ProjectTablesResult:
        """Return the configured project table aliases and resolved paths."""

        return build_project_tables_result(self._context)

    def query(self, sql: str) -> QueryResult:
        """Run trusted local SQL against the configured project tables."""

        operation = OperationContext(OperationToken())
        sources = tuple(
            _resolve_catalog_source(self._context, table, operation=operation)
            for table in self._context.config.tables
        )
        try:
            with CSVQLEngine(operation=operation) as engine:
                engine.prepare_sources(sources)
                return engine.query(sql)
        except SourceError as exc:
            source = next(
                (candidate for candidate in sources if candidate.spec.alias == exc.alias),
                None,
            )
            alias = exc.alias or "source"
            source_path = source.canonical_locator if source is not None else "<unavailable>"
            raise CSVQLError(
                f"Failed to register CSV table '{alias}' from {source_path}.",
                suggestion="Check that the file is a readable CSV with a header row.",
            ) from exc

    def run_file(self, path: str | Path) -> QueryResult:
        """Load and run a saved SQL file resolved from the project root."""

        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql)

    def inspect(self, table: str, *, exact: bool = False) -> InspectResult:
        """Inspect a configured table alias."""

        operation = OperationContext(OperationToken())
        source = _resolved_catalog_source(self._context, table, operation=operation)
        try:
            with CSVQLEngine(operation=operation) as engine:
                result = SourceOperations(engine, source).inspect(exact=exact)
            return replace(result, source={**result.source, "display_path": table})
        except CSVQLError as exc:
            raise CSVInspectionError(
                f"Failed to inspect CSV file: {table}",
                suggestion="Check that the file is a readable CSV with a header row.",
            ) from exc

    def sample(self, table: str, *, limit: int = 10) -> SampleResult:
        """Return a bounded sample from a configured table alias."""

        operation = OperationContext(OperationToken())
        source = _resolved_catalog_source(self._context, table, operation=operation)
        try:
            with CSVQLEngine(operation=operation) as engine:
                result = SourceOperations(engine, source).sample(limit=limit)
            return replace(result, source={**result.source, "display_path": table})
        except CSVQLError as exc:
            raise CSVInspectionError(
                f"Failed to sample CSV file: {table}",
                suggestion="Check that the file is a readable CSV with a header row.",
            ) from exc

    def profile(self, table: str) -> ProfileResult:
        """Profile a configured table alias."""

        operation = OperationContext(OperationToken())
        source = _resolved_catalog_source(self._context, table, operation=operation)
        try:
            with CSVQLEngine(operation=operation) as engine:
                result = SourceOperations(engine, source).profile()
            return replace(result, source={**result.source, "display_path": table})
        except CSVQLError as exc:
            raise CSVInspectionError(
                f"Failed to profile CSV file: {table}",
                suggestion="Check that the file is a readable CSV with a header row.",
            ) from exc

    def check(
        self,
        table: str | None = None,
        *,
        show_failures: bool = False,
        failure_limit: int = 5,
    ) -> CheckRunResult:
        """Run configured data-quality checks for the project or one table alias."""

        return run_configured_checks(
            self._context,
            table_name=table,
            show_failures=show_failures,
            failure_limit=failure_limit,
        )

    def export(
        self,
        sql_file: str | Path,
        out: str | Path,
        *,
        format: ExportFormat | str = ExportFormat.json,
        force: bool = False,
    ) -> Path:
        """Run a saved SQL file and export the result, defaulting to JSON output."""

        export_format = _export_format(format)
        output_path = resolve_export_path(
            str(out),
            base_dir=self._context.project_root,
            force=force,
        )
        result = self.run_file(sql_file)
        content = format_query_result_for_export(result, export_format)
        write_export_file(output_path, content, overwrite=force)
        return output_path


def _resolved_catalog_source(
    context: ProjectContext,
    table_name: str,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    return _resolve_catalog_source(
        context,
        _project_table(context, table_name),
        operation=operation,
    )


def _resolve_catalog_source(
    context: ProjectContext,
    table: ProjectTable,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    spec = source_spec_from_catalog_table(table, project_root=context.project_root)
    try:
        adapter = DEFAULT_SOURCE_ADAPTER_REGISTRY.create(spec.kind, capability="query")
        adapter.validate_options(spec)
        return adapter.resolve(spec, operation)
    except SourceError as exc:
        if exc.code == "source_missing":
            raise FileMissingError(
                f"CSV file not found for project catalog table '{table.name}': {table.path}",
                suggestion=(
                    "Update .csvql.yml, run csvql add "
                    f"{table.name} <path> --replace, or restore the CSV file."
                ),
            ) from exc
        raise


def _project_table(context: ProjectContext, table_name: str) -> ProjectTable:
    normalized = table_name.strip().lower()
    match = next(
        (table for table in context.config.tables if table.name.lower() == normalized),
        None,
    )
    if match is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' was not found in {context.config_path}.",
            suggestion="Run csvql tables to list configured table aliases.",
        )
    return match


def _export_format(value: ExportFormat | str) -> ExportFormat:
    if isinstance(value, ExportFormat):
        return value
    try:
        return ExportFormat(value)
    except ValueError as exc:
        raise ExportError(
            f"Unsupported export format: {value}",
            suggestion="Use csv, json, or markdown.",
        ) from exc
