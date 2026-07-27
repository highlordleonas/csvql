"""Selected-only lazy activation for LocalQL source adapters."""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from csvql.exceptions import (
    ConfigurationFailure,
    ConfigurationFinding,
    SourceActivationError,
)
from csvql.source import SelectedSource
from csvql.source_adapter import SourceAdapter
from csvql.source_registry import (
    DependencyRequirement,
    DescriptorRegistry,
    ProviderFactoryKey,
    validate_descriptor_factory_composition,
)

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")


@dataclass(frozen=True, slots=True)
class LazyAdapterRegistration:
    """Factory-owned import coordinates for one source provider."""

    provider_key: str
    factory_key: str
    import_module: str
    constructor_symbol: str
    dependency_requirement_key: str | None


@dataclass(frozen=True, slots=True)
class ProviderActivationFacts:
    """Immutable selected-runtime facts that affect provider interpretation."""

    provider_key: str
    adapter_implementation_version: str
    duckdb_version: str
    dependency_versions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ActivationContext:
    """Provider-neutral view of already-available selected dependencies."""

    available_dependencies: frozenset[str] = frozenset()
    dependency_versions: tuple[tuple[str, str], ...] = ()
    duckdb_version: str = "unknown"

    def __post_init__(self) -> None:
        keys = tuple(key for key, _version in self.dependency_versions)
        if len(keys) != len(set(keys)):
            raise ValueError("Activation dependency versions must have unique keys.")
        object.__setattr__(
            self,
            "dependency_versions",
            tuple(sorted(self.dependency_versions)),
        )

    def dependency_is_available(self, requirement: DependencyRequirement) -> bool:
        """Return availability without importing, installing, or loading anything."""

        return requirement.kind == "builtin" or requirement.key in self.available_dependencies

    def selected_dependency_versions(
        self,
        requirement: DependencyRequirement | None,
    ) -> tuple[tuple[str, str], ...]:
        """Return interpretation facts only for the selected dependency."""

        if requirement is None:
            return ()
        versions = dict(self.dependency_versions)
        version = versions.get(requirement.key)
        return () if version is None else ((requirement.key, version),)


class LazyAdapterTable:
    """Immutable validated mapping of provider keys to lazy imports."""

    def __init__(self, registrations: tuple[LazyAdapterRegistration, ...]) -> None:
        findings: list[ConfigurationFinding] = []
        by_provider: dict[str, LazyAdapterRegistration] = {}
        factory_owners: dict[str, str] = {}
        normalized: list[LazyAdapterRegistration] = []
        for registration in registrations:
            provider_key = registration.provider_key.casefold()
            factory_key = registration.factory_key.casefold()
            current = LazyAdapterRegistration(
                provider_key=provider_key,
                factory_key=factory_key,
                import_module=registration.import_module,
                constructor_symbol=registration.constructor_symbol,
                dependency_requirement_key=registration.dependency_requirement_key,
            )
            normalized.append(current)
            if not _KEY_PATTERN.fullmatch(provider_key):
                findings.append(
                    ConfigurationFinding(
                        "invalid_factory_provider_key",
                        provider_key,
                        "Provider key is invalid.",
                    )
                )
            if not _KEY_PATTERN.fullmatch(factory_key):
                findings.append(
                    ConfigurationFinding(
                        "invalid_factory_key",
                        provider_key,
                        "Factory key is invalid.",
                    )
                )
            if provider_key in by_provider:
                findings.append(
                    ConfigurationFinding(
                        "duplicate_factory_registration",
                        provider_key,
                        "Provider has more than one lazy registration.",
                    )
                )
            else:
                by_provider[provider_key] = current
            factory_owner = factory_owners.get(factory_key)
            if factory_owner is not None:
                findings.append(
                    ConfigurationFinding(
                        "duplicate_factory_key",
                        factory_key,
                        f"Factory key is shared by {factory_owner} and {provider_key}.",
                    )
                )
            else:
                factory_owners[factory_key] = provider_key
            if not registration.import_module or not registration.constructor_symbol:
                findings.append(
                    ConfigurationFinding(
                        "invalid_factory_import",
                        provider_key,
                        "Lazy import module and constructor symbol are required.",
                    )
                )
        if findings:
            raise ConfigurationFailure(tuple(findings))

        ordered = tuple(sorted(normalized, key=lambda item: item.provider_key))
        self.provider_keys = tuple(item.provider_key for item in ordered)
        self.factory_keys = tuple(
            ProviderFactoryKey(item.provider_key, item.factory_key) for item in ordered
        )
        self._registrations = MappingProxyType({item.provider_key: item for item in ordered})

    def registration(self, provider_key: str) -> LazyAdapterRegistration:
        """Return one lazy registration by canonical provider key."""

        return self._registrations[provider_key.casefold()]


class AdapterFactory:
    """Construct only the adapter named by a validated SelectedSource."""

    def __init__(
        self,
        registry: DescriptorRegistry,
        registrations: LazyAdapterTable,
    ) -> None:
        validate_descriptor_factory_composition(registry, registrations.factory_keys)
        findings: list[ConfigurationFinding] = []
        for descriptor in registry.descriptors:
            registration = registrations.registration(descriptor.provider_key)
            descriptor_dependency = (
                None if descriptor.dependency is None else descriptor.dependency.key
            )
            if registration.dependency_requirement_key != descriptor_dependency:
                findings.append(
                    ConfigurationFinding(
                        "factory_dependency_mismatch",
                        descriptor.provider_key,
                        "Descriptor and factory dependency keys do not match.",
                    )
                )
        if findings:
            raise ConfigurationFailure(tuple(findings))
        self._registry = registry
        self._registrations = registrations

    def activate(
        self,
        selected: SelectedSource,
        context: ActivationContext,
    ) -> SourceAdapter:
        """Activate one selected provider without inspecting any unselected runtime."""

        if not isinstance(selected, SelectedSource):
            raise TypeError("AdapterFactory accepts only SelectedSource outcomes.")
        registration = self._registrations.registration(selected.provider_key)
        descriptor = self._registry.descriptor(selected.provider_key)
        if (
            selected.descriptor.factory_key != registration.factory_key
            or selected.descriptor.provider_key != descriptor.provider_key
        ):
            raise SourceActivationError(
                "source.provider_contract_invalid",
                "Selected source metadata does not match application composition.",
                provider_key=selected.provider_key,
            )
        requirement = descriptor.dependency
        if requirement is not None and not context.dependency_is_available(requirement):
            raise SourceActivationError(
                "source.activation_dependency_missing",
                "The selected source provider dependency is not available.",
                provider_key=selected.provider_key,
                dependency_key=requirement.key,
                suggestion=requirement.guidance,
            )

        try:
            provider_module = importlib.import_module(registration.import_module)
        except (ImportError, ModuleNotFoundError) as exc:
            raise SourceActivationError(
                "source.activation_failed",
                "The selected source provider module could not be imported.",
                provider_key=selected.provider_key,
                dependency_key=(None if requirement is None else requirement.key),
            ) from exc
        constructor_value = getattr(
            provider_module,
            registration.constructor_symbol,
            None,
        )
        if not callable(constructor_value):
            raise SourceActivationError(
                "source.activation_failed",
                "The selected source provider constructor is unavailable.",
                provider_key=selected.provider_key,
            )
        module_version = getattr(provider_module, "__version__", "unknown")
        if not isinstance(module_version, str) or not module_version:
            module_version = "unknown"
        facts = ProviderActivationFacts(
            provider_key=selected.provider_key,
            adapter_implementation_version=module_version,
            duckdb_version=context.duckdb_version,
            dependency_versions=context.selected_dependency_versions(requirement),
        )
        constructor = cast(Callable[..., object], constructor_value)
        try:
            adapter = constructor(activation_facts=facts)
        except Exception as exc:
            raise SourceActivationError(
                "source.activation_failed",
                "The selected source provider could not be constructed.",
                provider_key=selected.provider_key,
            ) from exc
        if not isinstance(adapter, SourceAdapter):
            raise SourceActivationError(
                "source.provider_contract_invalid",
                "The selected source provider does not satisfy the adapter contract.",
                provider_key=selected.provider_key,
            )
        if (
            adapter.provider_key != selected.provider_key
            or adapter.implementation_version != module_version
        ):
            raise SourceActivationError(
                "source.provider_contract_invalid",
                "The selected source provider reported inconsistent runtime identity.",
                provider_key=selected.provider_key,
            )
        return adapter


BUILTIN_LAZY_ADAPTER_REGISTRATIONS = (
    LazyAdapterRegistration(
        "csv",
        "builtin.csv",
        "csvql.csv_adapter",
        "_create_csv_adapter",
        None,
    ),
    LazyAdapterRegistration(
        "parquet",
        "builtin.parquet",
        "csvql.parquet_adapter",
        "_create_parquet_adapter",
        "duckdb.parquet",
    ),
    LazyAdapterRegistration(
        "json",
        "builtin.json",
        "csvql.json_adapter",
        "_create_json_adapter",
        "duckdb.extension.json",
    ),
    LazyAdapterRegistration(
        "ndjson",
        "builtin.ndjson",
        "csvql.ndjson_adapter",
        "_create_ndjson_adapter",
        "duckdb.extension.json",
    ),
    LazyAdapterRegistration(
        "excel",
        "builtin.excel",
        "csvql.excel_adapter",
        "_create_excel_adapter",
        "duckdb.extension.excel",
    ),
)


def build_builtin_lazy_adapter_table() -> LazyAdapterTable:
    """Build the complete lazy table without importing any provider module."""

    return LazyAdapterTable(BUILTIN_LAZY_ADAPTER_REGISTRATIONS)
