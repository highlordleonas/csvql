"""Shared relational operations over one engine-prepared source binding."""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from csvql.csv_adapter import CSV_CAPABILITIES
from csvql.engine import CSVQLEngine
from csvql.exceptions import QueryExecutionError, SourceError
from csvql.models import (
    ColumnInfo,
    ColumnProfile,
    InspectResult,
    ProfileResult,
    QueryResult,
    RowCountInfo,
    SampleResult,
)
from csvql.source import CSVSource, ResolvedSource, SourceCapability, SourceSpec
from csvql.source_adapter import PreparedBinding, SourceAdapter, require_capability
from csvql.sql_utils import quote_identifier


class SourceOperations:
    """Run source-neutral relational operations over one prepared binding.

    The accepted Task 7 boundary does not permit widening ``CSVQLEngine``. This
    class therefore contains the only direct access to the engine's private
    registry, prepared-binding list, lifecycle guard, and operation context.
    Those seams supply adapter metadata, effective capabilities, terminal reuse
    protection, and shared cancellation without widening the engine API.
    """

    def __init__(self, engine: CSVQLEngine, source: ResolvedSource) -> None:
        self._engine = engine
        self._source = source
        self._prepared = False
        self._binding: PreparedBinding | None = None

    def inspect(self, *, exact: bool = False) -> InspectResult:
        """Inspect schema and adapter metadata, optionally counting all rows."""

        with self._engine._lifecycle_lock:
            self._require("inspect")
            if exact:
                self._require("exact_count")
            binding = self._prepare()
            self._require_effective(binding, "inspect")
            if exact:
                self._require_effective(binding, "exact_count")
            metadata = self._adapter("inspect").inspect_metadata(
                self._source,
                self._engine._operation,
            )
            columns = self._columns()
            row_count = RowCountInfo.not_counted()
            if exact:
                row_count = RowCountInfo.exact_count(
                    self._fetch_scalar_int(
                        f"SELECT count(*) FROM {self._quoted_alias()}",
                    )
                )
            return InspectResult(
                source=_source_summary(self._source),
                dialect=metadata.dialect,
                columns=tuple(
                    ColumnInfo(name=column_name, duckdb_type=duckdb_type)
                    for column_name, duckdb_type in columns
                ),
                row_count=row_count,
                warnings=metadata.warnings,
            )

    def sample(self, *, limit: int = 10) -> SampleResult:
        """Return at most ``limit`` rows, binding the limit as a SQL value."""

        with self._engine._lifecycle_lock:
            if limit <= 0:
                raise ValueError("Sample limit must be greater than zero.")
            self._require("sample")
            binding = self._prepare()
            self._require_effective(binding, "sample")
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

        with self._engine._lifecycle_lock:
            self._require("profile")
            binding = self._prepare()
            self._require_effective(binding, "profile")
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

    def _require(self, operation: SourceCapability) -> None:
        if self._prepared:
            self._engine._raise_if_closed()
        require_capability(
            self._source.capabilities,
            operation,
            kind=self._source.spec.kind,
            alias=self._source.spec.alias,
        )
        descriptor = self._engine._registry.descriptor(self._source.spec.kind)
        require_capability(
            descriptor.capabilities,
            operation,
            kind=self._source.spec.kind,
            alias=self._source.spec.alias,
        )

    def _prepare(self) -> PreparedBinding:
        if self._prepared:
            self._engine._raise_if_closed()
            self._engine._operation.checkpoint()
            if self._binding is None:
                raise SourceError(
                    "source_bind_failed",
                    "Prepared source binding identity is unavailable.",
                    kind=self._source.spec.kind,
                    alias=self._source.spec.alias,
                    suggestion="Start a new LocalQL operation.",
                )
            return self._binding

        prior_bindings = tuple(self._engine._bindings)
        try:
            self._engine.prepare_sources((self._source,))
        except duckdb.Error as exc:
            raise SourceError(
                "source_bind_failed",
                "Failed to prepare the source operation.",
                kind=self._source.spec.kind,
                alias=self._source.spec.alias,
                suggestion="Check that the source is a readable table.",
            ) from exc
        current_bindings = tuple(self._engine._bindings)
        if len(current_bindings) != len(prior_bindings) + 1 or any(
            current is not prior
            for current, prior in zip(
                current_bindings[: len(prior_bindings)],
                prior_bindings,
                strict=True,
            )
        ):
            raise SourceError(
                "source_bind_failed",
                "Engine source preparation did not produce one identifiable binding.",
                kind=self._source.spec.kind,
                alias=self._source.spec.alias,
                suggestion="Start a new LocalQL operation.",
            )
        binding = current_bindings[-1]
        self._binding = binding
        self._prepared = True
        return binding

    def _require_effective(
        self,
        binding: PreparedBinding,
        operation: SourceCapability,
    ) -> None:
        require_capability(
            binding.capabilities,
            operation,
            kind=self._source.spec.kind,
            alias=self._source.spec.alias,
        )

    def _adapter(self, capability: SourceCapability) -> SourceAdapter:
        registry = self._engine._registry
        expected_descriptor = registry.descriptor(self._source.spec.kind)
        adapter = registry.create(self._source.spec.kind, capability=capability)
        if adapter.descriptor is not expected_descriptor:
            raise SourceError(
                "source_bind_failed",
                "Selected source adapter descriptor does not match the registry.",
                kind=self._source.spec.kind,
                alias=self._source.spec.alias,
                suggestion="Start a new LocalQL operation with a valid adapter registry.",
            )
        return adapter

    def _columns(self) -> tuple[tuple[str, str], ...]:
        result = self._query(
            f"DESCRIBE SELECT * FROM {self._quoted_alias()}",
        )
        columns: list[tuple[str, str]] = []
        for row in result.rows:
            if len(row) < 2 or not isinstance(row[0], str) or not isinstance(row[1], str):
                raise QueryExecutionError(
                    "DuckDB returned invalid source column metadata.",
                    suggestion="Check that the source has a readable header row.",
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

    def _duplicate_row_count(self, columns: tuple[tuple[str, str], ...]) -> int:
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
        self._engine._operation.checkpoint()
        return result

    def _quoted_alias(self) -> str:
        # SourceSpec validates the alias before resolution; quoting preserves its exact spelling.
        return quote_identifier(self._source.spec.alias)


def _quote_column(column_name: str) -> str:
    if not column_name:
        raise QueryExecutionError(
            "DuckDB returned an invalid empty source column name.",
            suggestion="Check that the source has a readable header row.",
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
        raise SourceError(
            "source_bind_failed",
            "Resolved source identity is unavailable.",
            kind=source.spec.kind,
            alias=source.spec.alias,
            suggestion="Resolve the source again before running the operation.",
        )
    return {
        "display_path": source.spec.locator,
        "resolved_path": source.canonical_locator,
        "size_bytes": fingerprint.size_bytes,
        "modified_at": fingerprint.modified_at,
        "fingerprint": fingerprint.as_dict(),
    }


def _resolved_source_from_csv(source: CSVSource) -> ResolvedSource:
    """Translate the public CSV facade without re-resolving its captured identity."""

    return ResolvedSource(
        spec=SourceSpec(
            alias="csv_source",
            kind="csv",
            locator=source.display_path,
            anchor=source.path.parent,
        ),
        canonical_locator=str(source.path),
        fingerprint=source.fingerprint,
        capabilities=CSV_CAPABILITIES,
    )
