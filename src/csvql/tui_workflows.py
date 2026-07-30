"""Startup workflows for the CSVQL menu TUI."""

import os
import shlex
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

from csvql.atomic_write import write_text_atomic
from csvql.bounded_result import PreviewPolicy
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    CSVQLError,
    ExportError,
    ProjectConfigError,
    SourceError,
    TableMappingError,
)
from csvql.export import ExportFormat, resolve_export_path
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.project_config import (
    CURRENT_VERSION,
    SUPPORTED_VERSION,
    CatalogSourceDefinition,
    ProjectConfigV1,
    ProjectConfigV2,
    ProjectConfigValue,
    ProjectContext,
    ProjectTableV1,
    ProjectTableV2,
    ProjectTableValue,
    _parse_project_config,
    _project_catalog_path_value,
    _project_config_payload,
    load_project,
    project_tables_to_source_specs,
    resolve_catalog_path,
    save_project,
)
from csvql.query_workflow import _snapshot_optional_catalog
from csvql.source import (
    ResolvedSource,
    SelectedSource,
    source_options_as_python,
    source_request_from_definition,
)
from csvql.source_operations import SourceOperations
from csvql.source_registry import SourceOptionDefinition, build_builtin_descriptor_registry
from csvql.source_runtime import default_source_components, resolve_source_request
from csvql.streaming_export import write_streaming_export
from csvql.table_mapping import (
    derive_alias_from_locator,
    parse_source_options,
    parse_table_mapping,
    source_from_single_csv,
    validate_table_alias,
)
from csvql.tui_query_runner import TUIRunRequest
from csvql.tui_result_store import TUIResultHandle, TUIResultStore
from csvql.tui_state import (
    TUIExportIntent,
    TUIQueryOutcome,
    TUIQueryRunMode,
    TUISessionState,
    TUISource,
    TUISourceColumn,
)

_MISSING_PROJECT_PREFIX = "No .csvql.yml project catalog found."
_DERIVED_RESULTS_DIR = Path(".csvql") / "results"


@dataclass(frozen=True, slots=True)
class TUISourceTypeChoice:
    """Import-free source type and option metadata used by the TUI form."""

    source_type: str
    label: str
    extensions: tuple[str, ...]
    options: tuple[SourceOptionDefinition, ...]


@dataclass(frozen=True, slots=True)
class TUISourcePreview:
    """Deterministic selected-source preview awaiting explicit TUI confirmation."""

    source: TUISource
    provider_key: str
    selection_reason: str
    extension_evidence: str | None

    def confirmation_message(self) -> str:
        """Describe exactly why the provider would be selected."""

        if self.selection_reason == "explicit_type":
            reason = f"explicit type '{self.provider_key}'"
        else:
            reason = f"recognized extension '{self.extension_evidence}'"
        option_keys = tuple(key for key, _value in self.source.options)
        option_text = (
            f" Explicit options: {', '.join(option_keys)}."
            if option_keys
            else " No explicit options."
        )
        return (
            f"Add source '{self.source.name}' as {self.provider_key} from "
            f"'{self.source.locator}'? Selection reason: {reason}.{option_text}"
        )


def tui_source_type_choices() -> tuple[TUISourceTypeChoice, ...]:
    """Return deterministic descriptor metadata without importing adapters."""

    registry = build_builtin_descriptor_registry()
    return tuple(
        TUISourceTypeChoice(
            source_type=descriptor.source_kind,
            label=descriptor.source_kind.upper(),
            extensions=descriptor.extensions,
            options=descriptor.options,
        )
        for descriptor in registry.descriptors
    )


def build_tui_source_preview(
    *,
    alias: str,
    locator: str,
    source_type: str | None,
    option_mappings: Sequence[str],
    existing_sources: Sequence[TUISource],
    start_dir: Path,
) -> TUISourcePreview:
    """Validate TUI source intent and return a shared-detection preview."""

    source_name = validate_table_alias(alias)
    if any(source.name.casefold() == source_name.casefold() for source in existing_sources):
        raise TableMappingError(
            f"Source alias '{source_name}' is already loaded.",
            suggestion="Choose a different source alias or remove the existing source first.",
        )
    source = TUISource(
        name=source_name,
        locator=locator,
        anchor=start_dir,
        source_type=source_type,
        options=parse_source_options(option_mappings),
        origin="session",
    )
    request = source_request_from_definition(source.as_source_definition())
    detected = default_source_components().detection.detect(request)
    if not isinstance(detected, SelectedSource):
        raise SourceError(
            "unknown_source_kind",
            detected.diagnostic.message,
            alias=source.name,
            suggestion=(
                None
                if detected.required_action is None
                else detected.required_action.kind.replace("_", " ")
            ),
            diagnostic=detected.diagnostic,
        )
    return TUISourcePreview(
        source=source,
        provider_key=detected.provider_key,
        selection_reason=detected.selection_reason,
        extension_evidence=detected.extension_evidence,
    )


def structured_source_locator_from_text(
    raw_text: str,
    *,
    start_dir: Path,
) -> str | None:
    """Return one non-CSV locator suitable for the structured TUI flow."""

    cleaned = _path_value_from_terminal_token(_strip_terminal_quotes(raw_text.strip()))
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        return None
    candidate = Path(cleaned).expanduser()
    resolved = candidate if candidate.is_absolute() else start_dir / candidate
    try:
        is_directory = resolved.is_dir()
        is_file = resolved.is_file()
    except OSError:
        return None
    if not is_directory and not is_file:
        return None
    registry = build_builtin_descriptor_registry()
    if is_directory:
        return cleaned
    if Path(cleaned).suffix.casefold() == ".csv":
        return None
    if registry.match_extension(cleaned) is not None:
        return cleaned
    if registry.match_unsupported_extension(cleaned) is not None:
        return cleaned
    return cleaned if not Path(cleaned).suffix else None


def suggested_tui_source_alias(locator: str, *, start_dir: Path) -> str:
    """Derive the same conservative alias used by other source surfaces."""

    return derive_alias_from_locator(locator, base_dir=start_dir)


def tui_source_option_mappings(raw_text: str) -> tuple[str, ...]:
    """Split structured TUI option text into the shared repeatable mapping form."""

    if not raw_text.strip():
        return ()
    try:
        return tuple(shlex.split(raw_text))
    except ValueError as exc:
        raise TableMappingError(
            "Invalid source option quoting.",
            suggestion="Use space-separated key=value options with balanced quotes.",
        ) from exc


def build_initial_state(
    *,
    csv_path: str | None,
    table_mappings: Sequence[str],
    start_dir: Path,
) -> TUISessionState:
    """Build the initial in-memory TUI session state from startup inputs."""

    state = TUISessionState()

    if csv_path is None and not table_mappings:
        for source in _catalog_sources(start_dir=start_dir):
            state.add_source(source)
        return state

    if csv_path is not None:
        csv_source = source_from_single_csv(csv_path, base_dir=start_dir)
        state.add_source(TUISource(name=csv_source.name, path=csv_source.path, origin="argument"))

    for raw_mapping in table_mappings:
        mapping_source = parse_table_mapping(raw_mapping, base_dir=start_dir)
        state.add_source(
            TUISource(
                name=mapping_source.name,
                path=mapping_source.path,
                origin="argument",
            )
        )

    return state


def sources_from_csv_path_text(
    raw_text: str,
    *,
    existing_sources: Sequence[TUISource],
    start_dir: Path,
) -> tuple[TUISource, ...]:
    """Build session sources from terminal-pasted CSV path text.

    This helper returns an empty tuple when the pasted text is not exclusively
    one or more `.csv` paths, allowing normal SQL/editor paste behavior to
    continue.
    """

    path_values = _csv_path_values_from_text(raw_text)
    if not path_values:
        return ()

    reserved_aliases = {source.name.casefold() for source in existing_sources}
    sources: list[TUISource] = []
    for path_value in path_values:
        table_source = source_from_single_csv(path_value, base_dir=start_dir)
        source_name = _unique_table_alias(table_source.name, reserved_aliases)
        reserved_aliases.add(source_name.casefold())
        sources.append(
            TUISource(
                name=source_name,
                path=table_source.path,
                origin="session",
            )
        )
    return tuple(sources)


def external_catalog_source_paths(
    sources: Sequence[TUISource],
    *,
    start_dir: Path,
) -> tuple[Path, ...]:
    """Return catalog source paths that resolve outside the TUI start directory."""

    base_dir = start_dir.expanduser().resolve()
    external_paths: list[Path] = []
    for source in sources:
        source_path = source.path.expanduser()
        if source_path.is_absolute():
            resolved_path = source_path.resolve(strict=False)
        else:
            resolved_path = (base_dir / source_path).resolve(strict=False)
        try:
            resolved_path.relative_to(base_dir)
        except ValueError:
            external_paths.append(resolved_path)
    return tuple(external_paths)


def inspect_source(
    source: TUISource,
    *,
    exact: bool = False,
    operation: OperationContext | None = None,
) -> InspectResult:
    """Inspect a TUI source through its resolved adapter boundary."""

    active_operation = operation or OperationContext(OperationToken())
    resolved = _resolve_tui_source(source, operation=active_operation)
    with CSVQLEngine(operation=active_operation) as engine:
        result = SourceOperations(engine, resolved).inspect(exact=exact)
    return replace(result, source=_tui_source_summary(result.source, source))


def inspect_source_columns(
    source: TUISource,
    *,
    operation: OperationContext | None = None,
) -> tuple[TUISourceColumn, ...]:
    """Inspect a TUI source and return its columns for source intelligence."""

    result = inspect_source(source, operation=operation)
    return tuple(
        TUISourceColumn(name=column.name, duckdb_type=column.duckdb_type)
        for column in result.columns
    )


def render_duckdb_identifier(identifier: str) -> str:
    """Render one DuckDB delimited identifier for generated SQL snippets."""

    escaped_identifier = identifier.replace('"', '""')
    return f'"{escaped_identifier}"'


def sample_source(
    source: TUISource,
    *,
    limit: int = 10,
    operation: OperationContext | None = None,
) -> SampleResult:
    """Sample a TUI source through its resolved adapter boundary."""

    active_operation = operation or OperationContext(OperationToken())
    resolved = _resolve_tui_source(source, operation=active_operation)
    with CSVQLEngine(operation=active_operation) as engine:
        result = SourceOperations(engine, resolved).sample(limit=limit)
    return replace(result, source=_tui_source_summary(result.source, source))


def profile_source(
    source: TUISource,
    *,
    operation: OperationContext | None = None,
) -> ProfileResult:
    """Profile a TUI source through its resolved adapter boundary."""

    active_operation = operation or OperationContext(OperationToken())
    resolved = _resolve_tui_source(source, operation=active_operation)
    with CSVQLEngine(operation=active_operation) as engine:
        result = SourceOperations(engine, resolved).profile()
    return replace(result, source=_tui_source_summary(result.source, source))


def query_sources(sources: Sequence[TUISource], sql: str) -> QueryResult:
    """Query registered TUI sources with trusted local SQL."""

    operation = OperationContext(OperationToken())
    resolved = tuple(_resolve_tui_source(source, operation=operation) for source in sources)
    with CSVQLEngine(operation=operation) as engine:
        engine.prepare_sources(resolved)
        return engine.query(sql)


def build_tui_run_request(
    sources: Sequence[TUISource],
    statements: Sequence[str],
    *,
    sequences: Sequence[int],
    preview_policy: PreviewPolicy,
    run_mode: TUIQueryRunMode,
    submission_order: int,
    start_dir: Path,
    operation: OperationContext | None = None,
) -> TUIRunRequest:
    """Capture immutable SQL, source, fallback, and preview inputs for one TUI run."""

    active_operation = operation or OperationContext(OperationToken())
    resolved_sources = tuple(
        _resolve_tui_source(source, operation=active_operation) for source in tuple(sources)
    )
    fallback_sources = _snapshot_optional_catalog(
        start_dir=start_dir,
        operation=active_operation,
    )
    return TUIRunRequest(
        statements=tuple(statements),
        sequences=tuple(sequences),
        sources=resolved_sources,
        fallback_sources=fallback_sources,
        preview_policy=preview_policy,
        run_mode=run_mode,
        submission_order=submission_order,
    )


def build_tui_export_intent(
    *,
    result_sequence: int,
    path_value: str,
    export_format: ExportFormat,
    base_dir: Path,
) -> TUIExportIntent:
    """Resolve one export destination without creating or staging it."""

    destination = resolve_export_path(path_value, base_dir=base_dir, force=False)
    return TUIExportIntent(
        result_sequence=result_sequence,
        destination=destination,
        format=export_format,
    )


def run_buffer_for_tui(
    sources: Sequence[TUISource],
    statements: Sequence[str],
    *,
    sequences: Sequence[int],
) -> tuple[TUIQueryOutcome, ...]:
    """Run trusted local SQL statements in one DuckDB session for Run Buffer."""

    if len(statements) != len(sequences):
        raise ValueError("Run Buffer statements and sequences must have the same length.")

    outcomes: list[TUIQueryOutcome] = []
    operation = OperationContext(OperationToken())
    resolved = tuple(_resolve_tui_source(source, operation=operation) for source in sources)
    with CSVQLEngine(operation=operation) as engine:
        if resolved:
            engine.prepare_sources(resolved)
        for sql, sequence in zip(statements, sequences, strict=True):
            try:
                result = engine.query(sql)
            except CSVQLError as exc:
                outcomes.append(
                    TUIQueryOutcome.error(
                        sequence=sequence,
                        sql=sql,
                        error_message=exc.message,
                        suggestion=exc.suggestion,
                        diagnostic=exc.diagnostic,
                    )
                )
                break

            if not result.columns:
                outcomes.append(
                    TUIQueryOutcome.no_result(
                        sequence=sequence,
                        sql=sql,
                        elapsed_ms=result.elapsed_ms,
                    )
                )
            else:
                outcomes.append(TUIQueryOutcome.success(sequence=sequence, sql=sql, result=result))

    return tuple(outcomes)


def run_query_for_tui(
    sources: Sequence[TUISource],
    sql: str,
    *,
    sequence: int,
) -> TUIQueryOutcome:
    """Run trusted local SQL and return a TUI-local typed outcome."""

    try:
        result = query_sources(sources, sql)
    except CSVQLError as exc:
        return TUIQueryOutcome.error(
            sequence=sequence,
            sql=sql,
            error_message=exc.message,
            suggestion=exc.suggestion,
            diagnostic=exc.diagnostic,
        )

    if not result.columns:
        return TUIQueryOutcome.no_result(
            sequence=sequence,
            sql=sql,
            elapsed_ms=result.elapsed_ms,
        )
    return TUIQueryOutcome.success(sequence=sequence, sql=sql, result=result)


def export_last_result(
    result_store: TUIResultStore,
    handle: TUIResultHandle,
    path_value: str,
    *,
    columns: tuple[str, ...],
    elapsed_ms: float,
    export_format: ExportFormat,
    base_dir: Path,
    force: bool = False,
    token: OperationToken | None = None,
) -> Path:
    """Export one preserved TUI result without materializing all rows in memory."""

    export_source = _StoredResultExportSource(
        result_store=result_store,
        handle=handle,
        columns=columns,
        elapsed_ms=elapsed_ms,
    )
    output_path = resolve_export_path(path_value, base_dir=base_dir, force=force)
    write_streaming_export(
        export_source,
        output_path,
        export_format=export_format,
        overwrite=force,
        token=token,
    )
    return output_path


def save_derived_result_source(
    result_store: TUIResultStore,
    handle: TUIResultHandle,
    alias: str,
    *,
    columns: tuple[str, ...],
    elapsed_ms: float,
    existing_sources: Sequence[TUISource],
    start_dir: Path,
    token: OperationToken | None = None,
) -> TUISource:
    """Write one preserved TUI result as a project-local CSV and return a source."""

    export_source = _StoredResultExportSource(
        result_store=result_store,
        handle=handle,
        columns=columns,
        elapsed_ms=elapsed_ms,
    )
    source_name = validate_table_alias(alias)
    for existing_source in existing_sources:
        if existing_source.name.casefold() == source_name.casefold():
            raise TableMappingError(
                f"Source alias '{source_name}' is already loaded in the TUI session.",
                suggestion="Choose a unique alias for the derived result source.",
            )

    result_root = _derived_result_root(start_dir).resolve()
    result_dir = result_root / _DERIVED_RESULTS_DIR

    csvql_dir = result_root / ".csvql"
    if csvql_dir.exists():
        try:
            resolved_csvql_dir = csvql_dir.resolve(strict=True)
        except OSError as exc:
            raise ExportError(
                f"Failed to resolve derived results directory: {csvql_dir}",
                suggestion="Use a real project-local .csvql/results directory.",
            ) from exc
        if not resolved_csvql_dir.is_relative_to(result_root):
            raise ExportError(
                f"Derived results directory escapes project root: {resolved_csvql_dir}",
                suggestion="Use a real project-local .csvql/results directory.",
            )

    if result_dir.exists():
        try:
            resolved_result_dir = result_dir.resolve(strict=True)
        except OSError as exc:
            raise ExportError(
                f"Failed to resolve derived results directory: {result_dir}",
                suggestion="Use a real project-local .csvql/results directory.",
            ) from exc
        if not resolved_result_dir.is_relative_to(result_root):
            raise ExportError(
                f"Derived results directory escapes project root: {resolved_result_dir}",
                suggestion="Use a real project-local .csvql/results directory.",
            )

    try:
        result_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(
            f"Failed to create derived results directory: {result_dir}",
            suggestion="Check that the project directory is writable.",
        ) from exc

    try:
        resolved_result_dir = result_dir.resolve(strict=True)
    except OSError as exc:
        raise ExportError(
            f"Failed to resolve derived results directory: {result_dir}",
            suggestion="Use a real project-local .csvql/results directory.",
        ) from exc
    if not resolved_result_dir.is_relative_to(result_root):
        raise ExportError(
            f"Derived results directory escapes project root: {resolved_result_dir}",
            suggestion="Use a real project-local .csvql/results directory.",
        )

    existing_output_path = _existing_derived_result_path(resolved_result_dir, source_name)
    if existing_output_path is not None:
        raise ExportError(
            f"Derived result already exists at {existing_output_path}.",
            suggestion="Choose a different alias for this derived result source.",
        )

    output_path = resolved_result_dir / f"{source_name}.csv"
    try:
        write_streaming_export(
            export_source,
            output_path,
            export_format=ExportFormat.csv,
            overwrite=False,
            token=token,
        )
    except OperationCancelled:
        raise
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError(
            f"Failed to write derived source to {output_path}.",
            suggestion="Check that the derived results directory is writable.",
        ) from exc

    return TUISource(
        name=source_name,
        path=output_path,
        origin="derived",
        kind="csv",
    )


def save_sources_to_project_catalog(
    sources: Sequence[TUISource],
    *,
    start_dir: Path,
    replace: bool,
) -> ProjectContext:
    """Save TUI sources into the project catalog, creating it when absent."""

    context = _load_or_initialize_project(start_dir)
    tables = _stage_project_tables(context, sources, replace=replace)
    config: ProjectConfigValue
    if isinstance(context.config, ProjectConfigV1):
        config = ProjectConfigV1(
            version=SUPPORTED_VERSION,
            tables=tuple(sorted(cast(list[ProjectTableV1], tables), key=lambda table: table.name)),
        )
    else:
        config = ProjectConfigV2(
            version=CURRENT_VERSION,
            tables=tuple(sorted(cast(list[ProjectTableV2], tables), key=lambda table: table.name)),
        )
    staged_context = ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=config,
    )
    _validate_staged_project_context(staged_context)
    return save_project(staged_context)


def _catalog_sources(*, start_dir: Path) -> tuple[TUISource, ...]:
    try:
        context = load_project(start_dir)
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return ()
        raise

    sources: list[TUISource] = []
    tables = cast(Sequence[ProjectTableValue], context.config.tables)
    specs = project_tables_to_source_specs(context)
    for table, spec in zip(tables, specs, strict=True):
        # Validate artifact provenance before a provider is allowed to inspect it.
        source = TUISource(
            name=spec.alias,
            locator=spec.locator,
            anchor=spec.anchor,
            source_type=spec.kind,
            options=source_options_as_python(spec.options),
            origin="catalog",
        )
        # Preserve startup missing-locator behavior without constructing an adapter.
        resolve_catalog_path(table, context)
        sources.append(source)
    return tuple(sources)


class _StoredResultExportSource:
    """Lazy one-shot export source for one validated preserved result handle."""

    def __init__(
        self,
        *,
        result_store: TUIResultStore,
        handle: TUIResultHandle,
        columns: tuple[str, ...],
        elapsed_ms: float,
    ) -> None:
        self._result_store = result_store
        self._handle = handle
        self._columns = columns
        self._elapsed_ms = elapsed_ms
        self._used = False

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    @property
    def elapsed_ms(self) -> float:
        return self._elapsed_ms

    def iter_rows(self) -> Iterator[tuple[object, ...]]:
        if self._used:
            raise ExportError(
                "Stored result export can only be streamed once.",
                suggestion="Run the export again from the preserved result.",
            )
        self._used = True
        return self._result_store.open_rows(self._handle).iter_rows()


def _resolve_tui_source(
    source: TUISource,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    resolved = resolve_source_request(
        source_request_from_definition(source.as_source_definition()),
        operation=operation,
    )
    if not isinstance(resolved, ResolvedSource):
        raise RuntimeError("Source resolution returned an invalid value.")
    return resolved


def _tui_source_summary(
    summary: dict[str, object],
    source: TUISource,
) -> dict[str, object]:
    return {**summary, "display_path": source.name}


def _stage_project_tables(
    context: ProjectContext,
    sources: Sequence[TUISource],
    *,
    replace: bool,
) -> list[ProjectTableValue]:
    tables = list(cast(Sequence[ProjectTableValue], context.config.tables))
    existing_indexes = {table.name.casefold(): index for index, table in enumerate(tables)}
    seen_batch_aliases: set[str] = set()

    for source in sources:
        source_key = source.name.casefold()
        if source_key in seen_batch_aliases:
            raise ProjectConfigError(
                f"Duplicate project catalog table '{source.name}' in save batch.",
                suggestion="Use one entry per alias when saving sources to the project catalog.",
            )
        seen_batch_aliases.add(source_key)
        if isinstance(context.config, ProjectConfigV1):
            if source.source_type != "csv" or source.options:
                raise ProjectConfigError(
                    "Project catalog version 1 accepts only explicit option-free CSV sources.",
                    suggestion=(
                        "Create a version 2 catalog before saving provider-neutral source intent."
                    ),
                    code="catalog.v1_migration_required",
                )
        elif source.source_type is None:
            raise ProjectConfigError(
                f"Source '{source.name}' requires an explicit type before catalog save.",
                suggestion="Choose a source type in the TUI and save again.",
                code="catalog.source_type_required",
            )

    for source in sources:
        source_key = source.name.casefold()
        operation = OperationContext(OperationToken())
        resolved = _resolve_tui_source(
            source,
            operation=operation,
        )
        with CSVQLEngine(operation=operation) as engine:
            engine.prepare_sources((resolved,))
        resolved_path = Path(resolved.canonical_locator)
        stored_path = _project_catalog_path_value(context.project_root, resolved_path)
        if not stored_path and isinstance(context.config, ProjectConfigV2):
            raise ProjectConfigError(
                f"Missing source locator for project catalog table '{source.name}'.",
                suggestion="Choose a non-empty local source locator and save again.",
                code="catalog.source_locator_required",
            )
        existing_index = existing_indexes.get(source_key)

        if existing_index is not None and not replace:
            raise ProjectConfigError(
                f"Project catalog table '{source.name}' already exists in {context.config_path}.",
                suggestion="Pass replace=True to update the existing table entry.",
            )
        if existing_index is not None:
            existing_table = tables[existing_index]
            if isinstance(context.config, ProjectConfigV1):
                tables[existing_index] = ProjectTableV1(
                    name=source.name,
                    path=stored_path,
                    checks=existing_table.checks,
                )
            else:
                tables[existing_index] = ProjectTableV2(
                    name=source.name,
                    source=CatalogSourceDefinition(
                        source_type=resolved.source_kind,
                        locator=stored_path,
                        options=source.options,
                    ),
                    checks=existing_table.checks,
                )
        else:
            if isinstance(context.config, ProjectConfigV1):
                tables.append(ProjectTableV1(name=source.name, path=stored_path))
            else:
                tables.append(
                    ProjectTableV2(
                        name=source.name,
                        source=CatalogSourceDefinition(
                            source_type=resolved.source_kind,
                            locator=stored_path,
                            options=source.options,
                        ),
                    )
                )

    return tables


def _validate_staged_project_context(context: ProjectContext) -> None:
    payload = _project_config_payload(context.config)
    validated_config = _parse_project_config(payload, config_path=context.config_path)
    if validated_config != context.config:
        raise ProjectConfigError(
            f"Staged project catalog for {context.config_path} is invalid.",
            suggestion="Retry the save after repairing the staged project catalog entries.",
        )


def _load_or_initialize_project(start_dir: Path) -> ProjectContext:
    try:
        return load_project(start_dir)
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            project_root = start_dir.expanduser().resolve()
            return ProjectContext(
                project_root=project_root,
                config_path=project_root / ".csvql.yml",
                config=ProjectConfigV2(version=CURRENT_VERSION, tables=()),
            )
        raise


def _derived_result_root(start_dir: Path) -> Path:
    try:
        return load_project(start_dir).project_root
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return start_dir.expanduser().resolve()
        raise


def _existing_derived_result_path(result_dir: Path, source_name: str) -> Path | None:
    target_name = f"{source_name}.csv".casefold()
    try:
        for candidate in result_dir.iterdir():
            if candidate.name.casefold() == target_name:
                return candidate
    except OSError as exc:
        raise ExportError(
            f"Failed to inspect derived results directory: {result_dir}",
            suggestion="Check that the derived results directory is readable.",
        ) from exc
    return None


def _write_derived_result_file(
    path: Path,
    content: str,
    *,
    token: OperationToken | None = None,
) -> None:
    try:
        write_text_atomic(path, content, newline="", overwrite=False, token=token)
    except OperationCancelled:
        raise
    except FileExistsError as exc:
        raise ExportError(
            f"Derived result already exists at {path}.",
            suggestion="Choose a different alias for this derived result source.",
        ) from exc
    except OSError as exc:
        raise ExportError(
            f"Failed to write derived source to {path}.",
            suggestion="Check that the derived results directory is writable.",
        ) from exc


def _csv_path_values_from_text(raw_text: str) -> tuple[str, ...]:
    raw_text = raw_text.strip()
    try:
        tokens = tuple(
            _strip_terminal_quotes(token) for token in shlex.split(raw_text, posix=False)
        )
    except ValueError:
        tokens = ()

    if tokens:
        path_values = tuple(_path_value_from_terminal_token(token) for token in tokens)
        if all(Path(path_value).suffix.casefold() == ".csv" for path_value in path_values):
            return path_values

    raw_path_value = _path_value_from_terminal_token(_strip_terminal_quotes(raw_text))
    if Path(raw_path_value).suffix.casefold() == ".csv":
        return (raw_path_value,)
    return ()


def _path_value_from_terminal_token(token: str, *, os_name: str = os.name) -> str:
    parsed = urlparse(token)
    if parsed.scheme == "file":
        path_value = unquote(parsed.path)
        if os_name == "nt":
            if parsed.netloc:
                path_value = f"//{parsed.netloc}{path_value}"
            if (
                len(path_value) >= 3
                and path_value[0] == "/"
                and path_value[1].isalpha()
                and path_value[2] == ":"
            ):
                path_value = path_value[1:]
        return path_value
    return token


def _strip_terminal_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    return token


def _unique_table_alias(alias: str, reserved_casefold_aliases: set[str]) -> str:
    base_alias = validate_table_alias(alias)
    if base_alias.casefold() not in reserved_casefold_aliases:
        return base_alias

    suffix = 2
    while True:
        candidate = validate_table_alias(f"{base_alias}_{suffix}")
        if candidate.casefold() not in reserved_casefold_aliases:
            return candidate
        suffix += 1
