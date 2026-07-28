"""Application composition root for the internal source-provider runtime."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Never

import duckdb

from csvql.adapter_factory import (
    ActivationContext,
    AdapterFactory,
    build_builtin_lazy_adapter_table,
)
from csvql.exceptions import SourceError, SourceErrorCode, SourceIdentityError
from csvql.operation import OperationContext
from csvql.source import (
    PreparedSources,
    ResolvedSource,
    SelectedSource,
    SourceDiagnostic,
    SourcePreparationFailure,
    SourceRequest,
    build_source_request,
)
from csvql.source_adapter import EngineSession
from csvql.source_coordinator import PreparationContext, SourceCoordinator
from csvql.source_detection import SourceDetectionService
from csvql.source_identifiers import build_builtin_identifier_table
from csvql.source_registry import build_builtin_descriptor_registry


@dataclass(frozen=True, slots=True)
class SourceComponents:
    """Validated default source components constructed without provider imports."""

    detection: SourceDetectionService
    factory: AdapterFactory
    coordinator: SourceCoordinator


def build_default_source_components() -> SourceComponents:
    """Build validated import-free metadata, detection, factory, and coordinator."""

    registry = build_builtin_descriptor_registry()
    detection = SourceDetectionService(registry, build_builtin_identifier_table())
    factory = AdapterFactory(registry, build_builtin_lazy_adapter_table())
    return SourceComponents(
        detection=detection,
        factory=factory,
        coordinator=SourceCoordinator(detection, factory),
    )


@lru_cache(maxsize=1)
def default_source_components() -> SourceComponents:
    """Return one lazily constructed immutable default composition."""

    return build_default_source_components()


def default_activation_context() -> ActivationContext:
    """Build core runtime facts without inspecting optional provider dependencies."""

    return ActivationContext(duckdb_version=duckdb.__version__)


def resolve_source_request(
    request: SourceRequest,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    """Resolve one request through detection and selected-only activation."""

    components = default_source_components()
    outcome = components.detection.detect(request, operation=operation)
    if not isinstance(outcome, SelectedSource):
        raise SourceError(
            _legacy_error_code(outcome.diagnostic.code.value),
            outcome.diagnostic.message,
            alias=request.alias,
            suggestion=(
                None
                if outcome.required_action is None
                else outcome.required_action.kind.replace("_", " ")
            ),
        )
    adapter = components.factory.activate(outcome, default_activation_context())
    return adapter.resolve(outcome, operation)


def prepare_source_requests(
    requests: tuple[SourceRequest, ...],
    *,
    engine_session: EngineSession,
    operation: OperationContext,
    resolved_snapshots: tuple[ResolvedSource, ...] | None = None,
) -> PreparedSources | SourcePreparationFailure:
    """Prepare one request batch through the default coordinator."""

    return default_source_components().coordinator.prepare(
        requests,
        engine_session,
        PreparationContext(
            operation=operation,
            activation=default_activation_context(),
        ),
        resolved_snapshots=resolved_snapshots,
    )


def prepare_resolved_sources(
    resolved_sources: tuple[ResolvedSource, ...],
    *,
    engine_session: EngineSession,
    operation: OperationContext,
) -> PreparedSources:
    """Compatibility bridge that re-prepares and revalidates resolved snapshots."""

    requests = tuple(
        build_source_request(
            alias=source.alias,
            locator=source.canonical_locator,
            anchor=None,
            explicit_type=source.provider_key,
            options=(*source.semantic_options, *source.operational_options),
        )
        for source in resolved_sources
    )
    outcome = prepare_source_requests(
        requests,
        engine_session=engine_session,
        operation=operation,
        resolved_snapshots=resolved_sources,
    )
    if isinstance(outcome, SourcePreparationFailure):
        raise_preparation_failure(outcome, requests=requests)
    expected_identities = tuple(source.identity for source in resolved_sources)
    actual_identities = tuple(source.identity for source in outcome.resolved_sources)
    if actual_identities != expected_identities:
        default_source_components().coordinator.release(outcome)
        first = resolved_sources[0]
        raise SourceIdentityError(
            "source_changed",
            f"{first.source_kind.upper()} source changed after submission.",
            kind=first.source_kind,
            alias=first.alias,
            suggestion=(
                "Submit the operation again to capture the current "
                f"{first.source_kind.upper()} source."
            ),
        )
    return outcome


def raise_preparation_failure(
    failure: SourcePreparationFailure,
    *,
    requests: tuple[SourceRequest, ...] = (),
) -> Never:
    """Translate one typed internal preparation outcome for legacy boundaries."""

    diagnostic = failure.diagnostics[0]
    diagnostic_alias = next(
        (
            evidence.stable_detail
            for evidence in diagnostic.evidence
            if evidence.evidence_kind == "source_alias"
        ),
        None,
    )
    request = next(
        (
            candidate
            for candidate in requests
            if (diagnostic_alias is not None and candidate.alias == diagnostic_alias)
            or (
                diagnostic_alias is None
                and candidate.safe_source_reference == diagnostic.safe_source_reference
            )
        ),
        requests[0] if requests else None,
    )
    raise SourceError(
        _legacy_error_code(diagnostic.code.value),
        diagnostic.message,
        kind=None if request is None else request.explicit_type,
        alias=None if request is None else request.alias,
        suggestion=_legacy_suggestion(diagnostic, request),
    )


def _legacy_suggestion(
    diagnostic: SourceDiagnostic,
    request: SourceRequest | None,
) -> str | None:
    required_action = diagnostic.required_action
    if required_action is None:
        return None
    if required_action.kind == "resubmit_source":
        source_kind = "source" if request is None else (request.explicit_type or "source")
        display_kind = {
            "csv": "CSV",
            "excel": "Excel",
            "json": "JSON",
            "ndjson": "NDJSON",
            "parquet": "Parquet",
        }.get(source_kind, source_kind)
        return f"Submit the operation again to capture the current {display_kind} source."
    return required_action.kind.replace("_", " ")


def _legacy_error_code(code: str) -> SourceErrorCode:
    if code in {
        "source.bind_failed",
        "source.parquet_schema_mismatch",
        "source.provider_contract_invalid",
    }:
        return "source_bind_failed"
    if code in {
        "source.dataset_changed",
        "source.identity_changed",
        "source.identity_invalid",
        "source.identity_unavailable",
        "source.identity_strength_unavailable",
    }:
        return "source_changed"
    if code in {
        "source.dataset_manifest_limit",
        "source.dataset_symlink_rejected",
        "source.locator_shape_invalid",
        "source.parquet_dataset_empty",
        "source.parquet_invalid",
        "source.partitioning_invalid",
        "source.resolution_failed",
    }:
        return "source_missing"
    if code.startswith("source.activation"):
        return "missing_optional_dependency"
    return "unknown_source_kind"
