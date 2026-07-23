from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from types import MethodType

import duckdb
import pytest

from csvql.csv_adapter import CSV_CAPABILITIES, CSVSourceAdapter
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError, SourceError
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    ResolvedSource,
    SourceCapabilities,
    SourceCapability,
    SourceCapabilityStatus,
    SourceSpec,
)
from csvql.source_adapter import (
    AdapterInspectionMetadata,
    PreparedBinding,
    SourceAdapterDescriptor,
    SourceAdapterRegistry,
)
from csvql.source_operations import SourceOperations


def _resolved_csv(
    tmp_path: Path,
    *,
    text: str = "order_id,status\nORD-1,paid\nORD-2,pending\n",
    capabilities: SourceCapabilities = CSV_CAPABILITIES,
) -> ResolvedSource:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(text, encoding="utf-8")
    source = CSVSourceAdapter().resolve(
        SourceSpec(
            alias="orders",
            kind="csv",
            locator=str(csv_path),
            anchor=tmp_path,
        ),
        OperationContext(token=OperationToken()),
    )
    return ResolvedSource(
        spec=source.spec,
        canonical_locator=source.canonical_locator,
        fingerprint=source.fingerprint,
        capabilities=capabilities,
    )


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (
            lambda operations: operations.inspect(),
            {
                "columns": ("order_id", "status"),
                "row_count": None,
                "delimiter": ",",
            },
        ),
        (
            lambda operations: operations.inspect(exact=True),
            {
                "columns": ("order_id", "status"),
                "row_count": 2,
                "delimiter": ",",
            },
        ),
        (
            lambda operations: operations.sample(limit=1),
            {
                "columns": ("order_id", "status"),
                "rows": (("ORD-1", "paid"),),
            },
        ),
        (
            lambda operations: operations.profile(),
            {
                "row_count": 2,
                "column_count": 2,
                "duplicate_row_count": 0,
            },
        ),
    ],
    ids=("inspect", "exact_count", "sample", "profile"),
)
def test_common_csv_operation_matrix(
    tmp_path: Path,
    operation: Callable[[SourceOperations], object],
    expected: dict[str, object],
) -> None:
    source = _resolved_csv(tmp_path)

    with CSVQLEngine() as engine:
        result = operation(SourceOperations(engine, source))

    if "columns" in expected:
        columns = tuple(
            column.name if hasattr(column, "name") else column for column in result.columns
        )
        assert columns == expected["columns"]
    if "row_count" in expected:
        row_count = result.row_count
        value = row_count.value if hasattr(row_count, "value") else row_count
        assert value == expected["row_count"]
    if "delimiter" in expected:
        assert result.dialect.delimiter == expected["delimiter"]
    if "rows" in expected:
        assert result.rows == expected["rows"]
    if "column_count" in expected:
        assert result.column_count == expected["column_count"]
    if "duplicate_row_count" in expected:
        assert result.duplicate_row_count == expected["duplicate_row_count"]


def test_sample_binds_limit_as_a_value_parameter(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    observed: list[tuple[str, tuple[object, ...] | None]] = []

    with CSVQLEngine() as engine:
        original_query = engine.query

        def recording_query(
            self: CSVQLEngine,
            sql: str,
            params: tuple[object, ...] | None = None,
        ):
            observed.append((sql, params))
            return original_query(sql, params)

        engine.query = MethodType(recording_query, engine)
        result = SourceOperations(engine, source).sample(limit=2)

    sample_sql, params = observed[-1]
    assert "LIMIT ?" in sample_sql
    assert "LIMIT 2" not in sample_sql
    assert params == (2,)
    assert len(result.rows) == 2


def test_sample_preserves_positive_limit_validation(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)

    with CSVQLEngine() as engine:
        with pytest.raises(ValueError, match="Sample limit must be greater than zero"):
            SourceOperations(engine, source).sample(limit=0)


def test_missing_capability_fails_before_binding(tmp_path: Path) -> None:
    source = _resolved_csv(
        tmp_path,
        capabilities=_without_capability(CSV_CAPABILITIES, "sample"),
    )

    with CSVQLEngine() as engine:
        with pytest.raises(SourceError) as exc_info:
            SourceOperations(engine, source).sample()

    assert exc_info.value.code == "unsupported_capability"
    assert exc_info.value.capability == "sample"


def _without_capability(
    capabilities: SourceCapabilities,
    operation: SourceCapability,
) -> SourceCapabilities:
    return SourceCapabilities(
        tuple(
            SourceCapabilityStatus(
                operation=status.operation,
                state="unsupported" if status.operation == operation else status.state,
                reason_code=(
                    "not_supported" if status.operation == operation else status.reason_code
                ),
                remediation=(
                    "Choose a source with the required operation."
                    if status.operation == operation
                    else status.remediation
                ),
            )
            for status in CSV_CAPABILITIES.statuses
        )
    )


@pytest.mark.parametrize(
    ("capability", "invoke"),
    [
        ("inspect", lambda operations: operations.inspect()),
        ("exact_count", lambda operations: operations.inspect(exact=True)),
        ("sample", lambda operations: operations.sample()),
        ("profile", lambda operations: operations.profile()),
    ],
)
def test_cancellation_at_each_operation_entry_boundary(
    tmp_path: Path,
    capability: SourceCapability,
    invoke: Callable[[SourceOperations], object],
) -> None:
    source = _resolved_csv(tmp_path)
    operation = OperationContext(token=OperationToken())
    operation.token.cancel()

    with pytest.raises(OperationCancelled):
        with CSVQLEngine(operation=operation) as engine:
            invoke(SourceOperations(engine, source))


class _RecordingBinding:
    def __init__(
        self,
        binding: PreparedBinding,
        events: list[str],
        *,
        fail_cleanup: bool,
        capabilities: SourceCapabilities | None,
    ) -> None:
        self._binding = binding
        self._events = events
        self._fail_cleanup = fail_cleanup
        self._capabilities = capabilities

    @property
    def alias(self) -> str:
        return self._binding.alias

    @property
    def source(self) -> ResolvedSource:
        return self._binding.source

    @property
    def capabilities(self) -> SourceCapabilities:
        return self._capabilities or self._binding.capabilities

    def close(self) -> None:
        self._events.append("close")
        self._binding.close()
        if self._fail_cleanup:
            raise RuntimeError("injected cleanup failure")


class _RecordingCSVAdapter:
    def __init__(
        self,
        events: list[str],
        *,
        cancel_after_bind: bool = False,
        fail_cleanup: bool = False,
        binding_capabilities: SourceCapabilities | None = None,
        metadata_failure: BaseException | None = None,
        metadata_started: Event | None = None,
        metadata_release: Event | None = None,
    ) -> None:
        self._delegate = CSVSourceAdapter()
        self._events = events
        self._cancel_after_bind = cancel_after_bind
        self._fail_cleanup = fail_cleanup
        self._binding_capabilities = binding_capabilities
        self._metadata_failure = metadata_failure
        self._metadata_started = metadata_started
        self._metadata_release = metadata_release
        self._descriptor: SourceAdapterDescriptor | None = None

    @property
    def descriptor(self) -> SourceAdapterDescriptor:
        assert self._descriptor is not None
        return self._descriptor

    def validate_options(self, spec: SourceSpec) -> None:
        self._delegate.validate_options(spec)

    def resolve(self, spec: SourceSpec, context: OperationContext) -> ResolvedSource:
        return self._delegate.resolve(spec, context)

    def bind(
        self,
        connection: duckdb.DuckDBPyConnection,
        source: ResolvedSource,
        context: OperationContext,
    ) -> PreparedBinding:
        binding = self._delegate.bind(connection, source, context)
        self._events.append("bind")
        if self._cancel_after_bind:
            context.token.cancel()
        return _RecordingBinding(
            binding,
            self._events,
            fail_cleanup=self._fail_cleanup,
            capabilities=self._binding_capabilities,
        )

    def inspect_metadata(
        self,
        source: ResolvedSource,
        context: OperationContext,
    ) -> AdapterInspectionMetadata:
        self._events.append("metadata")
        if self._metadata_started is not None:
            self._metadata_started.set()
        if self._metadata_release is not None:
            if not self._metadata_release.wait(timeout=2):
                raise RuntimeError("metadata release timed out")
        if self._metadata_failure is not None:
            raise self._metadata_failure
        return self._delegate.inspect_metadata(source, context)


def _recording_registry(
    adapter: _RecordingCSVAdapter,
    *,
    descriptor_capabilities: SourceCapabilities = CSV_CAPABILITIES,
) -> SourceAdapterRegistry:
    descriptor = SourceAdapterDescriptor(
        kind="csv",
        access_mode="read_only",
        capabilities=descriptor_capabilities,
        dependency=None,
        extra=None,
        factory=lambda: adapter,
    )
    adapter._descriptor = descriptor
    return SourceAdapterRegistry((descriptor,))


@pytest.mark.parametrize(
    ("capability", "invoke"),
    [
        ("inspect", lambda operations: operations.inspect()),
        ("exact_count", lambda operations: operations.inspect(exact=True)),
        ("sample", lambda operations: operations.sample()),
        ("profile", lambda operations: operations.profile()),
    ],
)
def test_descriptor_capability_is_required_before_binding(
    tmp_path: Path,
    capability: SourceCapability,
    invoke: Callable[[SourceOperations], object],
) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events)
    registry = _recording_registry(
        adapter,
        descriptor_capabilities=_without_capability(CSV_CAPABILITIES, capability),
    )

    with pytest.raises(SourceError) as exc_info:
        with CSVQLEngine(registry=registry) as engine:
            invoke(SourceOperations(engine, source))

    assert exc_info.value.capability == capability
    assert events == []


@pytest.mark.parametrize(
    "invoke",
    [
        lambda operations: operations.inspect(),
        lambda operations: operations.inspect(exact=True),
        lambda operations: operations.sample(),
        lambda operations: operations.profile(),
    ],
    ids=("inspect", "exact_count", "sample", "profile"),
)
def test_cancellation_after_binding_closes_the_csv_binding(
    tmp_path: Path,
    invoke: Callable[[SourceOperations], object],
) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events, cancel_after_bind=True)

    with pytest.raises(OperationCancelled):
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            invoke(SourceOperations(engine, source))

    assert events == ["bind", "close"]


@pytest.mark.parametrize(
    ("capability", "invoke"),
    [
        ("inspect", lambda operations: operations.inspect()),
        ("exact_count", lambda operations: operations.inspect(exact=True)),
        ("sample", lambda operations: operations.sample()),
        ("profile", lambda operations: operations.profile()),
    ],
)
def test_effective_binding_capability_is_required_before_operation_work(
    tmp_path: Path,
    capability: SourceCapability,
    invoke: Callable[[SourceOperations], object],
) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(
        events,
        binding_capabilities=_without_capability(CSV_CAPABILITIES, capability),
    )

    with pytest.raises(SourceError) as exc_info:
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            engine.query = MethodType(
                lambda self, sql, params=None: (_ for _ in ()).throw(
                    AssertionError("relational work started")
                ),
                engine,
            )
            invoke(SourceOperations(engine, source))

    assert exc_info.value.code == "unsupported_capability"
    assert exc_info.value.capability == capability
    assert events == ["bind", "close"]


def test_effective_binding_query_capability_remains_an_engine_precondition(
    tmp_path: Path,
) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(
        events,
        binding_capabilities=_without_capability(CSV_CAPABILITIES, "query"),
    )

    with pytest.raises(SourceError) as exc_info:
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            SourceOperations(engine, source).sample()

    assert exc_info.value.capability == "query"
    assert events == ["bind", "close"]


def test_multiple_operations_reuse_one_exact_prepared_binding(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events)

    with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
        operations = SourceOperations(engine, source)
        operations.sample(limit=1)
        operations.profile()

    assert events == ["bind", "close"]


@pytest.mark.parametrize(
    ("invoke", "cancel_after_query"),
    [
        (lambda operations: operations.inspect(), 1),
        (lambda operations: operations.inspect(exact=True), 2),
        (lambda operations: operations.sample(), 1),
        (lambda operations: operations.profile(), 1),
        (lambda operations: operations.profile(), 2),
        (lambda operations: operations.profile(), 3),
        (lambda operations: operations.profile(), 4),
        (lambda operations: operations.profile(), 5),
    ],
    ids=(
        "inspect",
        "exact_count",
        "sample",
        "profile_schema",
        "profile_count",
        "profile_first_column",
        "profile_second_column",
        "profile_duplicates",
    ),
)
def test_cancellation_at_each_relational_boundary_is_observed(
    tmp_path: Path,
    invoke: Callable[[SourceOperations], object],
    cancel_after_query: int,
) -> None:
    source = _resolved_csv(tmp_path)
    operation = OperationContext(token=OperationToken())

    with pytest.raises(OperationCancelled):
        with CSVQLEngine(operation=operation) as engine:
            original_query = engine.query
            query_number = 0

            def cancelling_query(
                self: CSVQLEngine,
                sql: str,
                params: tuple[object, ...] | None = None,
            ):
                nonlocal query_number
                query_number += 1
                result = original_query(sql, params)
                if query_number == cancel_after_query:
                    operation.token.cancel()
                return result

            engine.query = MethodType(cancelling_query, engine)
            invoke(SourceOperations(engine, source))


def test_terminal_close_prevents_reuse_before_metadata_io(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events)
    engine = CSVQLEngine(registry=_recording_registry(adapter))
    operations = SourceOperations(engine, source)
    operations.sample()
    engine.close()
    events.clear()

    with pytest.raises(CSVQLError):
        operations.inspect()

    assert events == []


def test_unexpected_query_terminal_prevents_reuse_before_metadata_io(
    tmp_path: Path,
) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events)
    engine = CSVQLEngine(registry=_recording_registry(adapter))
    operations = SourceOperations(engine, source)
    operations.sample()
    connection = engine._connection
    assert connection is not None

    class FailOnceConnection:
        def __init__(self, delegate: duckdb.DuckDBPyConnection) -> None:
            self._delegate = delegate
            self._failed = False

        def execute(self, query: str, params: object = None):
            if not self._failed:
                self._failed = True
                raise RuntimeError("injected unexpected query failure")
            if params is None:
                return self._delegate.execute(query)
            return self._delegate.execute(query, params)

        def close(self) -> None:
            self._delegate.close()

    engine._connection = FailOnceConnection(connection)
    with pytest.raises(RuntimeError, match="unexpected query failure"):
        operations.sample()
    events.clear()

    with pytest.raises(CSVQLError):
        operations.inspect()

    assert events == []


def test_close_waits_for_the_full_metadata_and_relational_operation(
    tmp_path: Path,
) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    metadata_started = Event()
    metadata_release = Event()
    close_started = Event()
    close_finished = Event()
    errors: list[BaseException] = []
    adapter = _RecordingCSVAdapter(
        events,
        metadata_started=metadata_started,
        metadata_release=metadata_release,
    )
    engine = CSVQLEngine(registry=_recording_registry(adapter))
    operations = SourceOperations(engine, source)

    def run_inspect() -> None:
        try:
            operations.inspect()
        except BaseException as exc:
            errors.append(exc)

    def close_engine() -> None:
        close_started.set()
        engine.close()
        close_finished.set()

    inspect_thread = Thread(target=run_inspect)
    inspect_thread.start()
    assert metadata_started.wait(timeout=2)
    close_thread = Thread(target=close_engine)
    close_thread.start()
    assert close_started.wait(timeout=2)
    assert not close_finished.is_set()

    metadata_release.set()
    inspect_thread.join(timeout=2)
    close_thread.join(timeout=2)

    assert not inspect_thread.is_alive()
    assert not close_thread.is_alive()
    assert errors == []
    assert close_finished.is_set()
    assert events == ["bind", "metadata", "close"]


def test_query_failure_preserves_primary_and_closes_binding(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events)
    primary = QueryExecutionError("injected query failure")

    with pytest.raises(QueryExecutionError) as exc_info:
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            engine.query = MethodType(
                lambda self, sql, params=None: (_ for _ in ()).throw(primary),
                engine,
            )
            SourceOperations(engine, source).sample()

    assert exc_info.value is primary
    assert events == ["bind", "close"]


def test_metadata_failure_preserves_primary_and_closes_binding(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    primary = RuntimeError("injected metadata failure")
    adapter = _RecordingCSVAdapter(events, metadata_failure=primary)

    with pytest.raises(RuntimeError) as exc_info:
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            SourceOperations(engine, source).inspect()

    assert exc_info.value is primary
    assert events == ["bind", "metadata", "close"]


def test_success_result_cleanup_failure_is_surfaced(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events, fail_cleanup=True)

    with pytest.raises(CSVQLError, match="cleanup did not complete"):
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            SourceOperations(engine, source).sample()

    assert events == ["bind", "close"]


def test_cleanup_failure_does_not_replace_query_failure(tmp_path: Path) -> None:
    source = _resolved_csv(tmp_path)
    events: list[str] = []
    adapter = _RecordingCSVAdapter(events, fail_cleanup=True)
    primary = QueryExecutionError("injected query failure")

    with pytest.raises(QueryExecutionError) as exc_info:
        with CSVQLEngine(registry=_recording_registry(adapter)) as engine:
            engine.query = MethodType(
                lambda self, sql, params=None: (_ for _ in ()).throw(primary),
                engine,
            )
            SourceOperations(engine, source).profile()

    assert exc_info.value is primary
    assert events == ["bind", "close"]
    assert any("source bindings" in note for note in exc_info.value.__notes__)
