"""Small public Python API for project-backed CSVQL workflows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from csvql.checks import run_configured_checks
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    CSVInspectionError,
    CSVQLError,
    ExportError,
    FileMissingError,
    ProjectConfigError,
    SourceError,
)
from csvql.export import (
    ExportFormat,
    resolve_export_path,
)
from csvql.models import (
    InspectResult,
    ProfileResult,
    QueryResult,
    SampleResult,
    SourceDefinition,
    TableSource,
)
from csvql.operation import OperationContext, OperationToken
from csvql.project_config import (
    ProjectContext,
    ProjectTablesResult,
    ProjectTableValue,
    build_project_tables_result,
    load_project,
    project_tables_to_source_specs,
)
from csvql.quality import CheckRunResult
from csvql.query_workflow import (
    QueryRequest,
)
from csvql.result_export import write_query_request_export
from csvql.source import (
    ResolvedSource,
    SourceRequest,
    SourceSpec,
    build_source_request,
    source_spec_from_table_source,
)
from csvql.source_operations import SourceOperations
from csvql.source_runtime import resolve_source_request
from csvql.sql_file import load_sql_file


@dataclass(frozen=True, slots=True)
class CSVQLSession:
    """Thin project-backed API over existing CSVQL services."""

    _context: ProjectContext

    @classmethod
    def from_config(cls, start_dir: str | Path = ".") -> CSVQLSession:
        """Create a session from the nearest project config at or above ``start_dir``."""

        return cls(load_project(Path(start_dir)))

    def tables(self) -> ProjectTablesResult:
        """Return the configured project table aliases and resolved paths."""

        return build_project_tables_result(self._context)

    def query(
        self,
        sql: str,
        *,
        sources: Sequence[TableSource] | Sequence[SourceDefinition] | None = None,
    ) -> QueryResult:
        """Run trusted local SQL against catalog or explicitly supplied sources."""

        operation = OperationContext(OperationToken())
        resolved_sources = _resolve_session_sources(
            self._context,
            sources,
            operation=operation,
        )
        try:
            with CSVQLEngine(operation=operation) as engine:
                engine.prepare_sources(resolved_sources)
                return engine.query(sql)
        except SourceError as exc:
            source = next(
                (candidate for candidate in resolved_sources if candidate.spec.alias == exc.alias),
                None,
            )
            alias = exc.alias or "source"
            source_path = source.canonical_locator if source is not None else "<unavailable>"
            source_kind = source.source_kind if source is not None else (exc.kind or "source")
            if source_kind == "csv":
                message = f"Failed to register CSV table '{alias}' from {source_path}."
                suggestion = "Check that the file is a readable CSV with a header row."
            else:
                message = f"Failed to register {source_kind} source '{alias}' from {source_path}."
                suggestion = "Check the source locator, options, and provider dependency."
            raise CSVQLError(
                message,
                suggestion=suggestion,
                diagnostic=exc.diagnostic,
            ) from exc

    def run_file(
        self,
        path: str | Path,
        *,
        sources: Sequence[TableSource] | Sequence[SourceDefinition] | None = None,
    ) -> QueryResult:
        """Load and run a saved SQL file resolved from the project root."""

        sql_file = load_sql_file(str(path), base_dir=self._context.project_root)
        return self.query(sql_file.sql, sources=sources)

    def inspect(
        self,
        table: str | TableSource | SourceDefinition,
        *,
        exact: bool = False,
    ) -> InspectResult:
        """Inspect a catalog alias or one intentional source definition."""

        operation = OperationContext(OperationToken())
        source = _resolved_session_source(self._context, table, operation=operation)
        display_name = _source_display_name(table)
        try:
            with CSVQLEngine(operation=operation) as engine:
                result = SourceOperations(engine, source).inspect(exact=exact)
            return replace(result, source={**result.source, "display_path": display_name})
        except CSVQLError as exc:
            display_kind = "CSV file" if source.source_kind == "csv" else "source"
            raise CSVInspectionError(
                f"Failed to inspect {display_kind}: {display_name}",
                suggestion="Check that the source is readable and has a relational schema.",
                diagnostic=exc.diagnostic,
            ) from exc

    def sample(
        self,
        table: str | TableSource | SourceDefinition,
        *,
        limit: int = 10,
    ) -> SampleResult:
        """Return a bounded sample from a catalog alias or source definition."""

        operation = OperationContext(OperationToken())
        source = _resolved_session_source(self._context, table, operation=operation)
        display_name = _source_display_name(table)
        try:
            with CSVQLEngine(operation=operation) as engine:
                result = SourceOperations(engine, source).sample(limit=limit)
            return replace(result, source={**result.source, "display_path": display_name})
        except CSVQLError as exc:
            display_kind = "CSV file" if source.source_kind == "csv" else "source"
            raise CSVInspectionError(
                f"Failed to sample {display_kind}: {display_name}",
                suggestion="Check that the source is readable and has a relational schema.",
                diagnostic=exc.diagnostic,
            ) from exc

    def profile(
        self,
        table: str | TableSource | SourceDefinition,
    ) -> ProfileResult:
        """Profile a catalog alias or source definition."""

        operation = OperationContext(OperationToken())
        source = _resolved_session_source(self._context, table, operation=operation)
        display_name = _source_display_name(table)
        try:
            with CSVQLEngine(operation=operation) as engine:
                result = SourceOperations(engine, source).profile()
            return replace(result, source={**result.source, "display_path": display_name})
        except CSVQLError as exc:
            display_kind = "CSV file" if source.source_kind == "csv" else "source"
            raise CSVInspectionError(
                f"Failed to profile {display_kind}: {display_name}",
                suggestion="Check that the source is readable and has a relational schema.",
                diagnostic=exc.diagnostic,
            ) from exc

    def check(
        self,
        table: str | None = None,
        *,
        show_failures: bool = False,
        failure_limit: int = 5,
    ) -> CheckRunResult:
        """Run configured data-quality checks for the project or one table alias."""

        return run_configured_checks(
            self._context,
            table_name=table,
            show_failures=show_failures,
            failure_limit=failure_limit,
        )

    def export(
        self,
        sql_file: str | Path,
        out: str | Path,
        *,
        format: ExportFormat | str = ExportFormat.json,
        force: bool = False,
        sources: Sequence[TableSource] | Sequence[SourceDefinition] | None = None,
    ) -> Path:
        """Run a saved SQL file and export the result, defaulting to JSON output."""

        export_format = _export_format(format)
        output_path = resolve_export_path(
            str(out),
            base_dir=self._context.project_root,
            force=force,
        )
        loaded_sql = load_sql_file(str(sql_file), base_dir=self._context.project_root)
        operation = OperationContext(OperationToken())
        resolved_sources = _resolve_session_sources(
            self._context,
            sources,
            operation=operation,
        )
        request = QueryRequest(
            sql=loaded_sql.sql,
            required_sources=resolved_sources,
            fallback_sources=(),
        )
        try:
            with CSVQLEngine(operation=operation) as engine:
                write_query_request_export(
                    engine,
                    request,
                    output_path,
                    export_format=export_format,
                    overwrite=force,
                    operation=operation,
                )
        except SourceError as exc:
            source = next(
                (candidate for candidate in resolved_sources if candidate.spec.alias == exc.alias),
                None,
            )
            alias = exc.alias or "source"
            source_path = source.canonical_locator if source is not None else "<unavailable>"
            source_kind = source.source_kind if source is not None else (exc.kind or "source")
            if source_kind == "csv":
                message = f"Failed to register CSV table '{alias}' from {source_path}."
                suggestion = "Check that the file is a readable CSV with a header row."
            else:
                message = f"Failed to register {source_kind} source '{alias}' from {source_path}."
                suggestion = "Check the source locator, options, and provider dependency."
            raise CSVQLError(
                message,
                suggestion=suggestion,
                diagnostic=exc.diagnostic,
            ) from exc
        return output_path


def _resolve_session_sources(
    context: ProjectContext,
    sources: Sequence[TableSource | SourceDefinition] | None,
    *,
    operation: OperationContext,
) -> tuple[ResolvedSource, ...]:
    if sources is None:
        specs = project_tables_to_source_specs(context)
        return tuple(
            _resolve_source_spec(
                spec,
                operation=operation,
                catalog_alias=spec.alias,
            )
            for spec in specs
        )

    source_inputs = tuple(sources)
    input_types = {type(source) for source in source_inputs}
    if not input_types <= {TableSource} and not input_types <= {SourceDefinition}:
        raise CSVQLError(
            "Python source inputs must be one homogeneous sequence.",
            suggestion="Pass only TableSource values or only SourceDefinition values.",
        )
    resolved: list[ResolvedSource] = []
    for source in source_inputs:
        if isinstance(source, TableSource):
            spec = source_spec_from_table_source(
                source,
                anchor=context.project_root,
            )
            resolved.append(_resolve_source_spec(spec, operation=operation))
            continue
        if not isinstance(source, SourceDefinition):
            raise TypeError("Unsupported Python source input.")
        request = build_source_request(
            alias=source.alias,
            locator=source.locator,
            anchor=source.base_dir or context.project_root,
            explicit_type=source.source_type,
            options=source.options,
        )
        resolved.append(
            _resolve_source_request(
                request,
                operation=operation,
                display_reference=source.locator,
            )
        )
    return tuple(resolved)


def _resolved_session_source(
    context: ProjectContext,
    source: str | TableSource | SourceDefinition,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    if isinstance(source, str):
        return _resolved_catalog_source(context, source, operation=operation)
    return _resolve_session_sources(
        context,
        (source,),
        operation=operation,
    )[0]


def _resolved_catalog_source(
    context: ProjectContext,
    table_name: str,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    return _resolve_catalog_source(
        context,
        _project_table(context, table_name),
        operation=operation,
    )


def _resolve_catalog_source(
    context: ProjectContext,
    table: ProjectTableValue,
    *,
    operation: OperationContext,
) -> ResolvedSource:
    spec = next(
        (
            candidate
            for candidate in project_tables_to_source_specs(context)
            if candidate.alias.casefold() == table.name.casefold()
        ),
        None,
    )
    if spec is None:
        raise RuntimeError("Catalog source declaration was not found.")
    return _resolve_source_spec(
        spec,
        operation=operation,
        catalog_alias=table.name,
    )


def _resolve_source_spec(
    spec: SourceSpec,
    *,
    operation: OperationContext,
    catalog_alias: str | None = None,
) -> ResolvedSource:
    return _resolve_source_request(
        build_source_request(
            alias=spec.alias,
            locator=spec.locator,
            anchor=spec.anchor,
            explicit_type=spec.kind,
            options=spec.options,
        ),
        operation=operation,
        display_reference=spec.locator,
        catalog_alias=catalog_alias,
    )


def _resolve_source_request(
    request: SourceRequest,
    *,
    operation: OperationContext,
    display_reference: str,
    catalog_alias: str | None = None,
) -> ResolvedSource:
    try:
        resolved = resolve_source_request(
            request,
            operation=operation,
        )
        if not isinstance(resolved, ResolvedSource):
            raise RuntimeError("Catalog source resolution returned an invalid value.")
        return resolved
    except SourceError as exc:
        if exc.code == "source_missing":
            display_kind = "CSV file" if request.explicit_type == "csv" else "Source"
            if catalog_alias is None:
                raise FileMissingError(
                    f"{display_kind} not found: {display_reference}",
                    suggestion="Check the source locator and its project-relative anchor.",
                    diagnostic=exc.diagnostic,
                ) from exc
            suggestion = (
                "Update .csvql.yml, run csvql add "
                f"{catalog_alias} <path> --replace, or restore the CSV file."
                if request.explicit_type == "csv"
                else (
                    "Update .csvql.yml, run csvql add "
                    f"{catalog_alias} <locator> --replace, or restore the source."
                )
            )
            raise FileMissingError(
                (
                    f"{display_kind} not found for project catalog table "
                    f"'{catalog_alias}': {request.locator}"
                ),
                suggestion=suggestion,
                diagnostic=exc.diagnostic,
            ) from exc
        raise


def _project_table(context: ProjectContext, table_name: str) -> ProjectTableValue:
    normalized = table_name.strip().lower()
    match = next(
        (table for table in context.config.tables if table.name.lower() == normalized),
        None,
    )
    if match is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' was not found in {context.config_path}.",
            suggestion="Run csvql tables to list configured table aliases.",
        )
    return match


def _source_display_name(source: str | TableSource | SourceDefinition) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, TableSource):
        return source.name
    return source.alias


def _export_format(value: ExportFormat | str) -> ExportFormat:
    if isinstance(value, ExportFormat):
        return value
    try:
        return ExportFormat(value)
    except ValueError as exc:
        raise ExportError(
            f"Unsupported export format: {value}",
            suggestion="Use csv, json, ndjson, parquet, excel, markdown, or text.",
        ) from exc
