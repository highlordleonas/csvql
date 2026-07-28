"""Import-free metadata for deterministic LocalQL source detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal

from csvql.exceptions import ConfigurationFailure, ConfigurationFinding
from csvql.source import (
    FrozenJSONArray,
    FrozenJSONObject,
    freeze_source_value,
)

LocatorShape = Literal["file", "directory"]
OptionValueKind = Literal["string", "integer", "number", "boolean", "object", "array"]

_PROVIDER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_METADATA_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_OPTION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_OPTION_VALUE_KINDS = {"string", "integer", "number", "boolean", "object", "array"}
_LOCATOR_SHAPES = {"file", "directory"}
MAX_IDENTIFIER_REGISTRATIONS = 16


@dataclass(frozen=True, slots=True)
class SourceOptionDefinition:
    """Import-free validation and default metadata for one source option."""

    key: str
    value_kind: str
    required: bool = False
    has_default: bool = False
    default: object = None
    affects_identity: bool = True
    sensitive: bool = False


@dataclass(frozen=True, slots=True)
class DependencyRequirement:
    """Safe metadata describing one selected-provider runtime requirement."""

    key: str
    kind: str
    extra: str | None = None
    guidance: str | None = None


@dataclass(frozen=True, slots=True)
class IdentifierRegistration:
    """Opaque key for one dependency-light source identifier."""

    identifier_key: str


@dataclass(frozen=True, slots=True)
class UnsupportedExtensionHint:
    """Actionable guidance for a recognized but unsupported extension."""

    extension: str
    diagnostic_code: str
    guidance: str


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Immutable provider metadata that never references runtime implementation."""

    provider_key: str
    source_kind: str
    aliases: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    locator_shapes: tuple[LocatorShape, ...] = ("file",)
    directory_dataset: bool = False
    dependency: DependencyRequirement | None = None
    options: tuple[SourceOptionDefinition, ...] = ()
    identifier: IdentifierRegistration | None = None
    factory_key: str = ""
    provider_interpretation_version: str = "1"


@dataclass(frozen=True, slots=True)
class DescriptorView:
    """Detection-safe projection of one source descriptor."""

    provider_key: str
    source_kind: str
    factory_key: str
    provider_interpretation_version: str
    aliases: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    locator_shapes: tuple[LocatorShape, ...] = ("file",)
    directory_dataset: bool = False
    dependency: DependencyRequirement | None = None
    options: tuple[SourceOptionDefinition, ...] = ()
    identifier: IdentifierRegistration | None = None

    def option_defaults_as_python(self) -> dict[str, object]:
        """Return descriptor defaults as ordinary JSON-compatible values."""

        return {option.key: _thaw(option.default) for option in self.options if option.has_default}


@dataclass(frozen=True, slots=True)
class ProviderFactoryKey:
    """Import-free provider/factory association used by composition checks."""

    provider_key: str
    factory_key: str


def _thaw(value: object) -> object:
    if isinstance(value, FrozenJSONArray):
        return [_thaw(item) for item in value.values]
    if isinstance(value, FrozenJSONObject):
        return {key: _thaw(item) for key, item in value.items}
    return value


def _finding(code: str, subject: str, detail: str) -> ConfigurationFinding:
    return ConfigurationFinding(code=code, subject=subject, detail=detail)


def _normalize_extension(extension: str) -> str:
    return extension.casefold()


def _descriptor_view(descriptor: SourceDescriptor) -> DescriptorView:
    return DescriptorView(
        provider_key=descriptor.provider_key,
        source_kind=descriptor.source_kind,
        factory_key=descriptor.factory_key,
        provider_interpretation_version=descriptor.provider_interpretation_version,
        aliases=descriptor.aliases,
        extensions=descriptor.extensions,
        locator_shapes=descriptor.locator_shapes,
        directory_dataset=descriptor.directory_dataset,
        dependency=descriptor.dependency,
        options=descriptor.options,
        identifier=descriptor.identifier,
    )


class DescriptorRegistry:
    """Validated immutable source descriptors used only for detection metadata."""

    def __init__(
        self,
        descriptors: tuple[SourceDescriptor, ...],
        unsupported_extensions: tuple[UnsupportedExtensionHint, ...],
    ) -> None:
        self.source_descriptors = descriptors
        self.unsupported_extensions = unsupported_extensions
        self.descriptors = tuple(_descriptor_view(descriptor) for descriptor in descriptors)
        self.provider_keys = tuple(descriptor.provider_key for descriptor in self.descriptors)
        self.factory_keys = tuple(
            ProviderFactoryKey(descriptor.provider_key, descriptor.factory_key)
            for descriptor in self.descriptors
        )
        self._by_provider = MappingProxyType(
            {descriptor.provider_key: descriptor for descriptor in self.descriptors}
        )
        type_map: dict[str, DescriptorView] = {}
        for descriptor in self.descriptors:
            for source_type in (descriptor.source_kind, *descriptor.aliases):
                type_map[source_type.casefold()] = descriptor
        self._by_type = MappingProxyType(type_map)
        extension_map = {
            extension: descriptor
            for descriptor in self.descriptors
            for extension in descriptor.extensions
        }
        self._extensions = tuple(
            sorted(extension_map, key=lambda extension: (-len(extension), extension))
        )
        self._by_extension = MappingProxyType(extension_map)
        self._unsupported_extensions = tuple(
            sorted(
                unsupported_extensions,
                key=lambda hint: (-len(hint.extension), hint.extension),
            )
        )

    @classmethod
    def build(
        cls,
        descriptors: tuple[SourceDescriptor, ...],
        *,
        unsupported_extensions: tuple[UnsupportedExtensionHint, ...] = (),
    ) -> DescriptorRegistry:
        """Validate all metadata and return one deterministically ordered registry."""

        findings: list[ConfigurationFinding] = []
        normalized: list[SourceDescriptor] = []
        provider_owners: dict[str, str] = {}
        kind_owners: dict[str, str] = {}
        alias_owners: dict[str, str] = {}
        extension_owners: dict[str, str] = {}
        factory_owners: dict[str, str] = {}
        identifier_owners: dict[str, str] = {}

        for descriptor in descriptors:
            provider_key = descriptor.provider_key.casefold()
            source_kind = descriptor.source_kind.casefold()
            factory_key = descriptor.factory_key.casefold()
            aliases = tuple(alias.casefold() for alias in descriptor.aliases)
            normalized_extensions = tuple(
                _normalize_extension(extension) for extension in descriptor.extensions
            )
            for extension in sorted(
                {
                    extension
                    for extension in normalized_extensions
                    if normalized_extensions.count(extension) > 1
                }
            ):
                findings.append(
                    _finding(
                        "duplicate_extension",
                        extension,
                        "Descriptor claims the same normalized extension more than once.",
                    )
                )
            extensions = tuple(sorted(set(normalized_extensions)))
            locator_shapes = tuple(sorted(set(descriptor.locator_shapes)))
            options, invalid_default_indexes = _normalize_option_defaults(
                descriptor.options,
                provider_key=provider_key,
                findings=findings,
            )
            current = replace(
                descriptor,
                provider_key=provider_key,
                source_kind=source_kind,
                aliases=aliases,
                extensions=extensions,
                locator_shapes=locator_shapes,
                options=options,
                factory_key=factory_key,
            )
            normalized.append(current)

            if not _PROVIDER_KEY_PATTERN.fullmatch(provider_key):
                findings.append(
                    _finding("invalid_provider_key", provider_key, "Use a lowercase identifier.")
                )
            if not _PROVIDER_KEY_PATTERN.fullmatch(source_kind):
                findings.append(
                    _finding("invalid_source_kind", source_kind, "Use a lowercase identifier.")
                )
            _claim_unique(
                provider_owners,
                provider_key,
                provider_key,
                "duplicate_provider_key",
                findings,
            )
            _claim_unique(
                kind_owners,
                source_kind,
                provider_key,
                "duplicate_source_kind",
                findings,
            )
            for alias in (source_kind, *aliases):
                if not _PROVIDER_KEY_PATTERN.fullmatch(alias):
                    findings.append(
                        _finding("invalid_source_alias", alias, "Use a lowercase identifier.")
                    )
                _claim_unique(
                    alias_owners,
                    alias,
                    provider_key,
                    "duplicate_source_alias",
                    findings,
                )
            if not factory_key or not _METADATA_KEY_PATTERN.fullmatch(factory_key):
                findings.append(
                    _finding("invalid_factory_key", provider_key, "Factory key is invalid.")
                )
            _claim_unique(
                factory_owners,
                factory_key,
                provider_key,
                "duplicate_factory_key",
                findings,
            )
            for extension in extensions:
                if (
                    not extension.startswith(".")
                    or extension == "."
                    or "/" in extension
                    or "\\" in extension
                ):
                    findings.append(
                        _finding("invalid_extension", extension, "Extension syntax is invalid.")
                    )
                _claim_unique(
                    extension_owners,
                    extension,
                    provider_key,
                    "duplicate_extension",
                    findings,
                )
            invalid_shapes = sorted(set(locator_shapes) - _LOCATOR_SHAPES)
            for shape in invalid_shapes:
                findings.append(
                    _finding("invalid_locator_shape", provider_key, f"Unknown shape: {shape}.")
                )
            if not locator_shapes:
                findings.append(
                    _finding(
                        "missing_locator_shape",
                        provider_key,
                        "At least one locator shape is required.",
                    )
                )
            if current.directory_dataset and "directory" not in locator_shapes:
                findings.append(
                    _finding(
                        "directory_shape_missing",
                        provider_key,
                        "Directory datasets require the directory locator shape.",
                    )
                )
            _validate_options(
                current,
                findings,
                invalid_default_indexes=invalid_default_indexes,
            )
            if current.identifier is not None:
                identifier_key = current.identifier.identifier_key
                if not _METADATA_KEY_PATTERN.fullmatch(identifier_key):
                    findings.append(
                        _finding(
                            "invalid_identifier_key",
                            provider_key,
                            "Identifier key is invalid.",
                        )
                    )
                _claim_unique(
                    identifier_owners,
                    identifier_key,
                    provider_key,
                    "duplicate_identifier_key",
                    findings,
                )
            if current.dependency is not None:
                for value in (current.dependency.key, current.dependency.kind):
                    if not _METADATA_KEY_PATTERN.fullmatch(value):
                        findings.append(
                            _finding(
                                "invalid_dependency_metadata",
                                provider_key,
                                "Dependency metadata is invalid.",
                            )
                        )
            if not current.provider_interpretation_version:
                findings.append(
                    _finding(
                        "invalid_interpretation_version",
                        provider_key,
                        "Provider interpretation version is required.",
                    )
                )

        identifier_count = sum(descriptor.identifier is not None for descriptor in normalized)
        if identifier_count > MAX_IDENTIFIER_REGISTRATIONS:
            findings.append(
                _finding(
                    "identifier_limit_exceeded",
                    "registry",
                    f"{identifier_count} identifiers exceed the limit of "
                    f"{MAX_IDENTIFIER_REGISTRATIONS}.",
                )
            )

        normalized_hints: list[UnsupportedExtensionHint] = []
        hint_extensions: set[str] = set()
        for hint in unsupported_extensions:
            extension = _normalize_extension(hint.extension)
            normalized_hint = replace(hint, extension=extension)
            normalized_hints.append(normalized_hint)
            if extension in hint_extensions or extension in extension_owners:
                findings.append(
                    _finding(
                        "duplicate_unsupported_extension",
                        extension,
                        "Unsupported extension hint conflicts with another claim.",
                    )
                )
            hint_extensions.add(extension)

        if findings:
            raise ConfigurationFailure(tuple(findings))
        return cls(
            tuple(sorted(normalized, key=lambda descriptor: descriptor.provider_key)),
            tuple(sorted(normalized_hints, key=lambda hint: hint.extension)),
        )

    def descriptor(self, provider_key: str) -> DescriptorView:
        """Return one descriptor view by canonical provider key."""

        return self._by_provider[provider_key.casefold()]

    def resolve_type(self, source_type: str) -> DescriptorView | None:
        """Resolve one source-kind name or alias without importing a provider."""

        return self._by_type.get(source_type.casefold())

    def match_extension(self, locator: str) -> tuple[DescriptorView, str] | None:
        """Return the longest registered suffix match, if any."""

        normalized_locator = locator.casefold()
        for extension in self._extensions:
            if normalized_locator.endswith(extension):
                return self._by_extension[extension], extension
        return None

    def match_unsupported_extension(self, locator: str) -> UnsupportedExtensionHint | None:
        """Return deterministic guidance for a recognized unsupported suffix."""

        normalized_locator = locator.casefold()
        return next(
            (
                hint
                for hint in self._unsupported_extensions
                if normalized_locator.endswith(hint.extension)
            ),
            None,
        )


def _claim_unique(
    owners: dict[str, str],
    key: str,
    provider_key: str,
    code: str,
    findings: list[ConfigurationFinding],
) -> None:
    owner = owners.get(key)
    if owner is None:
        owners[key] = provider_key
        return
    findings.append(_finding(code, key, f"Claimed by both {owner} and {provider_key}."))


def _normalize_option_defaults(
    options: tuple[SourceOptionDefinition, ...],
    *,
    provider_key: str,
    findings: list[ConfigurationFinding],
) -> tuple[tuple[SourceOptionDefinition, ...], frozenset[int]]:
    normalized: list[SourceOptionDefinition] = []
    invalid_indexes: set[int] = set()
    for index, option in enumerate(options):
        if not option.has_default:
            normalized.append(option)
            continue
        try:
            default = freeze_source_value(option.default)
        except (TypeError, ValueError):
            findings.append(
                _finding(
                    "invalid_option_default",
                    f"{provider_key}.{option.key}",
                    "Default must be a finite JSON-compatible value.",
                )
            )
            invalid_indexes.add(index)
            normalized.append(option)
            continue
        normalized.append(replace(option, default=default))
    return tuple(normalized), frozenset(invalid_indexes)


def _validate_options(
    descriptor: SourceDescriptor,
    findings: list[ConfigurationFinding],
    *,
    invalid_default_indexes: frozenset[int],
) -> None:
    seen_keys: set[str] = set()
    for index, option in enumerate(descriptor.options):
        if not _OPTION_KEY_PATTERN.fullmatch(option.key):
            findings.append(
                _finding(
                    "invalid_option_key",
                    f"{descriptor.provider_key}.{option.key}",
                    "Option keys must be lowercase identifiers.",
                )
            )
        if option.key in seen_keys:
            findings.append(
                _finding(
                    "duplicate_option_key",
                    f"{descriptor.provider_key}.{option.key}",
                    "Option keys must be unique.",
                )
            )
        seen_keys.add(option.key)
        if option.value_kind not in _OPTION_VALUE_KINDS:
            findings.append(
                _finding(
                    "invalid_option_kind",
                    f"{descriptor.provider_key}.{option.key}",
                    "Option value kind is not supported.",
                )
            )
        if option.required and option.has_default:
            findings.append(
                _finding(
                    "required_option_has_default",
                    f"{descriptor.provider_key}.{option.key}",
                    "Required options cannot declare defaults.",
                )
            )
        if option.sensitive and option.affects_identity:
            findings.append(
                _finding(
                    "sensitive_identity_option",
                    f"{descriptor.provider_key}.{option.key}",
                    "Sensitive values cannot enter identity material.",
                )
            )
        if (
            option.has_default
            and index not in invalid_default_indexes
            and not _value_matches_kind(option.default, option.value_kind)
        ):
            findings.append(
                _finding(
                    "invalid_option_default",
                    f"{descriptor.provider_key}.{option.key}",
                    "Default does not match the declared basic value kind.",
                )
            )


def _value_matches_kind(value: object, value_kind: str) -> bool:
    if value_kind == "string":
        return isinstance(value, str)
    if value_kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_kind == "boolean":
        return isinstance(value, bool)
    if value_kind == "object":
        return isinstance(value, FrozenJSONObject)
    if value_kind == "array":
        return isinstance(value, FrozenJSONArray)
    return False


def validate_descriptor_factory_composition(
    registry: DescriptorRegistry,
    registrations: tuple[ProviderFactoryKey, ...],
) -> None:
    """Prove one descriptor/factory registration per provider without imports."""

    findings: list[ConfigurationFinding] = []
    registration_map: dict[str, ProviderFactoryKey] = {}
    for registration in registrations:
        provider_key = registration.provider_key.casefold()
        if provider_key in registration_map:
            findings.append(
                _finding(
                    "duplicate_factory_registration",
                    provider_key,
                    "Provider has more than one factory registration.",
                )
            )
            continue
        registration_map[provider_key] = registration

    descriptor_map = {
        association.provider_key: association for association in registry.factory_keys
    }
    for provider_key, association in descriptor_map.items():
        matched_registration = registration_map.get(provider_key)
        if matched_registration is None:
            findings.append(
                _finding(
                    "missing_factory_registration",
                    provider_key,
                    "Descriptor has no factory registration.",
                )
            )
        elif matched_registration.factory_key.casefold() != association.factory_key:
            findings.append(
                _finding(
                    "factory_key_mismatch",
                    provider_key,
                    "Descriptor and factory keys do not match.",
                )
            )
    for provider_key in sorted(set(registration_map) - set(descriptor_map)):
        findings.append(
            _finding(
                "orphan_factory_registration",
                provider_key,
                "Factory registration has no descriptor.",
            )
        )
    if findings:
        raise ConfigurationFailure(tuple(findings))


def _option(
    key: str,
    value_kind: OptionValueKind,
    *,
    default: object | None = None,
    has_default: bool = False,
    affects_identity: bool = True,
) -> SourceOptionDefinition:
    return SourceOptionDefinition(
        key=key,
        value_kind=value_kind,
        default=default,
        has_default=has_default,
        affects_identity=affects_identity,
    )


BUILTIN_SOURCE_DESCRIPTORS = (
    SourceDescriptor(
        provider_key="csv",
        source_kind="csv",
        extensions=(".csv",),
        identifier=IdentifierRegistration("csv.record_shape"),
        factory_key="builtin.csv",
        provider_interpretation_version="1",
    ),
    SourceDescriptor(
        provider_key="parquet",
        source_kind="parquet",
        extensions=(".parquet", ".parq"),
        locator_shapes=("file", "directory"),
        directory_dataset=True,
        dependency=DependencyRequirement("duckdb.parquet", "builtin"),
        options=(
            _option("partitioning", "string", default="none", has_default=True),
            _option("union_by_name", "boolean", default=False, has_default=True),
        ),
        identifier=IdentifierRegistration("parquet.magic"),
        factory_key="builtin.parquet",
        provider_interpretation_version="1",
    ),
    SourceDescriptor(
        provider_key="json",
        source_kind="json",
        extensions=(".json",),
        dependency=DependencyRequirement(
            "duckdb.extension.json",
            "duckdb_extension",
            guidance="Use a DuckDB runtime with the JSON extension available.",
        ),
        options=(
            _option("maximum_depth", "integer", default=10, has_default=True),
            _option("record_path", "string"),
            _option("sample_size", "integer", default=20_480, has_default=True),
            _option("schema", "object"),
        ),
        identifier=IdentifierRegistration("json.document"),
        factory_key="builtin.json",
        provider_interpretation_version="1",
    ),
    SourceDescriptor(
        provider_key="ndjson",
        source_kind="ndjson",
        aliases=("jsonl", "jsonlines"),
        extensions=(".ndjson", ".jsonl"),
        dependency=DependencyRequirement(
            "duckdb.extension.json",
            "duckdb_extension",
            guidance="Use a DuckDB runtime with the JSON extension available.",
        ),
        options=(
            _option("maximum_depth", "integer", default=10, has_default=True),
            _option("record_path", "string"),
            _option("sample_size", "integer", default=20_480, has_default=True),
            _option("schema", "object"),
        ),
        identifier=IdentifierRegistration("ndjson.records"),
        factory_key="builtin.ndjson",
        provider_interpretation_version="1",
    ),
    SourceDescriptor(
        provider_key="excel",
        source_kind="excel",
        aliases=("xlsx",),
        extensions=(".xlsx",),
        dependency=DependencyRequirement(
            "duckdb.extension.excel",
            "duckdb_extension",
            guidance=(
                "Install the DuckDB excel extension explicitly in this environment; "
                "installation is a separate networked action."
            ),
        ),
        options=(
            _option("header", "boolean", default=True, has_default=True),
            _option("range", "string"),
            _option("sheet", "string"),
            _option("stop_at_empty", "boolean", default=False, has_default=True),
            _option("type_mode", "string", default="text", has_default=True),
        ),
        identifier=IdentifierRegistration("excel.xlsx_container"),
        factory_key="builtin.excel",
        provider_interpretation_version="1",
    ),
)

BUILTIN_UNSUPPORTED_EXTENSIONS = (
    UnsupportedExtensionHint(
        extension=".xls",
        diagnostic_code="source.unsupported_excel_binary",
        guidance="Convert the workbook to .xlsx or choose another supported source type.",
    ),
)


def build_builtin_descriptor_registry() -> DescriptorRegistry:
    """Build the complete import-free v1.2 descriptor registry."""

    return DescriptorRegistry.build(
        BUILTIN_SOURCE_DESCRIPTORS,
        unsupported_extensions=BUILTIN_UNSUPPORTED_EXTENSIONS,
    )
