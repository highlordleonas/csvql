"""Format-neutral relational operations over one resolved source."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    QueryExecutionError,
    SourceBindingError,
    SourceIdentityError,
)
from csvql.models import (
    ColumnInfo,
    ColumnProfile,
    DialectInfo,
    InspectResult,
    ProfileResult,
    QueryResult,
    RowCountInfo,
    SampleResult,
)
from csvql.operation import OperationContext, OperationToken
from csvql.source import (
    CSVSource,
    FrozenJSONArray,
    FrozenJSONObject,
    FrozenJSONValue,
    ResolvedSource,
    build_source_request,
)
from csvql.source_runtime import resolve_source_request
from csvql.sql_utils import quote_identifier


class SourceOperations:
    """Run engine-owned relational operations over one resolved source."""

    def __init__(self, engine: CSVQLEngine, source: ResolvedSource) -> None:
        self._engine = engine
        self._source = source
        self._prepared = False

    def inspect(self, *, exact: bool = False) -> InspectResult:
        """Inspect schema and recorded provider facts, optionally counting rows."""

        self._prepare()
        columns = self._columns()
        row_count = RowCountInfo.not_counted()
        if exact:
            row_count = RowCountInfo.exact_count(
                self._fetch_scalar_int(
                    f"SELECT count(*) FROM {self._quoted_alias()}",
                )
            )
        dialect, warnings = _recorded_dialect(self._source)
        return InspectResult(
            source=_source_summary(self._source),
            dialect=dialect,
            columns=tuple(
                ColumnInfo(name=column_name, duckdb_type=duckdb_type)
                for column_name, duckdb_type in columns
            ),
            row_count=row_count,
            warnings=warnings,
        )

    def sample(self, *, limit: int = 10) -> SampleResult:
        """Return at most ``limit`` rows, binding the limit as a SQL value."""

        if limit <= 0:
            raise ValueError("Sample limit must be greater than zero.")
        self._prepare()
        result = self._query(
            f"SELECT * FROM {self._quoted_alias()} LIMIT ?",
            (limit,),
        )
        return SampleResult(
            source=_source_summary(self._source),
            limit=limit,
            columns=result.columns,
            rows=result.rows,
            warnings=(),
        )

    def profile(self) -> ProfileResult:
        """Return established full-scan aggregate metrics for the source."""

        self._prepare()
        columns = self._columns()
        row_count = self._fetch_scalar_int(
            f"SELECT count(*) FROM {self._quoted_alias()}",
        )
        column_profiles = tuple(
            self._profile_column(
                column_name=column_name,
                duckdb_type=duckdb_type,
                row_count=row_count,
            )
            for column_name, duckdb_type in columns
        )
        return ProfileResult(
            source=_source_summary(self._source),
            row_count=row_count,
            column_count=len(columns),
            duplicate_row_count=self._duplicate_row_count(columns),
            columns=column_profiles,
            warnings=(),
        )

    def _prepare(self) -> None:
        self._engine.operation_context.checkpoint()
        if self._prepared:
            return
        self._engine.prepare_sources((self._source,))
        if self._source.alias not in self._engine.registered_aliases:
            raise SourceBindingError(
                "source_bind_failed",
                "Engine source preparation did not register the requested alias.",
                kind=self._source.source_kind,
                alias=self._source.alias,
                suggestion="Start a new LocalQL operation.",
            )
        self._prepared = True

    def _columns(self) -> tuple[tuple[str, str], ...]:
        result = self._query(
            f"DESCRIBE SELECT * FROM {self._quoted_alias()}",
        )
        columns: list[tuple[str, str]] = []
        for row in result.rows:
            if len(row) < 2 or not isinstance(row[0], str) or not isinstance(row[1], str):
                raise QueryExecutionError(
                    "DuckDB returned invalid source column metadata.",
                    suggestion="Check that the source has a readable schema.",
                )
            columns.append((row[0], row[1]))
        return tuple(columns)

    def _profile_column(
        self,
        *,
        column_name: str,
        duckdb_type: str,
        row_count: int,
    ) -> ColumnProfile:
        quoted_column = _quote_column(column_name)
        result = self._query(
            f"""
                SELECT
                    count({quoted_column}) AS non_null_count,
                    count(*) - count({quoted_column}) AS null_count,
                    count(DISTINCT {quoted_column}) AS distinct_count,
                    min({quoted_column}) AS min_value,
                    max({quoted_column}) AS max_value
                FROM {self._quoted_alias()}
            """
        )
        row = _single_row(result)
        non_null_count = _integer_result(row[0])
        null_count = _integer_result(row[1])
        distinct_count = _integer_result(row[2])
        null_percentage = 0.0 if row_count == 0 else round((null_count / row_count) * 100, 3)
        return ColumnProfile(
            name=column_name,
            duckdb_type=duckdb_type,
            non_null_count=non_null_count,
            null_count=null_count,
            null_percentage=null_percentage,
            distinct_count=distinct_count,
            min=row[3],
            max=row[4],
        )

    def _duplicate_row_count(
        self,
        columns: tuple[tuple[str, str], ...],
    ) -> int:
        if not columns:
            return max(
                self._fetch_scalar_int(
                    f"SELECT count(*) FROM {self._quoted_alias()}",
                )
                - 1,
                0,
            )
        quoted_columns = ", ".join(_quote_column(column_name) for column_name, _ in columns)
        return self._fetch_scalar_int(
            f"""
                SELECT coalesce(sum(row_count - 1), 0)
                FROM (
                    SELECT count(*) AS row_count
                    FROM {self._quoted_alias()}
                    GROUP BY {quoted_columns}
                    HAVING count(*) > 1
                )
            """
        )

    def _fetch_scalar_int(
        self,
        query: str,
        params: Sequence[object] | None = None,
    ) -> int:
        result = self._query(query, params)
        if not result.rows:
            return 0
        value = result.rows[0][0]
        return 0 if value is None else _integer_result(value)

    def _query(
        self,
        query: str,
        params: Sequence[object] | None = None,
    ) -> QueryResult:
        result = self._engine.query(query, params)
        self._engine.operation_context.checkpoint()
        return result

    def _quoted_alias(self) -> str:
        return quote_identifier(self._source.alias)


def _quote_column(column_name: str) -> str:
    if not column_name:
        raise QueryExecutionError(
            "DuckDB returned an invalid empty source column name.",
            suggestion="Check that the source has a readable schema.",
        )
    return quote_identifier(column_name)


def _single_row(result: QueryResult) -> tuple[object, ...]:
    if not result.rows:
        raise QueryExecutionError(
            "DuckDB returned no aggregate row for the source.",
            suggestion="Check that the source is a readable table.",
        )
    return result.rows[0]


def _integer_result(value: object) -> int:
    if not isinstance(value, int):
        raise QueryExecutionError(
            "DuckDB returned an invalid aggregate value for the source.",
            suggestion="Check that the source is a readable table.",
        )
    return value


def _source_summary(source: ResolvedSource) -> dict[str, object]:
    fingerprint = source.fingerprint
    if fingerprint is None:
        raise SourceIdentityError(
            "source_bind_failed",
            "Resolved source identity is unavailable.",
            kind=source.source_kind,
            alias=source.alias,
            suggestion="Resolve the source again before running the operation.",
        )
    return {
        "display_path": source.requested_locator,
        "resolved_path": source.canonical_locator,
        "size_bytes": fingerprint.size_bytes,
        "modified_at": fingerprint.modified_at,
        "fingerprint": fingerprint.as_dict(),
    }


def _recorded_dialect(
    source: ResolvedSource,
) -> tuple[DialectInfo, tuple[str, ...]]:
    facts = {key: _thaw(value) for key, value in source.provider_facts.items}
    warnings_value = facts.get("dialect_warnings", [])
    warnings = (
        tuple(item for item in warnings_value if isinstance(item, str))
        if isinstance(warnings_value, list)
        else ()
    )
    header = facts.get("dialect_header")
    return (
        DialectInfo(
            delimiter=_optional_string(facts.get("dialect_delimiter")),
            quote=_optional_string(facts.get("dialect_quote")),
            escape=_optional_string(facts.get("dialect_escape")),
            header=header if isinstance(header, bool) else None,
            encoding=_optional_string(facts.get("dialect_encoding")),
        ),
        warnings,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _thaw(value: FrozenJSONValue) -> object:
    if isinstance(value, FrozenJSONArray):
        return [_thaw(item) for item in value.values]
    if isinstance(value, FrozenJSONObject):
        return {key: _thaw(item) for key, item in value.items}
    return value


def _resolved_source_from_csv(source: CSVSource) -> ResolvedSource:
    """Translate the public CSV facade through the default source runtime."""

    resolved = resolve_source_request(
        build_source_request(
            alias="csv_source",
            locator=str(source.path),
            anchor=source.path.parent,
            explicit_type="csv",
        ),
        operation=OperationContext(OperationToken()),
    )
    if not isinstance(resolved, ResolvedSource):
        raise RuntimeError("CSV compatibility resolution returned an invalid value.")
    if resolved.fingerprint != source.fingerprint:
        raise SourceIdentityError(
            "source_changed",
            "CSV source changed after submission.",
            kind="csv",
            alias="csv_source",
            suggestion="Submit the operation again to capture the current CSV source.",
        )
    return replace(resolved, requested_locator=source.display_path)
