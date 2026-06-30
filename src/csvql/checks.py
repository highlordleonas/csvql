"""DuckDB-backed data-quality check execution."""

from collections.abc import Iterable, Sequence
from typing import cast

import duckdb

from csvql.exceptions import CSVInspectionError, ProjectConfigError
from csvql.project_config import ProjectContext, ProjectTable, resolve_catalog_path
from csvql.quality import (
    CheckFailureSample,
    CheckResult,
    CheckRunResult,
    ConfiguredCheck,
    RunStatus,
)
from csvql.sql_utils import quote_identifier

CHECK_VIEW_PREFIX = "__csvql_check_"
CHECK_ROWS_ALIAS = "__csvql_check_rows"
CHECK_ROW_NUMBER_COLUMN = "__csvql_row_number"
_SUPPORTED_CHECK_TYPES = {
    "not_null",
    "unique",
    "accepted_values",
    "min",
    "max",
    "row_count_between",
    "foreign_key",
}


def run_configured_checks(
    context: ProjectContext,
    *,
    table_name: str | None,
    show_failures: bool,
    failure_limit: int,
) -> CheckRunResult:
    """Run configured data-quality checks from a project catalog."""

    if failure_limit < 1:
        raise ProjectConfigError(
            "Failure limit must be at least 1.",
            suggestion="Pass a failure limit of 1 or greater.",
        )

    _validate_table_aliases(context)
    selected_tables = _select_tables(context, table_name)
    checks = tuple(check for table in selected_tables for check in table.checks)
    if not checks:
        warning = (
            f"No data quality checks configured for table '{table_name}'."
            if table_name is not None
            else "No data quality checks configured."
        )
        return CheckRunResult(status="passed", checks=(), warnings=(warning,))

    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        column_names_by_table = _register_tables(
            connection,
            context,
            _required_tables(context, selected_tables),
        )
        results = tuple(
            _run_check(
                connection,
                check,
                column_names_by_table=column_names_by_table,
                show_failures=show_failures,
                failure_limit=failure_limit,
            )
            for check in checks
        )
    except CSVInspectionError:
        raise
    except duckdb.Error as exc:
        raise CSVInspectionError(
            "Failed to run data quality checks.",
            suggestion=(
                "Check that configured columns exist and values compare cleanly with "
                "DuckDB-inferred CSV types."
            ),
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    status: RunStatus = (
        "failed" if any(result.status == "failed" for result in results) else "passed"
    )
    return CheckRunResult(status=status, checks=results, warnings=())


def _select_tables(
    context: ProjectContext,
    table_name: str | None,
) -> tuple[ProjectTable, ...]:
    tables = tuple(
        sorted(context.config.tables, key=lambda table: (table.name.lower(), table.name))
    )
    if table_name is None:
        return tables

    normalized = table_name.strip().lower()
    match = next((table for table in tables if table.name.lower() == normalized), None)
    if match is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' was not found in {context.config_path}.",
            suggestion="Run csvql tables to list configured table aliases.",
        )
    return (match,)


def _validate_table_aliases(context: ProjectContext) -> None:
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for table in context.config.tables:
        normalized = table.name.lower()
        existing = seen.get(normalized)
        if existing is None:
            seen[normalized] = table.name
            continue
        if existing != table.name:
            collisions.append((existing, table.name))

    if collisions:
        collision_display = ", ".join(
            f"'{first}' and '{second}'" for first, second in sorted(collisions)
        )
        raise ProjectConfigError(
            f"Project catalog table aliases differ only by case: {collision_display}.",
            suggestion="Rename one of the colliding aliases before running csvql check.",
        )


def _required_tables(
    context: ProjectContext,
    selected_tables: tuple[ProjectTable, ...],
) -> tuple[ProjectTable, ...]:
    tables_by_name = {table.name.lower(): table for table in context.config.tables}
    required_names = {table.name.lower() for table in selected_tables}
    for table in selected_tables:
        for check in table.checks:
            if check.references is not None:
                required_names.add(check.references.table.lower())

    required_tables: list[ProjectTable] = []
    for required_name in sorted(required_names):
        if required_name not in tables_by_name:
            raise ProjectConfigError(
                (
                    f"Referenced project catalog table '{required_name}' was not found in "
                    f"{context.config_path}."
                ),
                suggestion="Add the referenced table to .csvql.yml before running csvql check.",
            )
        required_tables.append(tables_by_name[required_name])
    return tuple(required_tables)


def _register_tables(
    connection: duckdb.DuckDBPyConnection,
    context: ProjectContext,
    tables: Iterable[ProjectTable],
) -> dict[str, tuple[str, ...]]:
    column_names_by_table: dict[str, tuple[str, ...]] = {}
    for table in tables:
        try:
            resolved_path = resolve_catalog_path(table, context)
            relation = connection.read_csv(
                str(resolved_path),
                auto_detect=True,
                header=True,
            )
            relation.create_view(_view_name(table.name), replace=True)
            column_names_by_table[table.name.lower()] = tuple(
                str(column) for column in relation.columns
            )
        except (OSError, duckdb.Error) as exc:
            raise CSVInspectionError(
                f"Failed to run data quality checks for project catalog table '{table.name}'.",
                suggestion="Check that the configured CSV file exists and is readable.",
            ) from exc
    return column_names_by_table


def _view_name(table_name: str) -> str:
    return f"{CHECK_VIEW_PREFIX}{table_name.lower()}"


def _run_check(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    *,
    column_names_by_table: dict[str, tuple[str, ...]],
    show_failures: bool,
    failure_limit: int,
) -> CheckResult:
    _validate_check_execution(check)
    failed_count = _failed_count(connection, check, column_names_by_table)
    failures = (
        _failure_samples(
            connection,
            check,
            column_names_by_table=column_names_by_table,
            limit=failure_limit,
        )
        if show_failures and failed_count > 0
        else ()
    )
    return CheckResult(
        name=check.name,
        table=check.table,
        type=check.type,
        column=check.column,
        status="failed" if failed_count else "passed",
        failed_count=failed_count,
        failures=failures,
    )


def _validate_check_execution(check: ConfiguredCheck) -> None:
    context = _check_context(check)
    if check.type not in _SUPPORTED_CHECK_TYPES:
        raise ProjectConfigError(
            f"{context} uses unsupported check type '{check.type}'.",
            suggestion="Use one of the supported data quality check types.",
        )
    if check.column is None and check.type != "row_count_between":
        raise ProjectConfigError(
            f"{context} must define a column.",
            suggestion="Add a column for column-level checks.",
        )
    if check.type == "row_count_between":
        if check.min_value is None and check.max_value is None:
            raise ProjectConfigError(
                f"{context} must define min, max, or both.",
                suggestion="Use min, max, or both row-count bounds.",
            )
        min_value = (
            _require_strict_non_negative_int(check.min_value, field_name="min")
            if check.min_value is not None
            else None
        )
        max_value = (
            _require_strict_non_negative_int(check.max_value, field_name="max")
            if check.max_value is not None
            else None
        )
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ProjectConfigError(
                f"{context} has min greater than max.",
                suggestion="Set min to a value less than or equal to max.",
            )
    if check.type in {"min", "max"} and check.value is None:
        raise ProjectConfigError(
            f"{context} cannot use a null threshold.",
            suggestion="Set value to a non-null scalar for min and max checks.",
        )
    if check.type == "accepted_values" and not check.values:
        raise ProjectConfigError(
            f"{context} must define a non-empty accepted values list.",
            suggestion="Use at least one accepted value.",
        )
    if check.type == "foreign_key" and check.references is None:
        raise ProjectConfigError(
            f"{context} must define a foreign key reference.",
            suggestion="Add a referenced table and column for foreign_key checks.",
        )


def _failed_count(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> int:
    if check.type == "not_null":
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _fetch_scalar_int(connection, _not_null_count_sql(check, column_name))
    if check.type == "unique":
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _fetch_scalar_int(connection, _unique_count_sql(check, column_name))
    if check.type == "accepted_values":
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _fetch_scalar_int(
            connection,
            _accepted_values_count_sql(check, column_name),
            _accepted_values_parameters(check),
        )
    if check.type == "min":
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _fetch_scalar_int(connection, _min_count_sql(check, column_name), (check.value,))
    if check.type == "max":
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _fetch_scalar_int(connection, _max_count_sql(check, column_name), (check.value,))
    if check.type == "row_count_between":
        return _row_count_between_failure_count(connection, check)
    if check.type == "foreign_key":
        reference = check.references
        if reference is None:
            raise ProjectConfigError(
                f"{_check_context(check)} must define a foreign key reference.",
                suggestion="Add a referenced table and column for foreign_key checks.",
            )
        child_column = _resolve_column_name(check.table, check.column, column_names_by_table)
        parent_column = _resolve_column_name(
            reference.table,
            reference.column,
            column_names_by_table,
        )
        return _fetch_scalar_int(
            connection,
            _foreign_key_count_sql(check, child_column, parent_column),
        )
    raise AssertionError(f"Unhandled check type: {check.type}")


def _failure_samples(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    *,
    column_names_by_table: dict[str, tuple[str, ...]],
    limit: int,
) -> tuple[CheckFailureSample, ...]:
    if check.type in {"not_null", "accepted_values", "min", "max"}:
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _row_level_failure_samples(connection, check, column_name, limit=limit)
    if check.type == "unique":
        column_name = _resolve_column_name(check.table, check.column, column_names_by_table)
        return _unique_failure_samples(connection, check, column_name, limit=limit)
    if check.type == "row_count_between":
        return (_row_count_between_failure_sample(connection, check),)
    if check.type == "foreign_key":
        reference = check.references
        if reference is None:
            raise ProjectConfigError(
                f"{_check_context(check)} must define a foreign key reference.",
                suggestion="Add a referenced table and column for foreign_key checks.",
            )
        child_column = _resolve_column_name(check.table, check.column, column_names_by_table)
        parent_column = _resolve_column_name(
            reference.table,
            reference.column,
            column_names_by_table,
        )
        return _foreign_key_failure_samples(
            connection,
            check,
            child_column,
            parent_column,
            limit=limit,
        )
    raise AssertionError(f"Unhandled check type: {check.type}")


def _row_level_failure_samples(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    column_name: str,
    *,
    limit: int,
) -> tuple[CheckFailureSample, ...]:
    query = _row_level_failure_sql(check, column_name)
    rows = _fetch_rows(connection, query, _row_level_failure_parameters(check, limit))
    samples: list[CheckFailureSample] = []
    for row in rows:
        row_number = _as_int(row[CHECK_ROW_NUMBER_COLUMN])
        row_dict = {name: value for name, value in row.items() if name != CHECK_ROW_NUMBER_COLUMN}
        samples.append(
            CheckFailureSample(
                row_number=row_number,
                value=row_dict[column_name],
                row=row_dict,
            )
        )
    return tuple(samples)


def _unique_failure_samples(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    column_name: str,
    *,
    limit: int,
) -> tuple[CheckFailureSample, ...]:
    rows = _fetch_rows(connection, _unique_failure_samples_sql(check, column_name), (limit,))
    return tuple(
        CheckFailureSample(value=row["value"], observed=_as_int(row["observed"])) for row in rows
    )


def _row_count_between_failure_sample(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
) -> CheckFailureSample:
    observed = _fetch_scalar_int(
        connection,
        f"SELECT COUNT(*) FROM {quote_identifier(_view_name(check.table))}",
    )
    if check.min_value is not None and check.max_value is not None:
        return CheckFailureSample(
            observed=observed,
            min_value=check.min_value,
            max_value=check.max_value,
        )
    if check.min_value is not None:
        return CheckFailureSample(observed=observed, min_value=check.min_value)
    if check.max_value is not None:
        return CheckFailureSample(observed=observed, max_value=check.max_value)
    return CheckFailureSample(observed=observed)


def _foreign_key_failure_samples(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
    child_column: str,
    parent_column: str,
    *,
    limit: int,
) -> tuple[CheckFailureSample, ...]:
    rows = _fetch_rows(
        connection,
        _foreign_key_samples_sql(check, child_column, parent_column),
        (limit,),
    )
    reference = check.references
    return tuple(
        CheckFailureSample(
            row_number=_as_int(row[CHECK_ROW_NUMBER_COLUMN]),
            value=row[child_column],
            row={name: value for name, value in row.items() if name != CHECK_ROW_NUMBER_COLUMN},
            reference_table=reference.table if reference is not None else None,
            reference_column=reference.column if reference is not None else None,
        )
        for row in rows
    )


def _fetch_scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] = (),
) -> int:
    row = connection.execute(query, parameters).fetchone()
    if row is None or row[0] is None:
        return 0
    return _as_int(row[0])


def _fetch_rows(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] = (),
) -> tuple[dict[str, object], ...]:
    cursor = connection.execute(query, parameters)
    column_names = tuple(column[0] for column in cursor.description or ())
    return tuple(
        {name: value for name, value in zip(column_names, row, strict=True)}
        for row in cursor.fetchall()
    )


def _not_null_count_sql(check: ConfiguredCheck, column_name: str) -> str:
    return (
        f"SELECT COUNT(*) FROM {quote_identifier(_view_name(check.table))} "
        f"WHERE {quote_identifier(column_name)} IS NULL"
    )


def _unique_count_sql(check: ConfiguredCheck, column_name: str) -> str:
    column = quote_identifier(column_name)
    view_name = quote_identifier(_view_name(check.table))
    return (
        f"SELECT COALESCE(SUM(duplicate_count - 1), 0) "
        f"FROM ("
        f"SELECT COUNT(*) AS duplicate_count "
        f"FROM {view_name} "
        f"WHERE {column} IS NOT NULL "
        f"GROUP BY {column} "
        f"HAVING COUNT(*) > 1"
        f") AS duplicates"
    )


def _accepted_values_parameters(check: ConfiguredCheck) -> tuple[object, ...]:
    return tuple(check.values)


def _accepted_values_count_sql(check: ConfiguredCheck, column_name: str) -> str:
    column = quote_identifier(column_name)
    view_name = quote_identifier(_view_name(check.table))
    values = _accepted_values_values_clause(check)
    accepted_column = quote_identifier("value")
    return (
        f"SELECT COUNT(*) FROM {view_name} "
        f"WHERE {column} IS NOT NULL "
        f"AND NOT EXISTS ("
        f"SELECT 1 FROM (VALUES {values}) AS accepted({accepted_column}) "
        f"WHERE accepted.{accepted_column} IS NOT DISTINCT FROM {column}"
        f")"
    )


def _accepted_values_values_clause(check: ConfiguredCheck) -> str:
    return ", ".join("(?)" for _ in check.values)


def _min_count_sql(check: ConfiguredCheck, column_name: str) -> str:
    column = quote_identifier(column_name)
    view_name = quote_identifier(_view_name(check.table))
    return f"SELECT COUNT(*) FROM {view_name} WHERE {column} IS NOT NULL AND {column} < ?"


def _max_count_sql(check: ConfiguredCheck, column_name: str) -> str:
    column = quote_identifier(column_name)
    view_name = quote_identifier(_view_name(check.table))
    return f"SELECT COUNT(*) FROM {view_name} WHERE {column} IS NOT NULL AND {column} > ?"


def _row_count_between_failure_count(
    connection: duckdb.DuckDBPyConnection,
    check: ConfiguredCheck,
) -> int:
    min_value = (
        _require_strict_non_negative_int(check.min_value, field_name="min")
        if check.min_value is not None
        else None
    )
    max_value = (
        _require_strict_non_negative_int(check.max_value, field_name="max")
        if check.max_value is not None
        else None
    )
    observed = _fetch_scalar_int(
        connection,
        f"SELECT COUNT(*) FROM {quote_identifier(_view_name(check.table))}",
    )
    if min_value is not None and observed < min_value:
        return min_value - observed
    if max_value is not None and observed > max_value:
        return observed - max_value
    return 0


def _foreign_key_count_sql(
    check: ConfiguredCheck,
    child_column: str,
    parent_column: str,
) -> str:
    reference = check.references
    child_view = quote_identifier(_view_name(check.table))
    parent_view = quote_identifier(_view_name(reference.table if reference is not None else ""))
    child_alias = quote_identifier("child")
    parent_alias = quote_identifier("parent")
    child_column_name = quote_identifier(child_column)
    parent_column_name = quote_identifier(parent_column)
    return (
        f"SELECT COUNT(*) FROM {child_view} AS {child_alias} "
        f"WHERE {child_alias}.{child_column_name} IS NOT NULL "
        f"AND NOT EXISTS ("
        f"SELECT 1 FROM {parent_view} AS {parent_alias} "
        f"WHERE {parent_alias}.{parent_column_name} IS NOT DISTINCT FROM "
        f"{child_alias}.{child_column_name}"
        f")"
    )


def _row_level_failure_sql(check: ConfiguredCheck, column_name: str) -> str:
    view_name = quote_identifier(_view_name(check.table))
    rows_alias = quote_identifier(CHECK_ROWS_ALIAS)
    row_number_column = quote_identifier(CHECK_ROW_NUMBER_COLUMN)
    return (
        f"SELECT * FROM ("
        f"SELECT row_number() OVER () AS {row_number_column}, * "
        f"FROM {view_name}"
        f") AS {rows_alias} "
        f"WHERE {_row_level_failure_predicate(check, rows_alias, column_name)} "
        f"ORDER BY {rows_alias}.{row_number_column} "
        f"LIMIT ?"
    )


def _row_level_failure_parameters(
    check: ConfiguredCheck,
    limit: int,
) -> tuple[object, ...]:
    if check.type == "accepted_values":
        return (*check.values, limit)
    if check.type in {"min", "max"}:
        return (check.value, limit)
    return (limit,)


def _row_level_failure_predicate(
    check: ConfiguredCheck,
    rows_alias: str,
    column_name: str,
) -> str:
    if check.type == "not_null":
        return f"{rows_alias}.{quote_identifier(column_name)} IS NULL"
    if check.type == "accepted_values":
        return _accepted_values_failure_predicate(check, rows_alias, column_name)
    if check.type == "min":
        return (
            f"{rows_alias}.{quote_identifier(column_name)} IS NOT NULL "
            f"AND {rows_alias}.{quote_identifier(column_name)} < ?"
        )
    if check.type == "max":
        return (
            f"{rows_alias}.{quote_identifier(column_name)} IS NOT NULL "
            f"AND {rows_alias}.{quote_identifier(column_name)} > ?"
        )
    raise AssertionError(f"Unhandled row-level check type: {check.type}")


def _accepted_values_failure_predicate(
    check: ConfiguredCheck,
    rows_alias: str,
    column_name: str,
) -> str:
    column = quote_identifier(column_name)
    accepted_column = quote_identifier("value")
    values = _accepted_values_values_clause(check)
    return (
        f"{rows_alias}.{column} IS NOT NULL "
        f"AND NOT EXISTS ("
        f"SELECT 1 FROM (VALUES {values}) AS accepted({accepted_column}) "
        f"WHERE accepted.{accepted_column} IS NOT DISTINCT FROM {rows_alias}.{column}"
        f")"
    )


def _foreign_key_samples_sql(
    check: ConfiguredCheck,
    child_column: str,
    parent_column: str,
) -> str:
    reference = check.references
    child_view = quote_identifier(_view_name(check.table))
    parent_view = quote_identifier(_view_name(reference.table if reference is not None else ""))
    rows_alias = quote_identifier(CHECK_ROWS_ALIAS)
    row_number_column = quote_identifier(CHECK_ROW_NUMBER_COLUMN)
    parent_alias = quote_identifier("parent")
    child_column_name = quote_identifier(child_column)
    parent_column_name = quote_identifier(parent_column)
    return (
        f"SELECT * FROM ("
        f"SELECT row_number() OVER () AS {row_number_column}, * "
        f"FROM {child_view}"
        f") AS {rows_alias} "
        f"WHERE {rows_alias}.{child_column_name} IS NOT NULL "
        f"AND NOT EXISTS ("
        f"SELECT 1 FROM {parent_view} AS {parent_alias} "
        f"WHERE {parent_alias}.{parent_column_name} IS NOT DISTINCT FROM "
        f"{rows_alias}.{child_column_name}"
        f") "
        f"ORDER BY {rows_alias}.{row_number_column} "
        f"LIMIT ?"
    )


def _unique_failure_samples_sql(check: ConfiguredCheck, column_name: str) -> str:
    view_name = quote_identifier(_view_name(check.table))
    column = quote_identifier(column_name)
    value_column = quote_identifier("value")
    observed_column = quote_identifier("observed")
    return (
        f"SELECT {column} AS {value_column}, COUNT(*) AS {observed_column} "
        f"FROM {view_name} "
        f"WHERE {column} IS NOT NULL "
        f"GROUP BY {column} "
        f"HAVING COUNT(*) > 1 "
        f"ORDER BY {observed_column} DESC, {value_column} "
        f"LIMIT ?"
    )


def resolve_configured_column_name(
    table_name: str,
    configured_column: str | None,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> str:
    """Resolve a configured column name using CSVQL's existing check semantics."""

    return _resolve_column_name(table_name, configured_column, column_names_by_table)


def _resolve_column_name(
    table_name: str,
    configured_column: str | None,
    column_names_by_table: dict[str, tuple[str, ...]],
) -> str:
    if configured_column is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' must define a column.",
            suggestion="Add a column for column-level checks.",
        )

    actual_columns = column_names_by_table.get(table_name.lower())
    if actual_columns is None:
        raise ProjectConfigError(
            f"Project catalog table '{table_name}' is not registered for data quality checks.",
            suggestion="Register the table before running csvql check.",
        )

    if configured_column in actual_columns:
        return configured_column

    stripped_column = configured_column.strip()
    if stripped_column in actual_columns:
        return stripped_column

    raise ProjectConfigError(
        (
            f"Could not resolve column '{configured_column}' for project catalog table "
            f"'{table_name}'."
        ),
        suggestion="Check the CSV header spelling and surrounding whitespace.",
    )


def _check_context(check: ConfiguredCheck) -> str:
    return f"Project catalog check '{check.name}' for table '{check.table}'"


def _as_int(value: object) -> int:
    """Coerce a DuckDB scalar into an int for check accounting."""

    return int(cast(int | str | float | bool, value))


def _require_strict_non_negative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ProjectConfigError(
            f"{_check_context_for_row_count_between(field_name)} must be a non-negative integer.",
            suggestion="Use a whole number greater than or equal to zero.",
        )
    return value


def _check_context_for_row_count_between(field_name: str) -> str:
    return f"row_count_between {field_name}"
