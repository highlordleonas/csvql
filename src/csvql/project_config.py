"""Project catalog configuration loading and discovery."""

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from csvql.exceptions import ProjectConfigError, TableMappingError
from csvql.models import TableSource
from csvql.source import resolve_csv_path
from csvql.table_mapping import validate_table_alias

CONFIG_FILENAME = ".csvql.yml"
SUPPORTED_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProjectTable:
    """A project catalog table entry."""

    name: str
    path: str


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
            suggestion="Pass force=True to reinitialize the project catalog.",
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

    return resolve_csv_path(table.path, base_dir=context.project_root)


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
        table.name: {"path": table.path}
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
            f"Unsupported project catalog keys in {config_path}: {sorted(extra_keys)}.",
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

    allowed_keys = {"path"}
    extra_keys = set(raw_table) - allowed_keys
    if extra_keys:
        extra_keys_display = sorted(extra_keys)
        message = (
            f"Unsupported metadata for project catalog table '{name}' "
            f"in {config_path}: {extra_keys_display}."
        )
        raise ProjectConfigError(
            message,
            suggestion="Keep each table entry to a single path key.",
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

    return ProjectTable(name=name, path=raw_path)
