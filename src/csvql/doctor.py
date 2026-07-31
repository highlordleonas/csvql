"""Project-health result objects and workflow for `csvql doctor`."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import duckdb

from csvql.checks import resolve_configured_column_name, validate_table_aliases
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    ConfigurationFailure,
    CSVQLError,
    FileMissingError,
    ProjectConfigError,
    SourceError,
)
from csvql.operation import OperationContext, OperationToken
from csvql.project_config import (
    ProjectContext,
    ProjectTableValue,
    discover_project,
    load_project,
    project_tables_to_source_specs,
)
from csvql.source import (
    ResolvedSource,
    SourceDiagnostic,
    SourceSpec,
    build_source_request,
)
from csvql.source_operations import SourceOperations
from csvql.source_runtime import default_source_components, resolve_source_request

DoctorScope = Literal["project", "table", "check"]
DoctorStatus = Literal["passed", "warning", "failed"]
EXPECTED_TABLE_READINESS_ERRORS = (
    CSVQLError,
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
    source_type: str | None = None
    diagnostic: SourceDiagnostic | None = None

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
        if self.source_type is not None:
            payload["source_type"] = self.source_type
        if self.diagnostic is not None:
            payload["diagnostic"] = {
                "version": 1,
                **self.diagnostic.as_dict(redaction="safe"),
            }
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

    try:
        default_source_components()
    except ConfigurationFailure:
        probes.append(
            DoctorProbeResult(
                name="source_registry_composition",
                scope="project",
                status="failed",
                message="LocalQL source-provider registry composition is invalid.",
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
            name="source_registry_composition",
            scope="project",
            status="passed",
            message="Validated source-provider registry and lazy factory composition.",
            path=context.config_path,
            resolved_path=context.config_path,
        )
    )

    project_tables = cast(Sequence[ProjectTableValue], context.config.tables)
    tables = tuple(sorted(project_tables, key=lambda table: (table.name.lower(), table.name)))
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
    tables: tuple[ProjectTableValue, ...],
) -> tuple[tuple[DoctorProbeResult, ...], dict[str, tuple[str, ...]]]:
    probes: list[DoctorProbeResult] = []
    column_names_by_table: dict[str, tuple[str, ...]] = {}
    specs_by_alias = {
        spec.alias.casefold(): spec for spec in project_tables_to_source_specs(context)
    }
    for table in tables:
        operation = OperationContext(OperationToken())
        spec = specs_by_alias[table.name.casefold()]
        resolved = None
        readiness_error: BaseException | None = None
        try:
            candidate = resolve_source_request(
                build_source_request(
                    alias=spec.alias,
                    locator=spec.locator,
                    anchor=spec.anchor,
                    explicit_type=spec.kind,
                    options=spec.options,
                ),
                operation=operation,
            )
            if not isinstance(candidate, ResolvedSource):
                raise RuntimeError("Doctor source resolution returned an invalid value.")
            resolved = candidate
            with CSVQLEngine(operation=operation) as engine:
                sample = SourceOperations(engine, resolved).sample(limit=1)
            column_names_by_table[table.name.lower()] = sample.columns
        except AttributeError as exc:
            if not _is_engine_interrupt_attachment_error(exc):
                raise
            readiness_error = exc
        except EXPECTED_TABLE_READINESS_ERRORS as exc:
            internal_failure = _exception_in_chain(exc, duckdb.InternalException)
            if internal_failure is not None:
                raise internal_failure from exc
            readiness_error = exc

        if readiness_error is not None:
            column_names_by_table.pop(table.name.lower(), None)
            probes.append(
                DoctorProbeResult(
                    name="table_readiness",
                    scope="table",
                    status="failed",
                    message=_table_readiness_error_message(
                        readiness_error,
                        table,
                        spec,
                    ),
                    table=table.name,
                    source_type=spec.kind,
                    diagnostic=(
                        readiness_error.diagnostic
                        if isinstance(readiness_error, CSVQLError)
                        else None
                    ),
                )
            )
            continue

        if resolved is None:
            raise RuntimeError("Table readiness completed without a resolved source.")

        probes.append(
            DoctorProbeResult(
                name="table_readiness",
                scope="table",
                status="passed",
                message=(f"Registered and read configured {spec.kind} source through DuckDB."),
                table=table.name,
                path=Path(spec.locator),
                resolved_path=Path(resolved.canonical_locator),
                source_type=spec.kind,
            )
        )

    return tuple(probes), column_names_by_table


def _table_readiness_error_message(
    error: BaseException,
    table: ProjectTableValue,
    spec: SourceSpec,
) -> str:
    message: str
    if isinstance(error, SourceError):
        if error.code == "source_missing":
            display_kind = "CSV file" if spec.kind == "csv" else "Source"
            message = (
                f"{display_kind} not found for project catalog table '{table.name}': {spec.locator}"
            )
            return _with_cleanup_uncertainty(message, error)
        if error.code == "source_bind_failed" and error.__cause__ is not None:
            message = str(error.__cause__)
            return _with_cleanup_uncertainty(message, error)
    return _with_cleanup_uncertainty(str(error), error)


def _with_cleanup_uncertainty(message: str, error: BaseException) -> str:
    notes = tuple(
        note
        for note in getattr(error, "__notes__", ())
        if isinstance(note, str) and note.startswith("Cleanup uncertainty:")
    )
    if not notes:
        return message
    return f"{message} {' '.join(notes)}"


def _exception_in_chain(
    error: BaseException,
    expected_type: type[BaseException],
) -> BaseException | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, expected_type):
            return current
        seen.add(id(current))
        current = current.__cause__
    return None


def _is_engine_interrupt_attachment_error(error: AttributeError) -> bool:
    if error.name != "interrupt":
        return False

    expected_code = CSVQLEngine._ensure_connection.__code__
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code is expected_code:
            return True
        traceback = traceback.tb_next
    return False


def _run_check_schema_probes(
    context: ProjectContext,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> tuple[DoctorProbeResult, ...]:
    probes: list[DoctorProbeResult] = []
    project_tables = cast(Sequence[ProjectTableValue], context.config.tables)
    for table in sorted(
        project_tables,
        key=lambda item: (item.name.lower(), item.name),
    ):
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
