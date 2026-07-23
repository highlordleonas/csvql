"""Resolve inspect/sample inputs as CSV paths or project catalog aliases."""

from pathlib import Path

from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.project_config import load_project
from csvql.source import (
    CSVSource,
    csv_source_from_spec,
    source_from_path,
    source_spec_from_catalog_table,
)


def resolve_path_or_catalog_source(
    path_or_alias: str,
    *,
    base_dir: Path | None = None,
) -> CSVSource:
    """Resolve an inspect/sample argument as a path or catalog alias."""

    if _looks_like_path(path_or_alias):
        return source_from_path(path_or_alias, base_dir=base_dir)

    try:
        context = load_project(base_dir)
    except ProjectConfigError as exc:
        if "No .csvql.yml project catalog found." not in exc.message:
            raise
        return source_from_path(path_or_alias, base_dir=base_dir)

    alias_key = path_or_alias.lower()
    table = next(
        (
            catalog_table
            for catalog_table in context.config.tables
            if catalog_table.name.lower() == alias_key
        ),
        None,
    )
    if table is None:
        return source_from_path(path_or_alias, base_dir=base_dir)

    try:
        spec = source_spec_from_catalog_table(table, project_root=context.project_root)
    except ValueError as exc:
        if table.name.casefold().startswith("__localql_"):
            suggestion = (
                "Rename the table; aliases beginning with '__localql_' are reserved for LocalQL."
            )
        else:
            suggestion = "Use letters, numbers, and underscores; start with a letter or underscore."
        raise ProjectConfigError(
            f"Invalid project catalog table alias '{table.name}'.",
            suggestion=suggestion,
        ) from exc
    try:
        return csv_source_from_spec(spec, display_path=path_or_alias)
    except FileMissingError as exc:
        raise FileMissingError(
            f"CSV file not found for project catalog table '{table.name}': {table.path}",
            suggestion=(
                "Update .csvql.yml, run csvql add "
                f"{table.name} <path> --replace, or restore the CSV file."
            ),
        ) from exc


def _looks_like_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("~")
        or value.endswith(".csv")
    )
