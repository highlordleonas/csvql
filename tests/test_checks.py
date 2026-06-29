from pathlib import Path

import pytest

from csvql.checks import run_configured_checks
from csvql.exceptions import CSVInspectionError, ProjectConfigError
from csvql.project_config import CONFIG_FILENAME, ProjectConfig, ProjectContext, ProjectTable
from csvql.quality import ConfiguredCheck, ForeignKeyReference


def _context(project_root: Path, tables: tuple[ProjectTable, ...]) -> ProjectContext:
    return ProjectContext(
        project_root=project_root.resolve(),
        config_path=(project_root / CONFIG_FILENAME).resolve(),
        config=ProjectConfig(version=1, tables=tables),
    )


def _check(
    name: str,
    table: str,
    type_value: str,
    *,
    column: str | None = None,
    values: tuple[object, ...] = (),
    value: object | None = None,
    min_value: object | None = None,
    max_value: object | None = None,
    references: ForeignKeyReference | None = None,
) -> ConfiguredCheck:
    return ConfiguredCheck(
        name=name,
        table=table,
        type=type_value,  # type: ignore[arg-type]
        column=column,
        values=values,
        value=value,
        min_value=min_value,
        max_value=max_value,
        references=references,
    )


def test_run_configured_checks_returns_global_warning_for_zero_checks(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert result.status == "passed"
    assert result.check_count == 0
    assert result.warnings == ("No data quality checks configured.",)


def test_run_configured_checks_returns_table_specific_warning_for_zero_checks(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    result = run_configured_checks(
        context, table_name="orders", show_failures=False, failure_limit=5
    )

    assert result.status == "passed"
    assert result.check_count == 0
    assert result.warnings == ("No data quality checks configured for table 'orders'.",)


def test_run_configured_checks_resolves_table_filter_case_insensitively(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "Orders",
                "orders.csv",
                checks=(_check("order_id_required", "Orders", "not_null", column="order_id"),),
            ),
        ),
    )

    result = run_configured_checks(
        context, table_name="orders", show_failures=False, failure_limit=5
    )

    assert result.status == "passed"
    assert result.check_count == 1
    assert result.checks[0].name == "order_id_required"


def test_run_configured_checks_validates_core_semantics_and_identifier_quoting(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        '"order id",select,"total-amount"\nORD-1,paid,10\nORD-2,unknown,20\nORD-2,,30\n,paid,40\n',
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check("order_id_required", "orders", "not_null", column="order id"),
                    _check("order_id_unique", "orders", "unique", column="order id"),
                    _check(
                        "status_known",
                        "orders",
                        "accepted_values",
                        column="select",
                        values=("paid", "pending"),
                    ),
                    _check(
                        "total_non_negative",
                        "orders",
                        "min",
                        column="total-amount",
                        value=15,
                    ),
                    _check(
                        "total_under_limit",
                        "orders",
                        "max",
                        column="total-amount",
                        value=25,
                    ),
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=5,
                        max_value=10,
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    failures = {check.name: check.failed_count for check in result.checks}
    assert result.status == "failed"
    assert failures == {
        "order_id_required": 1,
        "order_id_unique": 1,
        "status_known": 1,
        "total_non_negative": 1,
        "total_under_limit": 2,
        "expected_rows": 1,
    }


def test_run_configured_checks_handles_whitespace_header_names(
    tmp_path: Path,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        '" total amount ",order_id\n10,ORD-1\n,ORD-2\n',
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "total_amount_required",
                        "orders",
                        "not_null",
                        column=" total amount ",
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert result.status == "failed"
    assert result.checks[0].failed_count == 1


def test_run_configured_checks_includes_capped_failure_samples(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,status\nORD-1,paid\n,unknown\n,paid\n",
        encoding="utf-8",
    )
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=1)

    assert result.checks[0].failed_count == 2
    assert len(result.checks[0].failures) == 1
    assert result.checks[0].failures[0].row_number == 2
    assert result.checks[0].failures[0].value is None
    assert result.checks[0].failures[0].row == {"order_id": None, "status": "unknown"}


def test_run_configured_checks_reports_row_count_between_sample(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\nORD-2\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=4,
                        max_value=6,
                    ),
                ),
            ),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=3)

    assert result.checks[0].failed_count == 2
    assert result.checks[0].failures[0].observed == 2
    assert result.checks[0].failures[0].min_value == 4
    assert result.checks[0].failures[0].max_value == 6


@pytest.mark.parametrize(
    ("min_value", "max_value"),
    [
        (None, None),
        (10, 1),
    ],
)
def test_run_configured_checks_rejects_invalid_row_count_between_bounds(
    tmp_path: Path,
    min_value: object | None,
    max_value: object | None,
) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "expected_rows",
                        "orders",
                        "row_count_between",
                        min_value=min_value,
                        max_value=max_value,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_run_configured_checks_reports_foreign_key_failures_and_null_child_passes(
    tmp_path: Path,
) -> None:
    (tmp_path / "orders.csv").write_text(
        "order_id,customer_id\nORD-1,CUST-1\nORD-2,CUST-MISSING\nORD-3,\n",
        encoding="utf-8",
    )
    (tmp_path / "customers.csv").write_text("customer_id\nCUST-1\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "customer_exists",
                        "orders",
                        "foreign_key",
                        column="customer_id",
                        references=ForeignKeyReference("customers", "customer_id"),
                    ),
                ),
            ),
            ProjectTable("customers", "customers.csv"),
        ),
    )

    result = run_configured_checks(context, table_name=None, show_failures=True, failure_limit=5)

    assert result.checks[0].failed_count == 1
    failure = result.checks[0].failures[0]
    assert failure.row_number == 2
    assert failure.value == "CUST-MISSING"
    assert failure.row == {"order_id": "ORD-2", "customer_id": "CUST-MISSING"}
    assert failure.reference_table == "customers"
    assert failure.reference_column == "customer_id"


def test_run_configured_checks_rejects_unknown_table_filter(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("order_id\nORD-1\n", encoding="utf-8")
    context = _context(tmp_path, (ProjectTable("orders", "orders.csv"),))

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name="missing", show_failures=False, failure_limit=5)


def test_run_configured_checks_rejects_null_min_threshold(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    orders.write_text("total_amount\n10\n", encoding="utf-8")
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "orders.csv",
                checks=(
                    _check(
                        "total_non_negative", "orders", "min", column="total_amount", value=None
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError):
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)


def test_run_configured_checks_wraps_missing_csv_for_catalog_table(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        (
            ProjectTable(
                "orders",
                "missing.csv",
                checks=(_check("order_id_required", "orders", "not_null", column="order_id"),),
            ),
        ),
    )

    with pytest.raises(CSVInspectionError) as exc_info:
        run_configured_checks(context, table_name=None, show_failures=False, failure_limit=5)

    assert "Failed to run data quality checks for project catalog table 'orders'" in str(
        exc_info.value,
    )
