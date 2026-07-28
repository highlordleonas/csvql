"""Format-neutral DuckDB session and relational query execution."""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock, get_ident
from time import perf_counter
from typing import cast
from uuid import uuid4

import duckdb

from csvql.exceptions import (
    CSVQLError,
    EngineSessionTaintedError,
    QueryExecutionError,
    SourceBindingError,
    SourceCleanupError,
)
from csvql.models import QueryResult, TableSource
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.result_stream import (
    CURSOR_CLEANUP_UNCERTAINTY_NOTE,
    ResultCursor,
    ResultStream,
)
from csvql.source import PreparedSources, ResolvedSource, source_alias_collision_key
from csvql.source_adapter import EngineDependencyState, StructuralCallback

_SOURCE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DUCKDB_EXTENSION_KEY_PATTERN = re.compile(r"^duckdb\.extension\.([a-z][a-z0-9_]*)$")
_RESERVED_ALIAS_PREFIX = "__localql_"
_QUERY_FETCH_ROWS = 1000


class EngineSessionState(StrEnum):
    """Lifecycle state of one DuckDB-backed LocalQL session."""

    CLEAN = "clean"
    CANCELLING = "cancelling"
    TAINTED = "tainted"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RegistrationToken:
    """Opaque engine-session-bound ownership token for one relation."""

    value: str
    engine_session_id: str
    alias_key: str


@dataclass(frozen=True, slots=True)
class _Registration:
    token: RegistrationToken
    alias: str
    unregister: StructuralCallback


class _PersistentResultSessionCursor:
    """Persistent child-session cursor with logical per-stream close semantics."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._cursor = connection.cursor()

    @property
    def description(self) -> Sequence[Sequence[object]] | None:
        return self._cursor.description

    def execute(
        self,
        sql: str,
        params: Sequence[object] | None = None,
    ) -> "_PersistentResultSessionCursor":
        self._cursor.execute(sql, params or [])
        return self

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        return self._cursor.fetchmany(size)

    def close(self) -> None:
        return

    def discard(self) -> None:
        self._cursor.close()

    def interrupt(self) -> None:
        self._cursor.interrupt()


class CSVQLEngine:
    """Public compatibility facade over one format-neutral DuckDB session."""

    def __init__(
        self,
        *,
        operation: OperationContext | None = None,
    ) -> None:
        self._operation = operation or OperationContext(token=OperationToken())
        self._session_id = uuid4().hex
        self._owner_thread_id = get_ident()
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._registrations: dict[str, _Registration] = {}
        self._alias_keys: dict[str, str] = {}
        self._retired_registration_tokens: set[str] = set()
        self._authorized_extension_keys: set[str] = set()
        self._loaded_extension_keys: set[str] = set()
        self._compatibility_scopes: list[PreparedSources] = []
        self._session_cursor: ResultCursor | None = None
        self._active_stream: ResultStream | None = None
        self._state = EngineSessionState.CLEAN
        self._lifecycle_lock = RLock()

    @property
    def session_id(self) -> str:
        """Return the opaque immutable identity of this engine session."""

        return self._session_id

    @property
    def operation_context(self) -> OperationContext:
        """Return the operation context shared by this compatibility facade."""

        return self._operation

    @property
    def state(self) -> EngineSessionState:
        """Return the engine-session lifecycle state."""

        return self._state

    @property
    def has_active_execution(self) -> bool:
        """Return whether a result stream currently owns the execution slot."""

        with self._lifecycle_lock:
            return self._active_stream is not None

    @property
    def is_tainted(self) -> bool:
        """Return whether terminal query state could not be established."""

        return self._state is EngineSessionState.TAINTED

    @property
    def registered_aliases(self) -> tuple[str, ...]:
        """Return registered aliases in deterministic registration order."""

        with self._lifecycle_lock:
            return tuple(registration.alias for registration in self._registrations.values())

    def __enter__(self) -> "CSVQLEngine":
        return self

    def __exit__(self, *exc_info: object) -> None:
        primary = exc_info[1] if len(exc_info) > 1 else None
        if isinstance(primary, BaseException):
            self._release_resources(primary=primary)
            return
        self.close()

    def assert_session_access(self) -> None:
        """Reject provider or binding use from a non-owner thread."""

        if get_ident() != self._owner_thread_id:
            raise SourceBindingError(
                "source_bind_failed",
                "Engine session cannot be used from a different thread.",
                suggestion="Prepare and use each source on the engine owner thread.",
            )

    def preflight_aliases(self, aliases: tuple[str, ...]) -> None:
        """Validate a complete incoming alias batch before provider work."""

        with self._lifecycle_lock:
            self.assert_session_access()
            self._raise_if_closed()
            incoming_keys: set[str] = set()
            for alias in aliases:
                if (
                    not isinstance(alias, str)
                    or not _SOURCE_ALIAS_PATTERN.fullmatch(alias)
                    or source_alias_collision_key(alias).startswith(_RESERVED_ALIAS_PREFIX)
                ):
                    raise SourceBindingError(
                        "source_bind_failed",
                        "Source alias is invalid or reserved.",
                        alias=alias if isinstance(alias, str) else None,
                        suggestion=("Use a unique SQL identifier outside the reserved prefix."),
                    )
                alias_key = source_alias_collision_key(alias)
                if alias_key in self._alias_keys or alias_key in incoming_keys:
                    raise SourceBindingError(
                        "source_bind_failed",
                        "Source alias conflicts with an existing registered source.",
                        alias=alias,
                        suggestion="Use a unique source alias.",
                    )
                incoming_keys.add(alias_key)

    def inspect_dependency(
        self,
        dependency_key: str | None,
        dependency_kind: str | None,
        *,
        operation: OperationContext,
    ) -> EngineDependencyState:
        """Inspect one selected runtime dependency without loading or installing it."""

        with self._lifecycle_lock:
            self.assert_session_access()
            self._raise_if_closed()
            self._raise_if_tainted()
            if self._active_stream is not None:
                raise SourceBindingError(
                    "source_bind_failed",
                    "Source dependencies cannot be inspected during active execution.",
                    suggestion="Wait for the active query to finish.",
                )
            operation.checkpoint()
            if dependency_key is None:
                if dependency_kind is not None:
                    raise SourceBindingError(
                        "source_bind_failed",
                        "Source dependency metadata is inconsistent.",
                    )
                return EngineDependencyState(
                    dependency_key=None,
                    available=True,
                    dependency_version=None,
                    duckdb_version=duckdb.__version__,
                )
            if dependency_kind == "builtin":
                return EngineDependencyState(
                    dependency_key=dependency_key,
                    available=True,
                    dependency_version=None,
                    duckdb_version=duckdb.__version__,
                )
            match = _DUCKDB_EXTENSION_KEY_PATTERN.fullmatch(dependency_key)
            if dependency_kind != "duckdb_extension" or match is None:
                return EngineDependencyState(
                    dependency_key=dependency_key,
                    available=False,
                    dependency_version=None,
                    duckdb_version=duckdb.__version__,
                )
            connection = self._ensure_connection()
            try:
                row = connection.execute(
                    """
                    SELECT
                        installed,
                        loaded,
                        extension_version,
                        install_mode
                    FROM duckdb_extensions()
                    WHERE extension_name = ?
                    """,
                    [match.group(1)],
                ).fetchone()
            except duckdb.Error as exc:
                raise SourceBindingError(
                    "source_bind_failed",
                    "Selected source dependency availability could not be inspected.",
                    suggestion="Start a new LocalQL engine session and retry.",
                ) from exc
            operation.checkpoint()
            if row is None:
                return EngineDependencyState(
                    dependency_key=dependency_key,
                    available=False,
                    dependency_version=None,
                    duckdb_version=duckdb.__version__,
                )
            installed, loaded, extension_version, install_mode = row
            available = bool(installed or loaded)
            dependency_version = None
            if available:
                raw_version = extension_version or install_mode or "available"
                dependency_version = str(raw_version)
                self._authorized_extension_keys.add(dependency_key)
                if loaded:
                    self._loaded_extension_keys.add(dependency_key)
            return EngineDependencyState(
                dependency_key=dependency_key,
                available=available,
                dependency_version=dependency_version,
                duckdb_version=duckdb.__version__,
            )

    def load_installed_extension(
        self,
        dependency_key: str,
        *,
        operation: OperationContext,
    ) -> None:
        """Load one previously inspected installed extension without acquisition."""

        with self._lifecycle_lock:
            self.assert_session_access()
            self._raise_if_closed()
            self._raise_if_tainted()
            if self._active_stream is not None:
                raise SourceBindingError(
                    "source_bind_failed",
                    "A source extension cannot be loaded during active execution.",
                    suggestion="Wait for the active query to finish.",
                )
            match = _DUCKDB_EXTENSION_KEY_PATTERN.fullmatch(dependency_key)
            if match is None or dependency_key not in self._authorized_extension_keys:
                raise SourceBindingError(
                    "source_bind_failed",
                    "Source extension load was not authorized by dependency inspection.",
                    suggestion="Prepare the selected source again in this engine session.",
                )
            if dependency_key in self._loaded_extension_keys:
                return
            operation.checkpoint()
            connection = self._ensure_connection()
            try:
                connection.load_extension(match.group(1))
            except duckdb.Error as exc:
                raise SourceBindingError(
                    "source_bind_failed",
                    "The installed source extension could not be loaded.",
                    suggestion="Verify the extension matches this DuckDB runtime.",
                ) from exc
            self._loaded_extension_keys.add(dependency_key)
            operation.checkpoint()

    def register_relation(
        self,
        *,
        alias: str,
        register: StructuralCallback,
        unregister: StructuralCallback,
        operation: OperationContext,
    ) -> RegistrationToken:
        """Register one provider-owned relation under an opaque cleanup token."""

        with self._lifecycle_lock:
            self.assert_session_access()
            self._raise_if_closed()
            self._raise_if_tainted()
            if self._active_stream is not None:
                raise SourceBindingError(
                    "source_bind_failed",
                    "A source cannot be registered while the engine is executing.",
                    alias=alias,
                    suggestion="Wait for the active query to finish.",
                )
            self.preflight_aliases((alias,))
            operation.checkpoint()
            connection = self._ensure_connection()
            register(connection)
            token = RegistrationToken(
                value=uuid4().hex,
                engine_session_id=self._session_id,
                alias_key=source_alias_collision_key(alias),
            )
            self._registrations[token.value] = _Registration(
                token=token,
                alias=alias,
                unregister=unregister,
            )
            self._alias_keys[token.alias_key] = token.value
            try:
                operation.checkpoint()
            except OperationCancelled:
                cleanup_operation = OperationContext(OperationToken())
                self.unregister_relation(token, operation=cleanup_operation)
                raise
            return token

    def unregister_relation(
        self,
        registration_token: object,
        *,
        operation: OperationContext,
    ) -> None:
        """Remove exactly one token-owned relation after execution is terminal."""

        with self._lifecycle_lock:
            self.assert_session_access()
            if not isinstance(registration_token, RegistrationToken):
                raise SourceBindingError(
                    "source_bind_failed",
                    "Source registration token is invalid.",
                    suggestion="Release sources through their owning binding.",
                )
            if registration_token.engine_session_id != self._session_id:
                raise SourceBindingError(
                    "source_bind_failed",
                    "Source registration belongs to a different engine session.",
                    suggestion="Release sources through their owning engine session.",
                )
            if registration_token.value in self._retired_registration_tokens:
                return
            self._raise_if_closed()
            self._raise_if_tainted()
            if self._active_stream is not None:
                raise SourceBindingError(
                    "source_bind_failed",
                    "Source relation cannot be removed during active execution.",
                    suggestion="Wait for the query terminal barrier before cleanup.",
                )
            registration = self._registrations.get(registration_token.value)
            if registration is None:
                raise SourceBindingError(
                    "source_bind_failed",
                    "Source registration token is unknown.",
                    suggestion="Release sources through their owning binding.",
                )
            operation.checkpoint()
            connection = self._connection
            if connection is not None:
                registration.unregister(connection)
            self._registrations.pop(registration_token.value, None)
            self._alias_keys.pop(registration_token.alias_key, None)
            self._retired_registration_tokens.add(registration_token.value)

    def close(self) -> None:
        """Close the owned DuckDB session after application source release."""

        cleanup_failures = self._release_resources(primary=None)
        if cleanup_failures:
            raise SourceCleanupError(
                "source_cleanup_failed",
                "LocalQL engine cleanup did not complete with certainty.",
                suggestion="Start a new LocalQL operation before retrying.",
            )

    def interrupt(self) -> None:
        """Request cancellation and best-effort interruption of live DuckDB work."""

        # The cursor executes while the lifecycle lock is held. Request the
        # attached DuckDB interrupt before acquiring that lock so another
        # thread can stop a query that has not returned a ResultStream yet.
        self._operation.request_cancel()
        with self._lifecycle_lock:
            if self._state is EngineSessionState.CLEAN:
                self._state = EngineSessionState.CANCELLING

    def prepare_sources(self, sources: Sequence[ResolvedSource]) -> None:
        """Compatibility facade over coordinator-owned source preparation."""

        from csvql.source_runtime import prepare_resolved_sources

        resolved_sources = tuple(sources)
        if not resolved_sources:
            return
        prepared = prepare_resolved_sources(
            resolved_sources,
            engine_session=self,
            operation=self._operation,
        )
        self._compatibility_scopes.append(prepared)

    def register_tables(self, table_sources: Iterable[TableSource]) -> None:
        """Translate retained CSV table facades into explicit source requests."""

        from csvql.source import build_source_request
        from csvql.source_runtime import (
            prepare_source_requests,
            raise_preparation_failure,
        )

        sources = tuple(table_sources)
        if not sources:
            return
        requests = tuple(
            build_source_request(
                alias=source.name,
                locator=str(source.path),
                anchor=source.path.parent,
                explicit_type="csv",
            )
            for source in sources
        )
        outcome = prepare_source_requests(
            requests,
            engine_session=self,
            operation=self._operation,
        )
        from csvql.source import SourcePreparationFailure

        if isinstance(outcome, SourcePreparationFailure):
            raise_preparation_failure(outcome, requests=requests)
        self._compatibility_scopes.append(outcome)

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
                _add_cleanup_note(primary)
        return QueryResult(
            columns=stream.columns,
            rows=tuple(rows),
            elapsed_ms=stream.elapsed_ms,
        )

    def stream(
        self,
        sql: str,
        params: Sequence[object] | None = None,
        *,
        on_terminal: Callable[[], None] | None = None,
    ) -> ResultStream:
        """Execute SQL and return one private single-consumer result stream."""

        with self._lifecycle_lock:
            self.assert_session_access()
            self._raise_if_closed(query=True)
            self._raise_if_tainted(query=True)
            if self._active_stream is not None:
                raise QueryExecutionError(
                    "LocalQL engine already has an active result stream.",
                    suggestion="Close the current result stream before starting another query.",
                )
            started_at = perf_counter()
            connection: duckdb.DuckDBPyConnection | None = None
            cursor: ResultCursor | None = None
            execution_started = False
            try:
                self._operation.checkpoint()
                connection = self._ensure_connection()
                cursor = self._ensure_session_cursor(connection)
                self._operation.attach_interrupt(_interrupt_callback(cursor, connection))
                self._operation.checkpoint()
                self._operation.begin_execution()
                execution_started = True
                cursor.execute(sql, params or [])
                self._operation.checkpoint()
                stream = ResultStream(
                    cursor=cursor,
                    operation=self._operation,
                    started_at=started_at,
                    close_owner=lambda: self._close_active_stream(on_terminal),
                    request_interrupt=self.interrupt,
                    now=perf_counter,
                    discard_cursor=self._discard_active_result_session,
                )
                self._active_stream = stream
                return stream
            except OperationCancelled as exc:
                self._finish_failed_execution(
                    cursor=cursor,
                    execution_started=execution_started,
                    primary=exc,
                )
                raise
            except duckdb.Error as exc:
                if self._operation.token.is_cancelled:
                    cancelled = OperationCancelled("Operation cancelled.")
                    self._finish_failed_execution(
                        cursor=cursor,
                        execution_started=execution_started,
                        primary=cancelled,
                    )
                    raise cancelled from exc
                public_error = QueryExecutionError(
                    f"DuckDB query failed: {exc}",
                    suggestion="Check table names, column names, and SQL syntax.",
                )
                if self._finish_failed_execution(
                    cursor=cursor,
                    execution_started=execution_started,
                    primary=public_error,
                ):
                    public_error = QueryExecutionError(
                        "DuckDB query failed and terminal cursor cleanup was uncertain.",
                        suggestion="Close this LocalQL engine before retrying.",
                    )
                    _add_cleanup_note(public_error)
                    self._mark_tainted()
                    raise public_error from exc
                raise public_error from exc
            except BaseException as exc:
                self._finish_failed_execution(
                    cursor=cursor,
                    execution_started=execution_started,
                    primary=exc,
                )
                raise

    def _finish_failed_execution(
        self,
        *,
        cursor: ResultCursor | None,
        execution_started: bool,
        primary: BaseException,
    ) -> bool:
        """Establish terminal state after a failed query start when provable."""

        cleanup_failed = cursor is not None and bool(self._discard_session_cursor())
        if cleanup_failed:
            self._mark_tainted()
            _add_cleanup_note(primary)
            return True
        if execution_started:
            self._operation.mark_terminal()
            if self._state is EngineSessionState.CANCELLING:
                self._state = EngineSessionState.CLEAN
        else:
            self._restore_connection_interrupt()
        return False

    def _ensure_connection(self) -> duckdb.DuckDBPyConnection:
        self._raise_if_closed()
        if self._connection is None:
            connection = duckdb.connect(
                database=":memory:",
                config={
                    "autoinstall_known_extensions": "false",
                    "autoload_known_extensions": "false",
                },
            )
            self._connection = connection
            self._operation.attach_interrupt(connection.interrupt)
        return self._connection

    def _ensure_session_cursor(
        self,
        connection: duckdb.DuckDBPyConnection,
    ) -> ResultCursor:
        self._raise_if_closed()
        if self._session_cursor is None:
            self._session_cursor = _open_result_cursor(connection)
        return self._session_cursor

    def _raise_if_closed(self, *, query: bool = False) -> None:
        if self._state is not EngineSessionState.CLOSED:
            return
        error_type = QueryExecutionError if query else CSVQLError
        raise error_type(
            "LocalQL engine is closed.",
            suggestion="Create a new engine for another operation.",
        )

    def _raise_if_tainted(self, *, query: bool = False) -> None:
        if self._state is not EngineSessionState.TAINTED:
            return
        if query:
            raise QueryExecutionError(
                "LocalQL engine session is tainted.",
                suggestion="Close the owning engine session.",
            )
        raise EngineSessionTaintedError(
            "engine_session_tainted",
            "LocalQL engine session is tainted.",
            suggestion="Close the owning engine session.",
        )

    def _mark_tainted(self) -> None:
        if self._state is not EngineSessionState.CLOSED:
            self._state = EngineSessionState.TAINTED

    def _release_resources(self, *, primary: BaseException | None) -> int:
        with self._lifecycle_lock:
            if self._state is EngineSessionState.CLOSED:
                return 0
            connection = self._connection
            session_cursor = self._session_cursor
            active_stream = self._active_stream
            compatibility_scopes = tuple(reversed(self._compatibility_scopes))
            self._compatibility_scopes.clear()

        cursor_failures = 0
        if active_stream is not None:
            try:
                active_stream.close()
            except BaseException:
                cursor_failures = 1
        if session_cursor is not None and _cursor_survives_stream_close(session_cursor):
            cursor_failures += self._close_cursor(session_cursor)
        elif active_stream is None and session_cursor is not None:
            cursor_failures += self._close_cursor(session_cursor)

        binding_failures = 0
        if compatibility_scopes:
            from csvql.source_runtime import default_source_components

            coordinator = default_source_components().coordinator
            for prepared in compatibility_scopes:
                report = coordinator.release(prepared)
                binding_failures += len(report.failures)

        connection_failures = 0
        if connection is not None:
            try:
                connection.close()
            except BaseException:
                connection_failures = 1
        self._operation.detach_interrupt()
        with self._lifecycle_lock:
            self._active_stream = None
            self._connection = None
            self._session_cursor = None
            self._registrations.clear()
            self._alias_keys.clear()
            self._authorized_extension_keys.clear()
            self._loaded_extension_keys.clear()
            self._state = EngineSessionState.CLOSED

        if primary is not None:
            if cursor_failures:
                _add_cleanup_note(primary)
            if binding_failures:
                primary.add_note(
                    "Cleanup uncertainty: one or more source bindings could not be closed."
                )
            if connection_failures:
                primary.add_note("Cleanup uncertainty: the engine connection could not be closed.")
        return cursor_failures + binding_failures + connection_failures

    def _close_active_stream(
        self,
        on_terminal: Callable[[], None] | None,
    ) -> None:
        with self._lifecycle_lock:
            self._active_stream = None
            if self._session_cursor is not None and not _cursor_survives_stream_close(
                self._session_cursor
            ):
                self._session_cursor = None
            if self._state is EngineSessionState.CANCELLING:
                self._state = EngineSessionState.CLEAN
        self._operation.mark_terminal()
        self._restore_connection_interrupt()
        if on_terminal is not None:
            on_terminal()

    def _close_cursor(self, cursor: ResultCursor | None) -> int:
        if cursor is None:
            return 0
        try:
            _discard_cursor(cursor)
        except BaseException:
            return 1
        return 0

    def _discard_session_cursor(self) -> int:
        cursor = self._session_cursor
        self._session_cursor = None
        self._active_stream = None
        failure = self._close_cursor(cursor)
        self._restore_connection_interrupt()
        return failure

    def _discard_active_result_session(self) -> None:
        with self._lifecycle_lock:
            cursor = self._session_cursor
        if cursor is None:
            return
        try:
            _discard_cursor(cursor)
        except BaseException:
            self._mark_tainted()
            raise
        with self._lifecycle_lock:
            if self._session_cursor is cursor:
                self._session_cursor = None

    def _restore_connection_interrupt(self) -> None:
        with self._lifecycle_lock:
            if self._state is EngineSessionState.CLOSED or self._connection is None:
                return
            self._operation.attach_interrupt(self._connection.interrupt)


def _add_cleanup_note(primary: BaseException) -> None:
    notes = getattr(primary, "__notes__", ())
    if CURSOR_CLEANUP_UNCERTAINTY_NOTE not in notes:
        primary.add_note(CURSOR_CLEANUP_UNCERTAINTY_NOTE)


def _open_result_cursor(
    connection: duckdb.DuckDBPyConnection,
) -> ResultCursor:
    return _PersistentResultSessionCursor(connection)


def _discard_cursor(cursor: ResultCursor) -> None:
    if isinstance(cursor, _PersistentResultSessionCursor):
        cursor.discard()
        return
    cursor.close()


def _cursor_survives_stream_close(cursor: ResultCursor) -> bool:
    return isinstance(cursor, _PersistentResultSessionCursor)


def _interrupt_callback(
    cursor: ResultCursor,
    connection: duckdb.DuckDBPyConnection,
) -> Callable[[], None]:
    interrupt = cast(Callable[[], None] | None, getattr(cursor, "interrupt", None))
    if callable(interrupt):
        return interrupt
    return connection.interrupt
