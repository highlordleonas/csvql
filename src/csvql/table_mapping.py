"""Parsing and validation for CLI table mappings."""

import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from csvql.exceptions import TableMappingError
from csvql.models import SourceDefinition, TableSource
from csvql.source import (
    _csv_source_from_resolved,
    _resolve_csv_source_spec,
    csv_source_from_spec,
    source_alias_collision_key,
    source_spec_from_cli_mapping,
)

TABLE_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SOURCE_OPTION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_JSON_NUMBER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")


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


def parse_source_option_value(raw_value: str) -> object:
    """Parse one provider-neutral CLI option value deterministically."""

    value = raw_value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if value.startswith(("{", "[")):
        try:
            return json.loads(
                value,
                parse_constant=lambda constant: _raise_invalid_json_constant(constant),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise TableMappingError(
                f"Invalid JSON source option value: {raw_value}.",
                suggestion="Use valid JSON after '=' or quote the value as ordinary text.",
            ) from exc
    if _JSON_NUMBER_PATTERN.fullmatch(value):
        parsed = json.loads(value)
        if isinstance(parsed, float) and not math.isfinite(parsed):
            raise TableMappingError(
                f"Source option number must be finite: {raw_value}.",
                suggestion="Use a finite JSON number.",
            )
        return parsed
    return value


def parse_source_mapping(
    raw_mapping: str,
    *,
    base_dir: Path | None = None,
) -> SourceDefinition:
    """Parse one provider-neutral `NAME=LOCATOR` source declaration."""

    alias, locator = _split_mapping(
        raw_mapping,
        label="source mapping",
        example="--source orders=data/orders.parquet",
    )
    return SourceDefinition(
        validate_table_alias(alias),
        locator,
        base_dir=base_dir or Path.cwd(),
    )


def parse_source_options(option_mappings: Sequence[str]) -> dict[str, object]:
    """Parse repeatable provider-neutral `KEY=VALUE` option declarations."""

    options: dict[str, object] = {}
    for raw_mapping in option_mappings:
        option_key, raw_value = _split_mapping(
            raw_mapping,
            label="source option",
            example="--option sheet=Orders",
        )
        if not SOURCE_OPTION_KEY_PATTERN.fullmatch(option_key):
            raise TableMappingError(
                f"Invalid source option key '{option_key}'.",
                suggestion="Use lowercase letters, numbers, and underscores.",
            )
        if option_key in options:
            raise TableMappingError(
                f"Duplicate source option '{option_key}'.",
                suggestion="Declare each source option at most once.",
            )
        options[option_key] = parse_source_option_value(raw_value)
    return options


def build_single_source_definition(
    locator: str,
    *,
    source_type: str | None = None,
    option_mappings: Sequence[str] = (),
    alias: str | None = None,
    base_dir: Path | None = None,
) -> SourceDefinition:
    """Build one provider-neutral source definition for a single-source surface."""

    anchor = base_dir or Path.cwd()
    return SourceDefinition(
        alias or derive_alias_from_locator(locator, base_dir=anchor),
        locator,
        source_type=source_type,
        options=parse_source_options(option_mappings),
        base_dir=anchor,
    )


def build_source_definitions(
    source_mappings: Sequence[str],
    source_type_mappings: Sequence[str] = (),
    source_option_mappings: Sequence[str] = (),
    *,
    base_dir: Path | None = None,
) -> tuple[SourceDefinition, ...]:
    """Build a validated source batch from repeatable CLI transport mappings."""

    anchor = base_dir or Path.cwd()
    declarations: dict[str, SourceDefinition] = {}
    aliases: dict[str, str] = {}
    for raw_mapping in source_mappings:
        definition = parse_source_mapping(raw_mapping, base_dir=anchor)
        alias_key = definition.alias.casefold()
        if alias_key in declarations:
            raise TableMappingError(
                f"Duplicate source alias '{definition.alias}'.",
                suggestion="Declare each --source alias exactly once.",
            )
        declarations[alias_key] = definition
        aliases[alias_key] = definition.alias

    source_types: dict[str, str] = {}
    for raw_mapping in source_type_mappings:
        raw_alias, source_type = _split_mapping(
            raw_mapping,
            label="source type mapping",
            example="--source-type orders=parquet",
        )
        alias = validate_table_alias(raw_alias)
        alias_key = alias.casefold()
        _require_declared_source(alias, alias_key, declarations, option_name="--source-type")
        if alias_key in source_types:
            raise TableMappingError(
                f"Duplicate source type for alias '{aliases[alias_key]}'.",
                suggestion="Declare at most one --source-type for each source.",
            )
        if not source_type.strip():
            raise TableMappingError(
                f"Missing source type for alias '{aliases[alias_key]}'.",
                suggestion="Use --source-type NAME=TYPE.",
            )
        source_types[alias_key] = source_type.strip()

    source_options: dict[str, dict[str, object]] = {alias_key: {} for alias_key in declarations}
    for raw_mapping in source_option_mappings:
        raw_subject, raw_value = _split_mapping(
            raw_mapping,
            label="source option mapping",
            example="--source-option orders.sheet=Orders",
        )
        if "." not in raw_subject:
            raise TableMappingError(
                f"Invalid source option subject '{raw_subject}'.",
                suggestion="Use --source-option NAME.KEY=VALUE.",
            )
        raw_alias, option_key = raw_subject.split(".", maxsplit=1)
        alias = validate_table_alias(raw_alias)
        alias_key = alias.casefold()
        _require_declared_source(alias, alias_key, declarations, option_name="--source-option")
        if not SOURCE_OPTION_KEY_PATTERN.fullmatch(option_key):
            raise TableMappingError(
                f"Invalid source option key '{option_key}'.",
                suggestion="Use lowercase letters, numbers, and underscores.",
            )
        options = source_options[alias_key]
        if option_key in options:
            raise TableMappingError(
                f"Duplicate source option '{option_key}' for alias '{aliases[alias_key]}'.",
                suggestion="Declare each source option at most once.",
            )
        options[option_key] = parse_source_option_value(raw_value)

    return tuple(
        SourceDefinition(
            definition.alias,
            definition.locator,
            source_type=source_types.get(alias_key),
            options=source_options[alias_key],
            base_dir=definition.base_dir,
        )
        for alias_key, definition in declarations.items()
    )


def derive_alias_from_path(path: Path) -> str:
    """Derive a conservative table alias from a file stem."""

    return derive_alias_from_locator(str(path))


def derive_alias_from_locator(
    locator: str,
    *,
    base_dir: Path | None = None,
) -> str:
    """Derive one stable source alias from a file or directory locator."""

    locator_path = Path(locator)
    observed_path = locator_path
    if not locator_path.is_absolute() and base_dir is not None:
        observed_path = base_dir / locator_path
    candidate = locator_path.name if observed_path.is_dir() else locator_path.stem
    normalized_stem = re.sub(r"[^A-Za-z0-9_]+", "_", candidate)
    alias = normalized_stem.strip("_")
    if not alias:
        alias = "source"
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
    actual_resolved = replace(
        resolved,
        alias=alias,
        alias_key=source_alias_collision_key(alias),
        requested_locator=resolved.canonical_locator,
        resolution_anchor=canonical_path.parent,
    )
    source = _csv_source_from_resolved(actual_resolved, display_path=path_value)
    return TableSource(name=alias, path=source.path)


def _split_mapping(raw_mapping: str, *, label: str, example: str) -> tuple[str, str]:
    if "=" not in raw_mapping:
        raise TableMappingError(
            f"Invalid {label} '{raw_mapping}'.",
            suggestion=f"Use {example}.",
        )
    subject, value = raw_mapping.split("=", maxsplit=1)
    if not subject.strip() or not value.strip():
        raise TableMappingError(
            f"Invalid {label} '{raw_mapping}'.",
            suggestion=f"Use {example}.",
        )
    return subject.strip(), value


def _require_declared_source(
    alias: str,
    alias_key: str,
    declarations: dict[str, SourceDefinition],
    *,
    option_name: str,
) -> None:
    if alias_key not in declarations:
        raise TableMappingError(
            f"{option_name} references undeclared source alias '{alias}'.",
            suggestion=f"Declare --source {alias}=LOCATOR first.",
        )


def _raise_invalid_json_constant(constant: str) -> object:
    raise ValueError(f"Invalid JSON constant: {constant}.")
