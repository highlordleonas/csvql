import pytest

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


def test_check_failure_sample_preserves_explicit_null_value() -> None:
    failure = CheckFailureSample(value=None)

    assert failure.as_dict() == {"value": None}


def test_check_failure_sample_with_row_defaults_value_to_null() -> None:
    failure = CheckFailureSample(row={"order_id": None})

    assert failure.as_dict() == {"value": None, "row": {"order_id": None}}


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


def test_check_result_rejects_negative_failed_count() -> None:
    with pytest.raises(ValueError, match="failed_count must be non-negative"):
        CheckResult(
            name="order_id_required",
            table="orders",
            type="not_null",
            column="order_id",
            status="failed",
            failed_count=-1,
        )


def test_check_result_rejects_passed_status_with_failures() -> None:
    with pytest.raises(ValueError, match="passed checks cannot have failed_count > 0"):
        CheckResult(
            name="order_id_required",
            table="orders",
            type="not_null",
            column="order_id",
            status="passed",
            failed_count=1,
        )


def test_check_result_rejects_failed_status_without_failures() -> None:
    with pytest.raises(ValueError, match="failed checks must have failed_count > 0"):
        CheckResult(
            name="order_id_required",
            table="orders",
            type="not_null",
            column="order_id",
            status="failed",
            failed_count=0,
        )


def test_check_run_result_requires_failed_status_when_child_check_failed() -> None:
    child = CheckResult(
        name="order_id_required",
        table="orders",
        type="not_null",
        column="order_id",
        status="failed",
        failed_count=1,
    )

    with pytest.raises(ValueError, match="run status must match child check statuses"):
        CheckRunResult(status="passed", checks=(child,), warnings=())


def test_check_run_result_requires_passed_status_when_all_child_checks_pass() -> None:
    child = CheckResult(
        name="order_id_required",
        table="orders",
        type="not_null",
        column="order_id",
        status="passed",
        failed_count=0,
    )

    with pytest.raises(ValueError, match="run status must match child check statuses"):
        CheckRunResult(status="failed", checks=(child,), warnings=())
