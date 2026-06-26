"""Parsing and validation for CLI table mappings."""

import re
from pathlib import Path

from csvql.exceptions import FileMissingError, TableMappingError
from csvql.models import TableSource

TABLE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_table_alias(alias: str) -> str:
    """Validate a DuckDB table alias accepted by CSVQL-generated SQL."""

    normalized_alias = alias.strip()
    if not normalized_alias:
        raise TableMappingError(
            "Table alias cannot be empty.",
            suggestion="Use --table name=path, for example --table orders=data/orders.csv.",
        )
    if not TABLE_ALIAS_PATTERN.fullmatch(normalized_alias):
        raise TableMappingError(
            f"Invalid table alias '{alias}'.",
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        )
    return normalized_alias


def resolve_csv_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    """Resolve and validate a local CSV path."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)
    if not resolved_path.is_file():
        raise FileMissingError(
            f"CSV file not found: {path_value}",
            suggestion="Check the path or run from the directory that contains the CSV file.",
        )
    return resolved_path


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
    return TableSource(name=alias, path=resolve_csv_path(raw_path, base_dir=base_dir))


def derive_alias_from_path(path: Path) -> str:
    """Derive a conservative table alias from a file stem."""

    alias = re.sub(r"[^A-Za-z0-9_]+", "_", path.stem).strip("_")
    if not alias:
        alias = "csv"
    if alias[0].isdigit():
        alias = f"table_{alias}"
    return validate_table_alias(alias)


def source_from_single_csv(path_value: str, *, base_dir: Path | None = None) -> TableSource:
    """Build a table source for single-file shortcut mode."""

    csv_path = resolve_csv_path(path_value, base_dir=base_dir)
    return TableSource(name=derive_alias_from_path(csv_path), path=csv_path)
