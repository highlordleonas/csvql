"""Resolve inspect/sample inputs as CSV paths or project catalog aliases."""

from pathlib import Path

from csvql.exceptions import ProjectConfigError
from csvql.project_config import load_project, resolve_catalog_path
from csvql.source import CSVSource, source_from_path


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

    table = next(
        (
            catalog_table
            for catalog_table in context.config.tables
            if catalog_table.name == path_or_alias
        ),
        None,
    )
    if table is None:
        return source_from_path(path_or_alias, base_dir=base_dir)

    resolved_path = resolve_catalog_path(table, context)
    source = source_from_path(str(resolved_path), base_dir=base_dir)
    return CSVSource(
        path=source.path,
        display_path=path_or_alias,
        fingerprint=source.fingerprint,
    )


def _looks_like_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("~")
        or value.endswith(".csv")
    )
