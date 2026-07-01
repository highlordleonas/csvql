"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csvql.checks import run_configured_checks
from csvql.engine import CSVQLEngine
from csvql.exceptions import ExportError, ProjectConfigError
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    ProjectContext,
    ProjectTable,
    ProjectTablesResult,
    build_project_tables_result,
    load_project,
    project_tables_to_sources,
    resolve_catalog_path,
)
from csvql.quality import CheckRunResult
from csvql.source import CSVSource, source_from_path
from csvql.sql_file import load_sql_file


@dataclass(frozen=True, slots=True)
class CSVQLSession:
    """Thin project-backed API over existing CSVQL services."""

    _context: ProjectContext

    @classmethod
    def from_config(cls, start_dir: str | Path = ".") -> CSVQLSession:
        return cls(load_project(Path(start_dir)))

    def tables(self) -> ProjectTablesResult:
        return build_project_tables_result(self._context)

    def query(self, sql: str) -> QueryResult:
        with CSVQLEngine() as engine:
            engine.register_tables(project_tables_to_sources(self._context))
            return engine.query(sql)

    def run_file(self, path: str | Path) -> QueryResult:
        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql)

    def inspect(self, table: str, *, exact: bool = False) -> InspectResult:
        return inspect_csv_source(_catalog_source(self._context, table), exact=exact)

    def sample(self, table: str, *, limit: int = 10) -> SampleResult:
        return sample_csv_source(_catalog_source(self._context, table), limit=limit)

    def profile(self, table: str) -> ProfileResult:
        return profile_csv_source(_catalog_source(self._context, table))

    def check(
        self,
        table: str | None = None,
        *,
        show_failures: bool = False,
        failure_limit: int = 5,
    ) -> CheckRunResult:
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
        format: ExportFormat | str,
        force: bool = False,
    ) -> Path:
        output_path = resolve_export_path(
            str(out),
            base_dir=self._context.project_root,
            force=force,
        )
        result = self.run_file(sql_file)
        content = format_query_result_for_export(result, _export_format(format))
        write_export_file(output_path, content)
        return output_path


def _catalog_source(context: ProjectContext, table_name: str) -> CSVSource:
    project_table = _project_table(context, table_name)
    resolved_path = resolve_catalog_path(project_table, context)
    resolved_source = source_from_path(
        str(resolved_path),
        base_dir=context.project_root,
    )
    return CSVSource(
        path=resolved_source.path,
        display_path=table_name,
        fingerprint=resolved_source.fingerprint,
    )


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
