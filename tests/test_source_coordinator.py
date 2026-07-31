from __future__ import annotations

import importlib
import importlib.util
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from csvql.source import (
    DiagnosticCode,
    DiagnosticStage,
    FrozenJSONObject,
    IdentityStrength,
    RequiredAction,
    SelectedSource,
    SourceDiagnostic,
    SourceIdentity,
    SourceRequest,
    SourceSpec,
    UnknownSource,
    build_source_request,
)
from csvql.source_registry import DependencyRequirement, DescriptorView


def _canonical_test_locator(filename: str) -> str:
    return str(Path.cwd() / "data" / filename)


def test_source_coordinator_module_exposes_the_lifecycle_boundary() -> None:
    """Removing the coordinator module would erase the application lifecycle seam."""

    spec = importlib.util.find_spec("csvql.source_coordinator")

    assert spec is not None
    module = importlib.import_module("csvql.source_coordinator")
    assert module.SourceCoordinator
    assert module.PreparationContext


def test_resolved_source_is_an_immutable_resource_free_progressive_value() -> None:
    """Adding a live runtime object to resolution would couple identity to lifecycle."""

    source_module = importlib.import_module("csvql.source")
    canonical_locator = _canonical_test_locator("orders.csv")
    canonical_parent = Path(canonical_locator).parent

    assert hasattr(source_module, "ResolvedSource")
    resolved = source_module.ResolvedSource(
        provider_key="csv",
        source_kind="csv",
        provider_interpretation_version="1",
        alias="orders",
        alias_key="orders",
        canonical_locator=canonical_locator,
        requested_locator="orders.csv",
        locator_shape="file",
        semantic_options=(),
        operational_options=(),
        identity=SourceIdentity("a" * 64, IdentityStrength.OBSERVATIONAL),
        selection_reason="explicit_type",
        adapter_implementation_version="1",
        duckdb_version="1.4.0",
        provider_facts=FrozenJSONObject(
            (
                ("fingerprint_version", 1),
                ("modified_at", "2026-07-27T00:00:00+00:00"),
                ("modified_time_ns", 1),
                ("size_bytes", 12),
            )
        ),
    )

    assert resolved.spec == SourceSpec(
        alias="orders",
        kind="csv",
        locator="orders.csv",
        anchor=canonical_parent,
    )
    assert resolved.fingerprint.as_dict() == {
        "version": 1,
        "size_bytes": 12,
        "modified_at": "2026-07-27T00:00:00+00:00",
    }
    assert resolved.as_json_value() == source_module.freeze_source_value(
        {
            "adapter_implementation_version": "1",
            "alias": "orders",
            "alias_key": "orders",
            "canonical_locator": canonical_locator,
            "dependency_versions": [],
            "duckdb_version": "1.4.0",
            "identity": {
                "digest": "a" * 64,
                "strength": "observational",
            },
            "locator_shape": "file",
            "operational_options": {},
            "provider_facts": {
                "fingerprint_version": 1,
                "modified_at": "2026-07-27T00:00:00+00:00",
                "modified_time_ns": 1,
                "size_bytes": 12,
            },
            "provider_interpretation_version": "1",
            "provider_key": "csv",
            "requested_locator": "orders.csv",
            "resolution_evidence": [],
            "selection_evidence": [],
            "selection_reason": "explicit_type",
            "semantic_options": {},
            "source_kind": "csv",
        }
    )
    with pytest.raises(FrozenInstanceError):
        resolved.alias = "changed"  # type: ignore[misc]


class _RecordingDetection:
    def __init__(self, outcomes: dict[str, object], events: list[str]) -> None:
        self._outcomes = outcomes
        self._events = events

    def detect(self, request: SourceRequest, *, operation: object) -> object:
        self._events.append(f"detect:{request.alias}")
        return self._outcomes[request.alias]


class _RecordingFactory:
    def __init__(self, adapters: dict[str, object], events: list[str]) -> None:
        self._adapters = adapters
        self._events = events

    def activate(self, selected: SelectedSource, context: object) -> object:
        self._events.append(f"activate:{selected.request.alias}")
        adapter = self._adapters[selected.request.alias]
        adapter._activation_context = context
        return adapter


class _RecordingEngineSession:
    session_id = "engine-session-1"

    def __init__(
        self,
        events: list[str],
        *,
        active: bool = False,
        tainted: bool = False,
    ) -> None:
        self.events = events
        self.has_active_execution = active
        self.is_tainted = tainted

    def preflight_aliases(self, aliases: tuple[str, ...]) -> None:
        self.events.append(f"preflight:{','.join(aliases)}")

    def inspect_dependency(
        self,
        dependency_key: str | None,
        dependency_kind: str | None,
        *,
        operation: object,
    ) -> object:
        del operation
        from csvql.source_adapter import EngineDependencyState

        self.events.append(f"inspect:{dependency_key or 'none'}")
        return EngineDependencyState(
            dependency_key=dependency_key,
            available=True,
            dependency_version=(None if dependency_key is None else f"{dependency_kind}-test"),
            duckdb_version="1.4.0",
        )


class _RecordingBinding:
    def __init__(
        self,
        resolved_source: object,
        engine_session_id: str,
        events: list[str],
        *,
        fail_close: bool = False,
        confirmed_strength: IdentityStrength = IdentityStrength.OBSERVATIONAL,
    ) -> None:
        self.resolved_source = resolved_source
        self.engine_session_id = engine_session_id
        self.events = events
        self.state = "idle"
        self._fail_close = fail_close
        self._confirmed_strength = confirmed_strength

    @property
    def alias(self) -> str:
        return self.resolved_source.alias

    def close(self, context: object) -> None:
        if self.state == "closed":
            return
        self.events.append(f"close:{self.alias}")
        if self._fail_close:
            raise RuntimeError("cleanup failed")
        self.state = "closed"

    def revalidate(self, requirement: object, context: object) -> object:
        source_module = importlib.import_module("csvql.source")
        self.events.append(f"revalidate:{self.alias}")
        return source_module.IdentityValidationResult(
            alias=self.alias,
            status=source_module.IdentityValidationStatus.CONFIRMED,
            required_strength=requirement.strength,
            confirmed_strength=self._confirmed_strength,
        )


class _RecordingAdapter:
    provider_key = "csv"
    implementation_version = "1"

    def __init__(
        self,
        *,
        events: list[str],
        fail_bind: bool = False,
    ) -> None:
        self._events = events
        self._fail_bind = fail_bind
        self._activation_context = None

    def resolve(self, selected: SelectedSource, operation: object) -> object:
        self._events.append(f"resolve:{selected.request.alias}")
        resolved = _resolved(selected.request)
        if self._activation_context is None:
            return resolved
        return replace(
            resolved,
            duckdb_version=self._activation_context.duckdb_version,
            dependency_versions=self._activation_context.selected_dependency_versions(
                selected.descriptor.dependency
            ),
        )

    def bind(
        self,
        resolved: object,
        engine_session: _RecordingEngineSession,
        binding_context: object,
    ) -> _RecordingBinding:
        self._events.append(f"bind:{resolved.alias}")
        if self._fail_bind:
            from csvql.exceptions import SourceError

            raise SourceError(
                "source_bind_failed",
                "Binding failed.",
                kind="csv",
                alias=resolved.alias,
            )
        return _RecordingBinding(resolved, engine_session.session_id, self._events)


def _selected(
    request: SourceRequest,
    *,
    dependency: DependencyRequirement | None = None,
) -> SelectedSource:
    descriptor = DescriptorView(
        provider_key="csv",
        source_kind="csv",
        factory_key="builtin.csv",
        provider_interpretation_version="1",
        extensions=(".csv",),
        dependency=dependency,
    )
    return SelectedSource(
        request=request,
        provider_key="csv",
        source_kind="csv",
        descriptor=descriptor,
        selection_reason="explicit_type",
        extension_evidence=None,
        options=(),
    )


def _resolved(request: SourceRequest) -> object:
    source_module = importlib.import_module("csvql.source")
    return source_module.ResolvedSource(
        provider_key="csv",
        source_kind="csv",
        provider_interpretation_version="1",
        alias=request.alias,
        alias_key=request.alias_key,
        canonical_locator=_canonical_test_locator(f"{request.alias}.csv"),
        requested_locator=request.locator,
        locator_shape="file",
        semantic_options=(),
        operational_options=(),
        identity=SourceIdentity(
            request.alias.encode("utf-8").hex().ljust(64, "0"),
            IdentityStrength.OBSERVATIONAL,
        ),
        selection_reason="explicit_type",
        adapter_implementation_version="1",
        duckdb_version="1.4.0",
    )


def _preparation_context() -> object:
    coordinator_module = importlib.import_module("csvql.source_coordinator")
    factory_module = importlib.import_module("csvql.adapter_factory")
    operation_module = importlib.import_module("csvql.operation")
    return coordinator_module.PreparationContext(
        operation=operation_module.OperationContext(operation_module.OperationToken()),
        activation=factory_module.ActivationContext(duckdb_version="1.4.0"),
    )


def test_prepare_resolves_every_source_before_binding_in_request_order() -> None:
    """Binding before all resolutions succeed would leak a partial source batch."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    requests = (
        build_source_request(
            alias="orders",
            locator="orders.csv",
            explicit_type="csv",
        ),
        build_source_request(
            alias="customers",
            locator="customers.csv",
            explicit_type="csv",
        ),
    )
    events: list[str] = []
    outcomes = {request.alias: _selected(request) for request in requests}
    adapters = {request.alias: _RecordingAdapter(events=events) for request in requests}
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(outcomes, events),
        _RecordingFactory(adapters, events),
    )

    outcome = coordinator.prepare(
        requests,
        _RecordingEngineSession(events),
        _preparation_context(),
    )

    assert isinstance(outcome, source_module.PreparedSources)
    assert tuple(source.alias for source in outcome.resolved_sources) == (
        "orders",
        "customers",
    )
    assert tuple(binding.alias for binding in outcome.bindings) == (
        "orders",
        "customers",
    )
    assert events == [
        "preflight:orders,customers",
        "detect:orders",
        "detect:customers",
        "activate:orders",
        "activate:customers",
        "resolve:orders",
        "resolve:customers",
        "bind:orders",
        "bind:customers",
    ]


def test_prepare_detects_entire_batch_before_selected_dependency_inspection() -> None:
    """Availability work before detection completes would probe an unselected provider."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    requests = (
        build_source_request(
            alias="orders",
            locator="orders.csv",
            explicit_type="csv",
        ),
        build_source_request(
            alias="customers",
            locator="customers.csv",
            explicit_type="csv",
        ),
    )
    events: list[str] = []
    outcomes = {
        "orders": _selected(
            requests[0],
            dependency=DependencyRequirement("runtime.orders", "test_runtime"),
        ),
        "customers": _selected(
            requests[1],
            dependency=DependencyRequirement("runtime.customers", "test_runtime"),
        ),
    }
    adapters = {request.alias: _RecordingAdapter(events=events) for request in requests}
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(outcomes, events),
        _RecordingFactory(adapters, events),
    )
    context = coordinator_module.PreparationContext(
        operation=importlib.import_module("csvql.operation").OperationContext(
            importlib.import_module("csvql.operation").OperationToken()
        )
    )

    outcome = coordinator.prepare(
        requests,
        _RecordingEngineSession(events),
        context,
    )

    assert isinstance(outcome, source_module.PreparedSources)
    assert events == [
        "preflight:orders,customers",
        "detect:orders",
        "detect:customers",
        "inspect:runtime.orders",
        "activate:orders",
        "inspect:runtime.customers",
        "activate:customers",
        "resolve:orders",
        "resolve:customers",
        "bind:orders",
        "bind:customers",
    ]


def test_prepare_reuses_valid_resolved_snapshots_without_resolving_again() -> None:
    """A resource-free snapshot may be rebound without repeating provider I/O."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    request = build_source_request(
        alias="orders",
        locator=_canonical_test_locator("orders.csv"),
        explicit_type="csv",
    )
    events: list[str] = []
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection({"orders": _selected(request)}, events),
        _RecordingFactory({"orders": _RecordingAdapter(events=events)}, events),
    )

    outcome = coordinator.prepare(
        (request,),
        _RecordingEngineSession(events),
        _preparation_context(),
        resolved_snapshots=(_resolved(request),),
    )

    assert isinstance(outcome, source_module.PreparedSources)
    assert events == [
        "preflight:orders",
        "detect:orders",
        "activate:orders",
        "bind:orders",
    ]


def test_prepare_rejects_snapshot_runtime_mismatch_before_binding() -> None:
    """A stale provider runtime fact must not be trusted as a bindable snapshot."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    request = build_source_request(
        alias="orders",
        locator=_canonical_test_locator("orders.csv"),
        explicit_type="csv",
    )
    events: list[str] = []
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection({"orders": _selected(request)}, events),
        _RecordingFactory({"orders": _RecordingAdapter(events=events)}, events),
    )
    stale = replace(_resolved(request), adapter_implementation_version="stale")

    outcome = coordinator.prepare(
        (request,),
        _RecordingEngineSession(events),
        _preparation_context(),
        resolved_snapshots=(stale,),
    )

    assert isinstance(outcome, source_module.SourcePreparationFailure)
    assert outcome.diagnostics[0].code is source_module.DiagnosticCode.SOURCE_IDENTITY_CHANGED
    assert events == [
        "preflight:orders",
        "detect:orders",
        "activate:orders",
    ]


def test_prepare_rejects_snapshot_dependency_version_mismatch() -> None:
    """A resolved workbook cannot be rebound under a different provider runtime."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    factory_module = importlib.import_module("csvql.adapter_factory")
    operation_module = importlib.import_module("csvql.operation")
    source_module = importlib.import_module("csvql.source")
    request = build_source_request(
        alias="orders",
        locator=_canonical_test_locator("orders.csv"),
        explicit_type="csv",
    )
    dependency = DependencyRequirement("runtime.orders", "test_runtime")
    events: list[str] = []
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(
            {"orders": _selected(request, dependency=dependency)},
            events,
        ),
        _RecordingFactory(
            {"orders": _RecordingAdapter(events=events)},
            events,
        ),
    )
    context = coordinator_module.PreparationContext(
        operation=operation_module.OperationContext(operation_module.OperationToken()),
        activation=factory_module.ActivationContext(
            available_dependencies=frozenset((dependency.key,)),
            dependency_versions=((dependency.key, "current"),),
            duckdb_version="1.4.0",
        ),
    )
    stale = replace(
        _resolved(request),
        dependency_versions=((dependency.key, "stale"),),
    )

    outcome = coordinator.prepare(
        (request,),
        _RecordingEngineSession(events),
        context,
        resolved_snapshots=(stale,),
    )

    assert isinstance(outcome, source_module.SourcePreparationFailure)
    assert outcome.diagnostics[0].code is source_module.DiagnosticCode.SOURCE_IDENTITY_CHANGED
    assert events == [
        "preflight:orders",
        "detect:orders",
        "activate:orders",
    ]


def test_prepare_collects_all_nonselection_diagnostics_before_activation() -> None:
    """Stopping at the first unknown source would hide deterministic batch defects."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    requests = (
        build_source_request(alias="first", locator="first.unknown"),
        build_source_request(alias="second", locator="second.unknown"),
    )
    outcomes: dict[str, object] = {}
    for request in requests:
        action = RequiredAction("specify_type", ("csv",))
        outcomes[request.alias] = UnknownSource(
            request=request,
            diagnostic=SourceDiagnostic(
                code=DiagnosticCode.SOURCE_UNKNOWN,
                stage=DiagnosticStage.DETECTION,
                message=f"{request.alias} is unknown.",
                safe_source_reference=request.safe_source_reference,
                required_action=action,
            ),
            required_action=action,
        )
    events: list[str] = []
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(outcomes, events),
        _RecordingFactory({}, events),
    )

    outcome = coordinator.prepare(
        requests,
        _RecordingEngineSession(events),
        coordinator_module.PreparationContext(
            operation=importlib.import_module("csvql.operation").OperationContext(
                importlib.import_module("csvql.operation").OperationToken()
            )
        ),
    )

    assert isinstance(outcome, source_module.SourcePreparationFailure)
    assert tuple(diagnostic.message for diagnostic in outcome.diagnostics) == (
        "first is unknown.",
        "second is unknown.",
    )
    assert events == [
        "preflight:first,second",
        "detect:first",
        "detect:second",
    ]


def test_prepare_rolls_back_completed_bindings_when_a_later_bind_fails() -> None:
    """A later bind failure must not leave an earlier registration live."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    requests = (
        build_source_request(
            alias="orders",
            locator="orders.csv",
            explicit_type="csv",
        ),
        build_source_request(
            alias="customers",
            locator="customers.csv",
            explicit_type="csv",
        ),
    )
    events: list[str] = []
    outcomes = {request.alias: _selected(request) for request in requests}
    adapters = {
        "orders": _RecordingAdapter(events=events),
        "customers": _RecordingAdapter(events=events, fail_bind=True),
    }
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(outcomes, events),
        _RecordingFactory(adapters, events),
    )

    outcome = coordinator.prepare(
        requests,
        _RecordingEngineSession(events),
        _preparation_context(),
    )

    assert isinstance(outcome, source_module.SourcePreparationFailure)
    assert tuple(diagnostic.code.value for diagnostic in outcome.diagnostics) == (
        "source.bind_failed",
    )
    assert events[-3:] == ["bind:orders", "bind:customers", "close:orders"]


def test_prepare_closes_a_returned_binding_that_fails_contract_validation() -> None:
    """A malformed returned binding is already live and must be rolled back."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    request = build_source_request(
        alias="orders",
        locator="orders.csv",
        explicit_type="csv",
    )
    events: list[str] = []

    class InvalidBindingAdapter(_RecordingAdapter):
        def bind(self, resolved, engine_session, binding_context):
            binding = super().bind(resolved, engine_session, binding_context)
            binding.engine_session_id = "wrong-session"
            return binding

    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection({"orders": _selected(request)}, events),
        _RecordingFactory(
            {"orders": InvalidBindingAdapter(events=events)},
            events,
        ),
    )

    outcome = coordinator.prepare(
        (request,),
        _RecordingEngineSession(events),
        _preparation_context(),
    )

    assert isinstance(outcome, source_module.SourcePreparationFailure)
    assert events[-2:] == ["bind:orders", "close:orders"]


def test_prepare_rolls_back_before_propagating_unexpected_bind_failure() -> None:
    """Unexpected provider defects must not bypass atomic rollback."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    requests = (
        build_source_request(
            alias="orders",
            locator="orders.csv",
            explicit_type="csv",
        ),
        build_source_request(
            alias="customers",
            locator="customers.csv",
            explicit_type="csv",
        ),
    )
    events: list[str] = []

    class UnexpectedFailureAdapter(_RecordingAdapter):
        def bind(self, resolved, engine_session, binding_context):
            del engine_session, binding_context
            self._events.append(f"bind:{resolved.alias}")
            raise RuntimeError("unexpected provider defect")

    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(
            {request.alias: _selected(request) for request in requests},
            events,
        ),
        _RecordingFactory(
            {
                "orders": _RecordingAdapter(events=events),
                "customers": UnexpectedFailureAdapter(events=events),
            },
            events,
        ),
    )

    with pytest.raises(RuntimeError, match="unexpected provider defect"):
        coordinator.prepare(
            requests,
            _RecordingEngineSession(events),
            _preparation_context(),
        )

    assert events[-3:] == ["bind:orders", "bind:customers", "close:orders"]


def test_preflight_diagnostic_never_emits_an_empty_provider_key() -> None:
    """Shared diagnostics must be valid and deterministic without explicit type."""

    coordinator_module = importlib.import_module("csvql.source_coordinator")
    source_module = importlib.import_module("csvql.source")
    request = build_source_request(alias="orders", locator="orders")
    events: list[str] = []

    class RejectingEngine(_RecordingEngineSession):
        def preflight_aliases(self, aliases: tuple[str, ...]) -> None:
            del aliases
            from csvql.exceptions import SourceError

            raise SourceError(
                "source_bind_failed",
                "Alias preflight failed.",
                alias="orders",
            )

    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection({}, events),
        _RecordingFactory({}, events),
    )

    outcome = coordinator.prepare(
        (request,),
        RejectingEngine(events),
        _preparation_context(),
    )

    assert isinstance(outcome, source_module.SourcePreparationFailure)
    assert outcome.diagnostics[0].required_action is not None
    assert outcome.diagnostics[0].required_action.provider_keys == ()


def _prepare_two_sources(
    *,
    events: list[str],
    engine: _RecordingEngineSession | None = None,
) -> tuple[object, object]:
    coordinator_module = importlib.import_module("csvql.source_coordinator")
    requests = (
        build_source_request(
            alias="orders",
            locator="orders.csv",
            explicit_type="csv",
        ),
        build_source_request(
            alias="customers",
            locator="customers.csv",
            explicit_type="csv",
        ),
    )
    outcomes = {request.alias: _selected(request) for request in requests}
    adapters = {request.alias: _RecordingAdapter(events=events) for request in requests}
    coordinator = coordinator_module.SourceCoordinator(
        _RecordingDetection(outcomes, events),
        _RecordingFactory(adapters, events),
    )
    prepared = coordinator.prepare(
        requests,
        engine or _RecordingEngineSession(events),
        _preparation_context(),
    )
    return coordinator, prepared


def test_revalidate_preserves_binding_order_and_rejects_strength_downgrade() -> None:
    """Reporting a weaker identity as confirmed would overstate reproducibility."""

    source_module = importlib.import_module("csvql.source")
    events: list[str] = []
    coordinator, prepared = _prepare_two_sources(events=events)
    events.clear()
    requirement = source_module.IdentityRequirement(source_module.IdentityStrength.STRONG)

    outcome = coordinator.revalidate(prepared, requirement)

    assert tuple(result.alias for result in outcome.results) == (
        "orders",
        "customers",
    )
    assert tuple(result.status.value for result in outcome.results) == (
        "unavailable",
        "unavailable",
    )
    assert events == ["revalidate:orders", "revalidate:customers"]


def test_revalidate_rejects_a_closed_scope_with_an_identity_failure() -> None:
    """A released scope cannot truthfully confirm its former source identity."""

    from csvql.exceptions import SourceIdentityError

    source_module = importlib.import_module("csvql.source")
    events: list[str] = []
    coordinator, prepared = _prepare_two_sources(events=events)
    coordinator.release(prepared)

    with pytest.raises(SourceIdentityError) as error:
        coordinator.revalidate(prepared, source_module.IdentityRequirement())

    assert error.value.code == "source_changed"


def test_release_closes_bindings_in_reverse_order_and_is_idempotent() -> None:
    """Changing cleanup order or repeating unregister would leak dependent resources."""

    events: list[str] = []
    coordinator, prepared = _prepare_two_sources(events=events)
    events.clear()

    first_report = coordinator.release(prepared)
    second_report = coordinator.release(prepared)

    assert first_report.succeeded
    assert not first_report.already_closed
    assert second_report.succeeded
    assert second_report.already_closed
    assert prepared.is_closed
    assert events == ["close:customers", "close:orders"]


def test_release_does_not_unregister_while_the_engine_is_executing() -> None:
    """Unregistering an active relation could race DuckDB execution."""

    source_module = importlib.import_module("csvql.source")
    events: list[str] = []
    engine = _RecordingEngineSession(events, active=True)
    coordinator, prepared = _prepare_two_sources(events=events, engine=engine)
    events.clear()

    report = coordinator.release(prepared)

    assert tuple(failure.code for failure in report.failures) == (
        source_module.DiagnosticCode.ENGINE_SESSION_ACTIVE.value,
    )
    assert not prepared.is_closed
    assert events == []


def test_release_returns_typed_taint_outcome_without_unregistering() -> None:
    """A borrowed tainted session must be left intact for its owner to close."""

    source_module = importlib.import_module("csvql.source")
    events: list[str] = []
    engine = _RecordingEngineSession(events, tainted=True)
    coordinator, prepared = _prepare_two_sources(events=events, engine=engine)
    events.clear()

    report = coordinator.release(prepared)

    assert tuple(failure.code for failure in report.failures) == (
        source_module.DiagnosticCode.ENGINE_SESSION_TAINTED.value,
    )
    assert not prepared.is_closed
    assert events == []
