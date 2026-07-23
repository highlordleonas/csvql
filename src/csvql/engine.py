"""DuckDB-backed query execution for CSVQL."""

import re
from collections.abc import Iterable, Sequence
from threading import RLock
from time import perf_counter

import duckdb

from csvql.csv_adapter import DEFAULT_SOURCE_ADAPTER_REGISTRY
from csvql.exceptions import CSVQLError, QueryExecutionError, SourceError
from csvql.models import QueryResult, TableSource
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.result_stream import ResultStream
from csvql.source import ResolvedSource, SourceSpec, source_alias_collision_key
from csvql.source_adapter import (
    PreparedBinding,
    SourceAdapter,
    SourceAdapterRegistry,
    require_capability,
)

_SOURCE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ALIAS_PREFIX = "__localql_"
_QUERY_FETCH_ROWS = 1000


class CSVQLEngine:
    """In-memory DuckDB engine that registers CSV files as queryable views."""

    def __init__(
        self,
        *,
        registry: SourceAdapterRegistry | None = None,
        operation: OperationContext | None = None,
    ) -> None:
        self._registry = registry or DEFAULT_SOURCE_ADAPTER_REGISTRY
        self._operation = operation or OperationContext(token=OperationToken())
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._bindings: list[PreparedBinding] = []
        self._alias_keys: set[str] = set()
        self._active_stream: ResultStream | None = None
        self._active_cursor: duckdb.DuckDBPyConnection | None = None
        self._closed = False
        self._lifecycle_lock = RLock()

    def __enter__(self) -> "CSVQLEngine":
        return self

    def __exit__(self, *exc_info: object) -> None:
        primary = exc_info[1] if len(exc_info) > 1 else None
        if isinstance(primary, BaseException):
            self._release_resources(primary=primary)
            return
        self.close()

    def close(self) -> None:
        """Close bindings in reverse order, then close the owned connection."""

        cleanup_failures = self._release_resources(primary=None)
        if cleanup_failures:
            raise CSVQLError(
                "LocalQL engine cleanup did not complete with certainty.",
                suggestion="Start a new LocalQL operation before retrying.",
            )

    def interrupt(self) -> None:
        """Request cancellation and best-effort interruption of live DuckDB work."""

        self._operation.request_cancel()

    def register_tables(self, table_sources: Iterable[TableSource]) -> None:
        """Resolve legacy CSV table sources and prepare them through the registry."""

        with self._lifecycle_lock:
            self._raise_if_closed()
            sources = tuple(table_sources)
            current_source: TableSource | None = None
            try:
                self._preflight_aliases(tuple(source.name for source in sources))
                resolved_sources: list[ResolvedSource] = []
                for source in sources:
                    current_source = source
                    self._operation.checkpoint()
                    source_path = source.path
                    spec = SourceSpec(
                        alias=source.name,
                        kind="csv",
                        locator=source_path.name,
                        anchor=source_path.parent,
                    )
                    adapter = self._select_adapter(spec)
                    adapter.validate_options(spec)
                    resolved_sources.append(adapter.resolve(spec, self._operation))
                current_source = None
                self._prepare_sources_locked(resolved_sources)
            except OperationCancelled as exc:
                self._release_resources(primary=exc)
                raise
            except SourceError as exc:
                public_error = self._legacy_register_error(
                    exc,
                    table_sources=sources,
                    current_source=current_source,
                )
                self._release_resources(primary=public_error)
                raise public_error from exc
            except BaseException as exc:
                self._release_resources(primary=exc)
                raise

    def prepare_sources(self, sources: Sequence[ResolvedSource]) -> None:
        """Preflight all required sources, then bind them in request order."""

        with self._lifecycle_lock:
            self._raise_if_closed()
            try:
                self._prepare_sources_locked(sources)
            except BaseException as exc:
                self._release_resources(primary=exc)
                raise

    def _prepare_sources_locked(self, sources: Sequence[ResolvedSource]) -> None:
        prepared = self._preflight_sources(sources)
        if not prepared:
            return
        connection = self._ensure_connection()
        self._operation.checkpoint()
        for adapter, source in prepared:
            self._operation.checkpoint()
            binding = adapter.bind(connection, source, self._operation)
            self._bindings.append(binding)
            self._validate_binding(binding, source)
            self._alias_keys.add(source.spec.alias_key)
            self._operation.checkpoint()

    def _legacy_register_error(
        self,
        exc: SourceError,
        *,
        table_sources: Sequence[TableSource],
        current_source: TableSource | None,
    ) -> CSVQLError:
        source_by_alias = {source.name: source for source in table_sources}
        failed_source = source_by_alias.get(exc.alias or "") or current_source
        alias = exc.alias or (failed_source.name if failed_source is not None else "source")
        source_path = str(failed_source.path) if failed_source is not None else "<unavailable>"
        return CSVQLError(
            f"Failed to register CSV table '{alias}' from {source_path}.",
            suggestion="Check that the file is a readable CSV with a header row.",
        )

    def query(self, sql: str, params: Sequence[object] | None = None) -> QueryResult:
        """Execute SQL and return all result rows."""

        stream = self.stream(sql, params)
        rows: list[tuple[object, ...]] = []
        primary: BaseException | None = None
        try:
            while True:
                batch = stream.fetch_rows(_QUERY_FETCH_ROWS)
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
                primary.add_note(
                    "Cleanup uncertainty: the active result cursor could not be closed."
                )
        return QueryResult(columns=stream.columns, rows=tuple(rows), elapsed_ms=stream.elapsed_ms)

    def stream(self, sql: str, params: Sequence[object] | None = None) -> ResultStream:
        """Execute SQL and return a private single-consumer result stream."""

        with self._lifecycle_lock:
            self._raise_if_closed(query=True)
            if self._active_stream is not None:
                raise QueryExecutionError(
                    "LocalQL engine already has an active result stream.",
                    suggestion="Close the current result stream before starting another query.",
                )
            started_at = perf_counter()
            connection: duckdb.DuckDBPyConnection | None = None
            cursor: duckdb.DuckDBPyConnection | None = None
            try:
                self._operation.checkpoint()
                connection = self._ensure_connection()
                cursor = connection.cursor()
                self._operation.checkpoint()
                cursor.execute(sql, params or [])
                self._operation.checkpoint()
                stream = ResultStream(
                    cursor=cursor,
                    operation=self._operation,
                    started_at=started_at,
                    close_owner=self._close_active_stream,
                    request_interrupt=self.interrupt,
                    now=perf_counter,
                )
                self._active_cursor = cursor
                self._active_stream = stream
                return stream
            except OperationCancelled as exc:
                if cursor is not None and cursor is not connection:
                    self._close_cursor(cursor)
                self._release_resources(primary=exc)
                raise
            except duckdb.Error as exc:
                if cursor is not None and cursor is not connection:
                    self._close_cursor(cursor)
                if self._operation.token.is_cancelled:
                    cancelled = OperationCancelled("Operation cancelled.")
                    self._release_resources(primary=cancelled)
                    raise cancelled from exc
                raise QueryExecutionError(
                    f"DuckDB query failed: {exc}",
                    suggestion="Check table names, column names, and SQL syntax.",
                ) from exc
            except BaseException as exc:
                if cursor is not None and cursor is not connection:
                    self._close_cursor(cursor)
                self._release_resources(primary=exc)
                raise

    def _preflight_sources(
        self,
        sources: Sequence[ResolvedSource],
    ) -> list[tuple[SourceAdapter, ResolvedSource]]:
        self._operation.checkpoint()
        self._preflight_aliases(tuple(source.spec.alias for source in sources))
        prepared: list[tuple[SourceAdapter, ResolvedSource]] = []
        for source in sources:
            spec = source.spec
            adapter = self._select_adapter(spec)
            adapter.validate_options(spec)
            require_capability(
                source.capabilities,
                "query",
                kind=spec.kind,
                alias=spec.alias,
            )
            if not source.canonical_locator:
                raise SourceError(
                    "source_missing",
                    "Resolved source locator is unavailable.",
                    kind=spec.kind,
                    alias=spec.alias,
                    suggestion="Resolve the source again before preparing it.",
                )
            if spec.kind == "csv" and source.fingerprint is None:
                raise SourceError(
                    "source_changed",
                    "CSV source identity is unavailable.",
                    kind=spec.kind,
                    alias=spec.alias,
                    suggestion="Submit the operation again to capture the current CSV source.",
                )
            self._operation.checkpoint()
            prepared.append((adapter, source))
        return prepared

    def _select_adapter(self, spec: SourceSpec) -> SourceAdapter:
        expected_descriptor = self._registry.descriptor(spec.kind)
        adapter = self._registry.create(spec.kind, capability="query")
        if adapter.descriptor is not expected_descriptor:
            raise SourceError(
                "source_bind_failed",
                "Selected source adapter descriptor does not match the registry.",
                kind=spec.kind,
                alias=spec.alias,
                suggestion="Start a new LocalQL operation with a valid adapter registry.",
            )
        return adapter

    def _validate_binding(
        self,
        binding: PreparedBinding,
        source: ResolvedSource,
    ) -> None:
        if binding.alias != source.spec.alias:
            raise SourceError(
                "source_bind_failed",
                "Prepared binding alias does not match the requested source.",
                kind=source.spec.kind,
                alias=source.spec.alias,
                suggestion="Start a new LocalQL operation with a valid source adapter.",
            )
        if binding.source is not source:
            raise SourceError(
                "source_bind_failed",
                "Prepared binding source does not match the resolved source.",
                kind=source.spec.kind,
                alias=source.spec.alias,
                suggestion="Start a new LocalQL operation with a valid source adapter.",
            )
        require_capability(
            binding.capabilities,
            "query",
            kind=source.spec.kind,
            alias=source.spec.alias,
        )

    def _preflight_aliases(self, aliases: tuple[str, ...]) -> None:
        incoming_keys: set[str] = set()
        for alias in aliases:
            if (
                not isinstance(alias, str)
                or not _SOURCE_ALIAS_PATTERN.fullmatch(alias)
                or source_alias_collision_key(alias).startswith(_RESERVED_ALIAS_PREFIX)
            ):
                raise SourceError(
                    "source_bind_failed",
                    "Source alias is invalid or reserved.",
                    alias=alias if isinstance(alias, str) else None,
                    suggestion="Use a unique SQL identifier outside the reserved prefix.",
                )
            alias_key = source_alias_collision_key(alias)
            if alias_key in self._alias_keys or alias_key in incoming_keys:
                raise SourceError(
                    "source_bind_failed",
                    "Source alias conflicts with an existing required source.",
                    alias=alias,
                    suggestion="Use a unique source alias.",
                )
            incoming_keys.add(alias_key)

    def _ensure_connection(self) -> duckdb.DuckDBPyConnection:
        with self._lifecycle_lock:
            self._raise_if_closed()
            if self._connection is None:
                connection = duckdb.connect(database=":memory:")
                self._connection = connection
                self._operation.attach_interrupt(connection.interrupt)
            return self._connection

    def _raise_if_closed(self, *, query: bool = False) -> None:
        if not self._closed:
            return
        error_type = QueryExecutionError if query else CSVQLError
        raise error_type(
            "LocalQL engine is closed.",
            suggestion="Create a new engine for another operation.",
        )

    def _release_resources(self, *, primary: BaseException | None) -> int:
        with self._lifecycle_lock:
            if self._closed:
                return 0
            connection = self._connection
            active_stream = self._active_stream
            self._active_stream = None
            self._active_cursor = None
            bindings = tuple(reversed(self._bindings))
            self._bindings.clear()
            self._alias_keys.clear()
            self._connection = None
            self._closed = True

        cursor_failures = 0
        if active_stream is not None:
            try:
                active_stream.close()
            except BaseException:
                cursor_failures = 1
        binding_failures = 0
        for binding in bindings:
            try:
                binding.close()
            except BaseException:
                binding_failures += 1

        connection_failures = 0
        if connection is not None:
            try:
                connection.close()
            except BaseException:
                connection_failures = 1
        self._operation.detach_interrupt()

        if primary is not None:
            if cursor_failures:
                primary.add_note(
                    "Cleanup uncertainty: the active result cursor could not be closed."
                )
            if binding_failures:
                primary.add_note(
                    "Cleanup uncertainty: one or more source bindings could not be closed."
                )
            if connection_failures:
                primary.add_note("Cleanup uncertainty: the engine connection could not be closed.")
        return cursor_failures + binding_failures + connection_failures

    def _close_active_stream(self) -> None:
        with self._lifecycle_lock:
            self._active_stream = None
            self._active_cursor = None

    def _close_cursor(self, cursor: duckdb.DuckDBPyConnection | None) -> int:
        if cursor is None:
            return 0
        try:
            cursor.close()
        except BaseException:
            return 1
        return 0
