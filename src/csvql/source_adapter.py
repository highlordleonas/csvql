"""Private source adapter behavior and explicit lazy registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal, Protocol

import duckdb

from csvql.exceptions import SourceError
from csvql.models import DialectInfo
from csvql.operation import OperationContext
from csvql.source import (
    ResolvedSource,
    SourceCapabilities,
    SourceCapability,
    SourceCapabilityStatus,
    SourceSpec,
)

SourceAccessMode = Literal["read_only"]
_SOURCE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class AdapterInspectionMetadata:
    """Adapter-owned metadata supplement for shared source inspection."""

    dialect: DialectInfo
    warnings: tuple[str, ...] = ()


class PreparedBinding(Protocol):
    """One source binding whose cleanup is idempotent and connection-independent."""

    @property
    def alias(self) -> str: ...

    @property
    def source(self) -> ResolvedSource: ...

    @property
    def capabilities(self) -> SourceCapabilities: ...

    def close(self) -> None: ...


class SourceAdapter(Protocol):
    """Private adapter seam for source resolution, binding, and supplemental metadata."""

    @property
    def descriptor(self) -> SourceAdapterDescriptor: ...

    def validate_options(self, spec: SourceSpec) -> None: ...

    def resolve(self, spec: SourceSpec, context: OperationContext) -> ResolvedSource: ...

    def bind(
        self,
        connection: duckdb.DuckDBPyConnection,
        source: ResolvedSource,
        context: OperationContext,
    ) -> PreparedBinding: ...

    def inspect_metadata(
        self,
        source: ResolvedSource,
        context: OperationContext,
    ) -> AdapterInspectionMetadata: ...


class SourceAdapterFactory(Protocol):
    """Lazy constructor for one selected source adapter."""

    def __call__(self) -> SourceAdapter: ...


@dataclass(frozen=True, slots=True)
class SourceAdapterDescriptor:
    """Import-free description and lazy factory for a stable source kind."""

    kind: str
    access_mode: SourceAccessMode
    capabilities: SourceCapabilities
    dependency: str | None
    extra: str | None
    factory: SourceAdapterFactory

    def __post_init__(self) -> None:
        if not _SOURCE_KIND_PATTERN.fullmatch(self.kind):
            raise ValueError("Adapter kind must be a stable lowercase identifier.")
        if self.access_mode != "read_only":
            raise ValueError("Source adapters must declare read_only access.")
        if (self.dependency is None) != (self.extra is None):
            raise ValueError("Optional adapter dependency and extra must be declared together.")

    def missing_optional_dependency_error(
        self,
        capability: SourceCapability,
    ) -> SourceError | None:
        """Return the exact optional-dependency error when capability truth already proves it."""

        status = self.capabilities.status_for(capability)
        if (
            self.dependency is None
            or self.extra is None
            or status.state != "unavailable"
            or status.reason_code not in {"runtime_missing", "missing_optional_dependency"}
        ):
            return None
        return SourceError.missing_optional_dependency(
            kind=self.kind,
            capability=capability,
            dependency=self.dependency,
            extra=self.extra,
        )

    def normalize_missing_optional_dependency(self) -> SourceAdapterDescriptor:
        """Return a truthful descriptor when any capability already proves runtime absence."""

        if self.dependency is None or self.extra is None:
            return self
        if not any(
            status.state == "unavailable"
            and status.reason_code in {"runtime_missing", "missing_optional_dependency"}
            for status in self.capabilities.statuses
        ):
            return self
        return replace(
            self,
            capabilities=SourceCapabilities(
                tuple(
                    self._runtime_missing_status(status.operation)
                    if status.state == "available"
                    else status
                    for status in self.capabilities.statuses
                )
            ),
        )

    def with_missing_optional_dependency(
        self,
        capability: SourceCapability,
    ) -> SourceAdapterDescriptor:
        """Return an immutable descriptor snapshot that truthfully records a missing runtime."""

        if self.dependency is None or self.extra is None:
            return self
        return replace(
            self,
            capabilities=SourceCapabilities(
                tuple(
                    self._runtime_missing_status(status.operation)
                    if status.state == "available"
                    else status
                    for status in self.capabilities.statuses
                )
            ),
        )

    def _runtime_missing_status(
        self,
        capability: SourceCapability,
    ) -> SourceCapabilityStatus:
        return SourceCapabilityStatus(
            operation=capability,
            state="unavailable",
            reason_code="runtime_missing",
            remediation=(f"Install the '{self.extra}' extra to enable this source capability."),
        )


class SourceAdapterRegistry:
    """Explicit immutable kind registry with selected-factory-only construction."""

    def __init__(self, descriptors: tuple[SourceAdapterDescriptor, ...]) -> None:
        by_kind: dict[str, SourceAdapterDescriptor] = {}
        for descriptor in descriptors:
            normalized = descriptor.normalize_missing_optional_dependency()
            key = normalized.kind.casefold()
            if key in by_kind:
                raise ValueError(f"Duplicate source adapter kind: {normalized.kind}.")
            by_kind[key] = normalized
        self._descriptor_map = by_kind
        self._descriptors = MappingProxyType(self._descriptor_map)

    def descriptor(self, kind: str) -> SourceAdapterDescriptor:
        """Return descriptor metadata without constructing or importing its runtime."""

        descriptor = self._descriptors.get(kind.casefold())
        if descriptor is None:
            raise SourceError(
                "unknown_source_kind",
                f"Unknown source kind '{kind}'.",
                kind=kind,
                suggestion="Choose a source kind supported by this LocalQL installation.",
            )
        return descriptor

    def create(
        self,
        kind: str,
        *,
        capability: SourceCapability,
    ) -> SourceAdapter:
        """Construct only the selected adapter and translate its missing dependency."""

        descriptor = self.descriptor(kind)
        missing_dependency_error = descriptor.missing_optional_dependency_error(capability)
        if missing_dependency_error is not None:
            raise missing_dependency_error
        require_capability(
            descriptor.capabilities,
            capability,
            kind=descriptor.kind,
        )
        try:
            return descriptor.factory()
        except ModuleNotFoundError as exc:
            # Dependency is the descriptor's deterministic import identifier. Only an exact
            # missing-module match proves the selected optional runtime itself is absent.
            if (
                descriptor.dependency is None
                or descriptor.extra is None
                or exc.name != descriptor.dependency
            ):
                raise
            self._descriptor_map[descriptor.kind.casefold()] = (
                descriptor.with_missing_optional_dependency(capability)
            )
            raise SourceError.missing_optional_dependency(
                kind=descriptor.kind,
                capability=capability,
                dependency=descriptor.dependency,
                extra=descriptor.extra,
            ) from exc


def require_capability(
    capabilities: SourceCapabilities,
    operation: SourceCapability,
    *,
    kind: str,
    alias: str | None = None,
) -> None:
    """Require an available operation with stable unavailable/unsupported diagnostics."""

    status = capabilities.status_for(operation)
    if status.state == "available":
        return

    raise SourceError(
        "unsupported_capability",
        f"Source capability '{operation}' is {status.state} ({status.reason_code}).",
        kind=kind,
        alias=alias,
        capability=operation,
        suggestion=status.remediation,
    )
