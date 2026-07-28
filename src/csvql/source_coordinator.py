"""Application lifecycle coordination for prepared LocalQL sources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from csvql.adapter_factory import (
    ActivationContext,
    AdapterFactory,
)
from csvql.exceptions import (
    SourceActivationError,
    SourceBindingError,
    SourceError,
    SourceIdentityError,
)
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    CleanupFailure,
    CleanupReport,
    DiagnosticCode,
    DiagnosticEvidence,
    DiagnosticStage,
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationOutcome,
    IdentityValidationResult,
    IdentityValidationStatus,
    PreparedSources,
    PreparedSourcesState,
    RequiredAction,
    ResolvedSource,
    SelectedSource,
    SourceDiagnostic,
    SourcePreparationFailure,
    SourceRequest,
)
from csvql.source_adapter import (
    BindingContext,
    EngineSession,
    RelationalBinding,
    SourceAdapter,
)
from csvql.source_detection import SourceDetectionService


@dataclass(frozen=True, slots=True)
class PreparationContext:
    """Operation-scoped inputs used while preparing sources."""

    operation: OperationContext
    activation: ActivationContext | None = None


class SourceCoordinator:
    """Thin application boundary for source preparation and cleanup."""

    def __init__(
        self,
        detection: SourceDetectionService,
        factory: AdapterFactory,
    ) -> None:
        self._detection = detection
        self._factory = factory

    def prepare(
        self,
        requests: Sequence[SourceRequest],
        engine_session: EngineSession,
        context: PreparationContext,
        *,
        resolved_snapshots: Sequence[ResolvedSource] | None = None,
    ) -> PreparedSources | SourcePreparationFailure:
        """Prepare one all-or-nothing source batch in request order.

        ``resolved_snapshots`` is an internal compatibility path for values
        already resolved in the same application workflow. Detection and
        activation still run, but provider resolution is not repeated.
        """

        normalized_requests = tuple(requests)
        if not normalized_requests:
            return SourcePreparationFailure(
                (
                    SourceDiagnostic(
                        code=DiagnosticCode.SOURCE_REQUEST_INVALID,
                        stage=DiagnosticStage.REQUEST,
                        message="At least one source request is required.",
                        safe_source_reference="",
                        required_action=RequiredAction("provide_source"),
                    ),
                )
            )
        if not all(isinstance(request, SourceRequest) for request in normalized_requests):
            return SourcePreparationFailure(
                (
                    SourceDiagnostic(
                        code=DiagnosticCode.SOURCE_REQUEST_INVALID,
                        stage=DiagnosticStage.REQUEST,
                        message="Source preparation accepts only validated source requests.",
                        safe_source_reference="",
                        required_action=RequiredAction("rebuild_request"),
                    ),
                )
            )
        normalized_snapshots = None if resolved_snapshots is None else tuple(resolved_snapshots)
        if normalized_snapshots is not None and (
            len(normalized_snapshots) != len(normalized_requests)
            or not all(isinstance(source, ResolvedSource) for source in normalized_snapshots)
        ):
            return SourcePreparationFailure(
                (
                    SourceDiagnostic(
                        code=DiagnosticCode.SOURCE_REQUEST_INVALID,
                        stage=DiagnosticStage.REQUEST,
                        message=(
                            "Resolved source snapshots must match the validated request batch."
                        ),
                        safe_source_reference="",
                        required_action=RequiredAction("rebuild_request"),
                    ),
                )
            )

        context.operation.checkpoint()
        try:
            engine_session.preflight_aliases(
                tuple(request.alias for request in normalized_requests)
            )
        except SourceError as exc:
            return SourcePreparationFailure(
                (
                    _source_error_diagnostic(
                        exc,
                        stage=DiagnosticStage.REQUEST,
                        request=_request_for_error(normalized_requests, exc),
                    ),
                )
            )

        detections = tuple(
            self._detection.detect(request, operation=context.operation)
            for request in normalized_requests
        )
        nonselection_diagnostics = tuple(
            outcome.diagnostic for outcome in detections if not isinstance(outcome, SelectedSource)
        )
        if nonselection_diagnostics:
            return SourcePreparationFailure(nonselection_diagnostics)

        selected_sources = cast(tuple[SelectedSource, ...], detections)
        adapters: list[SourceAdapter] = []
        activation_contexts: list[ActivationContext] = []
        dependency_contexts: dict[tuple[str | None, str | None], ActivationContext] = {}
        for selected in selected_sources:
            context.operation.checkpoint()
            requirement = selected.descriptor.dependency
            dependency_key = None if requirement is None else requirement.key
            dependency_kind = None if requirement is None else requirement.kind
            try:
                activation = context.activation
                if activation is None:
                    cache_key = (dependency_key, dependency_kind)
                    activation = dependency_contexts.get(cache_key)
                    if activation is None:
                        state = engine_session.inspect_dependency(
                            dependency_key,
                            dependency_kind,
                            operation=context.operation,
                        )
                        if state.dependency_key != dependency_key:
                            raise SourceActivationError(
                                "source.provider_contract_invalid",
                                "Engine dependency evidence does not match the selected provider.",
                                provider_key=selected.provider_key,
                                dependency_key=dependency_key,
                            )
                        available_dependencies = (
                            frozenset()
                            if dependency_key is None or not state.available
                            else frozenset((dependency_key,))
                        )
                        dependency_versions = (
                            ()
                            if dependency_key is None or state.dependency_version is None
                            else ((dependency_key, state.dependency_version),)
                        )
                        activation = ActivationContext(
                            available_dependencies=available_dependencies,
                            dependency_versions=dependency_versions,
                            duckdb_version=state.duckdb_version,
                        )
                        dependency_contexts[cache_key] = activation
                adapters.append(self._factory.activate(selected, activation))
                activation_contexts.append(activation)
            except SourceActivationError as exc:
                return SourcePreparationFailure((_activation_diagnostic(exc, selected.request),))
            except SourceError as exc:
                return SourcePreparationFailure(
                    (
                        _source_error_diagnostic(
                            exc,
                            stage=DiagnosticStage.ACTIVATION,
                            request=selected.request,
                        ),
                    )
                )

        if normalized_snapshots is None:
            resolved_sources: list[ResolvedSource] = []
            for selected, adapter, activation in zip(
                selected_sources,
                adapters,
                activation_contexts,
                strict=True,
            ):
                context.operation.checkpoint()
                try:
                    resolved = adapter.resolve(selected, context.operation)
                    _validate_resolved_snapshot(
                        selected,
                        resolved=resolved,
                        adapter=adapter,
                        activation=activation,
                    )
                    resolved_sources.append(resolved)
                except SourceError as exc:
                    return SourcePreparationFailure(
                        (
                            _source_error_diagnostic(
                                exc,
                                stage=DiagnosticStage.RESOLUTION,
                                request=selected.request,
                            ),
                        )
                    )
        else:
            resolved_sources = list(normalized_snapshots)
            for selected, adapter, resolved, activation in zip(
                selected_sources,
                adapters,
                resolved_sources,
                activation_contexts,
                strict=True,
            ):
                context.operation.checkpoint()
                try:
                    _validate_resolved_snapshot(
                        selected,
                        resolved=resolved,
                        adapter=adapter,
                        activation=activation,
                    )
                except SourceError as exc:
                    return SourcePreparationFailure(
                        (
                            _source_error_diagnostic(
                                exc,
                                stage=DiagnosticStage.IDENTITY,
                                request=selected.request,
                            ),
                        )
                    )

        bindings: list[RelationalBinding] = []
        for resolved, adapter, selected in zip(
            resolved_sources,
            adapters,
            selected_sources,
            strict=True,
        ):
            context.operation.checkpoint()
            try:
                binding = adapter.bind(
                    resolved,
                    engine_session,
                    BindingContext(operation=context.operation),
                )
                bindings.append(binding)
                _validate_binding(
                    binding,
                    resolved=resolved,
                    engine_session=engine_session,
                )
                context.operation.checkpoint()
            except OperationCancelled:
                _close_bindings(bindings)
                raise
            except SourceError as exc:
                cleanup_failures = _close_bindings(bindings)
                return SourcePreparationFailure(
                    (
                        _source_error_diagnostic(
                            exc,
                            stage=(
                                DiagnosticStage.IDENTITY
                                if isinstance(exc, SourceIdentityError)
                                else DiagnosticStage.BINDING
                            ),
                            request=selected.request,
                        ),
                    ),
                    cleanup_failures,
                )
            except BaseException as exc:
                cleanup_failures = _close_bindings(bindings)
                if cleanup_failures:
                    exc.add_note(
                        "Cleanup uncertainty: one or more prepared source bindings "
                        "could not be closed."
                    )
                raise

        return PreparedSources(
            engine_session_id=engine_session.session_id,
            resolved_sources=tuple(resolved_sources),
            bindings=tuple(bindings),
            _engine_session=engine_session,
            _operation_context=context.operation,
        )

    def revalidate(
        self,
        prepared_sources: PreparedSources,
        requirement: IdentityRequirement,
    ) -> IdentityValidationOutcome:
        """Revalidate every binding without weakening the requested strength."""

        if prepared_sources.state is PreparedSourcesState.CLOSED:
            raise SourceIdentityError(
                "source_changed",
                "Prepared sources are already closed.",
                suggestion="Prepare the sources again before executing a query.",
            )
        engine_session = cast(EngineSession, prepared_sources._engine_session)
        if engine_session.session_id != prepared_sources.engine_session_id:
            raise SourceBindingError(
                "source_bind_failed",
                "Prepared sources belong to a different engine session.",
                suggestion="Prepare the sources again in the active engine session.",
            )
        operation = prepared_sources._operation_context
        if not isinstance(operation, OperationContext):
            operation = OperationContext(OperationToken())

        results: list[IdentityValidationResult] = []
        for binding in prepared_sources.bindings:
            operation.checkpoint()
            result = binding.revalidate(requirement, operation)
            if (
                result.status is IdentityValidationStatus.CONFIRMED
                and result.confirmed_strength is not None
                and _identity_strength_rank(result.confirmed_strength)
                < _identity_strength_rank(requirement.strength)
            ):
                result = IdentityValidationResult(
                    alias=result.alias,
                    status=IdentityValidationStatus.UNAVAILABLE,
                    required_strength=requirement.strength,
                    diagnostic=SourceDiagnostic(
                        code=DiagnosticCode.SOURCE_IDENTITY_UNAVAILABLE,
                        stage=DiagnosticStage.IDENTITY,
                        message=("The requested source identity strength could not be confirmed."),
                        safe_source_reference=result.alias,
                        required_action=RequiredAction("choose_weaker_identity_or_resubmit"),
                    ),
                )
            results.append(result)
        return IdentityValidationOutcome(tuple(results))

    def release(self, prepared_sources: PreparedSources) -> CleanupReport:
        """Close every binding in reverse order without closing the engine."""

        if prepared_sources.is_closed:
            return CleanupReport(already_closed=True)
        engine_session = cast(EngineSession, prepared_sources._engine_session)
        if engine_session.session_id != prepared_sources.engine_session_id:
            return CleanupReport(
                (
                    CleanupFailure(
                        alias="",
                        code=DiagnosticCode.SOURCE_CLEANUP_FAILED.value,
                        message="Prepared sources belong to a different engine session.",
                    ),
                )
            )
        if engine_session.has_active_execution:
            return CleanupReport(
                (
                    CleanupFailure(
                        alias="",
                        code=DiagnosticCode.ENGINE_SESSION_ACTIVE.value,
                        message=(
                            "Prepared sources cannot be released while the engine is executing."
                        ),
                    ),
                )
            )
        if engine_session.is_tainted:
            return CleanupReport(
                (
                    CleanupFailure(
                        alias="",
                        code=DiagnosticCode.ENGINE_SESSION_TAINTED.value,
                        message=(
                            "Prepared sources cannot be released from a tainted engine session."
                        ),
                    ),
                )
            )

        failures = _close_bindings(prepared_sources.bindings)
        prepared_sources._mark_closed()
        return CleanupReport(failures)


def _validate_binding(
    binding: object,
    *,
    resolved: object,
    engine_session: EngineSession,
) -> None:
    alias = getattr(binding, "alias", None)
    resolved_alias = getattr(resolved, "alias", None)
    if alias != resolved_alias:
        raise SourceBindingError(
            "source_bind_failed",
            "Prepared binding alias does not match the resolved source.",
            alias=resolved_alias if isinstance(resolved_alias, str) else None,
        )
    if getattr(binding, "resolved_source", None) is not resolved:
        raise SourceBindingError(
            "source_bind_failed",
            "Prepared binding source does not match the resolved source.",
            alias=resolved_alias if isinstance(resolved_alias, str) else None,
        )
    if getattr(binding, "engine_session_id", None) != engine_session.session_id:
        raise SourceBindingError(
            "source_bind_failed",
            "Prepared binding belongs to a different engine session.",
            alias=resolved_alias if isinstance(resolved_alias, str) else None,
        )


def _validate_resolved_snapshot(
    selected: SelectedSource,
    *,
    resolved: ResolvedSource,
    adapter: SourceAdapter,
    activation: ActivationContext,
) -> None:
    """Reject stale or cross-provider snapshots before creating a binding."""

    if (
        resolved.provider_key != selected.provider_key
        or resolved.source_kind != selected.source_kind
        or resolved.alias != selected.request.alias
        or resolved.alias_key != selected.request.alias_key
        or resolved.provider_interpretation_version
        != selected.descriptor.provider_interpretation_version
        or resolved.adapter_implementation_version != adapter.implementation_version
        or resolved.duckdb_version != activation.duckdb_version
        or resolved.dependency_versions
        != activation.selected_dependency_versions(selected.descriptor.dependency)
    ):
        raise SourceIdentityError(
            "source_changed",
            "Resolved source runtime identity no longer matches the selected provider.",
            kind=resolved.source_kind,
            alias=resolved.alias,
            suggestion="Resolve the source again before preparing it.",
        )


def _close_bindings(
    bindings: Sequence[object],
) -> tuple[CleanupFailure, ...]:
    cleanup_context = OperationContext(OperationToken())
    failures: list[CleanupFailure] = []
    for binding in reversed(bindings):
        alias = getattr(binding, "alias", "")
        if not isinstance(alias, str):
            alias = ""
        close = getattr(binding, "close", None)
        if not callable(close):
            failures.append(
                CleanupFailure(
                    alias=alias,
                    code=DiagnosticCode.SOURCE_CLEANUP_FAILED.value,
                    message="A prepared source binding could not be closed.",
                )
            )
            continue
        try:
            close(cleanup_context)
        except BaseException:
            failures.append(
                CleanupFailure(
                    alias=alias,
                    code=DiagnosticCode.SOURCE_CLEANUP_FAILED.value,
                    message="A prepared source binding could not be closed.",
                )
            )
    return tuple(failures)


def _request_for_error(
    requests: Sequence[SourceRequest],
    error: SourceError,
) -> SourceRequest:
    if error.alias is not None:
        matching = next(
            (request for request in requests if request.alias == error.alias),
            None,
        )
        if matching is not None:
            return matching
    return requests[0]


def _source_error_diagnostic(
    error: SourceError,
    *,
    stage: DiagnosticStage,
    request: SourceRequest,
) -> SourceDiagnostic:
    if stage is DiagnosticStage.ACTIVATION:
        code = DiagnosticCode.SOURCE_ACTIVATION_FAILED
    else:
        try:
            code = DiagnosticCode(error.code)
        except ValueError:
            code = {
                DiagnosticStage.RESOLUTION: DiagnosticCode.SOURCE_RESOLUTION_FAILED,
                DiagnosticStage.BINDING: DiagnosticCode.SOURCE_BIND_FAILED,
                DiagnosticStage.IDENTITY: DiagnosticCode.SOURCE_IDENTITY_CHANGED,
            }.get(stage, DiagnosticCode.SOURCE_REQUEST_INVALID)
    return SourceDiagnostic(
        code=code,
        stage=stage,
        message=error.message,
        safe_source_reference=request.safe_source_reference,
        evidence=(
            DiagnosticEvidence(
                request.explicit_type or error.kind or "",
                "source_alias",
                request.alias,
            ),
        ),
        required_action=RequiredAction(
            ("resubmit_source" if stage is DiagnosticStage.IDENTITY else "correct_source"),
            () if error.kind is None else (error.kind,),
        ),
    )


def _activation_diagnostic(
    error: SourceActivationError,
    request: SourceRequest,
) -> SourceDiagnostic:
    try:
        code = DiagnosticCode(error.code)
    except ValueError:
        code = DiagnosticCode.SOURCE_ACTIVATION_FAILED
    evidence: list[DiagnosticEvidence] = []
    if error.dependency_key is not None:
        evidence.append(
            DiagnosticEvidence(
                error.provider_key,
                "dependency_key",
                error.dependency_key,
            )
        )
    if error.suggestion is not None:
        evidence.append(
            DiagnosticEvidence(
                error.provider_key,
                "dependency_guidance",
                error.suggestion,
            )
        )
    return SourceDiagnostic(
        code=code,
        stage=DiagnosticStage.ACTIVATION,
        message=error.message,
        safe_source_reference=request.safe_source_reference,
        evidence=tuple(evidence),
        required_action=RequiredAction("satisfy_provider_dependency", (error.provider_key,)),
    )


def _identity_strength_rank(strength: IdentityStrength) -> int:
    return {
        IdentityStrength.OBSERVATIONAL: 0,
        IdentityStrength.STRONG: 1,
        IdentityStrength.EXACT: 2,
    }[strength]
