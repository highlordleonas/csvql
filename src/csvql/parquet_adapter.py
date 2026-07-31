"""Parquet provider resolution, deterministic datasets, and relational binding."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

import duckdb

from csvql.adapter_factory import ProviderActivationFacts
from csvql.exceptions import (
    EngineSessionTaintedError,
    SourceBindingError,
    SourceCleanupError,
    SourceError,
    SourceErrorCode,
    SourceIdentityError,
    SourceResolutionError,
)
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    DatasetMemberFacts,
    DiagnosticCode,
    DiagnosticEvidence,
    DiagnosticStage,
    FrozenJSONArray,
    FrozenJSONObject,
    FrozenJSONValue,
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
from csvql.source_manifest import (
    DATASET_INCLUSION_POLICY_VERSION,
    DatasetManifest,
    DatasetManifestFailure,
    DatasetMember,
    build_dataset_manifest,
    summarize_manifest_change,
)
from csvql.sql_utils import quote_identifier

__version__ = "1"

_PROVIDER_KEY = "parquet"
_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_CHANGE_PATHS = 20


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    observed: ObservedFileFacts
    modified_at: str
    device: int
    inode: int


class _IdentityStrengthUnavailable(Exception):
    """Requested DuckDB metadata evidence is unavailable in this runtime."""


def _resolution_error(
    code: str,
    message: str,
    *,
    alias: str,
    suggestion: str,
) -> SourceResolutionError:
    return SourceResolutionError(
        cast(SourceErrorCode, code),
        message,
        kind=_PROVIDER_KEY,
        alias=alias,
        suggestion=suggestion,
    )


def _binding_error(
    code: str,
    message: str,
    *,
    alias: str,
    suggestion: str,
) -> SourceBindingError:
    return SourceBindingError(
        cast(SourceErrorCode, code),
        message,
        kind=_PROVIDER_KEY,
        alias=alias,
        suggestion=suggestion,
    )


def _canonical_locator(selected: SelectedSource) -> tuple[Path, os.stat_result]:
    request = selected.request
    candidate = Path(request.locator).expanduser()
    if not candidate.is_absolute():
        candidate = (request.anchor or Path.cwd()) / candidate
    canonical = Path(os.path.abspath(os.path.normpath(os.fspath(candidate))))
    try:
        locator_stat = canonical.lstat()
    except (OSError, ValueError) as exc:
        raise _resolution_error(
            "source.parquet_invalid",
            "Parquet source is missing or unreadable.",
            alias=request.alias,
            suggestion="Restore the source or update its configured locator.",
        ) from exc
    if stat.S_ISLNK(locator_stat.st_mode):
        raise _resolution_error(
            "source.dataset_symlink_rejected",
            "Parquet source locators cannot be symbolic links.",
            alias=request.alias,
            suggestion="Use the canonical regular file or directory path.",
        )
    return canonical, locator_stat


def _snapshot_file(
    path: Path,
    *,
    alias: str,
    operation: OperationContext,
    expected_stat: os.stat_result | None = None,
) -> _FileSnapshot:
    operation.checkpoint()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as source_file:
                file_stat = os.fstat(source_file.fileno())
                if not stat.S_ISREG(file_stat.st_mode):
                    raise OSError("not a regular file")
                if expected_stat is not None and (
                    file_stat.st_dev != expected_stat.st_dev
                    or file_stat.st_ino != expected_stat.st_ino
                ):
                    raise OSError("file changed during observation")
                if file_stat.st_size < 8:
                    leading = trailing = b""
                else:
                    leading = source_file.read(4)
                    source_file.seek(-4, os.SEEK_END)
                    trailing = source_file.read(4)
        except BaseException:
            descriptor = -1
            raise
    except OSError as exc:
        raise _resolution_error(
            "source.parquet_invalid",
            "Parquet source is missing, unreadable, or not a regular file.",
            alias=alias,
            suggestion="Choose a readable local Parquet file.",
        ) from exc
    operation.checkpoint()
    if leading != b"PAR1" or trailing != b"PAR1":
        raise _resolution_error(
            "source.parquet_invalid",
            "Parquet source does not contain valid leading and trailing magic.",
            alias=alias,
            suggestion="Choose a valid Parquet file or correct the explicit source type.",
        )
    return _FileSnapshot(
        observed=ObservedFileFacts(
            size_bytes=file_stat.st_size,
            modified_time_ns=file_stat.st_mtime_ns,
        ),
        modified_at=_iso_timestamp(file_stat.st_mtime_ns),
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
    )


def _iso_timestamp(modified_time_ns: int) -> str:
    return datetime.fromtimestamp(
        modified_time_ns / 1_000_000_000,
        tz=UTC,
    ).isoformat()


def _normalize_options(
    selected: SelectedSource,
) -> tuple[tuple[str, FrozenJSONValue], ...]:
    options = selected.options_as_python()
    partitioning = options.get("partitioning")
    union_by_name = options.get("union_by_name")
    if partitioning not in {"none", "hive"}:
        raise _resolution_error(
            "source.partitioning_invalid",
            "Parquet partitioning must be explicitly 'none' or 'hive'.",
            alias=selected.request.alias,
            suggestion="Use partitioning=none or partitioning=hive.",
        )
    if not isinstance(union_by_name, bool):
        raise _resolution_error(
            "source.parquet_invalid",
            "Parquet union_by_name must be a boolean.",
            alias=selected.request.alias,
            suggestion="Use union_by_name=true or union_by_name=false.",
        )
    return selected.options


def _file_manifest_digest(path: Path, snapshot: _FileSnapshot) -> str:
    material = {
        "inclusion_policy_version": DATASET_INCLUSION_POLICY_VERSION,
        "relative_path": unicodedata.normalize("NFC", path.name),
        "size_bytes": snapshot.observed.size_bytes,
        "modified_time_ns": snapshot.observed.modified_time_ns,
        "file_type_evidence": "regular_file",
    }
    return _json_digest(material)


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_provider_facts(path: Path, snapshot: _FileSnapshot) -> FrozenJSONObject:
    relative_path = unicodedata.normalize("NFC", path.name)
    return _freeze_facts(
        {
            "excluded_regular_file_count": 0,
            "excluded_suffix_summary": [],
            "excluded_symlink_paths": [],
            "fingerprint_version": 1,
            "manifest_digest": _file_manifest_digest(path, snapshot),
            "member_count": 1,
            "member_paths": [relative_path],
            "members": [
                {
                    "relative_path": relative_path,
                    "size_bytes": snapshot.observed.size_bytes,
                    "modified_time_ns": snapshot.observed.modified_time_ns,
                    "file_type_evidence": "regular_file",
                    "provider_evidence": None,
                    "locator_relative_path": path.name,
                }
            ],
            "modified_at": snapshot.modified_at,
            "modified_time_ns": snapshot.observed.modified_time_ns,
            "root_device": snapshot.device,
            "root_inode": snapshot.inode,
            "size_bytes": snapshot.observed.size_bytes,
            "total_relative_path_bytes": len(relative_path.encode("utf-8")),
        }
    )


def _dataset_provider_facts(manifest: DatasetManifest) -> FrozenJSONObject:
    latest_modified_time_ns = max(member.observed.modified_time_ns for member in manifest.members)
    return _freeze_facts(
        {
            "excluded_regular_file_count": manifest.excluded_regular_file_count,
            "excluded_suffix_summary": [
                [suffix, count] for suffix, count in manifest.excluded_suffix_summary
            ],
            "excluded_symlink_paths": list(manifest.excluded_symlink_paths),
            "fingerprint_version": 1,
            "inclusion_policy_version": manifest.inclusion_policy_version,
            "manifest_digest": manifest.aggregate_observational_digest,
            "member_count": manifest.member_count,
            "member_paths": [member.relative_path for member in manifest.members],
            "members": [
                {
                    "relative_path": member.relative_path,
                    "size_bytes": member.observed.size_bytes,
                    "modified_time_ns": member.observed.modified_time_ns,
                    "file_type_evidence": member.file_type_evidence,
                    "provider_evidence": member.provider_evidence,
                    "locator_relative_path": member.locator_relative_path,
                }
                for member in manifest.members
            ],
            "modified_at": _iso_timestamp(latest_modified_time_ns),
            "modified_time_ns": latest_modified_time_ns,
            "root_device": manifest.root_device,
            "root_inode": manifest.root_inode,
            "size_bytes": manifest.total_included_bytes,
            "total_relative_path_bytes": manifest.total_relative_path_bytes,
        }
    )


def _freeze_facts(value: dict[str, object]) -> FrozenJSONObject:
    frozen = freeze_source_value(value)
    if not isinstance(frozen, FrozenJSONObject):
        raise AssertionError("Parquet provider facts must be an immutable JSON object.")
    return frozen


def _thaw(value: FrozenJSONValue) -> object:
    if isinstance(value, FrozenJSONArray):
        return [_thaw(item) for item in value.values]
    if isinstance(value, FrozenJSONObject):
        return {key: _thaw(item) for key, item in value.items}
    return value


def _provider_facts(resolved: ResolvedSource) -> dict[str, object]:
    return {key: _thaw(value) for key, value in resolved.provider_facts.items}


def _observed_file_from_facts(resolved: ResolvedSource) -> ObservedFileFacts:
    facts = _provider_facts(resolved)
    size_bytes = facts.get("size_bytes")
    modified_time_ns = facts.get("modified_time_ns")
    if (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or not isinstance(modified_time_ns, int)
        or isinstance(modified_time_ns, bool)
    ):
        raise _source_changed(resolved, "Recorded Parquet file facts are unavailable.")
    return ObservedFileFacts(
        size_bytes=size_bytes,
        modified_time_ns=modified_time_ns,
    )


def _manifest_from_resolved(resolved: ResolvedSource) -> DatasetManifest:
    facts = _provider_facts(resolved)
    raw_members = facts.get("members")
    if not isinstance(raw_members, list):
        raise _source_changed(resolved, "Recorded Parquet dataset members are unavailable.")
    members: list[DatasetMember] = []
    for raw_member in raw_members:
        if not isinstance(raw_member, dict):
            raise _source_changed(resolved, "Recorded Parquet dataset members are invalid.")
        relative_path = raw_member.get("relative_path")
        size_bytes = raw_member.get("size_bytes")
        modified_time_ns = raw_member.get("modified_time_ns")
        file_type_evidence = raw_member.get("file_type_evidence")
        provider_evidence = raw_member.get("provider_evidence")
        locator_relative_path = raw_member.get("locator_relative_path", relative_path)
        if (
            not isinstance(relative_path, str)
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or not isinstance(modified_time_ns, int)
            or isinstance(modified_time_ns, bool)
            or not isinstance(file_type_evidence, str)
            or (provider_evidence is not None and not isinstance(provider_evidence, str))
            or not isinstance(locator_relative_path, str)
        ):
            raise _source_changed(resolved, "Recorded Parquet dataset members are invalid.")
        members.append(
            DatasetMember(
                relative_path=relative_path,
                observed=ObservedFileFacts(size_bytes, modified_time_ns),
                file_type_evidence=file_type_evidence,
                provider_evidence=provider_evidence,
                locator_relative_path=locator_relative_path,
            )
        )
    root_device = facts.get("root_device")
    root_inode = facts.get("root_inode")
    manifest_digest = facts.get("manifest_digest")
    total_relative_path_bytes = facts.get("total_relative_path_bytes")
    excluded_count = facts.get("excluded_regular_file_count")
    suffix_summary = facts.get("excluded_suffix_summary")
    symlink_paths = facts.get("excluded_symlink_paths")
    if (
        not isinstance(root_device, int)
        or isinstance(root_device, bool)
        or not isinstance(root_inode, int)
        or isinstance(root_inode, bool)
        or not isinstance(manifest_digest, str)
        or not isinstance(total_relative_path_bytes, int)
        or isinstance(total_relative_path_bytes, bool)
        or not isinstance(excluded_count, int)
        or isinstance(excluded_count, bool)
        or not isinstance(suffix_summary, list)
        or not isinstance(symlink_paths, list)
    ):
        raise _source_changed(resolved, "Recorded Parquet dataset manifest is invalid.")
    parsed_suffixes: list[tuple[str, int]] = []
    for item in suffix_summary:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], int)
            or isinstance(item[1], bool)
        ):
            raise _source_changed(resolved, "Recorded Parquet exclusion facts are invalid.")
        parsed_suffixes.append((item[0], item[1]))
    if not all(isinstance(item, str) for item in symlink_paths):
        raise _source_changed(resolved, "Recorded Parquet symlink facts are invalid.")
    return DatasetManifest(
        canonical_root=resolved.canonical_locator,
        inclusion_policy_version=str(
            facts.get("inclusion_policy_version", DATASET_INCLUSION_POLICY_VERSION)
        ),
        root_device=root_device,
        root_inode=root_inode,
        members=tuple(members),
        excluded_regular_file_count=excluded_count,
        excluded_suffix_summary=tuple(parsed_suffixes),
        excluded_symlink_paths=tuple(cast(list[str], symlink_paths)),
        total_included_bytes=sum(member.observed.size_bytes for member in members),
        total_relative_path_bytes=total_relative_path_bytes,
        aggregate_observational_digest=manifest_digest,
    )


def _source_changed(resolved: ResolvedSource, message: str) -> SourceIdentityError:
    return SourceIdentityError(
        "source.dataset_changed",
        message,
        kind=_PROVIDER_KEY,
        alias=resolved.alias,
        suggestion="Submit the operation again to capture the current Parquet source.",
    )


def _validate_observational(
    resolved: ResolvedSource,
    operation: OperationContext,
) -> None:
    operation.checkpoint()
    if resolved.locator_shape == "file":
        try:
            current_stat = Path(resolved.canonical_locator).lstat()
        except OSError as exc:
            raise _source_changed(resolved, "Parquet source is no longer readable.") from exc
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISREG(current_stat.st_mode):
            raise _source_changed(resolved, "Parquet source is no longer a regular file.")
        current_file = ObservedFileFacts(
            current_stat.st_size,
            current_stat.st_mtime_ns,
        )
        if current_file != _observed_file_from_facts(resolved):
            raise _source_changed(resolved, "Parquet source changed after resolution.")
        return

    recorded = _manifest_from_resolved(resolved)
    try:
        current_manifest = build_dataset_manifest(
            Path(resolved.canonical_locator),
            operation=operation,
        )
    except DatasetManifestFailure as exc:
        raise _source_changed(
            resolved,
            "Parquet dataset changed or became invalid after resolution.",
        ) from exc
    summary = summarize_manifest_change(
        recorded,
        current_manifest,
        max_paths=_MAX_CHANGE_PATHS,
    )
    if summary.has_changes:
        displayed_paths = (
            *summary.added_paths,
            *summary.removed_paths,
            *summary.changed_paths,
        )
        detail = ", ".join(displayed_paths)
        suffix = "" if not detail else f" Observed members: {detail}."
        if summary.omitted_path_count:
            suffix += f" {summary.omitted_path_count} additional changes omitted."
        raise _source_changed(
            resolved,
            f"Parquet dataset changed after resolution.{suffix}",
        )


def _member_paths(resolved: ResolvedSource) -> tuple[tuple[str, str], ...]:
    if resolved.locator_shape == "file":
        return ((Path(resolved.canonical_locator).name, resolved.canonical_locator),)
    root = Path(resolved.canonical_locator)
    manifest = _manifest_from_resolved(resolved)
    members: list[tuple[str, str]] = []
    for member in manifest.members:
        relative = PurePosixPath(member.locator_relative_path or member.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise _source_changed(resolved, "Recorded Parquet member path is invalid.")
        candidate = root.joinpath(*relative.parts)
        members.append((member.relative_path, str(candidate)))
    return tuple(members)


def _semantic_option(resolved: ResolvedSource, key: str) -> object:
    options = {option_key: _thaw(value) for option_key, value in resolved.semantic_options}
    return options[key]


def _schema_signature(
    connection: duckdb.DuckDBPyConnection,
    path: str,
    *,
    hive_partitioning: bool,
) -> tuple[tuple[str, str], ...]:
    relation = connection.read_parquet(
        path,
        hive_partitioning=hive_partitioning,
        union_by_name=False,
    )
    return tuple(
        (column, str(column_type))
        for column, column_type in zip(relation.columns, relation.types, strict=True)
    )


def _strong_identity_digest(
    members: tuple[tuple[str, str], ...],
    operation: OperationContext,
) -> str:
    material: list[dict[str, object]] = []
    connection = duckdb.connect(
        database=":memory:",
        config={
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        },
    )
    try:
        for relative_path, absolute_path in members:
            operation.checkpoint()
            try:
                file_metadata = connection.execute(
                    """
                    SELECT
                        num_rows,
                        num_row_groups,
                        format_version,
                        file_size_bytes,
                        footer_size,
                        CAST(column_orders AS VARCHAR)
                    FROM parquet_file_metadata(?)
                    """,
                    [absolute_path],
                ).fetchall()
                schema_metadata = connection.execute(
                    """
                    SELECT
                        name,
                        type,
                        type_length,
                        repetition_type,
                        num_children,
                        converted_type,
                        scale,
                        precision,
                        field_id,
                        CAST(logical_type AS VARCHAR),
                        duckdb_type,
                        column_id
                    FROM parquet_schema(?)
                    ORDER BY column_id
                    """,
                    [absolute_path],
                ).fetchall()
            except duckdb.CatalogException as exc:
                raise _IdentityStrengthUnavailable from exc
            material.append(
                {
                    "relative_path": relative_path,
                    "file_metadata": file_metadata,
                    "schema_metadata": schema_metadata,
                }
            )
    finally:
        connection.close()
    return _json_digest(material)


def _exact_identity_digest(
    members: tuple[tuple[str, str], ...],
    operation: OperationContext,
) -> str:
    digest = hashlib.sha256()
    for relative_path, absolute_path in members:
        operation.checkpoint()
        encoded_path = relative_path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        try:
            with Path(absolute_path).open("rb") as member_file:
                while True:
                    operation.checkpoint()
                    chunk = member_file.read(_HASH_CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError as exc:
            raise SourceIdentityError(
                "source.dataset_changed",
                "Parquet source became unreadable during exact validation.",
                kind=_PROVIDER_KEY,
                suggestion="Submit the operation again before requesting exact identity.",
            ) from exc
    return digest.hexdigest()


@dataclass(slots=True)
class _ParquetRelationalBinding:
    _engine_session: EngineSession
    _resolved_source: ResolvedSource
    _registration_token: object
    _members: tuple[tuple[str, str], ...]
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
        """Validate the immutable member set at exactly the requested strength."""

        self._engine_session.assert_session_access()
        context.checkpoint()
        if self._closed:
            raise _source_changed(
                self._resolved_source,
                "Parquet source binding is closed.",
            )
        try:
            _validate_observational(self._resolved_source, context)
        except SourceIdentityError:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.CHANGED,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_DATASET_CHANGED,
                    stage=DiagnosticStage.IDENTITY,
                    message="Parquet source changed after resolution.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction("resubmit_source", (_PROVIDER_KEY,)),
                ),
            )
        if requirement.strength is IdentityStrength.OBSERVATIONAL:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.CONFIRMED,
                required_strength=requirement.strength,
                confirmed_strength=IdentityStrength.OBSERVATIONAL,
            )

        try:
            if requirement.strength is IdentityStrength.STRONG:
                evidence_digest = _strong_identity_digest(self._members, context)
            else:
                evidence_digest = _exact_identity_digest(self._members, context)
        except _IdentityStrengthUnavailable:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.UNAVAILABLE,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_STRENGTH_UNAVAILABLE,
                    stage=DiagnosticStage.IDENTITY,
                    message="DuckDB cannot provide stable Parquet metadata evidence.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction(
                        "choose_observational_or_resubmit",
                        (_PROVIDER_KEY,),
                    ),
                ),
            )
        except (duckdb.Error, OSError, SourceIdentityError):
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.INVALID,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_INVALID,
                    stage=DiagnosticStage.IDENTITY,
                    message="Parquet identity evidence could not be read safely.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction("restore_or_resubmit", (_PROVIDER_KEY,)),
                ),
            )
        return IdentityValidationResult(
            alias=self.alias,
            status=IdentityValidationStatus.CONFIRMED,
            required_strength=requirement.strength,
            confirmed_strength=requirement.strength,
            evidence_digest=evidence_digest,
        )

    def close(self, context: OperationContext) -> None:
        """Remove this binding's relation without closing the engine session."""

        if self._closed:
            return
        self._engine_session.assert_session_access()
        if self._engine_session.has_active_execution:
            raise _binding_error(
                "source_bind_failed",
                "Parquet source binding is still in use.",
                alias=self.alias,
                suggestion="Wait for the active query to reach a terminal state.",
            )
        if self._engine_session.is_tainted:
            raise EngineSessionTaintedError(
                "engine_session_tainted",
                "Parquet source binding cannot be unregistered from a tainted session.",
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
                "Failed to clean up a Parquet source binding.",
                kind=_PROVIDER_KEY,
                alias=self.alias,
                suggestion="Close the LocalQL operation and try again.",
            ) from exc
        self._closed = True


class ParquetSourceAdapter:
    """Lightweight Parquet provider activated after deterministic selection."""

    provider_key = _PROVIDER_KEY

    def __init__(self, *, activation_facts: ProviderActivationFacts) -> None:
        if activation_facts.provider_key != self.provider_key:
            raise ValueError("Parquet activation facts have the wrong provider key.")
        self._activation_facts = activation_facts
        self.implementation_version = activation_facts.adapter_implementation_version

    def resolve(
        self,
        selected: SelectedSource,
        operation: OperationContext,
    ) -> ResolvedSource:
        """Resolve a file or explicitly typed directory into immutable facts."""

        operation.checkpoint()
        if selected.provider_key != self.provider_key or selected.source_kind != "parquet":
            raise _resolution_error(
                "source.parquet_invalid",
                "The Parquet adapter received a different source kind.",
                alias=selected.request.alias,
                suggestion="Select the adapter matching the source kind.",
            )
        semantic_options = _normalize_options(selected)
        path, locator_stat = _canonical_locator(selected)
        selection_evidence = (
            DiagnosticEvidence(
                self.provider_key,
                "selection_basis",
                selected.selection_reason,
            ),
        )

        if stat.S_ISDIR(locator_stat.st_mode):
            if selected.selection_reason != "explicit_type":
                raise _resolution_error(
                    "source.parquet_invalid",
                    "Parquet directories require an explicit source type.",
                    alias=selected.request.alias,
                    suggestion="Resubmit the directory with type=parquet.",
                )
            try:
                manifest = build_dataset_manifest(path, operation=operation)
            except DatasetManifestFailure as exc:
                raise _resolution_error(
                    exc.code,
                    exc.message,
                    alias=selected.request.alias,
                    suggestion="Correct the explicit Parquet dataset and resubmit it.",
                ) from exc
            provider_facts = _dataset_provider_facts(manifest)
            identity = build_source_identity(
                provider_key=self.provider_key,
                source_kind=selected.source_kind,
                canonical_locator=str(path),
                semantic_options=semantic_options,
                provider_interpretation_version=(
                    selected.descriptor.provider_interpretation_version
                ),
                strength=IdentityStrength.OBSERVATIONAL,
                dataset_members=(
                    DatasetMemberFacts(
                        member.relative_path,
                        member.observed,
                        member.provider_evidence,
                    )
                    for member in manifest.members
                ),
                provider_identity_evidence=manifest.aggregate_observational_digest,
            )
            locator_shape: Literal["file", "directory"] = "directory"
            resolution_evidence = (
                DiagnosticEvidence(
                    self.provider_key,
                    "dataset_manifest",
                    f"{manifest.member_count}_members",
                ),
            )
        elif stat.S_ISREG(locator_stat.st_mode):
            snapshot = _snapshot_file(
                path,
                alias=selected.request.alias,
                operation=operation,
                expected_stat=locator_stat,
            )
            provider_facts = _file_provider_facts(path, snapshot)
            identity = build_source_identity(
                provider_key=self.provider_key,
                source_kind=selected.source_kind,
                canonical_locator=str(path),
                semantic_options=semantic_options,
                provider_interpretation_version=(
                    selected.descriptor.provider_interpretation_version
                ),
                strength=IdentityStrength.OBSERVATIONAL,
                observed_file=snapshot.observed,
                provider_identity_evidence=_file_manifest_digest(path, snapshot),
            )
            locator_shape = "file"
            resolution_evidence = (
                DiagnosticEvidence(
                    self.provider_key,
                    "parquet_magic",
                    "leading_and_trailing_magic",
                ),
            )
        else:
            raise _resolution_error(
                "source.parquet_invalid",
                "Parquet source must be a regular file or explicitly typed directory.",
                alias=selected.request.alias,
                suggestion="Choose a supported local Parquet locator.",
            )

        return ResolvedSource(
            provider_key=self.provider_key,
            source_kind=selected.source_kind,
            provider_interpretation_version=(selected.descriptor.provider_interpretation_version),
            alias=selected.request.alias,
            alias_key=selected.request.alias_key,
            canonical_locator=str(path),
            requested_locator=selected.request.locator,
            locator_shape=locator_shape,
            semantic_options=semantic_options,
            operational_options=(),
            identity=identity,
            selection_reason=selected.selection_reason,
            adapter_implementation_version=self.implementation_version,
            duckdb_version=self._activation_facts.duckdb_version,
            dependency_versions=self._activation_facts.dependency_versions,
            provider_facts=provider_facts,
            selection_evidence=selection_evidence,
            resolution_evidence=resolution_evidence,
            resolution_anchor=selected.request.anchor,
        )

    def bind(
        self,
        resolved: ResolvedSource,
        engine_session: EngineSession,
        binding_context: BindingContext,
    ) -> RelationalBinding:
        """Eagerly validate structure and register one lazy-scanning relation."""

        operation = binding_context.operation
        operation.checkpoint()
        if resolved.provider_key != self.provider_key:
            raise _binding_error(
                "source_bind_failed",
                "The Parquet adapter received a different resolved provider.",
                alias=resolved.alias,
                suggestion="Resolve the source with the selected Parquet adapter.",
            )
        _validate_observational(resolved, operation)
        members = _member_paths(resolved)
        absolute_paths = [absolute_path for _relative_path, absolute_path in members]
        partitioning = _semantic_option(resolved, "partitioning")
        union_by_name = _semantic_option(resolved, "union_by_name")
        if partitioning not in {"none", "hive"} or not isinstance(union_by_name, bool):
            raise _binding_error(
                "source_bind_failed",
                "Resolved Parquet options are invalid.",
                alias=resolved.alias,
                suggestion="Resolve the source again before binding.",
            )
        hive_partitioning = partitioning == "hive"

        def register(connection_object: object) -> None:
            connection = cast(duckdb.DuckDBPyConnection, connection_object)
            _validate_observational(resolved, operation)
            if not union_by_name and len(absolute_paths) > 1:
                first_signature = _schema_signature(
                    connection,
                    absolute_paths[0],
                    hive_partitioning=hive_partitioning,
                )
                for member_path in absolute_paths[1:]:
                    operation.checkpoint()
                    if (
                        _schema_signature(
                            connection,
                            member_path,
                            hive_partitioning=hive_partitioning,
                        )
                        != first_signature
                    ):
                        raise _binding_error(
                            "source.parquet_schema_mismatch",
                            "Parquet dataset member schemas do not match.",
                            alias=resolved.alias,
                            suggestion="Correct the schemas or set union_by_name=true.",
                        )
            relation = connection.read_parquet(
                absolute_paths,
                hive_partitioning=hive_partitioning,
                union_by_name=union_by_name,
            )
            tuple(zip(relation.columns, relation.types, strict=True))
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
            raise _binding_error(
                "source_bind_failed",
                "Failed to bind Parquet source.",
                alias=resolved.alias,
                suggestion="Check that every resolved member is readable Parquet.",
            ) from exc
        binding = _ParquetRelationalBinding(
            engine_session,
            resolved,
            registration_token,
            members,
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


def _create_parquet_adapter(
    *,
    activation_facts: ProviderActivationFacts,
) -> ParquetSourceAdapter:
    """Construct the selected Parquet adapter for the lazy factory."""

    return ParquetSourceAdapter(activation_facts=activation_facts)
