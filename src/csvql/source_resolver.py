"""Resolve source-operation inputs as local locators or project catalog aliases."""

from collections.abc import Mapping
from pathlib import Path

from csvql.exceptions import FileMissingError, ProjectConfigError, SourceError
from csvql.models import SourceDefinition
from csvql.operation import OperationContext
from csvql.project_config import (
    ProjectTableV1,
    load_project,
    project_tables_to_source_specs,
)
from csvql.source import (
    CSVSource,
    ResolvedSource,
    SourceRequest,
    build_source_request,
    csv_source_from_spec,
    source_from_path,
    source_request_from_definition,
    source_spec_from_catalog_table,
)
from csvql.source_runtime import resolve_source_request, source_kind_hint
from csvql.table_mapping import derive_alias_from_locator


def resolve_path_or_catalog_source(
    path_or_alias: str,
    *,
    base_dir: Path | None = None,
) -> CSVSource:
    """Resolve an inspect/sample argument as a path or catalog alias."""

    if _looks_like_path(path_or_alias):
        return source_from_path(path_or_alias, base_dir=base_dir)

    try:
        context = load_project(base_dir)
    except ProjectConfigError as exc:
        if "No .csvql.yml project catalog found." not in exc.message:
            raise
        return source_from_path(path_or_alias, base_dir=base_dir)

    alias_key = path_or_alias.lower()
    table = next(
        (
            catalog_table
            for catalog_table in context.config.tables
            if catalog_table.name.lower() == alias_key
        ),
        None,
    )
    if table is None:
        return source_from_path(path_or_alias, base_dir=base_dir)
    if not isinstance(table, ProjectTableV1):
        raise ProjectConfigError(
            (f"Project catalog table '{table.name}' uses a provider-neutral version 2 source."),
            suggestion="Use the shared source-operation resolver for version 2 catalogs.",
        )

    try:
        spec = source_spec_from_catalog_table(table, project_root=context.project_root)
    except ValueError as exc:
        if table.name.casefold().startswith("__localql_"):
            suggestion = (
                "Rename the table; aliases beginning with '__localql_' are reserved for LocalQL."
            )
        else:
            suggestion = "Use letters, numbers, and underscores; start with a letter or underscore."
        raise ProjectConfigError(
            f"Invalid project catalog table alias '{table.name}'.",
            suggestion=suggestion,
        ) from exc
    try:
        return csv_source_from_spec(spec, display_path=path_or_alias)
    except FileMissingError as exc:
        raise FileMissingError(
            f"CSV file not found for project catalog table '{table.name}': {table.path}",
            suggestion=(
                "Update .csvql.yml, run csvql add "
                f"{table.name} <path> --replace, or restore the CSV file."
            ),
        ) from exc


def resolve_operation_source(
    locator_or_alias: str,
    *,
    source_type: str | None = None,
    options: Mapping[str, object] | None = None,
    base_dir: Path | None = None,
    operation: OperationContext,
) -> ResolvedSource:
    """Resolve one inspect/sample/profile input through the shared source runtime."""

    anchor = base_dir or Path.cwd()
    explicit_options = {} if options is None else dict(options)
    provider_syntax_used = source_type is not None or bool(explicit_options)
    if not provider_syntax_used and not _looks_like_path(locator_or_alias):
        catalog_source = _resolve_catalog_alias(
            locator_or_alias,
            base_dir=anchor,
            operation=operation,
        )
        if catalog_source is not None:
            return catalog_source

    definition = SourceDefinition(
        derive_alias_from_locator(locator_or_alias, base_dir=anchor),
        locator_or_alias,
        source_type=source_type,
        options=explicit_options,
        base_dir=anchor,
    )
    return _resolve_request_or_raise_missing(
        source_request_from_definition(definition),
        display_reference=locator_or_alias,
        operation=operation,
    )


def _resolve_catalog_alias(
    alias: str,
    *,
    base_dir: Path,
    operation: OperationContext,
) -> ResolvedSource | None:
    try:
        context = load_project(base_dir)
    except ProjectConfigError as exc:
        if "No .csvql.yml project catalog found." not in exc.message:
            raise
        return None

    alias_key = alias.casefold()
    spec = next(
        (
            source_spec
            for source_spec in project_tables_to_source_specs(context)
            if source_spec.alias.casefold() == alias_key
        ),
        None,
    )
    if spec is None:
        return None
    return _resolve_request_or_raise_missing(
        build_source_request(
            alias=spec.alias,
            locator=spec.locator,
            anchor=spec.anchor,
            explicit_type=spec.kind,
            options=spec.options,
        ),
        display_reference=alias,
        operation=operation,
        catalog_alias=spec.alias,
    )


def _resolve_request_or_raise_missing(
    request: SourceRequest,
    *,
    display_reference: str,
    operation: OperationContext,
    catalog_alias: str | None = None,
) -> ResolvedSource:
    try:
        return resolve_source_request(request, operation=operation)
    except SourceError as exc:
        is_missing = (
            exc.code == "source_missing"
            if exc.diagnostic is None
            else any(
                evidence.evidence_kind == "locator_shape"
                and evidence.stable_detail == "locator_missing"
                for evidence in exc.diagnostic.evidence
            )
        )
        if not is_missing:
            raise
        if catalog_alias is not None:
            message = (
                f"Source not found for project catalog table '{catalog_alias}': {request.locator}"
            )
            suggestion = (
                "Update .csvql.yml, run csvql add "
                f"{catalog_alias} <locator> --replace, or restore the source."
            )
        else:
            if source_kind_hint(request) == "csv":
                message = f"CSV file not found: {display_reference}"
                suggestion = "Check the path or run from the directory that contains the CSV file."
            else:
                message = f"Source not found: {display_reference}"
                suggestion = "Check the locator or run from the directory that contains the source."
        raise FileMissingError(
            message,
            suggestion=suggestion,
            diagnostic=exc.diagnostic,
        ) from exc


def _looks_like_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("~")
        or Path(value).suffix != ""
    )
