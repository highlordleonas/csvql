"""Project catalog configuration loading and discovery."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeAlias, cast

import yaml  # type: ignore[import-untyped]

from csvql.atomic_write import write_text_atomic
from csvql.exceptions import FileMissingError, ProjectConfigError, TableMappingError
from csvql.models import TableSource
from csvql.private_artifacts import is_private_result_artifact
from csvql.quality import CheckType, ConfiguredCheck, ForeignKeyReference
from csvql.source import (
    DetectionResult,
    FrozenSourceOptions,
    SelectedSource,
    SourceSpec,
    build_source_request,
    freeze_source_options,
    resolve_csv_path,
    source_options_as_python,
    source_spec_from_catalog_table,
)
from csvql.source_registry import DescriptorView, build_builtin_descriptor_registry
from csvql.source_runtime import detect_source_request
from csvql.table_mapping import validate_table_alias

CONFIG_FILENAME = ".csvql.yml"
# Retained for callers that construct the strict version-1 compatibility model.
SUPPORTED_VERSION = 1
CURRENT_VERSION = 2
SUPPORTED_VERSIONS = (SUPPORTED_VERSION, CURRENT_VERSION)


@dataclass(frozen=True, slots=True)
class ProjectTableV1:
    """A strict version-1 CSV project catalog table entry."""

    name: str
    path: str
    checks: tuple[ConfiguredCheck, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogSourceDefinition:
    """Normalized version-2 source intent persisted without runtime facts."""

    source_type: str
    locator: str
    options: FrozenSourceOptions = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, str) or not self.source_type:
            raise ValueError("Catalog source type must be a non-empty string.")
        if not isinstance(self.locator, str) or not self.locator or "\x00" in self.locator:
            raise ValueError("Catalog source locator must be a non-empty local path string.")
        object.__setattr__(self, "options", freeze_source_options(self.options))


@dataclass(frozen=True, slots=True)
class ProjectTableV2:
    """A strict version-2 provider-neutral project catalog table entry."""

    name: str
    source: CatalogSourceDefinition
    checks: tuple[ConfiguredCheck, ...] = ()


ProjectTable = ProjectTableV1
ProjectTableValue: TypeAlias = ProjectTableV1 | ProjectTableV2


@dataclass(frozen=True, slots=True)
class ProjectTableListing:
    """A resolved project catalog table listing."""

    name: str
    path: str
    resolved_path: Path
    source_type: str = "csv"
    options: FrozenSourceOptions = ()


@dataclass(frozen=True, slots=True)
class ProjectTablesResult:
    """A deterministic snapshot of the project catalog tables."""

    project_root: Path
    config_path: Path
    tables: tuple[ProjectTableListing, ...]


@dataclass(frozen=True, slots=True)
class ProjectConfigV1:
    """Strict version-1 project catalog configuration."""

    version: int
    tables: tuple[ProjectTableV1, ...]


@dataclass(frozen=True, slots=True)
class ProjectConfigV2:
    """Strict version-2 project catalog configuration."""

    version: int
    tables: tuple[ProjectTableV2, ...]


ProjectConfig = ProjectConfigV1
ProjectConfigValue: TypeAlias = ProjectConfigV1 | ProjectConfigV2


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """Resolved project catalog state."""

    project_root: Path
    config_path: Path
    config: ProjectConfigValue


def initialize_project(project_root: Path, *, force: bool = False) -> ProjectContext:
    """Create a new empty project catalog configuration."""

    resolved_root = project_root.expanduser().resolve()
    config_path = resolved_root / CONFIG_FILENAME
    if config_path.exists() and not force:
        raise ProjectConfigError(
            f"Project catalog already exists at {config_path}.",
            suggestion="Pass --force to reinitialize the project catalog.",
        )

    context = ProjectContext(
        project_root=resolved_root,
        config_path=config_path,
        config=ProjectConfigV2(version=CURRENT_VERSION, tables=()),
    )
    try:
        return save_project(context, overwrite=force)
    except FileExistsError as exc:
        raise ProjectConfigError(
            f"Project catalog already exists at {config_path}.",
            suggestion="Pass --force to reinitialize the project catalog.",
        ) from exc


def discover_project(start_dir: Path | None = None) -> tuple[Path, Path]:
    """Find the nearest project catalog by walking upward from a start directory."""

    current_dir = (start_dir or Path.cwd()).expanduser().resolve()
    if current_dir.is_file():
        current_dir = current_dir.parent

    while True:
        config_path = current_dir / CONFIG_FILENAME
        if config_path.is_file():
            return current_dir, config_path
        if current_dir.parent == current_dir:
            raise ProjectConfigError(
                f"No {CONFIG_FILENAME} project catalog found.",
                suggestion="Run project init/add or pass --table mappings explicitly.",
            )
        current_dir = current_dir.parent


def load_project(start_dir: Path | None = None) -> ProjectContext:
    """Load and validate a project catalog configuration."""

    project_root, config_path = discover_project(start_dir)
    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectConfigError(
            f"Invalid YAML in {config_path}.",
            suggestion="Fix the YAML syntax or reinitialize the project catalog.",
        ) from exc
    if raw_config is None:
        raise ProjectConfigError(
            f"Project catalog {config_path} cannot be empty.",
            suggestion="Initialize the project catalog or add a version and tables mapping.",
        )

    config = _parse_project_config(raw_config, config_path=config_path)
    return ProjectContext(project_root=project_root, config_path=config_path, config=config)


def save_project(context: ProjectContext, *, overwrite: bool = True) -> ProjectContext:
    """Persist a project catalog using the requested overwrite policy."""

    config_path = context.config_path
    _validate_private_catalog_locators(context)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _project_config_payload(context.config)
    write_text_atomic(
        config_path,
        yaml.safe_dump(payload, sort_keys=False),
        overwrite=overwrite,
    )
    return context


def resolve_catalog_path(table: ProjectTableValue, context: ProjectContext) -> Path:
    """Resolve a catalog locator relative to the project root."""

    locator = _catalog_table_locator(table)
    try:
        if isinstance(table, ProjectTableV1):
            return resolve_csv_path(locator, base_dir=context.project_root)
        return _resolve_source_locator(locator, base_dir=context.project_root)
    except FileMissingError as exc:
        raise FileMissingError(
            f"Source locator not found for project catalog table '{table.name}': {locator}",
            suggestion=(
                "Update .csvql.yml, run csvql add "
                f"{table.name} <locator> --replace, or restore the source."
            ),
        ) from exc


def add_project_table(
    context: ProjectContext,
    name: str,
    path_value: str,
    *,
    source_type: str | None = None,
    options: Mapping[str, object] | None = None,
    replace: bool = False,
    invocation_dir: Path | None = None,
) -> ProjectContext:
    """Add or replace a project catalog table and persist the update."""

    try:
        table_name = validate_table_alias(name)
    except TableMappingError as exc:
        raise ProjectConfigError(
            f"Invalid project catalog table alias '{name}'.",
            suggestion=exc.suggestion
            or "Use letters, numbers, and underscores; start with a letter or underscore.",
        ) from exc

    frozen_options = freeze_source_options(() if options is None else options.items())
    if isinstance(context.config, ProjectConfigV1):
        if source_type not in {None, "csv"} or frozen_options:
            raise ProjectConfigError(
                "Project catalog version 1 accepts only CSV path entries.",
                suggestion=(
                    "Create a version 2 catalog entry with source.type, "
                    "source.locator, and optional source.options."
                ),
                code="catalog.v1_migration_required",
            )
        return _add_project_table_v1(
            context,
            table_name,
            path_value,
            replace=replace,
            invocation_dir=invocation_dir,
        )

    return _add_project_table_v2(
        context,
        table_name,
        path_value,
        source_type=source_type,
        options=frozen_options,
        replace=replace,
        invocation_dir=invocation_dir,
    )


def _add_project_table_v1(
    context: ProjectContext,
    table_name: str,
    path_value: str,
    *,
    replace: bool,
    invocation_dir: Path | None,
) -> ProjectContext:
    config = cast(ProjectConfigV1, context.config)
    base_dir = (invocation_dir or Path.cwd()).expanduser().resolve()
    resolved_path = resolve_csv_path(path_value, base_dir=base_dir)
    stored_path = _project_catalog_path_value(context.project_root, resolved_path)
    tables = list(config.tables)
    table_key = table_name.casefold()
    existing_index = next(
        (index for index, table in enumerate(tables) if table.name.casefold() == table_key),
        None,
    )
    if existing_index is not None and not replace:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' already exists in {context.config_path}.",
            suggestion="Pass --replace to update the existing table entry.",
        )
    if existing_index is not None:
        existing_table = tables[existing_index]
        tables[existing_index] = ProjectTableV1(
            name=table_name,
            path=stored_path,
            checks=existing_table.checks,
        )
    else:
        tables.append(ProjectTableV1(name=table_name, path=stored_path))

    updated_context = ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=ProjectConfigV1(
            version=SUPPORTED_VERSION,
            tables=tuple(sorted(tables, key=lambda table: table.name)),
        ),
    )
    return save_project(updated_context)


def _add_project_table_v2(
    context: ProjectContext,
    table_name: str,
    path_value: str,
    *,
    source_type: str | None,
    options: FrozenSourceOptions,
    replace: bool,
    invocation_dir: Path | None,
) -> ProjectContext:
    config = cast(ProjectConfigV2, context.config)
    base_dir = (invocation_dir or Path.cwd()).expanduser().resolve()
    request = build_source_request(
        alias=table_name,
        locator=path_value,
        anchor=base_dir,
        explicit_type=source_type,
        options=options,
    )
    detection = detect_source_request(request)
    if not isinstance(detection, SelectedSource):
        raise _catalog_detection_error(
            detection,
            table_name=table_name,
            path_value=path_value,
        )
    descriptor = detection.descriptor
    _validate_catalog_source_options(descriptor, options, table_name=table_name)
    resolved_path = _resolve_source_locator(path_value, base_dir=base_dir)
    _reject_private_catalog_locator(
        resolved_path,
        table_name=table_name,
    )
    stored_locator = _project_catalog_path_value(context.project_root, resolved_path)
    source = CatalogSourceDefinition(
        source_type=descriptor.source_kind,
        locator=stored_locator,
        options=options,
    )
    tables = list(config.tables)
    table_key = table_name.casefold()
    existing_index = next(
        (index for index, table in enumerate(tables) if table.name.casefold() == table_key),
        None,
    )
    if existing_index is not None and not replace:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' already exists in {context.config_path}.",
            suggestion="Pass --replace to update the existing table entry.",
        )
    if existing_index is not None:
        existing_table = tables[existing_index]
        tables[existing_index] = ProjectTableV2(
            name=table_name,
            source=source,
            checks=existing_table.checks,
        )
    else:
        tables.append(ProjectTableV2(name=table_name, source=source))
    updated_context = ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=ProjectConfigV2(
            version=CURRENT_VERSION,
            tables=tuple(sorted(tables, key=lambda table: table.name)),
        ),
    )
    return save_project(updated_context)


def build_project_tables_result(context: ProjectContext) -> ProjectTablesResult:
    """Build a sorted, resolved view of the project catalog tables."""

    project_tables = cast(Sequence[ProjectTableValue], context.config.tables)
    tables = tuple(
        ProjectTableListing(
            name=table.name,
            path=_catalog_table_locator(table),
            resolved_path=resolve_catalog_path(table, context),
            source_type=_catalog_table_source_type(table),
            options=_catalog_table_options(table),
        )
        for table in sorted(project_tables, key=lambda table: table.name)
    )
    return ProjectTablesResult(
        project_root=context.project_root,
        config_path=context.config_path,
        tables=tables,
    )


def project_tables_to_sources(context: ProjectContext) -> list[TableSource]:
    """Convert project catalog tables into queryable table sources."""

    if isinstance(context.config, ProjectConfigV2):
        raise ProjectConfigError(
            "Version 2 catalog sources cannot be represented as legacy TableSource values.",
            suggestion="Use SourceDefinition or the provider-neutral project workflow.",
        )
    return [
        TableSource(name=table.name, path=resolve_catalog_path(table, context))
        for table in context.config.tables
    ]


def project_tables_to_source_specs(context: ProjectContext) -> list[SourceSpec]:
    """Convert catalog declarations using the immutable project-root anchor."""

    if isinstance(context.config, ProjectConfigV1):
        return [
            source_spec_from_catalog_table(table, project_root=context.project_root)
            for table in context.config.tables
        ]
    return [
        SourceSpec(
            alias=table.name,
            kind=table.source.source_type,
            locator=table.source.locator,
            anchor=context.project_root,
            options=table.source.options,
        )
        for table in context.config.tables
    ]


def _project_config_payload(config: ProjectConfigValue) -> dict[str, object]:
    if isinstance(config, ProjectConfigV1):
        if config.version != SUPPORTED_VERSION:
            raise _unsupported_catalog_version(config.version)
        tables_payload = {
            table.name: _project_table_v1_payload(table)
            for table in sorted(config.tables, key=lambda table: table.name)
        }
        return {"version": SUPPORTED_VERSION, "tables": tables_payload}
    if config.version != CURRENT_VERSION:
        raise _unsupported_catalog_version(config.version)
    tables_payload = {
        table.name: _project_table_v2_payload(table)
        for table in sorted(config.tables, key=lambda table: table.name)
    }
    return {"version": CURRENT_VERSION, "tables": tables_payload}


def _parse_project_config(raw_config: object, *, config_path: Path) -> ProjectConfigValue:
    if not isinstance(raw_config, dict):
        raise ProjectConfigError(
            f"Project catalog {config_path} must contain a mapping.",
            suggestion="Use version and tables keys in .csvql.yml.",
        )
    if not raw_config:
        raise ProjectConfigError(
            f"Project catalog {config_path} cannot be empty.",
            suggestion="Initialize the project catalog or add a version and tables mapping.",
        )

    allowed_keys = {"version", "tables"}
    extra_keys = set(raw_config) - allowed_keys
    if extra_keys:
        raise ProjectConfigError(
            (
                f"Unsupported project catalog keys in {config_path}: "
                f"{_sorted_key_display(extra_keys)}."
            ),
            suggestion="Keep the project catalog schema to version and tables only.",
        )

    version = raw_config.get("version")
    if version is None:
        raise ProjectConfigError(
            f"Missing version in {config_path}.",
            suggestion=f"Set version: {CURRENT_VERSION} in .csvql.yml.",
        )
    if type(version) is not int:
        raise ProjectConfigError(
            f"Project catalog version in {config_path} must be an integer.",
            suggestion=f"Set version: {CURRENT_VERSION} in .csvql.yml.",
        )
    if version not in SUPPORTED_VERSIONS:
        raise _unsupported_catalog_version(version)

    tables = raw_config.get("tables")
    if tables is None:
        raise ProjectConfigError(
            f"Missing tables in {config_path}.",
            suggestion="Set tables: {} for an empty project catalog.",
        )
    if not isinstance(tables, dict):
        raise ProjectConfigError(
            f"Project catalog tables in {config_path} must be a mapping.",
            suggestion="Use table names as keys and nested mappings with path string entries, "
            "for example orders: {path: data/orders.csv}.",
        )

    parser = (
        _parse_project_table_v1_entry
        if version == SUPPORTED_VERSION
        else _parse_project_table_v2_entry
    )
    project_tables = tuple(
        parser(name, table_value, config_path=config_path) for name, table_value in tables.items()
    )
    _validate_case_insensitive_table_aliases(project_tables, config_path=config_path)
    _validate_project_table_references(project_tables, config_path=config_path)
    if version == SUPPORTED_VERSION:
        return ProjectConfigV1(
            version=SUPPORTED_VERSION,
            tables=cast(tuple[ProjectTableV1, ...], project_tables),
        )
    return ProjectConfigV2(
        version=CURRENT_VERSION,
        tables=cast(tuple[ProjectTableV2, ...], project_tables),
    )


def _validate_case_insensitive_table_aliases(
    tables: Sequence[ProjectTableValue],
    *,
    config_path: Path,
) -> None:
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for table in tables:
        table_key = table.name.casefold()
        existing_name = seen.get(table_key)
        if existing_name is None:
            seen[table_key] = table.name
        elif existing_name != table.name:
            collisions.append((existing_name, table.name))

    if collisions:
        collision_display = ", ".join(
            f"'{first}' and '{second}'" for first, second in sorted(collisions)
        )
        raise ProjectConfigError(
            f"Project catalog table aliases differ only by case: {collision_display}.",
            suggestion="Rename one of the colliding aliases before using the project catalog.",
        )


def _parse_project_table_v1_entry(
    raw_name: object,
    raw_table: object,
    *,
    config_path: Path,
) -> ProjectTableV1:
    if not isinstance(raw_name, str):
        raise ProjectConfigError(
            f"Project catalog table names in {config_path} must be strings.",
            suggestion="Use safe table aliases such as orders or customer_orders.",
        )
    try:
        name = validate_table_alias(raw_name)
    except TableMappingError as exc:
        raise ProjectConfigError(
            f"Invalid project catalog table alias '{raw_name}'.",
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        ) from exc

    if not isinstance(raw_table, dict):
        raise ProjectConfigError(
            f"Project catalog table '{name}' in {config_path} must be a mapping.",
            suggestion="Use a nested path mapping such as orders: {path: data/orders.csv}.",
        )

    allowed_keys = {"path", "checks"}
    extra_keys = set(raw_table) - allowed_keys
    if extra_keys:
        extra_keys_display = _sorted_key_display(extra_keys)
        message = (
            f"Unsupported metadata for project catalog table '{name}' "
            f"in {config_path}: {extra_keys_display}."
        )
        raise ProjectConfigError(
            message,
            suggestion="Use only path and optional checks keys in each table entry.",
        )

    if "path" not in raw_table:
        raise ProjectConfigError(
            f"Missing CSV path for project catalog table '{name}' in {config_path}.",
            suggestion="Provide a nested path value for the CSV file.",
        )
    raw_path = raw_table["path"]
    if not isinstance(raw_path, str):
        raise ProjectConfigError(
            f"Project catalog table '{name}' in {config_path} must map to a string path.",
            suggestion="Use a nested string path value such as path: data/orders.csv.",
        )
    if not raw_path.strip():
        raise ProjectConfigError(
            f"Missing CSV path for project catalog table '{name}' in {config_path}.",
            suggestion="Provide a nested string path to the CSV file.",
        )

    checks: tuple[ConfiguredCheck, ...] = ()
    if "checks" in raw_table:
        checks = _parse_project_table_checks(
            raw_table["checks"],
            table_name=name,
            config_path=config_path,
        )

    return ProjectTableV1(name=name, path=raw_path, checks=checks)


def _parse_project_table_v2_entry(
    raw_name: object,
    raw_table: object,
    *,
    config_path: Path,
) -> ProjectTableV2:
    name = _parse_project_table_name(raw_name, config_path=config_path)
    if not isinstance(raw_table, dict):
        raise ProjectConfigError(
            f"Project catalog table '{name}' in {config_path} must be a mapping.",
            suggestion="Use source and optional checks mappings for each version 2 table.",
        )
    allowed_keys = {"source", "checks"}
    extra_keys = set(raw_table) - allowed_keys
    if extra_keys:
        raise ProjectConfigError(
            (
                f"Unsupported metadata for project catalog table '{name}' "
                f"in {config_path}: {_sorted_key_display(extra_keys)}."
            ),
            suggestion="Use only source and optional checks keys in each version 2 entry.",
        )
    raw_source = raw_table.get("source")
    if not isinstance(raw_source, dict):
        raise ProjectConfigError(
            f"Project catalog table '{name}' in {config_path} must define source as a mapping.",
            suggestion="Use source: {type: parquet, locator: data/orders.parquet}.",
        )
    source = _parse_catalog_source_definition(raw_source, table_name=name, config_path=config_path)
    checks = _parse_project_table_checks(
        raw_table.get("checks"),
        table_name=name,
        config_path=config_path,
    )
    return ProjectTableV2(name=name, source=source, checks=checks)


def _parse_project_table_name(raw_name: object, *, config_path: Path) -> str:
    if not isinstance(raw_name, str):
        raise ProjectConfigError(
            f"Project catalog table names in {config_path} must be strings.",
            suggestion="Use safe table aliases such as orders or customer_orders.",
        )
    try:
        return validate_table_alias(raw_name)
    except TableMappingError as exc:
        raise ProjectConfigError(
            f"Invalid project catalog table alias '{raw_name}'.",
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        ) from exc


def _parse_catalog_source_definition(
    raw_source: dict[object, object],
    *,
    table_name: str,
    config_path: Path,
) -> CatalogSourceDefinition:
    allowed_keys = {"type", "locator", "options"}
    extra_keys = set(raw_source) - allowed_keys
    if extra_keys:
        raise ProjectConfigError(
            (
                f"Unsupported source metadata for project catalog table '{table_name}' "
                f"in {config_path}: {_sorted_key_display(extra_keys)}."
            ),
            suggestion="Use only type, locator, and optional options keys.",
        )
    raw_type = raw_source.get("type")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' in {config_path} requires source.type.",
            suggestion="Set source.type to csv, parquet, json, ndjson, or excel.",
        )
    descriptor = _catalog_descriptor(raw_type, table_name=table_name)
    raw_locator = raw_source.get("locator")
    if not isinstance(raw_locator, str) or not raw_locator.strip() or "\x00" in raw_locator:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' in {config_path} requires source.locator.",
            suggestion="Set source.locator to a non-empty local path string.",
        )
    _reject_private_catalog_locator(
        _absolute_source_locator(raw_locator, base_dir=config_path.parent),
        table_name=table_name,
    )
    raw_options = raw_source.get("options", {})
    if not isinstance(raw_options, dict) or not all(isinstance(key, str) for key in raw_options):
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' in {config_path} has invalid source.options.",
            suggestion="Use a string-keyed mapping of JSON-compatible option values.",
        )
    try:
        options = freeze_source_options(cast(dict[str, object], raw_options).items())
    except (TypeError, ValueError) as exc:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' in {config_path} has invalid source.options.",
            suggestion="Use finite JSON-compatible option values.",
        ) from exc
    _validate_catalog_source_options(descriptor, options, table_name=table_name)
    return CatalogSourceDefinition(
        source_type=descriptor.source_kind,
        locator=raw_locator,
        options=options,
    )


def _project_table_v1_payload(table: ProjectTableV1) -> dict[str, object]:
    payload: dict[str, object] = {"path": table.path}
    if table.checks:
        payload["checks"] = [_project_check_payload(check) for check in table.checks]
    return payload


def _project_table_v2_payload(table: ProjectTableV2) -> dict[str, object]:
    source: dict[str, object] = {
        "type": table.source.source_type,
        "locator": table.source.locator,
    }
    if table.source.options:
        source["options"] = source_options_as_python(table.source.options)
    payload: dict[str, object] = {"source": source}
    if table.checks:
        payload["checks"] = [_project_check_payload(check) for check in table.checks]
    return payload


def _project_check_payload(check: ConfiguredCheck) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": check.name,
        "type": check.type,
    }
    if check.column is not None:
        payload["column"] = check.column
    if check.values:
        payload["values"] = list(check.values)
    if check.type in {"min", "max"}:
        payload["value"] = check.value
    if check.min_value is not None:
        payload["min"] = check.min_value
    if check.max_value is not None:
        payload["max"] = check.max_value
    if check.references is not None:
        payload["references"] = check.references.as_dict()
    return payload


def _parse_project_table_checks(
    raw_checks: object,
    *,
    table_name: str,
    config_path: Path,
) -> tuple[ConfiguredCheck, ...]:
    if raw_checks is None:
        return ()
    if not isinstance(raw_checks, list):
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' in {config_path} must define checks as a list.",
            suggestion="Use checks: [] or a list of nested check mappings.",
        )
    checks = tuple(
        _parse_project_check_entry(
            raw_check,
            table_name=table_name,
            config_path=config_path,
        )
        for raw_check in raw_checks
    )
    _validate_project_table_check_names(checks, table_name=table_name, config_path=config_path)
    return checks


def _parse_project_check_entry(
    raw_check: object,
    *,
    table_name: str,
    config_path: Path,
) -> ConfiguredCheck:
    if not isinstance(raw_check, dict):
        table_context = _project_check_entries_context(
            table_name=table_name,
            config_path=config_path,
        )
        raise ProjectConfigError(
            f"{table_context} must be mappings.",
            suggestion="Use nested check mappings with name and type keys.",
        )

    table_context = _project_check_entries_context(
        table_name=table_name,
        config_path=config_path,
    )
    raw_name = raw_check.get("name")
    if not isinstance(raw_name, str):
        raise ProjectConfigError(
            f"{table_context} must define a string name.",
            suggestion="Use a check alias such as order_id_required.",
        )
    try:
        name = validate_table_alias(raw_name)
    except TableMappingError as exc:
        raise ProjectConfigError(
            f"Invalid project catalog check alias '{raw_name}' for table '{table_name}'.",
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        ) from exc

    raw_type = raw_check.get("type")
    if not isinstance(raw_type, str):
        check_context = _project_check_context(
            table_name=table_name,
            check_name=name,
            config_path=config_path,
        )
        raise ProjectConfigError(
            f"{check_context} must define a string type.",
            suggestion="Use one of: not_null, unique, accepted_values, min, max, "
            "row_count_between, or foreign_key.",
        )
    check_type = cast(CheckType, raw_type.strip())
    check_context = _project_check_context(
        table_name=table_name,
        check_name=name,
        config_path=config_path,
    )
    if check_type not in _SUPPORTED_CHECK_TYPES:
        raise ProjectConfigError(
            f"Unsupported project catalog check type '{check_type}' for {check_context}.",
            suggestion="Use one of: not_null, unique, accepted_values, min, max, "
            "row_count_between, or foreign_key.",
        )

    allowed_keys = {"name", "type"} | _supported_check_keys(check_type)
    extra_keys = set(raw_check) - allowed_keys
    if extra_keys:
        raise ProjectConfigError(
            f"Unsupported metadata for {check_context}: {_sorted_key_display(extra_keys)}.",
            suggestion="Remove unsupported keys from the check entry.",
        )

    column = None
    if check_type in _CHECK_TYPES_REQUIRING_COLUMN:
        column = _parse_non_empty_string(
            raw_check.get("column"),
            field_name="column",
            table_name=table_name,
            check_name=name,
            config_path=config_path,
        )
    elif "column" in raw_check:
        raise ProjectConfigError(
            f"{check_context} cannot define column.",
            suggestion="Remove column for row_count_between checks.",
        )

    values: tuple[object, ...] = ()
    if check_type == "accepted_values":
        raw_values = raw_check.get("values")
        if not isinstance(raw_values, list) or not raw_values:
            raise ProjectConfigError(
                f"{check_context} must define a non-empty values list.",
                suggestion="Use values: [paid, pending] or another non-empty list.",
            )
        if not all(_is_yaml_scalar(value) for value in raw_values):
            raise ProjectConfigError(
                f"{check_context} must define values as YAML scalar entries.",
                suggestion="Use scalar values such as strings, numbers, booleans, or null.",
            )
        values = tuple(raw_values)

    value = None
    if check_type in {"min", "max"}:
        if "value" not in raw_check:
            raise ProjectConfigError(
                f"{check_context} must define value.",
                suggestion="Use value: <scalar> for min and max checks.",
            )
        if not _is_yaml_scalar(raw_check["value"]):
            raise ProjectConfigError(
                f"{check_context} must define value as a YAML scalar.",
                suggestion="Use a scalar value such as a string, number, boolean, or null.",
            )
        value = raw_check["value"]

    min_value = None
    max_value = None
    if check_type == "row_count_between":
        has_min = "min" in raw_check
        has_max = "max" in raw_check
        if not has_min and not has_max:
            raise ProjectConfigError(
                f"{check_context} must define min, max, or both.",
                suggestion="Use min, max, or both row-count bounds.",
            )
        if has_min:
            min_value = _parse_non_negative_int(
                raw_check["min"],
                field_name="min",
                table_name=table_name,
                check_name=name,
                config_path=config_path,
            )
        if has_max:
            max_value = _parse_non_negative_int(
                raw_check["max"],
                field_name="max",
                table_name=table_name,
                check_name=name,
                config_path=config_path,
            )
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ProjectConfigError(
                f"{check_context} has min greater than max.",
                suggestion="Set min to a value less than or equal to max.",
            )
    else:
        if "min" in raw_check or "max" in raw_check:
            raise ProjectConfigError(
                f"{check_context} cannot define min or max.",
                suggestion="Use min and max only for row_count_between checks.",
            )

    references = None
    if check_type == "foreign_key":
        raw_references = raw_check.get("references")
        references = _parse_foreign_key_reference(
            raw_references,
            table_name=table_name,
            check_name=name,
            config_path=config_path,
        )
    elif "references" in raw_check:
        raise ProjectConfigError(
            f"{check_context} cannot define references.",
            suggestion="Use references only for foreign_key checks.",
        )

    return ConfiguredCheck(
        name=name,
        table=table_name,
        type=check_type,
        column=column,
        values=values,
        value=value,
        min_value=min_value,
        max_value=max_value,
        references=references,
    )


def _parse_foreign_key_reference(
    raw_references: object,
    *,
    table_name: str,
    check_name: str,
    config_path: Path,
) -> ForeignKeyReference:
    check_context = _project_check_context(
        table_name=table_name,
        check_name=check_name,
        config_path=config_path,
    )
    if not isinstance(raw_references, dict):
        raise ProjectConfigError(
            f"{check_context} must define references as a mapping.",
            suggestion="Use references: {table: customers, column: customer_id}.",
        )
    allowed_keys = {"table", "column"}
    extra_keys = set(raw_references) - allowed_keys
    if extra_keys:
        raise ProjectConfigError(
            f"Unsupported metadata for {check_context}: {_sorted_key_display(extra_keys)}.",
            suggestion="Keep foreign_key references to table and column only.",
        )

    raw_reference_table = raw_references.get("table")
    if not isinstance(raw_reference_table, str) or not raw_reference_table.strip():
        raise ProjectConfigError(
            f"{check_context} must define references.table as a non-empty string.",
            suggestion="Use references: {table: customers, column: customer_id}.",
        )
    try:
        reference_table = validate_table_alias(raw_reference_table)
    except TableMappingError as exc:
        raise ProjectConfigError(
            (
                f"Invalid foreign_key reference table alias "
                f"'{raw_reference_table}' for {check_context}."
            ),
            suggestion="Use letters, numbers, and underscores; start with a letter or underscore.",
        ) from exc

    reference_column = _parse_non_empty_string(
        raw_references.get("column"),
        field_name="references.column",
        table_name=table_name,
        check_name=check_name,
        config_path=config_path,
    )
    return ForeignKeyReference(table=reference_table, column=reference_column)


def _parse_non_empty_string(
    raw_value: object,
    *,
    field_name: str,
    table_name: str,
    check_name: str,
    config_path: Path,
) -> str:
    check_context = _project_check_context(
        table_name=table_name,
        check_name=check_name,
        config_path=config_path,
    )
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ProjectConfigError(
            f"{check_context} must define {field_name} as a non-empty string.",
            suggestion="Use a non-empty string value.",
        )
    return raw_value


def _parse_non_negative_int(
    raw_value: object,
    *,
    field_name: str,
    table_name: str,
    check_name: str,
    config_path: Path,
) -> int:
    check_context = _project_check_context(
        table_name=table_name,
        check_name=check_name,
        config_path=config_path,
    )
    if type(raw_value) is not int or raw_value < 0:
        raise ProjectConfigError(
            f"{check_context} must define {field_name} as a non-negative integer.",
            suggestion="Use a whole number greater than or equal to zero.",
        )
    return raw_value


_SUPPORTED_CHECK_TYPES = {
    "not_null",
    "unique",
    "accepted_values",
    "min",
    "max",
    "row_count_between",
    "foreign_key",
}
_CHECK_TYPES_REQUIRING_COLUMN = {
    "not_null",
    "unique",
    "accepted_values",
    "min",
    "max",
    "foreign_key",
}


def _supported_check_keys(check_type: str) -> set[str]:
    if check_type in {"not_null", "unique"}:
        return {"column"}
    if check_type == "accepted_values":
        return {"column", "values"}
    if check_type in {"min", "max"}:
        return {"column", "value"}
    if check_type == "row_count_between":
        return {"min", "max"}
    return {"column", "references"}


def _project_check_entries_context(*, table_name: str, config_path: Path) -> str:
    return f"Project catalog check entries for table '{table_name}' in {config_path}"


def _project_check_context(*, table_name: str, check_name: str, config_path: Path) -> str:
    return f"Project catalog check '{check_name}' for table '{table_name}' in {config_path}"


def _sorted_key_display(keys: set[object]) -> list[str]:
    return sorted(str(key) for key in keys)


def _is_yaml_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool, date))


def _validate_project_table_check_names(
    checks: tuple[ConfiguredCheck, ...],
    *,
    table_name: str,
    config_path: Path,
) -> None:
    seen_names: set[str] = set()
    for check in checks:
        if check.name in seen_names:
            raise ProjectConfigError(
                (
                    f"Duplicate project catalog check name '{check.name}' "
                    f"for table '{table_name}' in {config_path}."
                ),
                suggestion="Use unique check names within each table.",
            )
        seen_names.add(check.name)


def _validate_project_table_references(
    tables: Sequence[ProjectTableValue],
    *,
    config_path: Path,
) -> None:
    table_names = {table.name.lower(): table.name for table in tables}
    for table in tables:
        for check in table.checks:
            if check.type != "foreign_key" or check.references is None:
                continue
            if table_names.get(check.references.table.lower()) is None:
                raise ProjectConfigError(
                    (
                        f"Project catalog check '{check.name}' for table "
                        f"'{table.name}' in {config_path} references unknown "
                        f"table '{check.references.table}'."
                    ),
                    suggestion=(
                        "Add the referenced table to the project catalog or "
                        "update the foreign_key reference table."
                    ),
                )


def _unsupported_catalog_version(version: object) -> ProjectConfigError:
    return ProjectConfigError(
        f"Unsupported project catalog version: {version}.",
        suggestion=(
            f"Use version {SUPPORTED_VERSION} for an existing CSV-only project "
            f"or version {CURRENT_VERSION} for provider-neutral sources."
        ),
        code="catalog.version_unsupported",
    )


def _catalog_descriptor(source_type: str, *, table_name: str) -> DescriptorView:
    descriptor = build_builtin_descriptor_registry().resolve_type(source_type.strip())
    if descriptor is None:
        raise ProjectConfigError(
            f"Unknown source type '{source_type}' for project catalog table '{table_name}'.",
            suggestion="Use csv, parquet, json, ndjson, or excel.",
            code="catalog.source_type_unknown",
        )
    return descriptor


def _catalog_detection_error(
    detection: DetectionResult,
    *,
    table_name: str,
    path_value: str,
) -> FileMissingError | ProjectConfigError:
    if isinstance(detection, SelectedSource):
        raise TypeError("Selected catalog detection cannot be translated into an error.")
    diagnostic = detection.diagnostic
    is_missing = any(
        evidence.evidence_kind == "locator_shape" and evidence.stable_detail == "locator_missing"
        for evidence in diagnostic.evidence
    )
    suggestion = (
        None
        if diagnostic.required_action is None
        else diagnostic.required_action.kind.replace("_", " ")
    )
    if is_missing:
        return FileMissingError(
            f"Source locator not found: {path_value}",
            suggestion="Check the path or restore the source before adding it.",
            diagnostic=diagnostic,
        )
    return ProjectConfigError(
        f"Cannot register project catalog table '{table_name}': {diagnostic.message}",
        suggestion=suggestion,
        code=diagnostic.code.value,
        diagnostic=diagnostic,
    )


def _validate_catalog_source_options(
    descriptor: DescriptorView,
    options: FrozenSourceOptions,
    *,
    table_name: str,
) -> None:
    for key, value in options:
        option = descriptor.option_definition(key)
        if option is None:
            raise ProjectConfigError(
                (
                    f"Unknown source option '{key}' for type '{descriptor.source_kind}' "
                    f"on project catalog table '{table_name}'."
                ),
                suggestion="Remove the option or choose one declared by the source descriptor.",
                code="catalog.source_option_unknown",
            )
        if not descriptor.accepts_option_value(key, value):
            raise ProjectConfigError(
                (
                    f"Source option '{key}' for type '{descriptor.source_kind}' "
                    f"on project catalog table '{table_name}' must be {option.value_kind}."
                ),
                suggestion="Use a value matching the descriptor's basic option type.",
                code="catalog.source_option_type",
            )
    missing_required = tuple(
        option.key
        for option in descriptor.options
        if option.required and all(key != option.key for key, _value in options)
    )
    if missing_required:
        raise ProjectConfigError(
            (
                f"Project catalog table '{table_name}' is missing required source options: "
                f"{', '.join(missing_required)}."
            ),
            suggestion="Persist every required option explicitly.",
            code="catalog.source_option_required",
        )


def _catalog_table_locator(table: ProjectTableValue) -> str:
    return table.path if isinstance(table, ProjectTableV1) else table.source.locator


def _catalog_table_source_type(table: ProjectTableValue) -> str:
    return "csv" if isinstance(table, ProjectTableV1) else table.source.source_type


def _catalog_table_options(table: ProjectTableValue) -> FrozenSourceOptions:
    return () if isinstance(table, ProjectTableV1) else table.source.options


def _resolve_source_locator(path_value: str, *, base_dir: Path) -> Path:
    resolved = _absolute_source_locator(path_value, base_dir=base_dir)
    try:
        resolved.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise FileMissingError(
            f"Source locator not found: {path_value}",
            suggestion="Check the path or restore the source before adding it.",
        ) from exc
    return resolved


def _absolute_source_locator(path_value: str, *, base_dir: Path) -> Path:
    expanded = Path(path_value).expanduser()
    candidate = expanded if expanded.is_absolute() else base_dir / expanded
    return Path(os.path.abspath(os.path.normpath(os.fspath(candidate))))


def _validate_private_catalog_locators(context: ProjectContext) -> None:
    if not isinstance(context.config, ProjectConfigV2):
        return
    for table in context.config.tables:
        _reject_private_catalog_locator(
            _absolute_source_locator(table.source.locator, base_dir=context.project_root),
            table_name=table.name,
        )


def _reject_private_catalog_locator(locator: Path, *, table_name: str) -> None:
    if not is_private_result_artifact(locator):
        return
    raise ProjectConfigError(
        f"Project catalog table '{table_name}' cannot reference LocalQL private result storage.",
        suggestion="Use Save as source to create a normal source before catalog registration.",
        code="catalog.private_result_artifact",
    )


def _project_catalog_path_value(project_root: Path, resolved_path: Path) -> str:
    try:
        return resolved_path.relative_to(project_root).as_posix()
    except ValueError:
        return str(resolved_path)
