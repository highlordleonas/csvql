from csvql.quality import (
    CheckFailureSample,
    CheckResult,
    CheckRunResult,
    ConfiguredCheck,
    ForeignKeyReference,
)


def test_configured_check_as_dict_includes_reference_when_present() -> None:
    check = ConfiguredCheck(
        name="customer_exists",
        table="orders",
        type="foreign_key",
        column="customer_id",
        values=(),
        value=None,
        min_value=None,
        max_value=None,
        references=ForeignKeyReference(table="customers", column="customer_id"),
    )

    assert check.as_dict() == {
        "name": "customer_exists",
        "table": "orders",
        "type": "foreign_key",
        "column": "customer_id",
        "references": {"table": "customers", "column": "customer_id"},
    }


def test_check_run_result_as_dict_omits_failures_when_not_requested() -> None:
    result = CheckRunResult(
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
                        row={"order_id": None, "status": "paid"},
                    ),
                ),
            ),
        ),
        warnings=(),
    )

    assert result.as_dict(include_failures=False) == {
        "status": "failed",
        "check_count": 1,
        "passed_count": 0,
        "failed_count": 1,
        "checks": [
            {
                "name": "order_id_required",
                "table": "orders",
                "type": "not_null",
                "column": "order_id",
                "status": "failed",
                "failed_count": 1,
            }
        ],
        "warnings": [],
    }


def test_check_run_result_as_dict_includes_failures_when_requested() -> None:
    result = CheckRunResult(
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
                        row={"order_id": None, "status": "paid"},
                    ),
                ),
            ),
        ),
        warnings=(),
    )

    check_payload = result.as_dict(include_failures=True)["checks"][0]

    assert check_payload["failures"] == [
        {
            "row_number": 2,
            "value": None,
            "row": {"order_id": None, "status": "paid"},
        }
    ]
