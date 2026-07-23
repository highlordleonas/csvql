"""Local CSV source resolution and metadata."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from csvql.exceptions import FileMissingError, SourceError

SourceOptionValue = str | int | float | bool | None
SourceOptions = tuple[tuple[str, SourceOptionValue], ...]
SourceCapability = Literal[
    "query",
    "inspect",
    "sample",
    "profile",
    "exact_count",
    "change_detection",
    "interruptible",
]
CapabilityState = Literal["available", "unavailable", "unsupported"]

SOURCE_CAPABILITY_OPERATIONS: tuple[SourceCapability, ...] = (
    "query",
    "inspect",
    "sample",
    "profile",
    "exact_count",
    "change_detection",
    "interruptible",
)
_SOURCE_CAPABILITY_ORDER = {
    operation: index for index, operation in enumerate(SOURCE_CAPABILITY_OPERATIONS)
}
_SOURCE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SOURCE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_CAPABILITY_REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_ALIAS_PREFIX = "__localql_"


def source_alias_collision_key(alias: str) -> str:
    """Return the case-insensitive identity used to detect alias collisions."""

    return alias.casefold()


def source_options(
    items: Iterable[tuple[str, SourceOptionValue]],
) -> SourceOptions:
    """Build deterministic immutable source options, rejecting duplicate keys."""

    normalized: list[tuple[str, SourceOptionValue]] = []
    seen_keys: set[str] = set()
    for key, value in items:
        if not isinstance(key, str) or not key:
            raise ValueError("Source option keys must be non-empty strings.")
        if key in seen_keys:
            raise ValueError(f"Duplicate source option key: {key}.")
        if not _is_source_option_value(value):
            raise TypeError("Source option values must be strings, numbers, booleans, or None.")
        seen_keys.add(key)
        normalized.append((key, value))
    return tuple(sorted(normalized, key=lambda item: item[0]))


def _is_source_option_value(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Private immutable declaration of one adapter-owned source."""

    alias: str
    kind: str
    locator: str
    anchor: Path
    options: SourceOptions = ()

    def __post_init__(self) -> None:
        if not isinstance(self.alias, str) or not _SOURCE_ALIAS_PATTERN.fullmatch(self.alias):
            raise ValueError("Source alias must be a valid unmodified SQL identifier.")
        if source_alias_collision_key(self.alias).startswith(_RESERVED_ALIAS_PREFIX):
            raise ValueError("Source aliases beginning with '__localql_' are reserved.")
        if not isinstance(self.kind, str) or not _SOURCE_KIND_PATTERN.fullmatch(self.kind):
            raise ValueError("Source kind must be a stable lowercase identifier.")
        if not isinstance(self.locator, str) or not self.locator:
            raise ValueError("Source locator must be a non-empty string.")
        if not isinstance(self.anchor, Path):
            raise TypeError("Source anchor must be an explicit pathlib.Path.")

        normalized_options = source_options(self.options)
        if self.kind == "csv" and normalized_options:
            raise SourceError(
                "unsupported_source_option",
                "CSV source options are not supported.",
                kind=self.kind,
                alias=self.alias,
                suggestion="Remove all source options to preserve CSV auto-detection.",
            )
        object.__setattr__(self, "anchor", self.anchor.resolve(strict=False))
        object.__setattr__(self, "options", normalized_options)

    @property
    def alias_key(self) -> str:
        """Return the case-insensitive identity used for collision checks."""

        return source_alias_collision_key(self.alias)


@dataclass(frozen=True, slots=True)
class SourceCapabilityStatus:
    """Availability state and stable human guidance for one source operation."""

    operation: SourceCapability
    state: CapabilityState
    reason_code: str | None = None
    remediation: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in SOURCE_CAPABILITY_OPERATIONS:
            raise ValueError(f"Unknown source capability: {self.operation}.")
        if self.state not in ("available", "unavailable", "unsupported"):
            raise ValueError(f"Unknown source capability state: {self.state}.")
        if self.state != "available" and (
            self.reason_code is None
            or not _CAPABILITY_REASON_CODE_PATTERN.fullmatch(self.reason_code)
        ):
            raise ValueError("A non-available source capability requires a stable reason code.")


@dataclass(frozen=True, slots=True)
class SourceCapabilities:
    """Deterministic operation capability statuses for one source."""

    statuses: tuple[SourceCapabilityStatus, ...]

    def __post_init__(self) -> None:
        seen_operations: set[SourceCapability] = set()
        for status in self.statuses:
            if status.operation in seen_operations:
                raise ValueError(f"Duplicate source capability: {status.operation}.")
            seen_operations.add(status.operation)
        if seen_operations != set(SOURCE_CAPABILITY_OPERATIONS):
            raise ValueError("Source capabilities require the exact source capability map.")
        ordered = tuple(
            sorted(
                self.statuses,
                key=lambda status: _SOURCE_CAPABILITY_ORDER[status.operation],
            )
        )
        object.__setattr__(self, "statuses", ordered)

    def status_for(self, operation: SourceCapability) -> SourceCapabilityStatus:
        """Return the definite status for an operation in the exhaustive report."""

        return next(status for status in self.statuses if status.operation == operation)

    def with_status(self, replacement: SourceCapabilityStatus) -> SourceCapabilities:
        """Return a copy with one operation status replaced."""

        return SourceCapabilities(
            tuple(
                replacement if status.operation == replacement.operation else status
                for status in self.statuses
            )
        )


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Versioned file metadata used to identify a local CSV source."""

    version: int
    size_bytes: int
    modified_at: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly fingerprint payload."""

        return {
            "version": self.version,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True, slots=True)
class CSVSource:
    """Resolved local CSV file plus display and fingerprint metadata."""

    path: Path
    display_path: str
    fingerprint: SourceFingerprint

    def to_json_summary(self) -> dict[str, object]:
        """Return the stable JSON source summary used by inspect and sample."""

        return {
            "display_path": self.display_path,
            "resolved_path": str(self.path),
            "size_bytes": self.fingerprint.size_bytes,
            "modified_at": self.fingerprint.modified_at,
            "fingerprint": self.fingerprint.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class RegisteredTable:
    """A validated table alias bound to a resolved CSV source."""

    name: str
    source: CSVSource


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """Private immutable source identity captured before adapter binding."""

    spec: SourceSpec
    canonical_locator: str
    fingerprint: SourceFingerprint | None
    capabilities: SourceCapabilities


class _NamedPathSource(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def path(self) -> Path: ...


class _CatalogTableEntry(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def path(self) -> str: ...


def source_spec_from_table_source(
    source: _NamedPathSource,
    *,
    anchor: Path | None = None,
) -> SourceSpec:
    """Convert a legacy table source without changing the legacy value."""

    source_path = source.path
    if anchor is None:
        if not source_path.is_absolute():
            raise ValueError("A relative legacy table source requires an explicit anchor.")
        anchor = source_path.parent
    return SourceSpec(
        alias=source.name,
        kind="csv",
        locator=str(source_path),
        anchor=anchor,
    )


def source_spec_from_catalog_table(
    table: _CatalogTableEntry,
    *,
    project_root: Path,
) -> SourceSpec:
    """Convert a version-1 catalog entry using its project resolution anchor."""

    return SourceSpec(
        alias=table.name,
        kind="csv",
        locator=table.path,
        anchor=project_root,
    )


def source_spec_from_cli_mapping(
    *,
    alias: str,
    path_value: str,
    anchor: Path,
) -> SourceSpec:
    """Convert validated CLI mapping values while retaining the entered locator."""

    return SourceSpec(alias=alias, kind="csv", locator=path_value, anchor=anchor)


def source_spec_from_tui_source(
    source: _NamedPathSource,
    *,
    anchor: Path | None = None,
) -> SourceSpec:
    """Convert a TUI source facade; UI provenance never becomes an adapter kind."""

    return source_spec_from_table_source(source, anchor=anchor)


def resolve_csv_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    """Resolve and validate a local CSV path."""

    return source_from_path(path_value, base_dir=base_dir).path


def csv_source_from_spec(spec: SourceSpec, *, display_path: str) -> CSVSource:
    """Resolve a CSV spec while preserving the established public source facade."""

    resolved = _resolve_csv_source_spec(spec, display_path=display_path)
    return _csv_source_from_resolved(resolved, display_path=display_path)


def _resolve_csv_source_spec(
    spec: SourceSpec,
    *,
    display_path: str,
) -> ResolvedSource:
    """Resolve one CSV spec through the production registry with legacy errors."""

    from csvql.csv_adapter import DEFAULT_SOURCE_ADAPTER_REGISTRY
    from csvql.operation import OperationContext, OperationToken

    try:
        adapter = DEFAULT_SOURCE_ADAPTER_REGISTRY.create(
            spec.kind,
            capability="query",
        )
        resolved = adapter.resolve(
            spec,
            OperationContext(token=OperationToken()),
        )
    except SourceError as exc:
        if exc.code != "source_missing":
            raise
        raise FileMissingError(
            f"CSV file not found: {display_path}",
            suggestion="Check the path or run from the directory that contains the CSV file.",
        ) from exc
    return resolved


def _csv_source_from_resolved(
    resolved: ResolvedSource,
    *,
    display_path: str,
) -> CSVSource:
    """Convert an immutable resolved snapshot without touching its locator again."""

    if resolved.fingerprint is None:
        raise RuntimeError("CSV resolution did not capture a source fingerprint.")
    return CSVSource(
        path=Path(resolved.canonical_locator),
        display_path=display_path,
        fingerprint=resolved.fingerprint,
    )


def source_from_path(path_value: str, *, base_dir: Path | None = None) -> CSVSource:
    """Build a resolved CSV source from a CLI path value."""

    spec = SourceSpec(
        alias="csv_source",
        kind="csv",
        locator=path_value,
        anchor=base_dir or Path.cwd(),
    )
    return csv_source_from_spec(spec, display_path=path_value)
