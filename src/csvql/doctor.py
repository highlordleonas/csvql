"""Project-health result objects and workflow for `csvql doctor`."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb

from csvql.checks import resolve_configured_column_name, validate_table_aliases
from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.project_config import (
    ProjectContext,
    ProjectTable,
    discover_project,
    load_project,
    resolve_catalog_path,
)
from csvql.sql_utils import quote_identifier

DoctorScope = Literal["project", "table", "check"]
DoctorStatus = Literal["passed", "warning", "failed"]
DOCTOR_VIEW_PREFIX = "__csvql_doctor_"
EXPECTED_TABLE_READINESS_ERRORS = (
    FileMissingError,
    OSError,
    duckdb.IOException,
    duckdb.InvalidInputException,
    duckdb.ParserException,
    duckdb.ConversionException,
)


@dataclass(frozen=True, slots=True)
class DoctorProbeResult:
    """One project-health finding emitted by `csvql doctor`."""

    name: str
    scope: DoctorScope
    status: DoctorStatus
    message: str
    table: str | None = None
    check: str | None = None
    path: Path | None = None
    resolved_path: Path | None = None
    column: str | None = None
    reference_table: str | None = None
    reference_column: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "scope": self.scope,
            "status": self.status,
            "message": self.message,
        }
        if self.table is not None:
            payload["table"] = self.table
        if self.check is not None:
            payload["check"] = self.check
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.resolved_path is not None:
            payload["resolved_path"] = str(self.resolved_path)
        if self.column is not None:
            payload["column"] = self.column
        if self.reference_table is not None:
            payload["reference_table"] = self.reference_table
        if self.reference_column is not None:
            payload["reference_column"] = self.reference_column
        return payload


@dataclass(frozen=True, slots=True)
class DoctorRunResult:
    """Aggregate result for a `csvql doctor` invocation."""

    project_root: Path | None
    config_path: Path | None
    probes: tuple[DoctorProbeResult, ...]

    @property
    def status(self) -> DoctorStatus:
        if any(probe.status == "failed" for probe in self.probes):
            return "failed"
        if any(probe.status == "warning" for probe in self.probes):
            return "warning"
        return "passed"

    @property
    def probe_count(self) -> int:
        return len(self.probes)

    @property
    def passed_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "passed")

    @property
    def warning_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "warning")

    @property
    def failed_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "failed")

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "probe_count": self.probe_count,
            "passed_count": self.passed_count,
            "warning_count": self.warning_count,
            "failed_count": self.failed_count,
            "project": {
                "config_path": str(self.config_path) if self.config_path is not None else None,
                "project_root": str(self.project_root) if self.project_root is not None else None,
            },
            "probes": [probe.as_dict() for probe in self.probes],
        }


def run_doctor(start_dir: Path | None = None) -> DoctorRunResult:
    """Run project-health probes for the nearest CSVQL project."""

    try:
        project_root, config_path = discover_project(start_dir)
    except ProjectConfigError as exc:
        return DoctorRunResult(
            project_root=None,
            config_path=None,
            probes=(
                DoctorProbeResult(
                    name="project_discovery",
                    scope="project",
                    status="warning",
                    message=exc.message,
                ),
            ),
        )

    probes: list[DoctorProbeResult] = [
        DoctorProbeResult(
            name="project_discovery",
            scope="project",
            status="passed",
            message="Discovered project catalog.",
            path=config_path,
            resolved_path=config_path,
        )
    ]

    try:
        context = load_project(start_dir)
        validate_table_aliases(context)
    except (ProjectConfigError, OSError) as exc:
        message = (
            exc.message
            if isinstance(exc, ProjectConfigError)
            else f"Failed to read project catalog {config_path}: {exc.strerror or str(exc)}."
        )
        probes.append(
            DoctorProbeResult(
                name="config_load",
                scope="project",
                status="failed",
                message=message,
                path=config_path,
                resolved_path=config_path,
            )
        )
        return DoctorRunResult(
            project_root=project_root,
            config_path=config_path,
            probes=tuple(probes),
        )

    probes.append(
        DoctorProbeResult(
            name="config_load",
            scope="project",
            status="passed",
            message="Loaded project catalog.",
            path=context.config_path,
            resolved_path=context.config_path,
        )
    )

    tables = tuple(
        sorted(context.config.tables, key=lambda table: (table.name.lower(), table.name))
    )
    if not tables:
        probes.append(
            DoctorProbeResult(
                name="catalog_tables_present",
                scope="project",
                status="warning",
                message="Project catalog has no configured tables.",
                path=context.config_path,
                resolved_path=context.config_path,
            )
        )
        return DoctorRunResult(
            project_root=context.project_root,
            config_path=context.config_path,
            probes=tuple(probes),
        )

    probes.append(
        DoctorProbeResult(
            name="catalog_tables_present",
            scope="project",
            status="passed",
            message=f"Project catalog has {len(tables)} configured table(s).",
            path=context.config_path,
            resolved_path=context.config_path,
        )
    )

    table_probes, column_names_by_table = _run_table_readiness_probes(context, tables)
    probes.extend(table_probes)
    probes.extend(_run_check_schema_probes(context, column_names_by_table))
    return DoctorRunResult(
        project_root=context.project_root,
        config_path=context.config_path,
        probes=tuple(probes),
    )


def _run_table_readiness_probes(
    context: ProjectContext,
    tables: tuple[ProjectTable, ...],
) -> tuple[tuple[DoctorProbeResult, ...], dict[str, tuple[str, ...]]]:
    probes: list[DoctorProbeResult] = []
    column_names_by_table: dict[str, tuple[str, ...]] = {}
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        for table in tables:
            try:
                resolved_path = resolve_catalog_path(table, context)
                relation = connection.read_csv(
                    str(resolved_path),
                    auto_detect=True,
                    header=True,
                )
                relation.create_view(_doctor_view_name(table.name), replace=True)
                discovered_columns = tuple(str(column) for column in relation.columns)
                connection.execute(
                    f"SELECT * FROM {quote_identifier(_doctor_view_name(table.name))} LIMIT 1"
                ).fetchall()
                column_names_by_table[table.name.lower()] = discovered_columns
            except EXPECTED_TABLE_READINESS_ERRORS as exc:
                probes.append(
                    DoctorProbeResult(
                        name="table_readiness",
                        scope="table",
                        status="failed",
                        message=str(exc),
                        table=table.name,
                    )
                )
                continue

            probes.append(
                DoctorProbeResult(
                    name="table_readiness",
                    scope="table",
                    status="passed",
                    message="Registered and read configured CSV through DuckDB.",
                    table=table.name,
                    path=Path(table.path),
                    resolved_path=resolved_path,
                )
            )
    finally:
        if connection is not None:
            connection.close()

    return tuple(probes), column_names_by_table


def _run_check_schema_probes(
    context: ProjectContext,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> tuple[DoctorProbeResult, ...]:
    probes: list[DoctorProbeResult] = []
    for table in sorted(context.config.tables, key=lambda item: (item.name.lower(), item.name)):
        if table.name.lower() not in column_names_by_table:
            continue
        for check in table.checks:
            reference = check.references
            if reference is not None and reference.table.lower() not in column_names_by_table:
                continue
            try:
                if check.type != "row_count_between":
                    resolve_configured_column_name(
                        check.table,
                        check.column,
                        column_names_by_table,
                    )
                if reference is not None:
                    resolve_configured_column_name(
                        reference.table,
                        reference.column,
                        column_names_by_table,
                    )
            except ProjectConfigError as exc:
                probes.append(
                    DoctorProbeResult(
                        name="check_schema_resolution",
                        scope="check",
                        status="failed",
                        message=exc.message,
                        table=check.table,
                        check=check.name,
                        column=check.column,
                        reference_table=reference.table if reference is not None else None,
                        reference_column=reference.column if reference is not None else None,
                    )
                )
                continue

            probes.append(
                DoctorProbeResult(
                    name="check_schema_resolution",
                    scope="check",
                    status="passed",
                    message="Resolved configured check columns against discovered schema.",
                    table=check.table,
                    check=check.name,
                    column=check.column,
                    reference_table=reference.table if reference is not None else None,
                    reference_column=reference.column if reference is not None else None,
                )
            )
    return tuple(probes)


def _doctor_view_name(table_name: str) -> str:
    return f"{DOCTOR_VIEW_PREFIX}{table_name.lower()}"
