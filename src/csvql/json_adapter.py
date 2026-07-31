"""Shared JSON and NDJSON provider resolution and relational binding."""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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
from csvql.json_schema import (
    JSONSchemaHint,
    JSONSchemaHintError,
    parse_json_schema_hint,
)
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    DiagnosticCode,
    DiagnosticEvidence,
    DiagnosticStage,
    FrozenJSONObject,
    FrozenSourceOptions,
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
    freeze_source_options,
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

_JSON_DEPENDENCY_KEY = "duckdb.extension.json"
_JSON_COMPRESSION: Literal["uncompressed"] = "uncompressed"
_HASH_CHUNK_BYTES = 1024 * 1024
_MAXIMUM_OBJECT_SIZE = 16_777_216
_STRUCTURAL_SAMPLE_ROWS = 2_048
_UTF8_PREFIX_BYTES = 64 * 1024
_SUPPORTED_PROVIDERS = frozenset({"json", "ndjson"})
_UNQUOTED_PATH_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class _JSONSnapshot:
    observed: ObservedFileFacts
    modified_at: str
    device: int
    inode: int


def _resolution_error(
    provider_key: str,
    code: str,
    message: str,
    *,
    alias: str,
    suggestion: str,
) -> SourceResolutionError:
    return SourceResolutionError(
        cast(SourceErrorCode, code),
        message,
        kind=provider_key,
        alias=alias,
        suggestion=suggestion,
    )


def _binding_error(
    provider_key: str,
    code: str,
    message: str,
    *,
    alias: str,
    suggestion: str,
) -> SourceBindingError:
    return SourceBindingError(
        cast(SourceErrorCode, code),
        message,
        kind=provider_key,
        alias=alias,
        suggestion=suggestion,
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
        raise _resolution_error(
            selected.provider_key,
            ("source.json_invalid" if selected.provider_key == "json" else "source.ndjson_invalid"),
            "JSON source is missing or unreadable.",
            alias=request.alias,
            suggestion="Restore the source or update its configured locator.",
        ) from exc
    if stat.S_ISLNK(locator_stat.st_mode) or not stat.S_ISREG(locator_stat.st_mode):
        raise _resolution_error(
            selected.provider_key,
            "source.json_record_shape_invalid",
            "JSON sources must be regular nonsymlink files.",
            alias=request.alias,
            suggestion="Choose a readable local JSON or NDJSON file.",
        )
    return canonical


def _snapshot_file(
    path: Path,
    *,
    provider_key: str,
    alias: str,
    operation: OperationContext,
) -> _JSONSnapshot:
    operation.checkpoint()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as source_file:
            file_stat = os.fstat(source_file.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise OSError("not a regular file")
            prefix = source_file.read(min(file_stat.st_size, _UTF8_PREFIX_BYTES))
    except OSError as exc:
        raise _resolution_error(
            provider_key,
            ("source.json_invalid" if provider_key == "json" else "source.ndjson_invalid"),
            "JSON source is missing, unreadable, or not a regular file.",
            alias=alias,
            suggestion="Choose a readable local JSON or NDJSON file.",
        ) from exc
    operation.checkpoint()
    try:
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        decoder.decode(prefix, final=file_stat.st_size <= len(prefix))
    except UnicodeDecodeError as exc:
        raise _resolution_error(
            provider_key,
            ("source.json_invalid" if provider_key == "json" else "source.ndjson_invalid"),
            "JSON source is not valid UTF-8.",
            alias=alias,
            suggestion="Encode the source as UTF-8 and resubmit it.",
        ) from exc
    return _JSONSnapshot(
        observed=ObservedFileFacts(
            size_bytes=file_stat.st_size,
            modified_time_ns=file_stat.st_mtime_ns,
        ),
        modified_at=datetime.fromtimestamp(
            file_stat.st_mtime_ns / 1_000_000_000,
            tz=UTC,
        ).isoformat(),
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
    )


def _normalized_options(selected: SelectedSource) -> FrozenSourceOptions:
    options = selected.options_as_python()
    sample_size = options.get("sample_size")
    maximum_depth = options.get("maximum_depth")
    if (
        not isinstance(sample_size, int)
        or isinstance(sample_size, bool)
        or sample_size <= 0
        or not isinstance(maximum_depth, int)
        or isinstance(maximum_depth, bool)
        or maximum_depth <= 0
    ):
        raise _resolution_error(
            selected.provider_key,
            "source.json_schema_invalid",
            "JSON inference bounds must be positive integers.",
            alias=selected.request.alias,
            suggestion="Use positive sample_size and maximum_depth values.",
        )
    schema_value = options.get("schema")
    try:
        schema = None if schema_value is None else parse_json_schema_hint(schema_value)
    except JSONSchemaHintError as exc:
        raise _resolution_error(
            selected.provider_key,
            "source.json_schema_invalid",
            "JSON schema hint is invalid.",
            alias=selected.request.alias,
            suggestion="Use the bounded LocalQL JSON scalar schema grammar.",
        ) from exc

    record_path_value = options.get("record_path")
    if record_path_value is not None:
        try:
            record_path = _normalize_record_path(record_path_value)
        except ValueError as exc:
            raise _resolution_error(
                selected.provider_key,
                "source.json_record_path_invalid",
                "JSON record path is outside the lookup-only subset.",
                alias=selected.request.alias,
                suggestion="Use '$' followed only by fixed key and array-index lookups.",
            ) from exc
        explicit_option_keys = {key for key, _value in selected.request.options}
        if schema is None or explicit_option_keys.intersection({"sample_size", "maximum_depth"}):
            raise _resolution_error(
                selected.provider_key,
                "source.json_schema_invalid",
                "JSON record paths require a schema and cannot use inference options.",
                alias=selected.request.alias,
                suggestion="Provide schema and remove sample_size and maximum_depth.",
            )
        return freeze_source_options(
            (
                ("record_path", record_path),
                ("schema", schema.as_duckdb_columns()),
            )
        )
    if schema is not None:
        return freeze_source_options((("schema", schema.as_duckdb_columns()),))
    return freeze_source_options(
        (
            ("maximum_depth", maximum_depth),
            ("sample_size", sample_size),
        )
    )


def _normalize_record_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("$"):
        raise ValueError("JSON record paths must start with '$'.")
    position = 1
    normalized = "$"
    decoder = json.JSONDecoder()
    while position < len(value):
        if value[position] == ".":
            position += 1
            if position >= len(value) or value[position] == ".":
                raise ValueError("JSON record path key lookup is malformed.")
            if value[position] == '"':
                try:
                    key, consumed = decoder.raw_decode(value[position:])
                except json.JSONDecodeError as exc:
                    raise ValueError("JSON record path quoted key is invalid.") from exc
                if not isinstance(key, str):
                    raise ValueError("JSON record path keys must be strings.")
                position += consumed
            else:
                match = _UNQUOTED_PATH_KEY.match(value, position)
                if match is None:
                    raise ValueError("JSON record path key lookup is invalid.")
                key = match.group(0)
                position = match.end()
            normalized += "." + json.dumps(
                key,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            continue
        if value[position] == "[":
            closing = value.find("]", position + 1)
            if closing < 0:
                raise ValueError("JSON record path index is unterminated.")
            index_text = value[position + 1 : closing]
            if (
                not index_text.isascii()
                or not index_text.isdigit()
                or (len(index_text) > 1 and index_text.startswith("0"))
            ):
                raise ValueError("JSON record path requires a non-negative fixed index.")
            normalized += f"[{int(index_text)}]"
            position = closing + 1
            continue
        raise ValueError("JSON record path contains unsupported syntax.")
    return normalized


def _provider_facts(
    provider_key: str,
    snapshot: _JSONSnapshot,
    semantic_options: FrozenSourceOptions,
) -> FrozenJSONObject:
    semantic_option_values = dict(semantic_options)
    semantic_option_keys = set(semantic_option_values)
    facts: dict[str, object] = {
        "dependency_key": _JSON_DEPENDENCY_KEY,
        "device": snapshot.device,
        "fingerprint_version": 1,
        "format": "array" if provider_key == "json" else "newline_delimited",
        "inode": snapshot.inode,
        "compression": _JSON_COMPRESSION,
        "maximum_object_size": _MAXIMUM_OBJECT_SIZE,
        "modified_at": snapshot.modified_at,
        "schema_mode": (
            "record_path"
            if "record_path" in semantic_option_keys
            else ("explicit" if "schema" in semantic_option_keys else "inferred")
        ),
        "structural_sample_rows": _STRUCTURAL_SAMPLE_ROWS,
    }
    if "schema" not in semantic_option_keys:
        facts["maximum_depth"] = semantic_option_values["maximum_depth"]
        facts["sample_size"] = semantic_option_values["sample_size"]
    value = freeze_source_value(facts)
    return cast(FrozenJSONObject, value)


def _schema_hint(resolved: ResolvedSource) -> JSONSchemaHint | None:
    value = dict(resolved.semantic_options).get("schema")
    if value is None:
        return None
    if not isinstance(value, FrozenJSONObject):
        raise ValueError("Resolved JSON schema facts are invalid.")
    return parse_json_schema_hint(dict(value.items))


def _sql_literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("DuckDB string values cannot contain NUL.")
    return "'" + value.replace("'", "''") + "'"


def _record_path_query_sql(
    resolved: ResolvedSource,
    *,
    record_path: str,
    schema: JSONSchemaHint,
    sample_rows: int | None,
) -> str:
    root_format = "unstructured" if resolved.provider_key == "json" else "newline_delimited"
    sampled_items = ""
    item_source = "raw_items"
    order_clause = "ORDER BY root_ordinal, item_ordinal"
    if sample_rows is not None:
        sampled_items = f"""
        ,
        sampled_items AS MATERIALIZED (
            SELECT root_ordinal, item_ordinal, value
            FROM raw_items
            ORDER BY root_ordinal, item_ordinal
            LIMIT {sample_rows}
        )
        """
        item_source = "sampled_items"
        order_clause = ""
    return f"""
        WITH roots AS (
            SELECT
                row_number() OVER () AS root_ordinal,
                json_extract(json, {_sql_literal(record_path)}) AS selected
            FROM read_json_objects(
                {_sql_literal(resolved.canonical_locator)},
                format={_sql_literal(root_format)},
                compression={_sql_literal(_JSON_COMPRESSION)},
                maximum_object_size={_MAXIMUM_OBJECT_SIZE},
                ignore_errors=false
            )
        ),
        validated_roots AS (
            SELECT
                root_ordinal,
                CASE
                    WHEN selected IS NULL
                        OR json_type(selected) IS NULL
                        OR json_type(selected) = 'NULL'
                        THEN CAST(error('source.json_record_path_missing') AS JSON)
                    WHEN json_type(selected) <> 'ARRAY'
                        THEN CAST(error('source.json_record_path_not_array') AS JSON)
                    ELSE selected
                END AS selected
            FROM roots
        ),
        raw_items AS (
            SELECT
                root_ordinal,
                CAST(entry.key AS UBIGINT) AS item_ordinal,
                entry.value AS value
            FROM validated_roots, LATERAL json_each(selected) AS entry
        )
        {sampled_items}
        SELECT transformed.*
        FROM (
            SELECT
                root_ordinal,
                item_ordinal,
                json_transform_strict(
                    CASE
                        WHEN json_type(value) = 'OBJECT'
                            THEN value
                        ELSE CAST(
                            error('source.json_record_not_object')
                            AS JSON
                        )
                    END,
                    {_sql_literal(schema.structure_json)}
                ) AS transformed
            FROM {item_source}
        ) AS ordered_rows
        {order_clause}
    """


def _record_path_view_sql(
    resolved: ResolvedSource,
    *,
    record_path: str,
    schema: JSONSchemaHint,
) -> str:
    query = _record_path_query_sql(
        resolved,
        record_path=record_path,
        schema=schema,
        sample_rows=None,
    )
    return f"CREATE VIEW {quote_identifier(resolved.alias)} AS\n{query}"


def _inference_bound(
    resolved: ResolvedSource,
    semantic_options: Mapping[str, object],
    *,
    key: str,
    default: int,
) -> int:
    value = semantic_options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _binding_error(
            resolved.provider_key,
            "source_bind_failed",
            "Resolved JSON inference options are invalid.",
            alias=resolved.alias,
            suggestion="Resolve the JSON source again before binding.",
        )
    return value


def _duckdb_binding_error(
    resolved: ResolvedSource,
    error: duckdb.Error,
    *,
    schema: JSONSchemaHint | None,
) -> SourceBindingError:
    detail = str(error).casefold()
    for code in (
        "source.json_record_path_missing",
        "source.json_record_path_not_array",
        "source.json_record_not_object",
    ):
        if code in detail:
            return _binding_error(
                resolved.provider_key,
                code,
                "JSON record-path selection has an invalid shape.",
                alias=resolved.alias,
                suggestion="Correct the record path or the selected JSON records.",
            )
    if any(
        marker in detail
        for marker in (
            "expected records",
            "expected top-level json array",
            "json_read expected records",
        )
    ):
        return _binding_error(
            resolved.provider_key,
            "source.json_record_shape_invalid",
            "JSON source does not contain object records in the selected format.",
            alias=resolved.alias,
            suggestion="Use object records or select the matching JSON source type.",
        )
    if schema is not None and any(
        marker in detail
        for marker in (
            "failed to cast",
            "failed to transform",
            "could not convert",
            "conversion error",
        )
    ):
        return _binding_error(
            resolved.provider_key,
            "source.json_schema_cast_failed",
            "JSON record values do not satisfy the declared schema.",
            alias=resolved.alias,
            suggestion="Correct the source values or the explicit schema hint.",
        )
    code = "source.json_invalid" if resolved.provider_key == "json" else "source.ndjson_invalid"
    return _binding_error(
        resolved.provider_key,
        code,
        f"{resolved.provider_key.upper()} source is structurally invalid.",
        alias=resolved.alias,
        suggestion=f"Choose valid {resolved.provider_key.upper()} object records.",
    )


def _observed_facts(resolved: ResolvedSource) -> ObservedFileFacts:
    facts = dict(resolved.provider_facts.items)
    size_bytes = facts["size_bytes"]
    modified_time_ns = facts["modified_time_ns"]
    if not isinstance(size_bytes, int) or not isinstance(modified_time_ns, int):
        raise ValueError("Resolved JSON observation facts are invalid.")
    return ObservedFileFacts(size_bytes, modified_time_ns)


def _validate_observational(
    resolved: ResolvedSource,
    operation: OperationContext,
) -> None:
    operation.checkpoint()
    try:
        current = Path(resolved.canonical_locator).lstat()
    except OSError as exc:
        raise SourceIdentityError(
            "source_changed",
            "JSON source is no longer readable.",
            kind=resolved.provider_key,
            alias=resolved.alias,
            suggestion="Resubmit the source before executing the query.",
        ) from exc
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        raise SourceIdentityError(
            "source_changed",
            "JSON source is no longer a regular file.",
            kind=resolved.provider_key,
            alias=resolved.alias,
            suggestion="Resubmit the source before executing the query.",
        )
    if ObservedFileFacts(current.st_size, current.st_mtime_ns) != _observed_facts(resolved):
        raise SourceIdentityError(
            "source_changed",
            "JSON source changed after resolution.",
            kind=resolved.provider_key,
            alias=resolved.alias,
            suggestion="Resubmit the source before executing the query.",
        )


def _exact_identity_digest(
    resolved: ResolvedSource,
    operation: OperationContext,
) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(resolved.canonical_locator, flags)
    with os.fdopen(descriptor, "rb", closefd=True) as source_file:
        opened_stat = os.fstat(source_file.fileno())
        if not stat.S_ISREG(opened_stat.st_mode) or ObservedFileFacts(
            opened_stat.st_size, opened_stat.st_mtime_ns
        ) != _observed_facts(resolved):
            raise OSError("JSON source changed before exact validation.")
        while True:
            operation.checkpoint()
            chunk = source_file.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
        final_stat = os.fstat(source_file.fileno())
    if (
        final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
    ):
        raise OSError("JSON source changed during exact validation.")
    operation.checkpoint()
    return digest.hexdigest()


@dataclass(slots=True)
class _JSONRelationalBinding:
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
        """Revalidate one JSON-family source without weakening identity."""

        self._engine_session.assert_session_access()
        context.checkpoint()
        if self._closed:
            raise SourceIdentityError(
                "source_changed",
                "JSON source binding is closed.",
                kind=self._resolved_source.provider_key,
                alias=self.alias,
                suggestion="Prepare the source again before executing a query.",
            )
        try:
            _validate_observational(self._resolved_source, context)
        except SourceIdentityError:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.CHANGED,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_CHANGED,
                    stage=DiagnosticStage.IDENTITY,
                    message="JSON source changed after resolution.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction(
                        "resubmit_source",
                        (self._resolved_source.provider_key,),
                    ),
                ),
            )
        if requirement.strength is IdentityStrength.STRONG:
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.UNAVAILABLE,
                required_strength=requirement.strength,
                diagnostic=SourceDiagnostic(
                    code=DiagnosticCode.SOURCE_IDENTITY_UNAVAILABLE,
                    stage=DiagnosticStage.IDENTITY,
                    message="Requested JSON identity evidence is unavailable.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction(
                        "choose_observational_or_resubmit",
                        (self._resolved_source.provider_key,),
                    ),
                ),
            )
        if requirement.strength is IdentityStrength.EXACT:
            try:
                evidence_digest = _exact_identity_digest(
                    self._resolved_source,
                    context,
                )
            except OSError:
                return IdentityValidationResult(
                    alias=self.alias,
                    status=IdentityValidationStatus.INVALID,
                    required_strength=requirement.strength,
                    diagnostic=SourceDiagnostic(
                        code=DiagnosticCode.SOURCE_IDENTITY_INVALID,
                        stage=DiagnosticStage.IDENTITY,
                        message="Exact JSON identity evidence could not be read safely.",
                        safe_source_reference=self._resolved_source.requested_locator,
                        required_action=RequiredAction(
                            "restore_or_resubmit",
                            (self._resolved_source.provider_key,),
                        ),
                    ),
                )
            return IdentityValidationResult(
                alias=self.alias,
                status=IdentityValidationStatus.CONFIRMED,
                required_strength=requirement.strength,
                confirmed_strength=IdentityStrength.EXACT,
                evidence_digest=evidence_digest,
            )
        return IdentityValidationResult(
            alias=self.alias,
            status=IdentityValidationStatus.CONFIRMED,
            required_strength=requirement.strength,
            confirmed_strength=IdentityStrength.OBSERVATIONAL,
        )

    def close(self, context: OperationContext) -> None:
        """Unregister this binding without closing the engine session."""

        if self._closed:
            return
        self._engine_session.assert_session_access()
        if self._engine_session.has_active_execution:
            raise _binding_error(
                self._resolved_source.provider_key,
                "source_bind_failed",
                "JSON source binding is still in use.",
                alias=self.alias,
                suggestion="Wait for the active query to reach a terminal state.",
            )
        if self._engine_session.is_tainted:
            raise EngineSessionTaintedError(
                "engine_session_tainted",
                "JSON source binding cannot be unregistered from a tainted session.",
                kind=self._resolved_source.provider_key,
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
                "Failed to clean up a JSON source binding.",
                kind=self._resolved_source.provider_key,
                alias=self.alias,
                suggestion="Close the LocalQL operation and try again.",
            ) from exc
        self._closed = True


class JSONSourceAdapter:
    """Shared provider implementation configured for JSON or NDJSON."""

    def __init__(
        self,
        *,
        provider_key: str,
        activation_facts: ProviderActivationFacts,
    ) -> None:
        if provider_key not in _SUPPORTED_PROVIDERS:
            raise ValueError("JSON adapter provider key is unsupported.")
        if activation_facts.provider_key != provider_key:
            raise ValueError("JSON activation facts have the wrong provider key.")
        self.provider_key = provider_key
        self._activation_facts = activation_facts
        self.implementation_version = activation_facts.adapter_implementation_version

    def resolve(
        self,
        selected: SelectedSource,
        operation: OperationContext,
    ) -> ResolvedSource:
        """Resolve one selected JSON-family file into immutable facts."""

        operation.checkpoint()
        if selected.provider_key != self.provider_key or selected.source_kind != self.provider_key:
            raise _resolution_error(
                self.provider_key,
                ("source.json_invalid" if self.provider_key == "json" else "source.ndjson_invalid"),
                "The JSON adapter received a different source kind.",
                alias=selected.request.alias,
                suggestion="Select the adapter matching the requested source kind.",
            )
        path = _canonical_file(selected)
        semantic_options = _normalized_options(selected)
        snapshot = _snapshot_file(
            path,
            provider_key=self.provider_key,
            alias=selected.request.alias,
            operation=operation,
        )
        provider_facts = _provider_facts(
            self.provider_key,
            snapshot,
            semantic_options,
        )
        provider_facts = FrozenJSONObject(
            tuple(
                sorted(
                    (
                        *provider_facts.items,
                        ("modified_time_ns", snapshot.observed.modified_time_ns),
                        ("size_bytes", snapshot.observed.size_bytes),
                    ),
                    key=lambda item: item[0],
                )
            )
        )
        identity = build_source_identity(
            provider_key=self.provider_key,
            source_kind=selected.source_kind,
            canonical_locator=str(path),
            semantic_options=semantic_options,
            provider_interpretation_version=(selected.descriptor.provider_interpretation_version),
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
            semantic_options=semantic_options,
            operational_options=(),
            identity=identity,
            selection_reason=selected.selection_reason,
            adapter_implementation_version=self.implementation_version,
            duckdb_version=self._activation_facts.duckdb_version,
            dependency_versions=self._activation_facts.dependency_versions,
            provider_facts=provider_facts,
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
                    "utf8_prefix",
                    "valid",
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
        """Bind one explicit JSON record format as a lazy DuckDB relation."""

        operation = binding_context.operation
        operation.checkpoint()
        if resolved.provider_key != self.provider_key:
            raise _binding_error(
                self.provider_key,
                "source_bind_failed",
                "The JSON adapter received a different resolved provider.",
                alias=resolved.alias,
                suggestion="Resolve the source with the selected JSON adapter.",
            )
        _validate_observational(resolved, operation)
        semantic_options = dict(resolved.semantic_options)
        sample_size = _inference_bound(
            resolved,
            semantic_options,
            key="sample_size",
            default=20_480,
        )
        maximum_depth = _inference_bound(
            resolved,
            semantic_options,
            key="maximum_depth",
            default=10,
        )
        record_path = semantic_options.get("record_path")
        schema = _schema_hint(resolved)
        file_format: Literal["array", "newline_delimited"] = (
            "array" if self.provider_key == "json" else "newline_delimited"
        )

        def register(connection_object: object) -> None:
            connection = cast(duckdb.DuckDBPyConnection, connection_object)
            connection.execute("LOAD json")
            _validate_observational(resolved, operation)
            try:
                if isinstance(record_path, str):
                    if schema is None:
                        raise ValueError("Resolved JSON record-path schema is missing.")
                    connection.execute(
                        _record_path_view_sql(
                            resolved,
                            record_path=record_path,
                            schema=schema,
                        )
                    )
                    connection.execute(
                        _record_path_query_sql(
                            resolved,
                            record_path=record_path,
                            schema=schema,
                            sample_rows=_STRUCTURAL_SAMPLE_ROWS,
                        )
                    ).fetchall()
                else:
                    relation = connection.read_json(
                        resolved.canonical_locator,
                        columns=(None if schema is None else schema.as_duckdb_columns()),
                        sample_size=sample_size,
                        maximum_depth=maximum_depth,
                        records="true",
                        format=file_format,
                        # DuckDB 1.5.4 accepts "uncompressed"; its Python stub
                        # omits that runtime enum spelling.
                        compression=_JSON_COMPRESSION,  # type: ignore[arg-type]
                        maximum_object_size=_MAXIMUM_OBJECT_SIZE,
                        ignore_errors=False,
                        hive_partitioning=False,
                    )
                    tuple(zip(relation.columns, relation.types, strict=True))
                    relation.create_view(resolved.alias, replace=False)
                    connection.execute(
                        f"""
                        SELECT *
                        FROM {quote_identifier(resolved.alias)}
                        LIMIT {_STRUCTURAL_SAMPLE_ROWS}
                        """
                    ).fetchall()
            except duckdb.Error as exc:
                connection.execute(f"DROP VIEW IF EXISTS {quote_identifier(resolved.alias)}")
                raise _duckdb_binding_error(
                    resolved,
                    exc,
                    schema=schema,
                ) from exc

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
                self.provider_key,
                (
                    "source.json_schema_cast_failed"
                    if schema is not None
                    else (
                        "source.json_invalid"
                        if self.provider_key == "json"
                        else "source.ndjson_invalid"
                    )
                ),
                f"Failed to bind {self.provider_key.upper()} source.",
                alias=resolved.alias,
                suggestion=f"Choose valid {self.provider_key.upper()} object records.",
            ) from exc
        binding = _JSONRelationalBinding(
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


def _create_json_adapter(
    *,
    activation_facts: ProviderActivationFacts,
) -> JSONSourceAdapter:
    """Construct the selected JSON adapter for lazy activation."""

    return JSONSourceAdapter(
        provider_key="json",
        activation_facts=activation_facts,
    )


def _create_ndjson_adapter(
    *,
    activation_facts: ProviderActivationFacts,
) -> JSONSourceAdapter:
    """Construct the selected NDJSON adapter for lazy activation."""

    return JSONSourceAdapter(
        provider_key="ndjson",
        activation_facts=activation_facts,
    )
