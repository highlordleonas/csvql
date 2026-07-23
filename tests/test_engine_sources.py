"""Engine source lifecycle and fault-injection tests."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import cast

import duckdb
import pytest

from csvql.csv_adapter import CSV_CAPABILITIES
from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, QueryExecutionError, SourceError
from csvql.models import DialectInfo, TableSource
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    SOURCE_CAPABILITY_OPERATIONS,
    ResolvedSource,
    SourceCapabilities,
    SourceCapabilityStatus,
    SourceFingerprint,
    SourceSpec,
)
from csvql.source_adapter import (
    AdapterInspectionMetadata,
    PreparedBinding,
    SourceAdapterDescriptor,
    SourceAdapterRegistry,
)


class RecordingConnection:
    """Small complete connection double for engine ownership tests."""

    def __init__(
        self,
        events: list[str],
        *,
        execute_error: BaseException | None = None,
        close_error: BaseException | None = None,
        cursor_close_error: BaseException | None = None,
        on_execute: Callable[[], None] | None = None,
        on_fetchmany: Callable[[], None] | None = None,
        interrupt_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.execute_error = execute_error
        self.close_error = close_error
        self.cursor_close_error = cursor_close_error
        self.on_execute = on_execute
        self.on_fetchmany = on_fetchmany
        self.interrupt_error = interrupt_error
        self.description: tuple[tuple[str], ...] = (("answer",),)
        self._fetchmany_pending = True

    def cursor(self) -> RecordingCursorHandle:
        return RecordingCursorHandle(self)

    def execute(
        self,
        sql: str,
        params: list[object] | None = None,
    ) -> RecordingConnection:
        del sql, params
        self.events.append("execute")
        if self.on_execute is not None:
            self.on_execute()
        if self.execute_error is not None:
            raise self.execute_error
        return self

    def fetchall(self) -> list[tuple[int]]:
        self.events.append("fetchall")
        return [(42,)]

    def fetchmany(self, size: int) -> list[tuple[int]]:
        self.events.append(f"fetchmany:{size}")
        if self.on_fetchmany is not None:
            self.on_fetchmany()
        if self._fetchmany_pending:
            self._fetchmany_pending = False
            return [(42,)]
        return []

    def interrupt(self) -> None:
        self.events.append("interrupt")
        if self.interrupt_error is not None:
            raise self.interrupt_error

    def close(self) -> None:
        self.events.append("connection-close")
        if self.close_error is not None:
            raise self.close_error


class RecordingCursorHandle:
    """Dedicated cursor double so cursor and connection cleanup are distinct."""

    def __init__(self, connection: RecordingConnection) -> None:
        self._connection = connection
        self.description = connection.description

    def execute(
        self,
        sql: str,
        params: list[object] | None = None,
    ) -> RecordingCursorHandle:
        self._connection.execute(sql, params)
        self.description = self._connection.description
        return self

    def fetchmany(self, size: int) -> list[tuple[int]]:
        return self._connection.fetchmany(size)

    def close(self) -> None:
        self._connection.events.append("cursor-close")
        if self._connection.cursor_close_error is not None:
            raise self._connection.cursor_close_error


class RecordingBinding:
    """Prepared binding double that records deterministic cleanup."""

    def __init__(
        self,
        source: ResolvedSource,
        events: list[str],
        *,
        close_error: BaseException | None = None,
        reported_alias: str | None = None,
        reported_source: ResolvedSource | None = None,
        reported_capabilities: SourceCapabilities | None = None,
    ) -> None:
        self._source = source
        self._events = events
        self._close_error = close_error
        self._reported_alias = reported_alias
        self._reported_source = reported_source
        self._reported_capabilities = reported_capabilities
        self._closed = False

    @property
    def alias(self) -> str:
        return self._reported_alias or self._source.spec.alias

    @property
    def source(self) -> ResolvedSource:
        return self._reported_source or self._source

    @property
    def capabilities(self):
        return self._reported_capabilities or self._source.capabilities

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._events.append(f"close:{self.alias}")
        if self._close_error is not None:
            raise self._close_error


class RecordingAdapter:
    """Adapter double with controlled resolve, bind, and cleanup failures."""

    def __init__(
        self,
        events: list[str],
        *,
        kind: str = "fake",
        resolve_error: BaseException | None = None,
        validate_error: BaseException | None = None,
        fail_bind_alias: str | None = None,
        bind_error: BaseException | None = None,
        cancel_after_bind_alias: str | None = None,
        close_errors: dict[str, BaseException] | None = None,
        binding_aliases: dict[str, str] | None = None,
        binding_sources: dict[str, ResolvedSource] | None = None,
        binding_capabilities: dict[str, SourceCapabilities] | None = None,
    ) -> None:
        self.events = events
        self.resolve_error = resolve_error
        self.validate_error = validate_error
        self.fail_bind_alias = fail_bind_alias
        self.bind_error = bind_error
        self.cancel_after_bind_alias = cancel_after_bind_alias
        self.close_errors = close_errors or {}
        self.binding_aliases = binding_aliases or {}
        self.binding_sources = binding_sources or {}
        self.binding_capabilities = binding_capabilities or {}
        self._descriptor = SourceAdapterDescriptor(
            kind=kind,
            access_mode="read_only",
            capabilities=CSV_CAPABILITIES,
            dependency=None,
            extra=None,
            factory=lambda: self,
        )

    @property
    def descriptor(self) -> SourceAdapterDescriptor:
        return self._descriptor

    def validate_options(self, spec: SourceSpec) -> None:
        self.events.append(f"validate:{spec.alias}")
        if self.validate_error is not None:
            raise self.validate_error

    def resolve(self, spec: SourceSpec, context: OperationContext) -> ResolvedSource:
        self.events.append(f"resolve:{spec.alias}:{spec.anchor}:{spec.locator}")
        context.checkpoint()
        if self.resolve_error is not None:
            raise self.resolve_error
        return ResolvedSource(
            spec=spec,
            canonical_locator=str(spec.anchor / spec.locator),
            fingerprint=_fingerprint(),
            capabilities=CSV_CAPABILITIES,
        )

    def bind(
        self,
        connection: duckdb.DuckDBPyConnection,
        source: ResolvedSource,
        context: OperationContext,
    ) -> PreparedBinding:
        del connection
        context.checkpoint()
        alias = source.spec.alias
        self.events.append(f"open:{alias}")
        if alias == self.fail_bind_alias:
            raise self.bind_error or SourceError(
                "source_bind_failed",
                "Injected source bind failure.",
                kind=source.spec.kind,
                alias=alias,
            )
        binding = RecordingBinding(
            source,
            self.events,
            close_error=self.close_errors.get(alias),
            reported_alias=self.binding_aliases.get(alias),
            reported_source=self.binding_sources.get(alias),
            reported_capabilities=self.binding_capabilities.get(alias),
        )
        if alias == self.cancel_after_bind_alias:
            context.token.cancel()
        return cast(PreparedBinding, binding)

    def inspect_metadata(
        self,
        source: ResolvedSource,
        context: OperationContext,
    ) -> AdapterInspectionMetadata:
        del source, context
        return AdapterInspectionMetadata(
            dialect=DialectInfo(
                delimiter=",",
                quote='"',
                escape=None,
                header=True,
                encoding="utf-8",
            )
        )


class CoordinatedOperationContext(OperationContext):
    """Operation context that pauses interrupt attachment for race tests."""

    def __init__(
        self,
        *,
        token: OperationToken,
        attach_started: threading.Event,
        allow_attach: threading.Event,
    ) -> None:
        super().__init__(token=token)
        self._attach_started_event = attach_started
        self._allow_attach_event = allow_attach

    def attach_interrupt(self, callback: Callable[[], None]) -> None:
        self._attach_started_event.set()
        if not self._allow_attach_event.wait(timeout=2):
            raise AssertionError("Timed out waiting to release interrupt attachment.")
        super().attach_interrupt(callback)


class DetachRecordingOperationContext(OperationContext):
    """Operation context that records exactly when detach occurs."""

    def __init__(self, *, token: OperationToken, events: list[str]) -> None:
        super().__init__(token=token)
        self._events = events

    def detach_interrupt(self) -> None:
        self._events.append("detach-interrupt")
        super().detach_interrupt()


def _fingerprint() -> SourceFingerprint:
    return SourceFingerprint(version=1, size_bytes=1, modified_at="2026-07-22T00:00:00+00:00")


def _query_unavailable_capabilities() -> SourceCapabilities:
    return SourceCapabilities(
        statuses=tuple(
            SourceCapabilityStatus(
                operation=operation,
                state="unavailable" if operation == "query" else "available",
                reason_code="query_unavailable" if operation == "query" else None,
            )
            for operation in SOURCE_CAPABILITY_OPERATIONS
        )
    )


def _resolved(
    alias: str,
    *,
    kind: str = "fake",
    capabilities: SourceCapabilities = CSV_CAPABILITIES,
    fingerprint: SourceFingerprint | None = None,
    canonical_locator: str | None = None,
) -> ResolvedSource:
    return ResolvedSource(
        spec=SourceSpec(
            alias=alias,
            kind=kind,
            locator=f"{alias}.csv",
            anchor=Path("/captured"),
        ),
        canonical_locator=canonical_locator or f"/captured/{alias}.csv",
        fingerprint=fingerprint if fingerprint is not None else _fingerprint(),
        capabilities=capabilities,
    )


def _registry(adapter: RecordingAdapter) -> SourceAdapterRegistry:
    return SourceAdapterRegistry((adapter.descriptor,))


def _install_connection(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    connection: RecordingConnection | None = None,
) -> RecordingConnection:
    selected = connection or RecordingConnection(events)

    def connect(*, database: str) -> duckdb.DuckDBPyConnection:
        assert database == ":memory:"
        events.append("connect")
        return cast(duckdb.DuckDBPyConnection, selected)

    monkeypatch.setattr("csvql.engine.duckdb.connect", connect)
    monkeypatch.setattr("csvql.engine._open_result_cursor", lambda connection: connection.cursor())
    return selected


def _mutate_alias(source: ResolvedSource, alias: str) -> ResolvedSource:
    object.__setattr__(source.spec, "alias", alias)
    return source


@pytest.mark.parametrize(
    "sources",
    [
        (_resolved("orders"), _resolved("orders")),
        (_resolved("Orders"), _resolved("orders")),
        (_mutate_alias(_resolved("orders"), "__localql_private"),),
    ],
    ids=["duplicate", "case-only", "reserved"],
)
def test_alias_preflight_fails_before_connection_or_binding(
    monkeypatch: pytest.MonkeyPatch,
    sources: tuple[ResolvedSource, ...],
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises((SourceError, ValueError)):
        engine.prepare_sources(sources)

    assert "connect" not in events
    assert not any(event.startswith("open:") for event in events)


def test_descriptor_and_option_preflight_fail_before_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    validation_error = SourceError(
        "unsupported_source_option",
        "Injected option failure.",
        kind="fake",
    )
    adapter = RecordingAdapter(events, validate_error=validation_error)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(SourceError) as captured:
        engine.prepare_sources((_resolved("orders"),))

    assert captured.value is validation_error
    assert events == ["validate:orders"]

    events.clear()
    adapter = RecordingAdapter(events)
    engine = CSVQLEngine(registry=_registry(adapter))
    unknown = _resolved("customers", kind="unknown")
    with pytest.raises(SourceError) as unknown_error:
        engine.prepare_sources((unknown,))
    assert unknown_error.value.code == "unknown_source_kind"
    assert events == []


def test_csv_resolved_source_requires_submission_fingerprint_before_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events, kind="csv")
    _install_connection(monkeypatch, events)
    source = ResolvedSource(
        spec=SourceSpec(
            alias="orders",
            kind="csv",
            locator="orders.csv",
            anchor=Path("/captured"),
        ),
        canonical_locator="/captured/orders.csv",
        fingerprint=None,
        capabilities=CSV_CAPABILITIES,
    )
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(SourceError) as captured:
        engine.prepare_sources((source,))

    assert captured.value.code == "source_changed"
    assert "connect" not in events


def test_register_tables_resolves_all_sources_before_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events, kind="csv")
    _install_connection(monkeypatch, events)
    first = tmp_path / "first.csv"
    second = tmp_path / "nested" / "second.csv"
    engine = CSVQLEngine(registry=_registry(adapter))

    engine.register_tables(
        (
            TableSource(name="first", path=first),
            TableSource(name="second", path=second),
        )
    )

    assert events == [
        "validate:first",
        f"resolve:first:{tmp_path}:first.csv",
        "validate:second",
        f"resolve:second:{second.parent}:second.csv",
        "validate:first",
        "validate:second",
        "connect",
        "open:first",
        "open:second",
    ]
    engine.close()


def test_register_tables_missing_file_raises_public_csvql_error_and_never_connects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine()
    missing = tmp_path / "orders.csv"

    with pytest.raises(CSVQLError) as captured:
        engine.register_tables((TableSource(name="orders", path=missing),))

    assert type(captured.value) is CSVQLError
    assert captured.value.message == f"Failed to register CSV table 'orders' from {missing}."
    assert captured.value.suggestion == "Check that the file is a readable CSV with a header row."
    assert isinstance(captured.value.__cause__, SourceError)
    assert captured.value.__cause__.code == "source_missing"
    assert not hasattr(captured.value, "code")
    assert "connect" not in events


@pytest.mark.parametrize("failed_alias", ["first", "second", "third"])
def test_bind_failure_closes_only_completed_bindings_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
    failed_alias: str,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events, fail_bind_alias=failed_alias)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(SourceError, match="Injected source bind failure"):
        engine.prepare_sources((_resolved("first"), _resolved("second"), _resolved("third")))

    failure_index = ["first", "second", "third"].index(failed_alias)
    completed = ["first", "second", "third"][:failure_index]
    expected_closes = [f"close:{alias}" for alias in reversed(completed)]
    assert [event for event in events if event.startswith("close:")] == expected_closes
    assert events[-1] == "connection-close"


def test_malformed_selected_adapter_descriptor_aborts_live_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    registry = _registry(adapter)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=registry)
    engine.prepare_sources((_resolved("existing"),))
    events.clear()
    adapter._descriptor = SourceAdapterDescriptor(
        kind="other",
        access_mode="read_only",
        capabilities=CSV_CAPABILITIES,
        dependency=None,
        extra=None,
        factory=lambda: adapter,
    )

    with pytest.raises(SourceError, match="descriptor"):
        engine.prepare_sources((_resolved("new"),))

    assert events == ["close:existing", "connection-close"]


@pytest.mark.parametrize("contract_failure", ["alias", "source", "capability"])
def test_invalid_returned_binding_is_owned_then_aborts_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
    contract_failure: str,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    if contract_failure == "alias":
        adapter.binding_aliases["new"] = "wrong"
    elif contract_failure == "source":
        adapter.binding_sources["new"] = _resolved("other")
    else:
        adapter.binding_capabilities["new"] = _query_unavailable_capabilities()
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("existing"),))
    events.clear()

    with pytest.raises(SourceError):
        engine.prepare_sources((_resolved("new"),))

    assert [event for event in events if event.startswith(("open:", "close:"))] == [
        "open:new",
        "close:wrong" if contract_failure == "alias" else "close:new",
        "close:existing",
    ]
    assert events[-1] == "connection-close"


def test_cancellation_before_preparation_does_not_create_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    _install_connection(monkeypatch, events)
    operation = OperationContext(token=OperationToken())
    operation.request_cancel()
    engine = CSVQLEngine(registry=_registry(adapter), operation=operation)

    with pytest.raises(OperationCancelled):
        engine.prepare_sources((_resolved("orders"),))

    assert events == []


def test_cancellation_between_binds_reverses_completed_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events, cancel_after_bind_alias="second")
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(OperationCancelled):
        engine.prepare_sources((_resolved("first"), _resolved("second"), _resolved("third")))

    assert [event for event in events if event.startswith(("open:", "close:"))] == [
        "open:first",
        "open:second",
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_keyboard_interrupt_between_binds_still_cleans_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(
        events,
        fail_bind_alias="second",
        bind_error=KeyboardInterrupt(),
    )
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(KeyboardInterrupt):
        engine.prepare_sources((_resolved("first"), _resolved("second")))

    assert [event for event in events if event.startswith("close:")] == ["close:first"]
    assert events[-1] == "connection-close"


def test_second_preparation_alias_conflict_fails_before_new_adapter_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("Orders"),))
    events.clear()

    with pytest.raises(SourceError):
        engine.prepare_sources((_resolved("orders"),))

    assert events == ["close:Orders", "connection-close"]
    with pytest.raises(CSVQLError, match="closed"):
        engine.prepare_sources((_resolved("customers"),))
    engine.close()


@pytest.mark.parametrize(
    "failure_kind",
    ["descriptor", "options", "capability", "resolved_identity"],
)
def test_live_preflight_failure_aborts_existing_bindings_and_connection(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("existing"),))
    events.clear()

    source = _resolved("new")
    if failure_kind == "descriptor":
        source = _resolved("new", kind="unknown")
    elif failure_kind == "options":
        adapter.validate_error = SourceError(
            "unsupported_source_option",
            "Injected option failure.",
            kind="fake",
        )
    elif failure_kind == "capability":
        source = _resolved(
            "new",
            capabilities=_query_unavailable_capabilities(),
        )
    else:
        source = ResolvedSource(
            spec=source.spec,
            canonical_locator="",
            fingerprint=source.fingerprint,
            capabilities=source.capabilities,
        )

    with pytest.raises(SourceError):
        engine.prepare_sources((source,))

    assert events[-2:] == ["close:existing", "connection-close"]
    with pytest.raises(CSVQLError, match="closed"):
        engine.prepare_sources((_resolved("later"),))


def test_live_csv_fingerprint_failure_aborts_existing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events, kind="csv")
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("existing", kind="csv"),))
    events.clear()
    missing_identity = ResolvedSource(
        spec=SourceSpec(
            alias="new",
            kind="csv",
            locator="new.csv",
            anchor=Path("/captured"),
        ),
        canonical_locator="/captured/new.csv",
        fingerprint=None,
        capabilities=CSV_CAPABILITIES,
    )

    with pytest.raises(SourceError, match="identity"):
        engine.prepare_sources((missing_identity,))

    assert events == ["validate:new", "close:existing", "connection-close"]


def test_live_register_resolution_failure_aborts_existing_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events, kind="csv")
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.register_tables((TableSource(name="existing", path=tmp_path / "existing.csv"),))
    events.clear()
    primary = SourceError("source_missing", "Injected resolution failure.", kind="csv")
    adapter.resolve_error = primary

    with pytest.raises(CSVQLError) as captured:
        engine.register_tables((TableSource(name="new", path=tmp_path / "new.csv"),))

    assert type(captured.value) is CSVQLError
    assert (
        captured.value.message == f"Failed to register CSV table 'new' from {tmp_path / 'new.csv'}."
    )
    assert captured.value.suggestion == "Check that the file is a readable CSV with a header row."
    assert captured.value.__cause__ is primary
    assert events == [
        "validate:new",
        f"resolve:new:{tmp_path}:new.csv",
        "close:existing",
        "connection-close",
    ]


def test_live_register_resolution_cancellation_aborts_existing_state_without_reconnect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class CancellingResolveAdapter(RecordingAdapter):
        def __init__(self, events: list[str]) -> None:
            super().__init__(events, kind="csv")
            self.cancel_on_resolve = False

        def resolve(self, spec: SourceSpec, context: OperationContext) -> ResolvedSource:
            self.events.append(f"resolve:{spec.alias}:{spec.anchor}:{spec.locator}")
            if self.cancel_on_resolve:
                context.token.cancel()
                context.checkpoint()
                raise AssertionError("Cancellation should have interrupted resolution.")
            return ResolvedSource(
                spec=spec,
                canonical_locator=str(spec.anchor / spec.locator),
                fingerprint=_fingerprint(),
                capabilities=CSV_CAPABILITIES,
            )

    adapter = CancellingResolveAdapter(events)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.register_tables((TableSource(name="existing", path=tmp_path / "existing.csv"),))
    events.clear()
    adapter.cancel_on_resolve = True

    with pytest.raises(OperationCancelled):
        engine.register_tables((TableSource(name="new", path=tmp_path / "new.csv"),))

    assert events == [
        "validate:new",
        f"resolve:new:{tmp_path}:new.csv",
        "close:existing",
        "connection-close",
    ]


def test_register_tables_double_abort_is_idempotent_and_notes_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    primary = SourceError(
        "source_bind_failed",
        "Primary compatibility bind failure.",
        kind="csv",
        alias="second",
    )
    adapter = RecordingAdapter(
        events,
        kind="csv",
        fail_bind_alias="second",
        bind_error=primary,
        close_errors={"first": KeyboardInterrupt()},
    )
    connection = RecordingConnection(events, close_error=SystemExit(2))
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(CSVQLError) as captured:
        engine.register_tables(
            (
                TableSource(name="first", path=tmp_path / "first.csv"),
                TableSource(name="second", path=tmp_path / "second.csv"),
            )
        )

    assert type(captured.value) is CSVQLError
    assert captured.value.message == (
        f"Failed to register CSV table 'second' from {tmp_path / 'second.csv'}."
    )
    assert captured.value.suggestion == "Check that the file is a readable CSV with a header row."
    assert captured.value.__cause__ is primary
    assert events.count("close:first") == 1
    assert events.count("connection-close") == 1
    notes = getattr(captured.value, "__notes__", ())
    assert len(notes) == 2
    assert all("Cleanup uncertainty" in note for note in notes)
    assert getattr(primary, "__notes__", ()) == ()


def test_register_tables_bind_failure_raises_public_csvql_error_from_source_error(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_bytes(b"order_id,status\n\xff,paid\n")

    with CSVQLEngine() as engine:
        with pytest.raises(CSVQLError) as captured:
            engine.register_tables((TableSource(name="orders", path=csv_path),))

    assert type(captured.value) is CSVQLError
    assert captured.value.message == f"Failed to register CSV table 'orders' from {csv_path}."
    assert captured.value.suggestion == "Check that the file is a readable CSV with a header row."
    assert isinstance(captured.value.__cause__, SourceError)
    assert captured.value.__cause__.code == "source_bind_failed"
    assert not hasattr(captured.value, "alias")


def test_register_tables_prefers_source_error_alias_for_multi_source_bind_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    primary = SourceError(
        "source_bind_failed",
        "Injected source bind failure.",
        kind="csv",
        alias="second",
    )
    adapter = RecordingAdapter(
        events,
        kind="csv",
        fail_bind_alias="second",
        bind_error=primary,
    )
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(CSVQLError) as captured:
        engine.register_tables(
            (
                TableSource(name="first", path=tmp_path / "first.csv"),
                TableSource(name="second", path=tmp_path / "second.csv"),
                TableSource(name="third", path=tmp_path / "third.csv"),
            )
        )

    assert type(captured.value) is CSVQLError
    assert captured.value.message == (
        f"Failed to register CSV table 'second' from {tmp_path / 'second.csv'}."
    )
    assert captured.value.__cause__ is primary
    assert [event for event in events if event.startswith("close:")] == ["close:first"]


def test_register_tables_prefers_current_resolving_source_when_source_error_has_no_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    primary = SourceError("source_missing", "Injected resolution failure.", kind="csv")
    adapter = RecordingAdapter(events, kind="csv", resolve_error=primary)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(CSVQLError) as captured:
        engine.register_tables(
            (
                TableSource(name="first", path=tmp_path / "first.csv"),
                TableSource(name="second", path=tmp_path / "second.csv"),
            )
        )

    assert type(captured.value) is CSVQLError
    assert (
        captured.value.message
        == f"Failed to register CSV table 'first' from {tmp_path / 'first.csv'}."
    )
    assert captured.value.__cause__ is primary


def test_query_failure_preserves_primary_and_live_bindings_until_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    connection = RecordingConnection(events, execute_error=duckdb.Error("private detail"))
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("first"), _resolved("second")))

    with pytest.raises(QueryExecutionError) as captured:
        engine.query("SELECT * FROM missing")

    assert "private detail" in captured.value.message
    assert [event for event in events if event.startswith("close:")] == []

    engine.close()
    assert [event for event in events if event.startswith("close:")] == [
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_query_cancellation_cleans_bindings_and_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    operation = OperationContext(token=OperationToken())

    def cancel_during_execute() -> None:
        operation.token.cancel()

    adapter = RecordingAdapter(events)
    connection = RecordingConnection(
        events,
        execute_error=duckdb.Error("interrupted"),
        on_execute=cancel_during_execute,
    )
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter), operation=operation)
    engine.prepare_sources((_resolved("first"), _resolved("second")))

    with pytest.raises(OperationCancelled):
        engine.query("SELECT * FROM first")

    assert [event for event in events if event.startswith("close:")] == [
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_query_keyboard_interrupt_cleans_bindings_and_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    connection = RecordingConnection(events, execute_error=KeyboardInterrupt())
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("first"), _resolved("second")))

    with pytest.raises(KeyboardInterrupt):
        engine.query("SELECT * FROM first")

    assert [event for event in events if event.startswith("close:")] == [
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_source_free_query_opens_immediately_before_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine()

    result = engine.query("SELECT 42 AS answer")

    assert result.columns == ("answer",)
    assert result.rows == ((42,),)
    assert events[:3] == ["connect", "execute", "fetchmany:1000"]
    engine.close()


def test_interrupt_is_best_effort_and_close_still_cleans_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    connection = RecordingConnection(
        events,
        interrupt_error=RuntimeError("private interrupt detail"),
    )
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("orders"),))

    engine.interrupt()
    engine.close()

    assert events[-3:] == ["interrupt", "close:orders", "connection-close"]


def test_close_detaches_interrupt_after_cursor_bindings_and_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    operation = DetachRecordingOperationContext(token=OperationToken(), events=events)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(operation=operation)
    engine.query("SELECT 42")

    engine.close()
    operation.request_cancel()

    assert events[-2:] == ["connection-close", "detach-interrupt"]
    assert "interrupt" not in events


def test_stream_close_cleans_cursor_then_bindings_then_connection_then_interrupt_detach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    operation = DetachRecordingOperationContext(token=OperationToken(), events=events)
    adapter = RecordingAdapter(events)
    connection = RecordingConnection(events)
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter), operation=operation)
    engine.prepare_sources((_resolved("first"), _resolved("second")))

    stream = engine.stream("SELECT 42 AS answer")
    engine.close()
    operation.request_cancel()

    del stream
    relevant_events = [
        event
        for event in events
        if event.startswith(
            ("execute", "cursor-close", "close:", "connection-close", "detach-interrupt")
        )
    ]
    assert relevant_events == [
        "execute",
        "cursor-close",
        "close:second",
        "close:first",
        "connection-close",
        "detach-interrupt",
    ]
    assert "interrupt" not in events


def test_engine_rejects_second_active_stream_until_first_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine()

    first = engine.stream("SELECT 1 AS value")

    with pytest.raises(QueryExecutionError, match="active result stream"):
        engine.stream("SELECT 2 AS value")

    first.close()
    second = engine.stream("SELECT 2 AS value")
    second.close()


def test_stream_close_failure_keeps_engine_active_slot_until_full_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = RecordingConnection(
        events,
        cursor_close_error=RuntimeError("private close detail"),
    )
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine()

    stream = engine.stream("SELECT 1 AS value")
    with pytest.raises(RuntimeError, match="private close detail"):
        stream.close()

    with pytest.raises(QueryExecutionError, match="active result stream"):
        engine.stream("SELECT 2 AS value")

    with pytest.raises(CSVQLError, match="cleanup did not complete with certainty"):
        engine.close()

    with pytest.raises(QueryExecutionError, match="closed"):
        engine.query("SELECT 3 AS value")


def test_query_consumes_stream_to_complete_rows_without_fetchall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class StreamOnlyConnection(RecordingConnection):
        def __init__(self, events: list[str]) -> None:
            super().__init__(events)
            self._remaining = [[(42,)], []]

        def fetchall(self) -> list[tuple[int]]:
            raise AssertionError("query() must consume the result stream, not fetchall()")

        def fetchmany(self, size: int) -> list[tuple[int]]:
            self.events.append(f"fetchmany:{size}")
            return self._remaining.pop(0)

    connection = StreamOnlyConnection(events)
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine()

    result = engine.query("SELECT 42 AS answer")

    assert result.columns == ("answer",)
    assert result.rows == ((42,),)
    assert "fetchall" not in events
    assert "fetchmany" in ",".join(events)


def test_query_preserves_real_duckdb_temp_tables_across_sequential_streams(
    tmp_path: Path,
) -> None:
    orders_path = tmp_path / "orders.csv"
    orders_path.write_text("id,value\n1,alpha\n", encoding="utf-8")
    engine = CSVQLEngine()
    engine.register_tables((TableSource(name="orders", path=orders_path),))

    try:
        create_result = engine.query("CREATE TEMP TABLE scratch AS SELECT * FROM orders")
        count_result = engine.query("SELECT COUNT(*) AS row_count FROM scratch")
    finally:
        engine.close()

    assert create_result.columns == ("Count",)
    assert count_result.columns == ("row_count",)
    assert count_result.rows == ((1,),)


def test_failed_multistatement_query_discards_temp_session_state_before_retry(
    tmp_path: Path,
) -> None:
    orders_path = tmp_path / "orders.csv"
    orders_path.write_text("id,value\n1,alpha\n", encoding="utf-8")
    engine = CSVQLEngine()
    engine.register_tables((TableSource(name="orders", path=orders_path),))

    try:
        with pytest.raises(QueryExecutionError, match="missing_table"):
            engine.query(
                "CREATE TEMP TABLE scratch AS SELECT * FROM orders; SELECT * FROM missing_table"
            )

        fallback_result = engine.query("SELECT COUNT(*) AS row_count FROM orders")
        with pytest.raises(QueryExecutionError, match="scratch"):
            engine.query("SELECT COUNT(*) AS row_count FROM scratch")
    finally:
        engine.close()

    assert fallback_result.columns == ("row_count",)
    assert fallback_result.rows == ((1,),)


def test_stream_close_preserves_successful_temp_session_state_for_next_query(
    tmp_path: Path,
) -> None:
    orders_path = tmp_path / "orders.csv"
    orders_path.write_text("id,value\n1,alpha\n", encoding="utf-8")
    engine = CSVQLEngine()
    engine.register_tables((TableSource(name="orders", path=orders_path),))

    try:
        engine.query("CREATE TEMP TABLE scratch AS SELECT * FROM orders")
        stream = engine.stream("SELECT * FROM scratch ORDER BY id")
        stream.close()
        result = engine.query("SELECT COUNT(*) AS row_count FROM scratch")
    finally:
        engine.close()

    assert result.columns == ("row_count",)
    assert result.rows == ((1,),)


def test_fetch_failure_discards_session_cursor_and_releases_stream_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = RecordingConnection(events, execute_error=None)

    def fail_fetchmany(size: int) -> list[tuple[int]]:
        events.append(f"fetchmany:{size}")
        raise duckdb.Error("private fetch detail")

    connection.fetchmany = fail_fetchmany  # type: ignore[method-assign]
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine()

    stream = engine.stream("SELECT 1 AS value")
    with pytest.raises(QueryExecutionError, match="private fetch detail"):
        stream.fetch_rows(1)

    assert events == ["connect", "execute", "fetchmany:1", "cursor-close"]
    retry = engine.stream("SELECT 2 AS value")
    retry.close()


def test_fetch_failure_with_discard_uncertainty_keeps_engine_fail_closed_until_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = RecordingConnection(
        events,
        cursor_close_error=RuntimeError("private close detail"),
    )

    def fail_fetchmany(size: int) -> list[tuple[int]]:
        events.append(f"fetchmany:{size}")
        raise duckdb.Error("private fetch detail")

    connection.fetchmany = fail_fetchmany  # type: ignore[method-assign]
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine()

    stream = engine.stream("SELECT 1 AS value")
    with pytest.raises(QueryExecutionError, match="private fetch detail") as captured:
        stream.fetch_rows(1)

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert "cursor could not be closed" in notes
    assert events == ["connect", "execute", "fetchmany:1", "cursor-close"]
    with pytest.raises(QueryExecutionError, match="active result stream"):
        engine.stream("SELECT 2 AS value")
    with pytest.raises(CSVQLError, match="cleanup did not complete with certainty"):
        engine.close()


def test_fetch_path_cancellation_interrupts_active_stream_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    operation = OperationContext(token=OperationToken())
    fetch_started = threading.Event()
    allow_fetch_error = threading.Event()
    connection = RecordingConnection(events)

    def blocking_fetchmany(size: int) -> list[tuple[int]]:
        events.append(f"fetchmany:{size}")
        fetch_started.set()
        if not allow_fetch_error.wait(timeout=2):
            raise AssertionError("Timed out waiting to release fetchmany.")
        raise duckdb.Error("interrupted")

    connection.fetchmany = blocking_fetchmany  # type: ignore[method-assign]
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(operation=operation)
    stream = engine.stream("SELECT 42 AS answer")
    failures: list[BaseException] = []

    def fetch_rows() -> None:
        try:
            stream.fetch_rows(1)
        except BaseException as exc:
            failures.append(exc)

    fetch_thread = threading.Thread(target=fetch_rows)
    fetch_thread.start()
    assert fetch_started.wait(timeout=2)
    operation.request_cancel()
    allow_fetch_error.set()
    fetch_thread.join(timeout=2)

    assert not fetch_thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], OperationCancelled)
    assert events == ["connect", "execute", "fetchmany:1", "interrupt", "cursor-close"]
    assert engine._active_stream is None
    with pytest.raises(OperationCancelled):
        engine.stream("SELECT 7 AS answer")
    engine.close()
    if "detach-interrupt" in events:
        assert events[-2:] == ["connection-close", "detach-interrupt"]
    else:
        assert events[-2:] == ["cursor-close", "connection-close"]


@pytest.mark.parametrize("operation_kind", ["query", "prepare", "stream"])
def test_cancellation_during_connect_stops_work_after_interrupt_attachment(
    monkeypatch: pytest.MonkeyPatch,
    operation_kind: str,
) -> None:
    events: list[str] = []
    operation = OperationContext(token=OperationToken())
    connection = RecordingConnection(events)

    def connect(*, database: str) -> duckdb.DuckDBPyConnection:
        assert database == ":memory:"
        events.append("connect")
        operation.request_cancel()
        return cast(duckdb.DuckDBPyConnection, connection)

    monkeypatch.setattr("csvql.engine.duckdb.connect", connect)
    adapter = RecordingAdapter(events)
    engine = CSVQLEngine(registry=_registry(adapter), operation=operation)

    with pytest.raises(OperationCancelled):
        if operation_kind == "query":
            engine.query("SELECT 42")
        elif operation_kind == "stream":
            engine.stream("SELECT 42")
        else:
            engine.prepare_sources((_resolved("orders"),))

    assert "execute" not in events
    assert not any(event.startswith("open:") for event in events)
    assert events.count("connection-close") == 1
    operation.request_cancel()
    assert "interrupt" not in events
    with pytest.raises(CSVQLError, match="closed"):
        engine.prepare_sources((_resolved("later"),))


def test_interrupt_attach_and_close_are_linearized_without_stale_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    attach_started = threading.Event()
    allow_attach = threading.Event()
    close_done = threading.Event()
    operation = CoordinatedOperationContext(
        token=OperationToken(),
        attach_started=attach_started,
        allow_attach=allow_attach,
    )
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(operation=operation)
    failures: list[BaseException] = []

    def run_query() -> None:
        try:
            engine.query("SELECT 42")
        except BaseException as exc:
            failures.append(exc)

    def run_close() -> None:
        try:
            engine.close()
        except BaseException as exc:
            failures.append(exc)
        finally:
            close_done.set()

    query_thread = threading.Thread(target=run_query)
    query_thread.start()
    assert attach_started.wait(timeout=2)
    close_thread = threading.Thread(target=run_close)
    close_thread.start()
    assert not close_done.wait(timeout=0.05)
    allow_attach.set()
    query_thread.join(timeout=2)
    close_thread.join(timeout=2)

    assert not query_thread.is_alive()
    assert not close_thread.is_alive()
    assert failures == []
    assert events.count("connect") == 1
    assert events.count("execute") == 1
    assert events.count("connection-close") == 1
    operation.request_cancel()
    assert "interrupt" not in events
    with pytest.raises(QueryExecutionError, match="closed"):
        engine.query("SELECT 42")


def test_stream_start_failure_with_cursor_close_uncertainty_preserves_primary_and_closes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = RecordingConnection(
        events,
        execute_error=duckdb.Error("private execute detail"),
        cursor_close_error=RuntimeError("private close detail"),
    )
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine()

    with pytest.raises(QueryExecutionError, match="private execute detail") as captured:
        engine.stream("SELECT * FROM missing")

    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert "cursor could not be closed" in notes
    assert "private close detail" not in notes
    assert events == ["connect", "execute", "cursor-close", "cursor-close", "connection-close"]
    with pytest.raises(QueryExecutionError, match="closed"):
        engine.stream("SELECT 42")


def test_primary_prepare_failure_keeps_sanitized_cleanup_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    primary = SourceError(
        "source_bind_failed",
        "Primary bind failure.",
        kind="fake",
        alias="third",
    )
    adapter = RecordingAdapter(
        events,
        fail_bind_alias="third",
        bind_error=primary,
        close_errors={"second": RuntimeError("sensitive binding detail")},
    )
    connection = RecordingConnection(
        events,
        close_error=RuntimeError("sensitive connection detail"),
    )
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))

    with pytest.raises(SourceError) as captured:
        engine.prepare_sources((_resolved("first"), _resolved("second"), _resolved("third")))

    assert captured.value is primary
    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    assert "cleanup" in notes.lower()
    assert "sensitive" not in notes
    assert [event for event in events if event.startswith("close:")] == [
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_ordinary_close_attempts_all_cleanup_in_reverse_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(
        events,
        close_errors={"second": RuntimeError("sensitive binding detail")},
    )
    connection = RecordingConnection(
        events,
        close_error=RuntimeError("sensitive connection detail"),
    )
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("first"), _resolved("second"), _resolved("third")))

    with pytest.raises(CSVQLError) as captured:
        engine.close()

    assert "cleanup" in captured.value.message.lower()
    assert "sensitive" not in captured.value.message
    assert [event for event in events if event.startswith("close:")] == [
        "close:third",
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"

    event_count = len(events)
    engine.close()
    assert len(events) == event_count


def test_ordinary_close_continues_after_binding_and_connection_base_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(
        events,
        close_errors={
            "third": KeyboardInterrupt(),
            "second": SystemExit(2),
        },
    )
    connection = RecordingConnection(events, close_error=KeyboardInterrupt())
    _install_connection(monkeypatch, events, connection)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("first"), _resolved("second"), _resolved("third")))

    with pytest.raises(CSVQLError) as captured:
        engine.close()

    assert "cleanup" in captured.value.message.lower()
    assert [event for event in events if event.startswith("close:")] == [
        "close:third",
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_context_exit_preserves_body_primary_and_notes_base_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(
        events,
        close_errors={"second": KeyboardInterrupt()},
    )
    connection = RecordingConnection(events, close_error=SystemExit(2))
    _install_connection(monkeypatch, events, connection)
    primary = RuntimeError("body primary")

    with pytest.raises(RuntimeError) as captured:
        with CSVQLEngine(registry=_registry(adapter)) as engine:
            engine.prepare_sources((_resolved("first"), _resolved("second")))
            raise primary

    assert captured.value is primary
    notes = "\n".join(getattr(primary, "__notes__", ()))
    assert notes.count("Cleanup uncertainty") == 2
    assert [event for event in events if event.startswith("close:")] == [
        "close:second",
        "close:first",
    ]
    assert events[-1] == "connection-close"


def test_successful_close_order_is_reverse_bind_then_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    adapter = RecordingAdapter(events)
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine(registry=_registry(adapter))
    engine.prepare_sources((_resolved("first"), _resolved("second"), _resolved("third")))

    engine.close()
    engine.close()

    assert [event for event in events if event.startswith(("open:", "close:"))] == [
        "open:first",
        "open:second",
        "open:third",
        "close:third",
        "close:second",
        "close:first",
    ]
    assert events.count("connection-close") == 1


def test_close_is_terminal_and_later_work_does_not_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_connection(monkeypatch, events)
    engine = CSVQLEngine()
    engine.query("SELECT 42")
    engine.close()

    with pytest.raises(CSVQLError, match="closed"):
        engine.query("SELECT 42")
    with pytest.raises(CSVQLError, match="closed"):
        engine.prepare_sources((_resolved("orders"),))

    assert events.count("connect") == 1
