"""Startup workflows for the CSVQL menu TUI."""

from collections.abc import Sequence
from pathlib import Path

from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVQLError, ExportError, ProjectConfigError, TableMappingError
from csvql.export import (
    ExportFormat,
    format_query_result_for_export,
    resolve_export_path,
    write_export_file,
)
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult
from csvql.profiling import profile_csv_source
from csvql.project_config import (
    SUPPORTED_VERSION,
    ProjectConfig,
    ProjectContext,
    ProjectTable,
    _project_catalog_path_value,
    load_project,
    resolve_catalog_path,
    save_project,
)
from csvql.source import CSVSource, source_from_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv, validate_table_alias
from csvql.tui_state import TUIQueryOutcome, TUISessionState, TUISource

_MISSING_PROJECT_PREFIX = "No .csvql.yml project catalog found."
_DERIVED_RESULTS_DIR = Path(".csvql") / "results"


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


def inspect_source(source: TUISource, *, exact: bool = False) -> InspectResult:
    """Inspect a TUI source using the existing CSV inspection service."""

    return inspect_csv_source(_csv_source(source), exact=exact)


def sample_source(source: TUISource, *, limit: int = 10) -> SampleResult:
    """Sample a TUI source using the existing CSV sampling service."""

    return sample_csv_source(_csv_source(source), limit=limit)


def profile_source(source: TUISource) -> ProfileResult:
    """Profile a TUI source using the existing CSV profiling service."""

    return profile_csv_source(_csv_source(source))


def query_sources(sources: Sequence[TUISource], sql: str) -> QueryResult:
    """Query registered TUI sources with trusted local SQL."""

    with CSVQLEngine() as engine:
        engine.register_tables(source.as_table_source() for source in sources)
        return engine.query(sql)


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
        )

    if not result.columns:
        return TUIQueryOutcome.no_result(
            sequence=sequence,
            sql=sql,
            elapsed_ms=result.elapsed_ms,
        )
    return TUIQueryOutcome.success(sequence=sequence, sql=sql, result=result)


def export_last_result(
    result: QueryResult,
    path_value: str,
    *,
    export_format: ExportFormat,
    base_dir: Path,
    force: bool = False,
) -> Path:
    """Export the last query result using the existing export helpers."""

    output_path = resolve_export_path(path_value, base_dir=base_dir, force=force)
    content = format_query_result_for_export(result, export_format)
    write_export_file(output_path, content)
    return output_path


def save_derived_result_source(
    result: QueryResult,
    alias: str,
    *,
    existing_sources: Sequence[TUISource],
    start_dir: Path,
) -> TUISource:
    """Write a query result as a project-local CSV and return a derived source."""

    source_name = validate_table_alias(alias)
    for source in existing_sources:
        if source.name.casefold() == source_name.casefold():
            raise TableMappingError(
                f"Source alias '{source.name}' is already loaded in the TUI session.",
                suggestion="Choose a unique alias for the derived result source.",
            )

    result_root = _derived_result_root(start_dir)
    result_dir = result_root / _DERIVED_RESULTS_DIR
    output_path = (result_dir / f"{source_name}.csv").resolve(strict=False)
    if output_path.exists():
        raise ExportError(
            f"Derived result already exists at {output_path}.",
            suggestion="Choose a different alias for this derived result source.",
        )

    try:
        result_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(
            f"Failed to create derived results directory: {result_dir}",
            suggestion="Check that the project directory is writable.",
        ) from exc

    content = format_query_result_for_export(result, ExportFormat.csv)
    try:
        write_export_file(output_path, content)
    except ExportError as exc:
        raise ExportError(
            f"Failed to write derived source to {output_path}.",
            suggestion="Check that the derived results directory is writable.",
        ) from exc

    return TUISource(
        name=source_name,
        path=output_path,
        origin="session",
        kind="derived",
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
    staged_context = ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=ProjectConfig(
            version=context.config.version,
            tables=tuple(sorted(tables, key=lambda table: table.name)),
        ),
    )
    return save_project(staged_context)


def _catalog_sources(*, start_dir: Path) -> tuple[TUISource, ...]:
    try:
        context = load_project(start_dir)
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return ()
        raise

    return tuple(
        TUISource(
            name=table.name,
            path=resolve_catalog_path(table, context),
            origin="catalog",
        )
        for table in context.config.tables
    )


def _csv_source(source: TUISource) -> CSVSource:
    resolved = source_from_path(str(source.path))
    return CSVSource(
        path=resolved.path,
        display_path=source.name,
        fingerprint=resolved.fingerprint,
    )


def _stage_project_tables(
    context: ProjectContext,
    sources: Sequence[TUISource],
    *,
    replace: bool,
) -> list[ProjectTable]:
    tables = list(context.config.tables)
    existing_indexes = {table.name: index for index, table in enumerate(tables)}
    seen_batch_aliases: set[str] = set()

    for source in sources:
        if source.name in seen_batch_aliases:
            raise ProjectConfigError(
                f"Duplicate project catalog table '{source.name}' in save batch.",
                suggestion="Use one entry per alias when saving sources to the project catalog.",
            )
        seen_batch_aliases.add(source.name)

        resolved_path = source_from_path(str(source.path), base_dir=context.project_root).path
        stored_path = _project_catalog_path_value(context.project_root, resolved_path)
        existing_index = existing_indexes.get(source.name)

        if existing_index is not None and not replace:
            raise ProjectConfigError(
                f"Project catalog table '{source.name}' already exists in {context.config_path}.",
                suggestion="Pass replace=True to update the existing table entry.",
            )
        if existing_index is not None:
            existing_table = tables[existing_index]
            tables[existing_index] = ProjectTable(
                name=source.name,
                path=stored_path,
                checks=existing_table.checks,
            )
        else:
            tables.append(ProjectTable(name=source.name, path=stored_path))

    return tables


def _load_or_initialize_project(start_dir: Path) -> ProjectContext:
    try:
        return load_project(start_dir)
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            project_root = start_dir.expanduser().resolve()
            return ProjectContext(
                project_root=project_root,
                config_path=project_root / ".csvql.yml",
                config=ProjectConfig(version=SUPPORTED_VERSION, tables=()),
            )
        raise


def _derived_result_root(start_dir: Path) -> Path:
    try:
        return load_project(start_dir).project_root
    except ProjectConfigError as exc:
        if exc.message.startswith(_MISSING_PROJECT_PREFIX):
            return start_dir.expanduser().resolve()
        raise
