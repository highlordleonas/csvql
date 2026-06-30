"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csvql.checks import run_configured_checks
from csvql.engine import CSVQLEngine
from csvql.exceptions import ProjectConfigError
from csvql.models import ProfileResult, QueryResult
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    ProjectContext,
    ProjectTable,
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

    def query(self, sql: str) -> QueryResult:
        with CSVQLEngine() as engine:
            engine.register_tables(project_tables_to_sources(self._context))
            return engine.query(sql)

    def run_file(self, path: str | Path) -> QueryResult:
        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql)

    def profile(self, table: str) -> ProfileResult:
        project_table = _project_table(self._context, table)
        resolved_path = resolve_catalog_path(project_table, self._context)
        resolved_source = source_from_path(
            str(resolved_path),
            base_dir=self._context.project_root,
        )
        source = CSVSource(
            path=resolved_source.path,
            display_path=table,
            fingerprint=resolved_source.fingerprint,
        )
        return profile_csv_source(source)

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
