"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csvql.engine import CSVQLEngine
from csvql.models import QueryResult
from csvql.project_config import ProjectContext, load_project, project_tables_to_sources
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
