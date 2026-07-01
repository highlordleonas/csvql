"""Startup workflows for the CSVQL menu TUI."""

from collections.abc import Sequence
from pathlib import Path

from csvql.exceptions import ProjectConfigError
from csvql.project_config import load_project, resolve_catalog_path
from csvql.table_mapping import parse_table_mapping, source_from_single_csv
from csvql.tui_state import TUISessionState, TUISource

_MISSING_PROJECT_PREFIX = "No .csvql.yml project catalog found."


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
