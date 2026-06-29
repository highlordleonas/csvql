import json
from pathlib import Path

from csvql.models import (
    ColumnInfo,
    ColumnProfile,
    DialectInfo,
    InspectResult,
    ProfileResult,
    RowCountInfo,
    SampleResult,
)
from csvql.output import (
    format_check_result_json,
    format_check_result_table,
    format_inspect_result_json,
    format_inspect_result_table,
    format_profile_result_json,
    format_profile_result_table,
    format_project_tables_json,
    format_project_tables_table,
    format_sample_result_json,
    format_sample_result_table,
)
from csvql.project_config import ProjectTableListing, ProjectTablesResult
from csvql.quality import CheckFailureSample, CheckResult, CheckRunResult


def _inspect_result() -> InspectResult:
    return InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.not_counted(),
        warnings=(),
    )


def test_format_inspect_result_json_is_deterministic() -> None:
    payload = json.loads(format_inspect_result_json(_inspect_result()))

    assert payload["columns"] == [{"duckdb_type": "VARCHAR", "name": "order_id"}]
    assert payload["row_count"]["mode"] == "not_counted"


def test_format_inspect_result_table_contains_core_fields() -> None:
    output = format_inspect_result_table(_inspect_result())

    assert "orders.csv" in output
    assert "order_id" in output
    assert "not_counted" in output


def test_format_inspect_result_table_uses_exact_row_count() -> None:
    result = InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.exact_count(3),
        warnings=(),
    )

    output = format_inspect_result_table(result)

    assert "Rows: 3" in output
    assert "Rows: exact" not in output


def test_format_sample_result_json_is_deterministic() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=1,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    payload = json.loads(format_sample_result_json(result))

    assert payload["limit"] == 1
    assert payload["rows"] == [{"order_id": "ORD-1", "status": "paid"}]


def test_format_sample_result_table_contains_rows() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=1,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    output = format_sample_result_table(result)

    assert "ORD-1" in output
    assert "paid" in output


def test_format_profile_result_json_is_deterministic() -> None:
    result = ProfileResult(
        source={"display_path": "orders.csv"},
        row_count=2,
        column_count=1,
        duplicate_row_count=0,
        columns=(
            ColumnProfile(
                name="status",
                duckdb_type="VARCHAR",
                non_null_count=1,
                null_count=1,
                null_percentage=50.0,
                distinct_count=1,
                min="paid",
                max="paid",
            ),
        ),
        warnings=(),
    )

    payload = json.loads(format_profile_result_json(result))

    assert payload["row_count"] == 2
    assert payload["column_count"] == 1
    assert payload["duplicate_row_count"] == 0
    assert payload["columns"] == [
        {
            "duckdb_type": "VARCHAR",
            "distinct_count": 1,
            "max": "paid",
            "min": "paid",
            "name": "status",
            "non_null_count": 1,
            "null_count": 1,
            "null_percentage": 50.0,
        }
    ]


def test_format_profile_result_table_contains_profile_metrics() -> None:
    result = ProfileResult(
        source={"display_path": "orders.csv"},
        row_count=2,
        column_count=1,
        duplicate_row_count=0,
        columns=(
            ColumnProfile(
                name="status",
                duckdb_type="VARCHAR",
                non_null_count=1,
                null_count=1,
                null_percentage=50.0,
                distinct_count=1,
                min="paid",
                max="paid",
            ),
        ),
        warnings=(),
    )

    output = format_profile_result_table(result)

    assert "orders.csv" in output
    assert "Rows: 2" in output
    assert "Duplicate rows: 0" in output
    assert "status" in output
    assert "50.000" in output


def _check_run_result() -> CheckRunResult:
    return CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(CheckFailureSample(row_number=2, value=None, row={"order_id": None}),),
            ),
            CheckResult(
                name="status_known",
                table="orders",
                type="accepted_values",
                column="status",
                status="passed",
                failed_count=0,
            ),
        ),
        warnings=("No data quality checks configured for table 'customers'.",),
    )


def _zero_check_result() -> CheckRunResult:
    return CheckRunResult(
        status="passed",
        checks=(),
        warnings=("No data quality checks configured for table 'orders'.",),
    )


def _rich_failure_result() -> CheckRunResult:
    return CheckRunResult(
        status="failed",
        checks=(
            CheckResult(
                name="order_id_required",
                table="orders",
                type="not_null",
                column="order_id",
                status="failed",
                failed_count=1,
                failures=(
                    CheckFailureSample(
                        row_number=2,
                        value=None,
                        row={
                            "order_id": None,
                            "tags": ["vip", "web"],
                            "meta": {"source": "api", "flags": ("new", "urgent")},
                        },
                    ),
                ),
            ),
            CheckResult(
                name="customer_exists",
                table="orders",
                type="foreign_key",
                column="customer_id",
                status="failed",
                failed_count=1,
                failures=(
                    CheckFailureSample(
                        observed="CUST-9",
                        reference_table="customers",
                        reference_column="customer_id",
                        min_value=1,
                        max_value=10,
                    ),
                ),
            ),
        ),
        warnings=(),
    )


def test_format_check_result_json_is_deterministic_without_failures() -> None:
    payload = json.loads(format_check_result_json(_check_run_result(), include_failures=False))

    assert payload["status"] == "failed"
    assert payload["check_count"] == 2
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 1
    assert "failures" not in payload["checks"][0]


def test_format_check_result_json_includes_failures_when_requested() -> None:
    payload = json.loads(format_check_result_json(_check_run_result(), include_failures=True))

    assert payload["checks"][0]["failures"] == [
        {"row_number": 2, "value": None, "row": {"order_id": None}}
    ]


def test_format_check_result_table_contains_status_counts_and_failures() -> None:
    output = format_check_result_table(_check_run_result(), include_failures=True)

    assert "Status: failed" in output
    assert "Checks: 2 | Passed: 1 | Failed: 1" in output
    assert "orders" in output
    assert "order_id_required" in output
    assert "accepted_values" in output
    assert "order_id" in output
    assert "Failures:" in output
    assert "row_number=2" in output
    assert "Warnings:" in output
    assert "No data quality checks configured for table 'customers'." in output


def test_format_check_result_table_suppresses_failures_when_disabled() -> None:
    output = format_check_result_table(_check_run_result(), include_failures=False)

    assert "Failures:" not in output
    assert "row_number=2" not in output


def test_format_check_result_json_and_table_render_zero_check_warnings() -> None:
    payload = json.loads(format_check_result_json(_zero_check_result(), include_failures=False))

    assert payload["status"] == "passed"
    assert payload["check_count"] == 0
    assert payload["warnings"] == ["No data quality checks configured for table 'orders'."]

    output = format_check_result_table(_zero_check_result(), include_failures=False)

    assert "Status: passed" in output
    assert "Checks: 0 | Passed: 0 | Failed: 0" in output
    assert "Warnings:" in output
    assert "No data quality checks configured for table 'orders'." in output


def test_format_check_result_table_renders_nested_failure_values_deterministically() -> None:
    output = format_check_result_table(_rich_failure_result(), include_failures=True)

    assert '"meta":{"flags":["new","urgent"],"source":"api"}' in output
    assert '"tags":["vip","web"]' in output
    assert "observed=CUST-9" in output
    assert "reference_table=customers" in output
    assert "reference_column=customer_id" in output
    assert "min=1" in output
    assert "max=10" in output


def test_format_project_tables_json_is_deterministic() -> None:
    result = ProjectTablesResult(
        project_root=Path("/path/to/project"),
        config_path=Path("/path/to/project/.csvql.yml"),
        tables=(
            ProjectTableListing(
                name="orders",
                path="data/orders.csv",
                resolved_path=Path("/path/to/project/data/orders.csv"),
            ),
        ),
    )

    expected = {
        "config_path": "/path/to/project/.csvql.yml",
        "project_root": "/path/to/project",
        "tables": [
            {
                "name": "orders",
                "path": "data/orders.csv",
                "resolved_path": "/path/to/project/data/orders.csv",
            }
        ],
    }

    payload = format_project_tables_json(result)

    assert payload == json.dumps(expected, indent=2, sort_keys=True)


def test_format_project_tables_table_contains_catalog_paths() -> None:
    result = ProjectTablesResult(
        project_root=Path("/path/to/project"),
        config_path=Path("/path/to/project/.csvql.yml"),
        tables=(
            ProjectTableListing(
                name="orders",
                path="data/orders.csv",
                resolved_path=Path("/path/to/project/data/orders.csv"),
            ),
        ),
    )

    output = format_project_tables_table(result)

    assert "orders" in output
    assert "data/orders.csv" in output
    assert "/path/to/project/data/orders.csv" in output
