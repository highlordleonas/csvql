"""Local CSV source resolution and metadata."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast

from csvql.exceptions import FileMissingError, SourceError

if TYPE_CHECKING:
    from csvql.source_adapter import RelationalBinding
    from csvql.source_registry import DescriptorView

SourceOptionValue = str | int | float | bool | None
SourceOptions = tuple[tuple[str, SourceOptionValue], ...]
_SOURCE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SOURCE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_ALIAS_PREFIX = "__localql_"
_STABLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")

FrozenJSONScalar: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class FrozenJSONArray:
    """Immutable JSON array used by source-domain values."""

    values: tuple[FrozenJSONValue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "values",
            tuple(freeze_source_value(value) for value in self.values),
        )


@dataclass(frozen=True, slots=True)
class FrozenJSONObject:
    """Immutable JSON object whose keys are stored in lexical order."""

    items: tuple[tuple[str, FrozenJSONValue], ...]

    def __post_init__(self) -> None:
        normalized: list[tuple[str, FrozenJSONValue]] = []
        seen_keys: set[str] = set()
        for key, value in self.items:
            if not isinstance(key, str):
                raise TypeError("Frozen JSON object keys must be strings.")
            if key in seen_keys:
                raise ValueError("Frozen JSON object keys must be unique.")
            seen_keys.add(key)
            normalized.append((key, freeze_source_value(value)))
        ordered = tuple(sorted(normalized, key=lambda item: item[0]))
        if tuple(self.items) != ordered:
            raise ValueError("Frozen JSON object keys must be unique and lexically ordered.")
        object.__setattr__(self, "items", ordered)


FrozenJSONValue: TypeAlias = FrozenJSONScalar | FrozenJSONArray | FrozenJSONObject
FrozenSourceOptions: TypeAlias = tuple[tuple[str, FrozenJSONValue], ...]


def freeze_source_value(value: object) -> FrozenJSONValue:
    """Freeze one JSON-compatible source value without accepting lossy coercions."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Source option floats must be finite.")
        return value
    if isinstance(value, FrozenJSONArray):
        return FrozenJSONArray(value.values)
    if isinstance(value, FrozenJSONObject):
        return FrozenJSONObject(value.items)
    if isinstance(value, Mapping):
        items: list[tuple[str, FrozenJSONValue]] = []
        seen_keys: set[str] = set()
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise TypeError("Source option mappings require string keys.")
            if key in seen_keys:
                raise ValueError(f"Duplicate source option key: {key}.")
            seen_keys.add(key)
            items.append((key, freeze_source_value(nested_value)))
        return FrozenJSONObject(tuple(sorted(items, key=lambda item: item[0])))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return FrozenJSONArray(tuple(freeze_source_value(item) for item in value))
    raise TypeError("Source option values must be JSON-compatible.")


def freeze_source_options(items: Iterable[tuple[str, object]]) -> FrozenSourceOptions:
    """Freeze source options while preserving duplicate-key rejection."""

    frozen: list[tuple[str, FrozenJSONValue]] = []
    seen_keys: set[str] = set()
    for key, value in items:
        if not isinstance(key, str) or not key:
            raise ValueError("Source option keys must be non-empty strings.")
        if key in seen_keys:
            raise ValueError(f"Duplicate source option key: {key}.")
        seen_keys.add(key)
        frozen.append((key, freeze_source_value(value)))
    return tuple(sorted(frozen, key=lambda item: item[0]))


def _thaw_source_value(value: FrozenJSONValue) -> object:
    if isinstance(value, FrozenJSONArray):
        return [_thaw_source_value(item) for item in value.values]
    if isinstance(value, FrozenJSONObject):
        return {key: _thaw_source_value(item) for key, item in value.items}
    return value


def canonical_source_json_bytes(value: FrozenJSONValue) -> bytes:
    """Serialize one frozen source-domain value to canonical UTF-8 JSON."""

    return json.dumps(
        _thaw_source_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_source_options_bytes(options: FrozenSourceOptions) -> bytes:
    """Serialize frozen source options to canonical UTF-8 JSON."""

    return canonical_source_json_bytes(FrozenJSONObject(options))


@dataclass(frozen=True, slots=True)
class SourceApplicationContext:
    """Presentation and observability context excluded from source semantics."""

    surface: str

    def __post_init__(self) -> None:
        if not _STABLE_KEY_PATTERN.fullmatch(self.surface):
            raise ValueError("Source application surface must be a stable identifier.")


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """Provider-neutral request built before any filesystem observation."""

    alias: str
    locator: str
    anchor: Path | None
    explicit_type: str | None
    options: FrozenSourceOptions = ()

    def __post_init__(self) -> None:
        if not isinstance(self.alias, str) or not _SOURCE_ALIAS_PATTERN.fullmatch(self.alias):
            raise ValueError("Source alias must be a valid unmodified SQL identifier.")
        if source_alias_collision_key(self.alias).startswith(_RESERVED_ALIAS_PREFIX):
            raise ValueError("Source aliases beginning with '__localql_' are reserved.")
        if not isinstance(self.locator, str) or not self.locator or "\x00" in self.locator:
            raise ValueError("Source locator must be a non-empty local path string.")
        if self.anchor is not None and not isinstance(self.anchor, Path):
            raise TypeError("Source anchor must be a pathlib.Path when supplied.")
        explicit_type = self.explicit_type
        if explicit_type is not None:
            if not isinstance(explicit_type, str) or not explicit_type.strip():
                raise ValueError("An explicit source type must be a non-empty string.")
            explicit_type = explicit_type.strip()
        normalized_anchor = None
        if self.anchor is not None:
            normalized_anchor = Path(os.path.abspath(os.path.normpath(os.fspath(self.anchor))))
        object.__setattr__(self, "locator", os.path.normpath(self.locator))
        object.__setattr__(self, "anchor", normalized_anchor)
        object.__setattr__(self, "explicit_type", explicit_type)
        object.__setattr__(self, "options", freeze_source_options(self.options))

    @property
    def alias_key(self) -> str:
        """Return the case-insensitive alias collision key."""

        return source_alias_collision_key(self.alias)

    @property
    def safe_source_reference(self) -> str:
        """Return a display reference that does not expose an absolute parent path."""

        locator_path = Path(self.locator)
        return locator_path.name if locator_path.is_absolute() else self.locator


def build_source_request(
    *,
    alias: str,
    locator: str,
    anchor: Path | None = None,
    explicit_type: str | None = None,
    options: Iterable[tuple[str, object]] = (),
) -> SourceRequest:
    """Build one source request without selecting a provider or observing a locator."""

    return SourceRequest(
        alias=alias,
        locator=locator,
        anchor=anchor,
        explicit_type=explicit_type,
        options=freeze_source_options(options),
    )


class DiagnosticCode(StrEnum):
    """Stable source diagnostic codes."""

    SOURCE_REQUEST_INVALID = "source.request_invalid"
    SOURCE_ALIAS_INVALID = "source.alias_invalid"
    SOURCE_ALIAS_COLLISION = "source.alias_collision"
    SOURCE_TYPE_UNKNOWN = "source.type_unknown"
    SOURCE_LOCATOR_SHAPE_INVALID = "source.locator_shape_invalid"
    SOURCE_EXTENSION_CONFLICT = "source.extension_conflict"
    SOURCE_AMBIGUOUS = "source.ambiguous"
    SOURCE_UNKNOWN = "source.unknown"
    SOURCE_UNSUPPORTED = "source.unsupported"
    SOURCE_UNSUPPORTED_EXCEL_BINARY = "source.unsupported_excel_binary"
    SOURCE_IDENTIFICATION_BUDGET_EXHAUSTED = "source.identification_budget_exhausted"
    SOURCE_REGISTRY_INVALID = "source.registry_invalid"
    SOURCE_ACTIVATION_DEPENDENCY_MISSING = "source.activation_dependency_missing"
    SOURCE_ACTIVATION_FAILED = "source.activation_failed"
    SOURCE_PROVIDER_CONTRACT_INVALID = "source.provider_contract_invalid"
    SOURCE_RESOLUTION_FAILED = "source.resolution_failed"
    SOURCE_BIND_FAILED = "source.bind_failed"
    SOURCE_IDENTITY_CHANGED = "source.identity_changed"
    SOURCE_IDENTITY_UNAVAILABLE = "source.identity_unavailable"
    SOURCE_IDENTITY_INVALID = "source.identity_invalid"
    SOURCE_PARQUET_INVALID = "source.parquet_invalid"
    SOURCE_PARQUET_DATASET_EMPTY = "source.parquet_dataset_empty"
    SOURCE_DATASET_MANIFEST_LIMIT = "source.dataset_manifest_limit"
    SOURCE_DATASET_SYMLINK_REJECTED = "source.dataset_symlink_rejected"
    SOURCE_DATASET_CHANGED = "source.dataset_changed"
    SOURCE_PARQUET_SCHEMA_MISMATCH = "source.parquet_schema_mismatch"
    SOURCE_PARTITIONING_INVALID = "source.partitioning_invalid"
    SOURCE_IDENTITY_STRENGTH_UNAVAILABLE = "source.identity_strength_unavailable"
    SOURCE_CLEANUP_FAILED = "source.cleanup_failed"
    ENGINE_SESSION_ACTIVE = "engine.session_active"
    ENGINE_SESSION_TAINTED = "engine.session_tainted"


class DiagnosticStage(StrEnum):
    """Lifecycle stage that produced a source diagnostic."""

    REQUEST = "request"
    COMPOSITION = "composition"
    DETECTION = "detection"
    ACTIVATION = "activation"
    RESOLUTION = "resolution"
    BINDING = "binding"
    IDENTITY = "identity"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    """One deterministic, sanitized source-diagnostic fact."""

    provider_key: str
    evidence_kind: str
    stable_detail: str

    def __post_init__(self) -> None:
        if self.provider_key and not _STABLE_KEY_PATTERN.fullmatch(self.provider_key):
            raise ValueError("Diagnostic provider keys must be stable identifiers.")
        if not _STABLE_KEY_PATTERN.fullmatch(self.evidence_kind):
            raise ValueError("Diagnostic evidence kinds must be stable identifiers.")
        if not self.stable_detail:
            raise ValueError("Diagnostic evidence detail must not be empty.")


@dataclass(frozen=True, slots=True)
class RequiredAction:
    """Machine-readable next action shared by every output surface."""

    kind: str
    provider_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _STABLE_KEY_PATTERN.fullmatch(self.kind):
            raise ValueError("Required action kind must be a stable identifier.")
        if any(
            not isinstance(provider_key, str) or not _STABLE_KEY_PATTERN.fullmatch(provider_key)
            for provider_key in self.provider_keys
        ):
            raise ValueError("Required action provider keys must be stable identifiers.")
        object.__setattr__(self, "provider_keys", tuple(sorted(set(self.provider_keys))))


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    """Structured source failure information safe for shared rendering."""

    code: DiagnosticCode
    stage: DiagnosticStage
    message: str
    safe_source_reference: str
    evidence: tuple[DiagnosticEvidence, ...] = ()
    required_action: RequiredAction | None = None
    cause_classifications: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("Source diagnostic message must not be empty.")
        safe_reference = self.safe_source_reference
        if safe_reference and Path(safe_reference).is_absolute():
            safe_reference = Path(safe_reference).name
        object.__setattr__(self, "safe_source_reference", safe_reference)
        object.__setattr__(
            self,
            "evidence",
            tuple(
                sorted(
                    self.evidence,
                    key=lambda item: (
                        item.provider_key,
                        item.evidence_kind,
                        item.stable_detail,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "cause_classifications",
            tuple(sorted(set(self.cause_classifications))),
        )

    def as_json_value(self) -> FrozenJSONValue:
        """Return the canonical, sanitized diagnostic value."""

        evidence = [
            {
                "provider_key": item.provider_key,
                "kind": item.evidence_kind,
                "detail": item.stable_detail,
            }
            for item in self.evidence
        ]
        required_action: object = None
        if self.required_action is not None:
            required_action = {
                "kind": self.required_action.kind,
                "provider_keys": list(self.required_action.provider_keys),
            }
        return freeze_source_value(
            {
                "code": self.code.value,
                "stage": self.stage.value,
                "message": self.message,
                "source": self.safe_source_reference,
                "evidence": evidence,
                "required_action": required_action,
                "causes": list(self.cause_classifications),
            }
        )


SelectionReason = Literal["explicit_type", "extension"]


@dataclass(frozen=True, slots=True)
class SelectedSource:
    """Deterministic descriptor selection accepted by the adapter factory."""

    request: SourceRequest
    provider_key: str
    source_kind: str
    descriptor: DescriptorView
    selection_reason: SelectionReason
    extension_evidence: str | None
    options: FrozenSourceOptions

    def options_as_python(self) -> dict[str, object]:
        """Return selected, defaulted options as ordinary JSON-compatible values."""

        return {key: _thaw_source_value(value) for key, value in self.options}


@dataclass(frozen=True, slots=True)
class AmbiguousSource:
    """Source for which explicit user intent is deliberately required."""

    request: SourceRequest
    diagnostic: SourceDiagnostic
    candidates: tuple[str, ...]
    required_action: RequiredAction

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(sorted(set(self.candidates))))


@dataclass(frozen=True, slots=True)
class UnsupportedSource:
    """Recognized source shape without a supported registered provider."""

    request: SourceRequest
    diagnostic: SourceDiagnostic
    unsupported_value: str
    required_action: RequiredAction


@dataclass(frozen=True, slots=True)
class UnknownSource:
    """Source for which bounded identification found no provider evidence."""

    request: SourceRequest
    diagnostic: SourceDiagnostic
    required_action: RequiredAction


@dataclass(frozen=True, slots=True)
class InvalidSource:
    """Selected source whose locator or static options violate its descriptor."""

    request: SourceRequest
    diagnostic: SourceDiagnostic
    required_action: RequiredAction


DetectionResult: TypeAlias = (
    SelectedSource | AmbiguousSource | UnsupportedSource | UnknownSource | InvalidSource
)


class IdentityStrength(StrEnum):
    """Confidence level represented by one source identity."""

    OBSERVATIONAL = "observational"
    STRONG = "strong"
    EXACT = "exact"


@dataclass(frozen=True, slots=True)
class ObservedFileFacts:
    """Provider-neutral local file observations used for source identity."""

    size_bytes: int
    modified_time_ns: int

    def __post_init__(self) -> None:
        if self.size_bytes < 0 or self.modified_time_ns < 0:
            raise ValueError("Observed file facts must be non-negative.")


@dataclass(frozen=True, slots=True)
class DatasetMemberFacts:
    """Identity facts for one normalized member of a multi-file source."""

    relative_path: str
    observed: ObservedFileFacts
    provider_evidence: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticOptionMaterial:
    """Normalized identity-affecting source options."""

    options: FrozenSourceOptions


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Canonical source identity digest and its qualified strength."""

    digest: str
    strength: IdentityStrength


@dataclass(frozen=True, slots=True)
class IdentityRequirement:
    """Minimum source-identity strength required before execution."""

    strength: IdentityStrength = IdentityStrength.OBSERVATIONAL


class IdentityValidationStatus(StrEnum):
    """Deterministic outcome of one binding-owned identity check."""

    CONFIRMED = "confirmed"
    CHANGED = "changed"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class IdentityValidationResult:
    """Identity-validation outcome for one prepared alias."""

    alias: str
    status: IdentityValidationStatus
    required_strength: IdentityStrength
    confirmed_strength: IdentityStrength | None = None
    evidence_digest: str | None = None
    diagnostic: SourceDiagnostic | None = None

    def __post_init__(self) -> None:
        if self.status is IdentityValidationStatus.CONFIRMED:
            if self.confirmed_strength is None:
                raise ValueError("Confirmed identity requires a confirmed strength.")
            if self.evidence_digest is not None and not re.fullmatch(
                r"[0-9a-f]{64}",
                self.evidence_digest,
            ):
                raise ValueError("Identity evidence digests must be lowercase SHA-256.")
        elif self.confirmed_strength is not None or self.evidence_digest is not None:
            raise ValueError("Non-confirmed identity cannot report confirmed evidence.")


@dataclass(frozen=True, slots=True)
class IdentityValidationOutcome:
    """Ordered identity-validation results for one prepared source batch."""

    results: tuple[IdentityValidationResult, ...]

    @property
    def is_confirmed(self) -> bool:
        """Return whether every source met the requested identity strength."""

        return all(result.status is IdentityValidationStatus.CONFIRMED for result in self.results)


def build_source_identity(
    *,
    provider_key: str,
    source_kind: str,
    canonical_locator: str,
    semantic_options: FrozenSourceOptions,
    sensitive_option_keys: Iterable[str] = (),
    provider_interpretation_version: str,
    strength: IdentityStrength,
    observed_file: ObservedFileFacts | None = None,
    dataset_members: Iterable[DatasetMemberFacts] = (),
    provider_identity_evidence: str | None = None,
) -> SourceIdentity:
    """Build a SHA-256 identity from canonical provider interpretation material."""

    members = tuple(sorted(dataset_members, key=lambda item: item.relative_path))
    sensitive_keys = frozenset(sensitive_option_keys)
    identity_material: dict[str, object] = {
        "provider_key": provider_key,
        "source_kind": source_kind,
        "canonical_locator": canonical_locator,
        "semantic_options": {
            key: _thaw_source_value(value)
            for key, value in semantic_options
            if key not in sensitive_keys
        },
        "provider_interpretation_version": provider_interpretation_version,
        "strength": strength.value,
        "observed_file": (
            None
            if observed_file is None
            else {
                "size_bytes": observed_file.size_bytes,
                "modified_time_ns": observed_file.modified_time_ns,
            }
        ),
        "dataset_members": [
            {
                "relative_path": member.relative_path,
                "size_bytes": member.observed.size_bytes,
                "modified_time_ns": member.observed.modified_time_ns,
                "provider_evidence": member.provider_evidence,
            }
            for member in members
        ],
    }
    if provider_identity_evidence is not None:
        identity_material["provider_identity_evidence"] = provider_identity_evidence
    material = freeze_source_value(identity_material)
    return SourceIdentity(
        digest=hashlib.sha256(canonical_source_json_bytes(material)).hexdigest(),
        strength=strength,
    )


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
    """Immutable resource-free source interpretation captured before binding."""

    provider_key: str
    source_kind: str
    provider_interpretation_version: str
    alias: str
    alias_key: str
    canonical_locator: str
    requested_locator: str
    locator_shape: Literal["file", "directory"]
    semantic_options: FrozenSourceOptions
    operational_options: FrozenSourceOptions
    identity: SourceIdentity
    selection_reason: SelectionReason
    adapter_implementation_version: str
    duckdb_version: str
    dependency_versions: tuple[tuple[str, str], ...] = ()
    provider_facts: FrozenJSONObject = FrozenJSONObject(())
    selection_evidence: tuple[DiagnosticEvidence, ...] = ()
    resolution_evidence: tuple[DiagnosticEvidence, ...] = ()
    resolution_anchor: Path | None = None

    def __post_init__(self) -> None:
        if not _STABLE_KEY_PATTERN.fullmatch(self.provider_key):
            raise ValueError("Resolved provider key must be a stable identifier.")
        if not _SOURCE_KIND_PATTERN.fullmatch(self.source_kind):
            raise ValueError("Resolved source kind must be a stable lowercase identifier.")
        if not _SOURCE_ALIAS_PATTERN.fullmatch(self.alias):
            raise ValueError("Resolved source alias must be a valid SQL identifier.")
        if self.alias_key != source_alias_collision_key(self.alias):
            raise ValueError("Resolved source alias collision key is inconsistent.")
        if not self.canonical_locator or not Path(self.canonical_locator).is_absolute():
            raise ValueError("Resolved source locator must be an absolute canonical path.")
        if self.locator_shape not in ("file", "directory"):
            raise ValueError("Resolved source locator shape is invalid.")
        if not self.provider_interpretation_version:
            raise ValueError("Resolved provider interpretation version is required.")
        if not self.adapter_implementation_version:
            raise ValueError("Resolved adapter implementation version is required.")
        if not self.duckdb_version:
            raise ValueError("Resolved DuckDB version fact is required.")
        dependency_keys = tuple(key for key, _version in self.dependency_versions)
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError("Resolved dependency versions require unique keys.")
        object.__setattr__(self, "semantic_options", freeze_source_options(self.semantic_options))
        object.__setattr__(
            self,
            "operational_options",
            freeze_source_options(self.operational_options),
        )
        object.__setattr__(
            self,
            "dependency_versions",
            tuple(sorted(self.dependency_versions)),
        )
        object.__setattr__(
            self,
            "provider_facts",
            freeze_source_value(self.provider_facts),
        )
        object.__setattr__(
            self,
            "selection_evidence",
            tuple(
                sorted(
                    self.selection_evidence,
                    key=lambda item: (
                        item.provider_key,
                        item.evidence_kind,
                        item.stable_detail,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "resolution_evidence",
            tuple(
                sorted(
                    self.resolution_evidence,
                    key=lambda item: (
                        item.provider_key,
                        item.evidence_kind,
                        item.stable_detail,
                    ),
                )
            ),
        )
        if self.resolution_anchor is not None:
            object.__setattr__(
                self,
                "resolution_anchor",
                Path(
                    os.path.abspath(
                        os.path.normpath(os.fspath(self.resolution_anchor)),
                    )
                ),
            )

    @property
    def spec(self) -> SourceSpec:
        """Return the retained CSV compatibility declaration."""

        anchor = self.resolution_anchor or Path(self.canonical_locator).parent
        legacy_options: list[tuple[str, SourceOptionValue]] = []
        for key, value in (*self.semantic_options, *self.operational_options):
            thawed = _thaw_source_value(value)
            if not _is_source_option_value(thawed):
                raise RuntimeError("Legacy source options cannot represent nested values.")
            legacy_options.append((key, cast(SourceOptionValue, thawed)))
        return SourceSpec(
            alias=self.alias,
            kind=self.source_kind,
            locator=self.requested_locator,
            anchor=anchor,
            options=tuple(legacy_options),
        )

    @property
    def fingerprint(self) -> SourceFingerprint | None:
        """Return the version-1 CSV fingerprint compatibility view when present."""

        facts = {key: _thaw_source_value(value) for key, value in self.provider_facts.items}
        version = facts.get("fingerprint_version")
        size_bytes = facts.get("size_bytes")
        modified_at = facts.get("modified_at")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or not isinstance(modified_at, str)
        ):
            return None
        return SourceFingerprint(
            version=version,
            size_bytes=size_bytes,
            modified_at=modified_at,
        )

    def as_json_value(self) -> FrozenJSONValue:
        """Return deterministic internal JSON-compatible resolution material."""

        return freeze_source_value(
            {
                "provider_key": self.provider_key,
                "source_kind": self.source_kind,
                "provider_interpretation_version": self.provider_interpretation_version,
                "alias": self.alias,
                "alias_key": self.alias_key,
                "canonical_locator": self.canonical_locator,
                "requested_locator": self.requested_locator,
                "locator_shape": self.locator_shape,
                "semantic_options": {
                    key: _thaw_source_value(value) for key, value in self.semantic_options
                },
                "operational_options": {
                    key: _thaw_source_value(value) for key, value in self.operational_options
                },
                "identity": {
                    "digest": self.identity.digest,
                    "strength": self.identity.strength.value,
                },
                "selection_reason": self.selection_reason,
                "adapter_implementation_version": self.adapter_implementation_version,
                "duckdb_version": self.duckdb_version,
                "dependency_versions": [
                    [key, version] for key, version in self.dependency_versions
                ],
                "provider_facts": _thaw_source_value(self.provider_facts),
                "selection_evidence": [
                    {
                        "provider_key": evidence.provider_key,
                        "kind": evidence.evidence_kind,
                        "detail": evidence.stable_detail,
                    }
                    for evidence in self.selection_evidence
                ],
                "resolution_evidence": [
                    {
                        "provider_key": evidence.provider_key,
                        "kind": evidence.evidence_kind,
                        "detail": evidence.stable_detail,
                    }
                    for evidence in self.resolution_evidence
                ],
            }
        )


class PreparedSourcesState(StrEnum):
    """Lifecycle state of one atomic prepared-source aggregate."""

    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class CleanupFailure:
    """One deterministic secondary failure observed during source cleanup."""

    alias: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Ordered source-cleanup evidence returned by coordinator release."""

    failures: tuple[CleanupFailure, ...] = ()
    already_closed: bool = False

    @property
    def succeeded(self) -> bool:
        """Return whether cleanup completed without secondary failures."""

        return not self.failures


@dataclass(frozen=True, slots=True)
class SourcePreparationFailure:
    """Typed application outcome for an expected source-preparation failure."""

    diagnostics: tuple[SourceDiagnostic, ...]
    cleanup_failures: tuple[CleanupFailure, ...] = ()

    def __post_init__(self) -> None:
        if not self.diagnostics:
            raise ValueError("Source preparation failure requires a diagnostic.")


@dataclass(slots=True)
class PreparedSources:
    """Atomic live source aggregate bound to one engine session."""

    engine_session_id: str
    resolved_sources: tuple[ResolvedSource, ...]
    bindings: tuple[RelationalBinding, ...]
    _engine_session: object
    _operation_context: object | None = None
    _state: PreparedSourcesState = PreparedSourcesState.OPEN

    @property
    def state(self) -> PreparedSourcesState:
        """Return the aggregate lifecycle state."""

        return self._state

    @property
    def is_closed(self) -> bool:
        """Return whether coordinator release has completed."""

        return self._state is PreparedSourcesState.CLOSED

    def source_for_alias(self, alias: str) -> ResolvedSource:
        """Return one resolved source by case-insensitive alias."""

        alias_key = source_alias_collision_key(alias)
        return next(source for source in self.resolved_sources if source.alias_key == alias_key)

    def _mark_closed(self) -> None:
        self._state = PreparedSourcesState.CLOSED


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
    """Resolve one CSV compatibility spec through the selected-provider runtime."""

    from csvql.operation import OperationContext, OperationToken
    from csvql.source_runtime import resolve_source_request

    try:
        resolved = resolve_source_request(
            build_source_request(
                alias=spec.alias,
                locator=spec.locator,
                anchor=spec.anchor,
                explicit_type=spec.kind,
                options=spec.options,
            ),
            operation=OperationContext(token=OperationToken()),
        )
    except SourceError as exc:
        if exc.code != "source_missing":
            raise
        raise FileMissingError(
            f"CSV file not found: {display_path}",
            suggestion="Check the path or run from the directory that contains the CSV file.",
        ) from exc
    if not isinstance(resolved, ResolvedSource):
        raise RuntimeError("CSV resolution returned an invalid source value.")
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
