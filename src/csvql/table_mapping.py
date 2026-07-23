"""Parsing and validation for CLI table mappings."""

import re
from dataclasses import replace
from pathlib import Path

from csvql.exceptions import TableMappingError
from csvql.models import TableSource
from csvql.source import (
    SourceSpec,
    _csv_source_from_resolved,
    _resolve_csv_source_spec,
    csv_source_from_spec,
    source_spec_from_cli_mapping,
)

TABLE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_table_alias(alias: str) -> str:
    """Validate a DuckDB table alias accepted by CSVQL-generated SQL."""

    normalized_alias = alias.strip()
    if not normalized_alias:
        raise TableMappingError(
            "Table alias cannot be empty.",
            suggestion="Use --table name=path, for example --table orders=data/orders.csv.",
        )
    if normalized_alias.casefold().startswith("__localql_"):
        raise TableMappingError(
            f"Table alias '{normalized_alias}' uses a reserved prefix.",
            suggestion="Choose an alias that does not begin with '__localql_'.",
        )
    if not TABLE_ALIAS_PATTERN.fullmatch(normalized_alias):
        raise TableMappingError(
            f"Invalid table alias '{alias}'.",
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        )
    return normalized_alias


def parse_table_mapping(raw_mapping: str, *, base_dir: Path | None = None) -> TableSource:
    """Parse a `name=path` CLI mapping into a table source."""

    if "=" not in raw_mapping:
        raise TableMappingError(
            f"Invalid table mapping '{raw_mapping}'.",
            suggestion="Use --table name=path, for example --table orders=data/orders.csv.",
        )

    raw_alias, raw_path = raw_mapping.split("=", maxsplit=1)
    alias = validate_table_alias(raw_alias)
    if not raw_path.strip():
        raise TableMappingError(
            f"Missing CSV path for table alias '{alias}'.",
            suggestion="Use --table name=path, for example --table orders=data/orders.csv.",
        )
    spec = source_spec_from_cli_mapping(
        alias=alias,
        path_value=raw_path,
        anchor=base_dir or Path.cwd(),
    )
    source = csv_source_from_spec(spec, display_path=raw_path)
    return TableSource(name=alias, path=source.path)


def derive_alias_from_path(path: Path) -> str:
    """Derive a conservative table alias from a file stem."""

    normalized_stem = re.sub(r"[^A-Za-z0-9_]+", "_", path.stem)
    alias = normalized_stem.strip("_")
    if not alias:
        alias = "csv"
    if alias[0].isdigit():
        alias = f"table_{alias}"
    return validate_table_alias(alias)


def source_from_single_csv(path_value: str, *, base_dir: Path | None = None) -> TableSource:
    """Build a table source for single-file shortcut mode."""

    anchor = base_dir or Path.cwd()
    placeholder_spec = source_spec_from_cli_mapping(
        alias="csv_source",
        path_value=path_value,
        anchor=anchor,
    )
    resolved = _resolve_csv_source_spec(placeholder_spec, display_path=path_value)
    canonical_path = Path(resolved.canonical_locator)
    alias = derive_alias_from_path(canonical_path)
    actual_spec = SourceSpec(
        alias=alias,
        kind=resolved.spec.kind,
        locator=resolved.canonical_locator,
        anchor=canonical_path.parent,
        options=resolved.spec.options,
    )
    actual_resolved = replace(resolved, spec=actual_spec)
    source = _csv_source_from_resolved(actual_resolved, display_path=path_value)
    return TableSource(name=alias, path=source.path)
