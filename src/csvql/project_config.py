"""Project catalog configuration loading and discovery."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

from csvql.exceptions import FileMissingError, ProjectConfigError, TableMappingError
from csvql.models import TableSource
from csvql.quality import CheckType, ConfiguredCheck, ForeignKeyReference
from csvql.source import resolve_csv_path
from csvql.table_mapping import validate_table_alias

CONFIG_FILENAME = ".csvql.yml"
SUPPORTED_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProjectTable:
    """A project catalog table entry."""

    name: str
    path: str
    checks: tuple[ConfiguredCheck, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectTableListing:
    """A resolved project catalog table listing."""

    name: str
    path: str
    resolved_path: Path


@dataclass(frozen=True, slots=True)
class ProjectTablesResult:
    """A deterministic snapshot of the project catalog tables."""

    project_root: Path
    config_path: Path
    tables: tuple[ProjectTableListing, ...]


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """The on-disk project catalog configuration."""

    version: int
    tables: tuple[ProjectTable, ...]


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """Resolved project catalog state."""

    project_root: Path
    config_path: Path
    config: ProjectConfig


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
        config=ProjectConfig(version=SUPPORTED_VERSION, tables=()),
    )
    return save_project(context)


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


def save_project(context: ProjectContext) -> ProjectContext:
    """Persist a project catalog configuration deterministically."""

    config_path = context.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _project_config_payload(context.config)
    config_path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return context


def resolve_catalog_path(table: ProjectTable, context: ProjectContext) -> Path:
    """Resolve a table path relative to the project root."""

    try:
        return resolve_csv_path(table.path, base_dir=context.project_root)
    except FileMissingError as exc:
        raise FileMissingError(
            f"CSV file not found for project catalog table '{table.name}': {table.path}",
            suggestion=(
                "Update .csvql.yml, run csvql add "
                f"{table.name} <path> --replace, or restore the CSV file."
            ),
        ) from exc


def add_project_table(
    context: ProjectContext,
    name: str,
    path_value: str,
    *,
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

    base_dir = (invocation_dir or Path.cwd()).expanduser().resolve()
    resolved_path = resolve_csv_path(path_value, base_dir=base_dir)
    stored_path = _project_catalog_path_value(context.project_root, resolved_path)
    tables = list(context.config.tables)
    existing_index = next(
        (index for index, table in enumerate(tables) if table.name == table_name),
        None,
    )
    if existing_index is not None and not replace:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' already exists in {context.config_path}.",
            suggestion="Pass --replace to update the existing table entry.",
        )
    if existing_index is not None:
        existing_table = tables[existing_index]
        tables[existing_index] = ProjectTable(
            name=table_name,
            path=stored_path,
            checks=existing_table.checks,
        )
    else:
        tables.append(ProjectTable(name=table_name, path=stored_path))

    updated_context = ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=ProjectConfig(
            version=context.config.version,
            tables=tuple(sorted(tables, key=lambda table: table.name)),
        ),
    )
    return save_project(updated_context)


def build_project_tables_result(context: ProjectContext) -> ProjectTablesResult:
    """Build a sorted, resolved view of the project catalog tables."""

    tables = tuple(
        ProjectTableListing(
            name=table.name,
            path=table.path,
            resolved_path=resolve_catalog_path(table, context),
        )
        for table in sorted(context.config.tables, key=lambda table: table.name)
    )
    return ProjectTablesResult(
        project_root=context.project_root,
        config_path=context.config_path,
        tables=tables,
    )


def project_tables_to_sources(context: ProjectContext) -> list[TableSource]:
    """Convert project catalog tables into queryable table sources."""

    return [
        TableSource(name=table.name, path=resolve_catalog_path(table, context))
        for table in context.config.tables
    ]


def _project_config_payload(config: ProjectConfig) -> dict[str, object]:
    if config.version != SUPPORTED_VERSION:
        raise ProjectConfigError(
            f"Unsupported project catalog version: {config.version}.",
            suggestion=f"Use version {SUPPORTED_VERSION} or reinitialize the project catalog.",
        )

    tables_payload = {
        table.name: _project_table_payload(table)
        for table in sorted(config.tables, key=lambda table: table.name)
    }
    return {
        "version": config.version,
        "tables": tables_payload,
    }


def _parse_project_config(raw_config: object, *, config_path: Path) -> ProjectConfig:
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
            suggestion=f"Set version: {SUPPORTED_VERSION} in .csvql.yml.",
        )
    if type(version) is not int:
        raise ProjectConfigError(
            f"Project catalog version in {config_path} must be an integer.",
            suggestion=f"Set version: {SUPPORTED_VERSION} in .csvql.yml.",
        )
    if version != SUPPORTED_VERSION:
        raise ProjectConfigError(
            f"Unsupported project catalog version: {version}.",
            suggestion=f"Use version {SUPPORTED_VERSION} or reinitialize the project catalog.",
        )

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

    project_tables = tuple(
        _parse_project_table_entry(name, table_value, config_path=config_path)
        for name, table_value in tables.items()
    )
    _validate_project_table_references(project_tables, config_path=config_path)
    return ProjectConfig(version=SUPPORTED_VERSION, tables=project_tables)


def _parse_project_table_entry(
    raw_name: object,
    raw_table: object,
    *,
    config_path: Path,
) -> ProjectTable:
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

    return ProjectTable(name=name, path=raw_path, checks=checks)


def _project_table_payload(table: ProjectTable) -> dict[str, object]:
    payload: dict[str, object] = {"path": table.path}
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
    if check.value is not None:
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
    return raw_value.strip()


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
    return value is None or isinstance(value, (str, int, float, bool))


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
    tables: tuple[ProjectTable, ...],
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


def _project_catalog_path_value(project_root: Path, resolved_path: Path) -> str:
    try:
        return resolved_path.relative_to(project_root).as_posix()
    except ValueError:
        return str(resolved_path)
