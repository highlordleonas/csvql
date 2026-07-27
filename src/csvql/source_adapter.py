"""Narrow runtime contracts for LocalQL source providers and bindings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from csvql.operation import OperationContext
from csvql.source import (
    IdentityRequirement,
    IdentityValidationResult,
    ResolvedSource,
    SelectedSource,
)
from csvql.source_identifiers import SourceIdentifier as SourceIdentifier

StructuralCallback = Callable[[object], None]


class BindingState(StrEnum):
    """Observable lifecycle state of one session-bound relation."""

    IDLE = "idle"
    IN_USE = "in_use"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class BindingContext:
    """Operation-scoped context passed to one adapter binding."""

    operation: OperationContext


@runtime_checkable
class EngineSession(Protocol):
    """Provider-neutral engine operations available to bindings."""

    @property
    def session_id(self) -> str: ...

    @property
    def has_active_execution(self) -> bool: ...

    @property
    def is_tainted(self) -> bool: ...

    def assert_session_access(self) -> None: ...

    def preflight_aliases(self, aliases: tuple[str, ...]) -> None: ...

    def register_relation(
        self,
        *,
        alias: str,
        register: StructuralCallback,
        unregister: StructuralCallback,
        operation: OperationContext,
    ) -> object: ...

    def unregister_relation(
        self,
        registration_token: object,
        *,
        operation: OperationContext,
    ) -> None: ...


@runtime_checkable
class RelationalBinding(Protocol):
    """Live read-only relation owned by one engine session."""

    @property
    def alias(self) -> str: ...

    @property
    def resolved_source(self) -> ResolvedSource: ...

    @property
    def engine_session_id(self) -> str: ...

    @property
    def state(self) -> BindingState: ...

    def revalidate(
        self,
        requirement: IdentityRequirement,
        context: OperationContext,
    ) -> IdentityValidationResult: ...

    def close(self, context: OperationContext) -> None: ...


@runtime_checkable
class SourceAdapter(Protocol):
    """Lightweight selected-provider behavior with no owned runtime resources."""

    provider_key: str
    implementation_version: str

    def resolve(
        self,
        selected: SelectedSource,
        operation: OperationContext,
    ) -> ResolvedSource: ...

    def bind(
        self,
        resolved: ResolvedSource,
        engine_session: EngineSession,
        binding_context: BindingContext,
    ) -> RelationalBinding: ...
