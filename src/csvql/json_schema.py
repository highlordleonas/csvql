"""Validated canonical schema hints for JSON-family source providers."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

_TYPE_ALIASES = {
    "BIGINT": "BIGINT",
    "BOOL": "BOOLEAN",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DOUBLE": "DOUBLE",
    "FLOAT": "REAL",
    "HUGEINT": "HUGEINT",
    "INT": "INTEGER",
    "INTEGER": "INTEGER",
    "JSON": "JSON",
    "REAL": "REAL",
    "SMALLINT": "SMALLINT",
    "TEXT": "VARCHAR",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMPTZ": "TIMESTAMPTZ",
    "TINYINT": "TINYINT",
    "UBIGINT": "UBIGINT",
    "UHUGEINT": "UHUGEINT",
    "UINTEGER": "UINTEGER",
    "USMALLINT": "USMALLINT",
    "UTINYINT": "UTINYINT",
    "UUID": "UUID",
    "VARCHAR": "VARCHAR",
}
_COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DECIMAL_PATTERN = re.compile(r"^DECIMAL\s*\(\s*([0-9]+)\s*,\s*([0-9]+)\s*\)$")
_MAX_DECIMAL_PRECISION = 38


class JSONSchemaHintError(ValueError):
    """Raised when a JSON schema hint is outside the bounded v1.2 grammar."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class JSONSchemaHint:
    """Immutable ordered JSON column schema."""

    columns: tuple[tuple[str, str], ...]

    def as_duckdb_columns(self) -> dict[str, str]:
        """Return a fresh DuckDB ``columns`` mapping."""

        return dict(self.columns)

    @property
    def structure_json(self) -> str:
        """Return the canonical structure accepted by ``json_transform_strict``."""

        return json.dumps(
            self.as_duckdb_columns(),
            ensure_ascii=False,
            separators=(",", ":"),
        )


def parse_json_schema_hint(value: object) -> JSONSchemaHint:
    """Normalize one schema mapping into deterministic column order."""

    if not isinstance(value, Mapping):
        raise JSONSchemaHintError(
            "schema_not_mapping",
            "JSON schema hints must be mappings.",
        )
    if not value:
        raise JSONSchemaHintError(
            "schema_empty",
            "JSON schema hints must define at least one column.",
        )

    columns: list[tuple[str, str]] = []
    column_keys: set[str] = set()
    for column_name, declared_type in value.items():
        if not isinstance(column_name, str):
            raise JSONSchemaHintError(
                "column_name_invalid",
                "JSON schema column names must be strings.",
            )
        normalized_name = unicodedata.normalize("NFC", column_name)
        if not _COLUMN_NAME_PATTERN.fullmatch(normalized_name):
            raise JSONSchemaHintError(
                "column_name_invalid",
                "JSON schema column names must be simple identifiers.",
            )
        column_key = normalized_name.casefold()
        if column_key in column_keys:
            raise JSONSchemaHintError(
                "column_name_collision",
                "JSON schema column names must be unique ignoring case.",
            )
        column_keys.add(column_key)
        columns.append((normalized_name, _normalize_type(declared_type)))

    columns.sort(key=lambda item: item[0])
    return JSONSchemaHint(tuple(columns))


def _normalize_type(value: object) -> str:
    if not isinstance(value, str):
        raise JSONSchemaHintError(
            "type_invalid",
            "JSON schema types must be strings.",
        )
    normalized = value.strip().upper()
    scalar = _TYPE_ALIASES.get(normalized)
    if scalar is not None:
        return scalar
    decimal = _DECIMAL_PATTERN.fullmatch(normalized)
    if decimal is None:
        raise JSONSchemaHintError(
            "type_invalid",
            "JSON schema type is outside the bounded v1.2 grammar.",
        )
    precision = int(decimal.group(1))
    scale = int(decimal.group(2))
    if not (1 <= precision <= _MAX_DECIMAL_PRECISION and 0 <= scale <= precision):
        raise JSONSchemaHintError(
            "type_invalid",
            "JSON DECIMAL precision or scale is outside DuckDB bounds.",
        )
    return f"DECIMAL({precision},{scale})"
