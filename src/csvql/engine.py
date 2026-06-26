"""DuckDB-backed query execution for CSVQL."""

from collections.abc import Iterable, Sequence
from time import perf_counter

import duckdb

from csvql.exceptions import CSVQLError, QueryExecutionError
from csvql.models import QueryResult, TableSource


class CSVQLEngine:
    """In-memory DuckDB engine that registers CSV files as queryable views."""

    def __init__(self) -> None:
        self._connection = duckdb.connect(database=":memory:")

    def __enter__(self) -> "CSVQLEngine":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def register_tables(self, table_sources: Iterable[TableSource]) -> None:
        """Register CSV sources as DuckDB views."""

        for source in table_sources:
            try:
                relation = self._connection.read_csv(
                    str(source.path),
                    auto_detect=True,
                    header=True,
                )
                relation.create_view(source.name, replace=True)
            except duckdb.Error as exc:
                raise CSVQLError(
                    f"Failed to register CSV table '{source.name}' from {source.path}.",
                    suggestion="Check that the file is a readable CSV with a header row.",
                ) from exc

    def query(self, sql: str, params: Sequence[object] | None = None) -> QueryResult:
        """Execute SQL and return all result rows."""

        started_at = perf_counter()
        try:
            cursor = self._connection.execute(sql, params or [])
            rows = tuple(tuple(row) for row in cursor.fetchall())
            columns = tuple(column[0] for column in cursor.description or ())
        except duckdb.Error as exc:
            raise QueryExecutionError(
                f"DuckDB query failed: {exc}",
                suggestion="Check table names, column names, and SQL syntax.",
            ) from exc

        elapsed_ms = (perf_counter() - started_at) * 1000
        return QueryResult(columns=columns, rows=rows, elapsed_ms=elapsed_ms)
