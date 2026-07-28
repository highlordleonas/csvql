"""Excel XLSX source resolution and relational binding."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import duckdb

from csvql.adapter_factory import ProviderActivationFacts
from csvql.excel_workbook import (
    ExcelWorkbookError,
    WorkbookSelection,
    inspect_excel_workbook,
)
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

_PROVIDER_KEY = "excel"
_DEPENDENCY_KEY = "duckdb.extension.excel"
_HASH_CHUNK_BYTES = 1024 * 1024
_READ_XLSX_SQL = """
    SELECT *
    FROM read_xlsx(
        ?,
        header=?,
        stop_at_empty=?,
        all_varchar=?,
        range=?,
        ignore_errors=?,
        sheet=?,
        empty_as_varchar=?
    )
"""


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


def _canonical_file(selected: SelectedSource) -> tuple[Path, os.stat_result]:
    request = selected.request
    candidate = Path(request.locator).expanduser()
    if not candidate.is_absolute():
        candidate = (request.anchor or Path.cwd()) / candidate
    canonical = Path(os.path.abspath(os.path.normpath(os.fspath(candidate))))
    suffix = canonical.suffix.casefold()
    if suffix != ".xlsx" and not (selected.selection_reason == "explicit_type" and suffix == ""):
        raise _resolution_error(
            "source.excel_invalid",
            "Excel sources must be .xlsx files or explicitly typed extensionless files.",
            alias=request.alias,
            suggestion="Choose a .xlsx workbook or explicitly type an extensionless source.",
        )
    try:
        file_stat = canonical.lstat()
    except (OSError, ValueError) as exc:
        raise _resolution_error(
            "source.excel_invalid",
            "Excel source is missing or unreadable.",
            alias=request.alias,
            suggestion="Restore the workbook or update its configured locator.",
        ) from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise _resolution_error(
            "source.excel_invalid",
            "Excel source must be a nonsymlink regular local file.",
            alias=request.alias,
            suggestion="Choose the canonical path to a regular .xlsx file.",
        )
    return canonical, file_stat


def _normalize_options(
    selected: SelectedSource,
) -> tuple[bool, str | None, str | None, bool, str]:
    options = selected.options_as_python()
    header = options.get("header")
    requested_range = options.get("range")
    requested_sheet = options.get("sheet")
    stop_at_empty = options.get("stop_at_empty")
    type_mode = options.get("type_mode")
    if not isinstance(header, bool) or not isinstance(stop_at_empty, bool):
        raise _resolution_error(
            "source.excel_invalid",
            "Excel header and stop_at_empty options must be booleans.",
            alias=selected.request.alias,
            suggestion="Use explicit true or false values for Excel Boolean options.",
        )
    if requested_range is not None and (
        not isinstance(requested_range, str) or not requested_range
    ):
        raise _resolution_error(
            "source.excel_range_invalid",
            "Excel range must be a non-empty string when supplied.",
            alias=selected.request.alias,
            suggestion="Use one finite A1 rectangle such as A1:D100.",
        )
    if requested_sheet is not None and (
        not isinstance(requested_sheet, str) or not requested_sheet
    ):
        raise _resolution_error(
            "source.excel_sheet_missing",
            "Excel sheet must be a non-empty exact worksheet name.",
            alias=selected.request.alias,
            suggestion="Choose one exact worksheet name.",
        )
    if type_mode not in {"text", "infer"}:
        raise _resolution_error(
            "source.excel_invalid",
            "Excel type_mode must be explicitly 'text' or 'infer'.",
            alias=selected.request.alias,
            suggestion="Use type_mode=text or type_mode=infer.",
        )
    return header, requested_range, requested_sheet, stop_at_empty, type_mode


def _semantic_options(
    selection: WorkbookSelection,
    *,
    header: bool,
    stop_at_empty: bool,
    type_mode: str,
) -> tuple[tuple[str, FrozenJSONValue], ...]:
    return freeze_source_options(
        (
            ("header", header),
            ("range", selection.resolved_range),
            ("sheet", selection.selected_sheet.name),
            ("stop_at_empty", stop_at_empty),
            ("type_mode", type_mode),
        )
    )


def _modified_at(modified_time_ns: int) -> str:
    return datetime.fromtimestamp(
        modified_time_ns / 1_000_000_000,
        tz=UTC,
    ).isoformat()


def _provider_facts(selection: WorkbookSelection) -> FrozenJSONObject:
    value = freeze_source_value(
        {
            "device": selection.device,
            "fingerprint_version": 1,
            "inode": selection.inode,
            "metadata_bytes_read": selection.metadata_bytes_read,
            "modified_at": _modified_at(selection.modified_time_ns),
            "modified_time_ns": selection.modified_time_ns,
            "range_source": selection.range_source,
            "resolved_range": selection.resolved_range,
            "selected_relationship_id": selection.selected_sheet.relationship_id,
            "selected_relationship_target": (selection.selected_sheet.relationship_target),
            "selected_sheet": selection.selected_sheet.name,
            "selected_sheet_index": selection.selected_sheet.index,
            "sheet_count": selection.sheet_count,
            "sheet_source": selection.sheet_source,
            "size_bytes": selection.size_bytes,
            "worksheet_part": selection.selected_sheet.worksheet_part,
            "zip_entry_count": selection.zip_entry_count,
        }
    )
    if not isinstance(value, FrozenJSONObject):
        raise AssertionError("Excel provider facts must be an immutable JSON object.")
    return value


def _structural_identity_evidence(selection: WorkbookSelection) -> str:
    material = {
        "relationship_id": selection.selected_sheet.relationship_id,
        "relationship_target": selection.selected_sheet.relationship_target,
        "sheet_index": selection.selected_sheet.index,
        "worksheet_part": selection.selected_sheet.worksheet_part,
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _thaw(value: FrozenJSONValue) -> object:
    if isinstance(value, FrozenJSONArray):
        return [_thaw(item) for item in value.values]
    if isinstance(value, FrozenJSONObject):
        return {key: _thaw(item) for key, item in value.items}
    return value


def _facts(resolved: ResolvedSource) -> dict[str, object]:
    return {key: _thaw(value) for key, value in resolved.provider_facts.items}


def _semantic_value(resolved: ResolvedSource, key: str) -> object:
    value = dict(resolved.semantic_options).get(key)
    return None if value is None else _thaw(value)


def _current_selection(
    resolved: ResolvedSource,
    operation: OperationContext,
) -> WorkbookSelection:
    facts = _facts(resolved)
    selected_sheet = _semantic_value(resolved, "sheet")
    selected_range = _semantic_value(resolved, "range")
    if not isinstance(selected_sheet, str) or not isinstance(selected_range, str):
        raise SourceIdentityError(
            "source_changed",
            "Recorded Excel sheet or range facts are invalid.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Resolve the Excel source again.",
        )
    requested_sheet = None if facts.get("sheet_source") == "workbook_order" else selected_sheet
    requested_range = None if facts.get("range_source") == "worksheet_dimension" else selected_range
    path = Path(resolved.canonical_locator)
    try:
        current_stat = path.lstat()
    except OSError as exc:
        raise SourceIdentityError(
            "source_changed",
            "Excel source is no longer readable.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Submit the operation again with the current workbook.",
        ) from exc
    if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISREG(current_stat.st_mode):
        raise SourceIdentityError(
            "source_changed",
            "Excel source is no longer a nonsymlink regular file.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Submit the operation again with the current workbook.",
        )
    try:
        return inspect_excel_workbook(
            path,
            requested_sheet=requested_sheet,
            requested_range=requested_range,
            operation=operation,
            expected_stat=current_stat,
        )
    except ExcelWorkbookError as exc:
        raise SourceIdentityError(
            "source_changed",
            "Excel workbook structure changed after resolution.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Submit the operation again with the current workbook.",
        ) from exc


def _validate_observational(
    resolved: ResolvedSource,
    operation: OperationContext,
) -> None:
    current = _current_selection(resolved, operation)
    recorded = _facts(resolved)
    current_material = {
        "device": current.device,
        "inode": current.inode,
        "modified_time_ns": current.modified_time_ns,
        "range_source": current.range_source,
        "resolved_range": current.resolved_range,
        "selected_relationship_id": current.selected_sheet.relationship_id,
        "selected_relationship_target": current.selected_sheet.relationship_target,
        "selected_sheet": current.selected_sheet.name,
        "selected_sheet_index": current.selected_sheet.index,
        "sheet_count": current.sheet_count,
        "sheet_source": current.sheet_source,
        "size_bytes": current.size_bytes,
        "worksheet_part": current.selected_sheet.worksheet_part,
        "zip_entry_count": current.zip_entry_count,
    }
    if any(recorded.get(key) != value for key, value in current_material.items()):
        raise SourceIdentityError(
            "source_changed",
            "Excel workbook changed after resolution.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Submit the operation again with the current workbook.",
        )


def _exact_identity_digest(
    resolved: ResolvedSource,
    operation: OperationContext,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    facts = _facts(resolved)
    expected_stat = (
        facts.get("device"),
        facts.get("inode"),
        facts.get("size_bytes"),
        facts.get("modified_time_ns"),
    )
    try:
        descriptor = os.open(resolved.canonical_locator, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as source_file:
            descriptor = -1
            file_stat = os.fstat(source_file.fileno())
            if not stat.S_ISREG(file_stat.st_mode) or expected_stat != (
                file_stat.st_dev,
                file_stat.st_ino,
                file_stat.st_size,
                file_stat.st_mtime_ns,
            ):
                raise OSError("not a regular file")
            while True:
                operation.checkpoint()
                chunk = source_file.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
            final_stat = os.fstat(source_file.fileno())
            if (
                file_stat.st_dev != final_stat.st_dev
                or file_stat.st_ino != final_stat.st_ino
                or file_stat.st_size != final_stat.st_size
                or file_stat.st_mtime_ns != final_stat.st_mtime_ns
            ):
                raise OSError("file changed during exact validation")
    except OSError as exc:
        raise SourceIdentityError(
            "source_changed",
            "Excel source became unreadable during exact validation.",
            kind=_PROVIDER_KEY,
            alias=resolved.alias,
            suggestion="Submit the operation again before requesting exact identity.",
        ) from exc
    finally:
        if "descriptor" in locals() and descriptor >= 0:
            os.close(descriptor)
    return digest.hexdigest()


@dataclass(slots=True)
class _ExcelRelationalBinding:
    _engine_session: EngineSession
    _resolved_source: ResolvedSource
    _registration_token: object
    runtime_schema: tuple[tuple[str, str], ...]
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
        """Revalidate one workbook at exactly the requested strength."""

        self._engine_session.assert_session_access()
        context.checkpoint()
        if self._closed:
            raise SourceIdentityError(
                "source_changed",
                "Excel source binding is closed.",
                kind=_PROVIDER_KEY,
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
                    message="Excel source changed after resolution.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction(
                        "resubmit_source",
                        (_PROVIDER_KEY,),
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
                    message="Requested Excel identity evidence is unavailable.",
                    safe_source_reference=self._resolved_source.requested_locator,
                    required_action=RequiredAction(
                        "choose_observational_or_resubmit",
                        (_PROVIDER_KEY,),
                    ),
                ),
            )
        if requirement.strength is IdentityStrength.EXACT:
            try:
                evidence_digest = _exact_identity_digest(
                    self._resolved_source,
                    context,
                )
            except SourceIdentityError:
                return IdentityValidationResult(
                    alias=self.alias,
                    status=IdentityValidationStatus.INVALID,
                    required_strength=requirement.strength,
                    diagnostic=SourceDiagnostic(
                        code=DiagnosticCode.SOURCE_IDENTITY_INVALID,
                        stage=DiagnosticStage.IDENTITY,
                        message="Exact Excel identity evidence could not be read safely.",
                        safe_source_reference=self._resolved_source.requested_locator,
                        required_action=RequiredAction(
                            "restore_or_resubmit",
                            (_PROVIDER_KEY,),
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
        """Unregister this workbook relation without unloading the extension."""

        if self._closed:
            return
        self._engine_session.assert_session_access()
        if self._engine_session.has_active_execution:
            raise _binding_error(
                "source_bind_failed",
                "Excel source binding is still in use.",
                alias=self.alias,
                suggestion="Wait for the active query to reach a terminal state.",
            )
        if self._engine_session.is_tainted:
            raise EngineSessionTaintedError(
                "engine_session_tainted",
                "Excel source binding cannot be unregistered from a tainted session.",
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
                "Failed to clean up an Excel source binding.",
                kind=_PROVIDER_KEY,
                alias=self.alias,
                suggestion="Close the LocalQL operation and try again.",
            ) from exc
        self._closed = True


class ExcelSourceAdapter:
    """Lightweight Excel provider activated after deterministic selection."""

    provider_key = _PROVIDER_KEY

    def __init__(self, *, activation_facts: ProviderActivationFacts) -> None:
        if activation_facts.provider_key != self.provider_key:
            raise ValueError("Excel activation facts have the wrong provider key.")
        if _DEPENDENCY_KEY not in dict(activation_facts.dependency_versions):
            raise ValueError("Excel activation facts omit the selected extension version.")
        self._activation_facts = activation_facts
        self.implementation_version = activation_facts.adapter_implementation_version

    def resolve(
        self,
        selected: SelectedSource,
        operation: OperationContext,
    ) -> ResolvedSource:
        """Resolve one XLSX workbook into immutable sheet and range facts."""

        operation.checkpoint()
        if selected.provider_key != self.provider_key or selected.source_kind != "excel":
            raise _resolution_error(
                "source.excel_invalid",
                "The Excel adapter received a different source kind.",
                alias=selected.request.alias,
                suggestion="Select the adapter matching the source kind.",
            )
        header, requested_range, requested_sheet, stop_at_empty, type_mode = _normalize_options(
            selected
        )
        path, file_stat = _canonical_file(selected)
        try:
            selection = inspect_excel_workbook(
                path,
                requested_sheet=requested_sheet,
                requested_range=requested_range,
                operation=operation,
                expected_stat=file_stat,
            )
        except ExcelWorkbookError as exc:
            raise _resolution_error(
                exc.code,
                exc.message,
                alias=selected.request.alias,
                suggestion=exc.suggestion,
            ) from exc
        semantic_options = _semantic_options(
            selection,
            header=header,
            stop_at_empty=stop_at_empty,
            type_mode=type_mode,
        )
        observed = ObservedFileFacts(
            selection.size_bytes,
            selection.modified_time_ns,
        )
        identity = build_source_identity(
            provider_key=self.provider_key,
            source_kind=selected.source_kind,
            canonical_locator=str(path),
            semantic_options=semantic_options,
            provider_interpretation_version=(selected.descriptor.provider_interpretation_version),
            strength=IdentityStrength.OBSERVATIONAL,
            observed_file=observed,
            provider_identity_evidence=_structural_identity_evidence(selection),
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
            provider_facts=_provider_facts(selection),
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
                    "workbook_metadata",
                    "bounded_and_valid",
                ),
                DiagnosticEvidence(
                    self.provider_key,
                    "worksheet_selection",
                    f"sheet_index_{selection.selected_sheet.index}",
                ),
                DiagnosticEvidence(
                    self.provider_key,
                    "range_selection",
                    selection.range_source,
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
        """Load the pre-authorized extension and register one lazy XLSX relation."""

        operation = binding_context.operation
        operation.checkpoint()
        if resolved.provider_key != self.provider_key:
            raise _binding_error(
                "source_bind_failed",
                "The Excel adapter received a different resolved provider.",
                alias=resolved.alias,
                suggestion="Resolve the source with the selected Excel adapter.",
            )
        _validate_observational(resolved, operation)
        header = _semantic_value(resolved, "header")
        selected_range = _semantic_value(resolved, "range")
        selected_sheet = _semantic_value(resolved, "sheet")
        stop_at_empty = _semantic_value(resolved, "stop_at_empty")
        type_mode = _semantic_value(resolved, "type_mode")
        if (
            not isinstance(header, bool)
            or not isinstance(selected_range, str)
            or not isinstance(selected_sheet, str)
            or not isinstance(stop_at_empty, bool)
            or type_mode not in {"text", "infer"}
        ):
            raise _binding_error(
                "source_bind_failed",
                "Resolved Excel options are invalid.",
                alias=resolved.alias,
                suggestion="Resolve the Excel source again before binding.",
            )
        all_varchar = type_mode == "text"
        engine_session.load_installed_extension(
            _DEPENDENCY_KEY,
            operation=operation,
        )
        runtime_schema: list[tuple[str, str]] = []

        def register(connection_object: object) -> None:
            connection = cast(duckdb.DuckDBPyConnection, connection_object)
            _validate_observational(resolved, operation)
            try:
                relation = connection.sql(
                    _READ_XLSX_SQL,
                    params=[
                        resolved.canonical_locator,
                        header,
                        stop_at_empty,
                        all_varchar,
                        selected_range,
                        False,
                        selected_sheet,
                        False,
                    ],
                )
                runtime_schema.extend(
                    (column, str(column_type))
                    for column, column_type in zip(
                        relation.columns,
                        relation.types,
                        strict=True,
                    )
                )
                relation.create_view(resolved.alias, replace=False)
            except duckdb.Error as exc:
                connection.execute(f"DROP VIEW IF EXISTS {quote_identifier(resolved.alias)}")
                raise _binding_error(
                    (
                        "source.excel_schema_inference_failed"
                        if type_mode == "infer"
                        else "source.excel_invalid"
                    ),
                    "DuckDB could not construct the selected Excel relation.",
                    alias=resolved.alias,
                    suggestion=(
                        "Correct the workbook values or use type_mode=text."
                        if type_mode == "infer"
                        else "Check the selected sheet, range, and workbook contents."
                    ),
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
                "source_bind_failed",
                "Failed to bind Excel source.",
                alias=resolved.alias,
                suggestion="Check that the resolved workbook remains readable.",
            ) from exc
        binding = _ExcelRelationalBinding(
            engine_session,
            resolved,
            registration_token,
            tuple(runtime_schema),
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


def _create_excel_adapter(
    *,
    activation_facts: ProviderActivationFacts,
) -> ExcelSourceAdapter:
    """Construct the selected Excel adapter for the lazy factory."""

    return ExcelSourceAdapter(activation_facts=activation_facts)
