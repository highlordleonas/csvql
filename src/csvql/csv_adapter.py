"""CSV provider resolution and engine-session binding."""

from __future__ import annotations

import csv
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import duckdb

from csvql.adapter_factory import ProviderActivationFacts
from csvql.exceptions import (
    EngineSessionTaintedError,
    SourceBindingError,
    SourceCleanupError,
    SourceError,
    SourceIdentityError,
    SourceResolutionError,
)
from csvql.models import DialectInfo
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.private_artifacts import is_private_result_artifact
from csvql.source import (
    DiagnosticCode,
    DiagnosticEvidence,
    DiagnosticStage,
    FrozenJSONObject,
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationResult,
    IdentityValidationStatus,
    ObservedFileFacts,
    RequiredAction,
    ResolvedSource,
    SelectedSource,
    SourceDiagnostic,
    build_source_identity,
    freeze_source_value,
)
from csvql.source_adapter import (
    BindingContext,
    BindingState,
    EngineSession,
    RelationalBinding,
)
from csvql.sql_utils import quote_identifier

__version__ = "1"

SNIFF_BYTES = 64 * 1024
_PROVIDER_KEY = "csv"


@dataclass(frozen=True, slots=True)
class _CSVSnapshot:
    observed: ObservedFileFacts
    modified_at: str
    dialect: DialectInfo
    warnings: tuple[str, ...]


def _source_missing(alias: str) -> SourceResolutionError:
    return SourceResolutionError(
        "source_missing",
        "CSV source is missing or unreadable.",
        kind=_PROVIDER_KEY,
        alias=alias,
        suggestion="Restore the CSV source or update its configured locator.",
    )


def _source_changed(alias: str) -> SourceIdentityError:
    return SourceIdentityError(
        "source_changed",
        "CSV source changed after submission.",
        kind=_PROVIDER_KEY,
        alias=alias,
        suggestion="Submit the operation again to capture the current CSV source.",
    )


def _canonical_file(selected: SelectedSource) -> Path:
    request = selected.request
    candidate = Path(request.locator).expanduser()
    if not candidate.is_absolute():
        candidate = (request.anchor or Path.cwd()) / candidate
    canonical = Path(os.path.abspath(os.path.normpath(os.fspath(candidate))))
    try:
        locator_stat = canonical.lstat()
    except (OSError, ValueError) as exc:
        raise _source_missing(request.alias) from exc
    if stat.S_ISLNK(locator_stat.st_mode) or not stat.S_ISREG(locator_stat.st_mode):
        raise _source_missing(request.alias)
    if is_private_result_artifact(canonical):
        raise SourceResolutionError(
            "source_missing",
            "CSV source is inside LocalQL private result storage.",
            kind=_PROVIDER_KEY,
            alias=request.alias,
            suggestion="Use Save as source to create a normal CSV source.",
        )
    return canonical


def _snapshot(path: Path, *, alias: str) -> _CSVSnapshot:
    warnings: list[str] = []
    try:
        with path.open("rb") as source_file:
            file_stat = os.fstat(source_file.fileno())
            sample_bytes = source_file.read(SNIFF_BYTES)
    except OSError as exc:
        raise _source_missing(alias) from exc
    sample = sample_bytes.decode("utf-8", errors="replace")
    dialect = _detect_dialect(sample, warnings=warnings)
    return _CSVSnapshot(
        observed=ObservedFileFacts(
            size_bytes=file_stat.st_size,
            modified_time_ns=file_stat.st_mtime_ns,
        ),
        modified_at=datetime.fromtimestamp(
            file_stat.st_mtime_ns / 1_000_000_000,
            tz=UTC,
        ).isoformat(),
        dialect=dialect,
        warnings=tuple(warnings),
    )


def _facts(snapshot: _CSVSnapshot) -> FrozenJSONObject:
    value = freeze_source_value(
        {
            "dialect_delimiter": snapshot.dialect.delimiter,
            "dialect_encoding": snapshot.dialect.encoding,
            "dialect_escape": snapshot.dialect.escape,
            "dialect_header": snapshot.dialect.header,
            "dialect_quote": snapshot.dialect.quote,
            "dialect_warnings": list(snapshot.warnings),
            "fingerprint_version": 1,
            "modified_at": snapshot.modified_at,
            "modified_time_ns": snapshot.observed.modified_time_ns,
            "size_bytes": snapshot.observed.size_bytes,
        }
    )
    if not isinstance(value, FrozenJSONObject):
        raise AssertionError("CSV provider facts must be an immutable JSON object.")
    return value


def _observed_facts(resolved: ResolvedSource) -> ObservedFileFacts:
    facts = {key: value for key, value in resolved.provider_facts.items}
    size_bytes = facts.get("size_bytes")
    modified_time_ns = facts.get("modified_time_ns")
    if (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or not isinstance(modified_time_ns, int)
        or isinstance(modified_time_ns, bool)
    ):
        raise SourceIdentityError(
            "source_changed",
            "CSV source identity is unavailable.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Resolve the source again before continuing.",
        )
    return ObservedFileFacts(size_bytes=size_bytes, modified_time_ns=modified_time_ns)


def _current_observed_facts(resolved: ResolvedSource) -> ObservedFileFacts:
    path = Path(resolved.canonical_locator)
    try:
        locator_stat = path.lstat()
    except OSError as exc:
        raise _source_changed(resolved.alias) from exc
    if stat.S_ISLNK(locator_stat.st_mode) or not stat.S_ISREG(locator_stat.st_mode):
        raise _source_changed(resolved.alias)
    return ObservedFileFacts(
        size_bytes=locator_stat.st_size,
        modified_time_ns=locator_stat.st_mtime_ns,
    )


@dataclass(slots=True)
class _CSVRelationalBinding:
    _engine_session: EngineSession
    _resolved_source: ResolvedSource
    _registration_token: object
    _closed: bool = field(default=False, init=False)

    @property
    def alias(self) -> str:
        return self._resolved_source.alias

    @property
    def resolved_source(self) -> ResolvedSource:
        return self._resolved_source

    @property
    def engine_session_id(self) -> str:
        return self._engine_session.session_id

    @property
    def state(self) -> BindingState:
        if self._closed:
            return BindingState.CLOSED
        if self._engine_session.has_active_execution:
            return BindingState.IN_USE
        return BindingState.IDLE

    def revalidate(
        self,
        requirement: IdentityRequirement,
        context: OperationContext,
    ) -> IdentityValidationResult:
        """Compare the recorded observational file facts before execution."""

        self._engine_session.assert_session_access()
        context.checkpoint()
        if self._closed:
            raise SourceIdentityError(
                "source_changed",
                "CSV source binding is closed.",
                kind=_PROVIDER_KEY,
                alias=self.alias,
                suggestion="Prepare the source again before executing a query.",
            )
        if requirement.strength is not IdentityStrength.OBSERVATIONAL:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.UNAVAILABLE,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_UNAVAILABLE,
                    stage=DiagnosticStage.IDENTITY,
                    message=(
                        "CSV cannot confirm the requested identity strength without "
                        "an explicit stronger validation."
                    ),
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction(
                        "choose_observational_or_resubmit",
                        (_PROVIDER_KEY,),
                    ),
                ),
            )
        try:
            current = _current_observed_facts(self._resolved_source)
        except SourceError:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.INVALID,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_INVALID,
                    stage=DiagnosticStage.IDENTITY,
                    message="CSV source is no longer a readable regular file.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction("restore_or_resubmit", (_PROVIDER_KEY,)),
                ),
            )
        if current != _observed_facts(self._resolved_source):
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.CHANGED,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_CHANGED,
                    stage=DiagnosticStage.IDENTITY,
                    message="CSV source changed after resolution.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction("resubmit_source", (_PROVIDER_KEY,)),
                ),
            )
        return IdentityValidationResult(
            alias=self.alias,
            status=IdentityValidationStatus.CONFIRMED,
            required_strength=requirement.strength,
            confirmed_strength=IdentityStrength.OBSERVATIONAL,
        )

    def close(self, context: OperationContext) -> None:
        """Remove only this binding's relation after the execution barrier."""

        if self._closed:
            return
        self._engine_session.assert_session_access()
        if self._engine_session.has_active_execution:
            raise SourceBindingError(
                "source_bind_failed",
                "CSV source binding is still in use.",
                kind=_PROVIDER_KEY,
                alias=self.alias,
                suggestion="Wait for the active query to reach a terminal state.",
            )
        if self._engine_session.is_tainted:
            raise EngineSessionTaintedError(
                "engine_session_tainted",
                "CSV source binding cannot be unregistered from a tainted session.",
                kind=_PROVIDER_KEY,
                alias=self.alias,
                suggestion="Close the owning LocalQL engine session.",
            )
        try:
            self._engine_session.unregister_relation(
                self._registration_token,
                operation=context,
            )
        except SourceError:
            raise
        except (duckdb.Error, OSError) as exc:
            raise SourceCleanupError(
                "source_cleanup_failed",
                "Failed to clean up a CSV source binding.",
                kind=_PROVIDER_KEY,
                alias=self.alias,
                suggestion="Close the LocalQL operation and try again.",
            ) from exc
        self._closed = True


class CSVSourceAdapter:
    """Lightweight CSV provider activated only after deterministic selection."""

    provider_key = _PROVIDER_KEY

    def __init__(self, *, activation_facts: ProviderActivationFacts) -> None:
        if activation_facts.provider_key != self.provider_key:
            raise ValueError("CSV activation facts have the wrong provider key.")
        self._activation_facts = activation_facts
        self.implementation_version = activation_facts.adapter_implementation_version

    def resolve(
        self,
        selected: SelectedSource,
        operation: OperationContext,
    ) -> ResolvedSource:
        """Resolve a selected CSV into immutable identity and interpretation facts."""

        operation.checkpoint()
        if selected.provider_key != self.provider_key or selected.source_kind != "csv":
            raise SourceResolutionError(
                "unknown_source_kind",
                "The CSV adapter received a different source kind.",
                kind=selected.source_kind,
                alias=selected.request.alias,
                suggestion="Select the adapter matching the source kind.",
            )
        if selected.options:
            raise SourceResolutionError(
                "unsupported_source_option",
                "CSV source options are not supported.",
                kind=self.provider_key,
                alias=selected.request.alias,
                suggestion="Remove all CSV source options.",
            )
        path = _canonical_file(selected)
        snapshot = _snapshot(path, alias=selected.request.alias)
        operation.checkpoint()
        identity = build_source_identity(
            provider_key=self.provider_key,
            source_kind=selected.source_kind,
            canonical_locator=str(path),
            semantic_options=(),
            provider_interpretation_version=selected.descriptor.provider_interpretation_version,
            strength=IdentityStrength.OBSERVATIONAL,
            observed_file=snapshot.observed,
        )
        return ResolvedSource(
            provider_key=self.provider_key,
            source_kind=selected.source_kind,
            provider_interpretation_version=(selected.descriptor.provider_interpretation_version),
            alias=selected.request.alias,
            alias_key=selected.request.alias_key,
            canonical_locator=str(path),
            requested_locator=selected.request.locator,
            locator_shape="file",
            semantic_options=(),
            operational_options=(),
            identity=identity,
            selection_reason=selected.selection_reason,
            adapter_implementation_version=self.implementation_version,
            duckdb_version=self._activation_facts.duckdb_version,
            dependency_versions=self._activation_facts.dependency_versions,
            provider_facts=_facts(snapshot),
            selection_evidence=(
                DiagnosticEvidence(
                    self.provider_key,
                    "selection_basis",
                    selected.selection_reason,
                ),
            ),
            resolution_evidence=(
                DiagnosticEvidence(
                    self.provider_key,
                    "bounded_dialect",
                    "recorded",
                ),
            ),
            resolution_anchor=selected.request.anchor,
        )

    def bind(
        self,
        resolved: ResolvedSource,
        engine_session: EngineSession,
        binding_context: BindingContext,
    ) -> RelationalBinding:
        """Eagerly validate and register one lazy-scanning CSV relation."""

        operation = binding_context.operation
        operation.checkpoint()
        if resolved.provider_key != self.provider_key:
            raise SourceBindingError(
                "source_bind_failed",
                "The CSV adapter received a different resolved provider.",
                kind=resolved.source_kind,
                alias=resolved.alias,
            )
        if _current_observed_facts(resolved) != _observed_facts(resolved):
            raise _source_changed(resolved.alias)

        def register(connection_object: object) -> None:
            connection = cast(duckdb.DuckDBPyConnection, connection_object)
            relation = connection.read_csv(
                resolved.canonical_locator,
                auto_detect=True,
                header=True,
            )
            relation.create_view(resolved.alias, replace=False)

        def unregister(connection_object: object) -> None:
            connection = cast(duckdb.DuckDBPyConnection, connection_object)
            connection.execute(f"DROP VIEW IF EXISTS {quote_identifier(resolved.alias)}")

        try:
            registration_token = engine_session.register_relation(
                alias=resolved.alias,
                register=register,
                unregister=unregister,
                operation=operation,
            )
        except SourceError:
            raise
        except (duckdb.Error, OSError) as exc:
            raise SourceBindingError(
                "source_bind_failed",
                "Failed to bind CSV source.",
                kind=self.provider_key,
                alias=resolved.alias,
                suggestion="Check that the source is a readable CSV with a header row.",
            ) from exc
        binding = _CSVRelationalBinding(
            engine_session,
            resolved,
            registration_token,
        )
        try:
            operation.checkpoint()
        except OperationCancelled:
            try:
                binding.close(OperationContext(OperationToken()))
            except SourceError:
                pass
            raise
        return binding


def _detect_dialect(sample: str, *, warnings: list[str]) -> DialectInfo:
    if not sample:
        warnings.append("CSV file is empty; dialect detection used default values.")
        return _default_dialect()

    try:
        sniffed = csv.Sniffer().sniff(sample)
    except csv.Error:
        warnings.append("Could not detect CSV dialect from the bounded sample.")
        return _default_dialect()

    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = None
        warnings.append("Could not determine whether the CSV has a header row.")

    return DialectInfo(
        delimiter=sniffed.delimiter,
        quote=sniffed.quotechar,
        escape=sniffed.escapechar,
        header=has_header,
        encoding="utf-8",
    )


def _default_dialect() -> DialectInfo:
    return DialectInfo(
        delimiter=None,
        quote=None,
        escape=None,
        header=None,
        encoding="utf-8",
    )


def _create_csv_adapter(
    *,
    activation_facts: ProviderActivationFacts,
) -> CSVSourceAdapter:
    return CSVSourceAdapter(activation_facts=activation_facts)
