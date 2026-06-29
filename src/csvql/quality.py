"""Typed data-quality check configuration and results."""

from dataclasses import dataclass
from typing import Literal

CheckType = Literal[
    "not_null",
    "unique",
    "accepted_values",
    "min",
    "max",
    "row_count_between",
    "foreign_key",
]
CheckStatus = Literal["passed", "failed"]
RunStatus = Literal["passed", "failed"]
_UNSET = object()


@dataclass(frozen=True, slots=True)
class ForeignKeyReference:
    """Single-column foreign-key target from project config."""

    table: str
    column: str

    def as_dict(self) -> dict[str, str]:
        return {
            "table": self.table,
            "column": self.column,
        }


@dataclass(frozen=True, slots=True)
class ConfiguredCheck:
    """Validated data-quality check from `.csvql.yml`."""

    name: str
    table: str
    type: CheckType
    column: str | None
    values: tuple[object, ...]
    value: object | None
    min_value: object | None
    max_value: object | None
    references: ForeignKeyReference | None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "table": self.table,
            "type": self.type,
        }
        if self.column is not None:
            payload["column"] = self.column
        if self.values:
            payload["values"] = list(self.values)
        if self.value is not None:
            payload["value"] = self.value
        if self.min_value is not None:
            payload["min"] = self.min_value
        if self.max_value is not None:
            payload["max"] = self.max_value
        if self.references is not None:
            payload["references"] = self.references.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class CheckFailureSample:
    """One sampled failure for verbose check output."""

    row_number: int | None = None
    value: object = _UNSET
    row: dict[str, object] | None = None
    observed: object | None = None
    expected: object | None = None
    min_value: object | None = None
    max_value: object | None = None
    reference_table: str | None = None
    reference_column: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.row_number is not None:
            payload["row_number"] = self.row_number
        if self.value is not _UNSET:
            payload["value"] = self.value
        elif self.row is not None:
            payload["value"] = None
        if self.row is not None:
            payload["row"] = self.row
        if self.observed is not None:
            payload["observed"] = self.observed
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.min_value is not None:
            payload["min"] = self.min_value
        if self.max_value is not None:
            payload["max"] = self.max_value
        if self.reference_table is not None:
            payload["reference_table"] = self.reference_table
        if self.reference_column is not None:
            payload["reference_column"] = self.reference_column
        return payload


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result for one configured data-quality check."""

    name: str
    table: str
    type: CheckType
    column: str | None
    status: CheckStatus
    failed_count: int
    failures: tuple[CheckFailureSample, ...] = ()

    def __post_init__(self) -> None:
        if self.failed_count < 0:
            raise ValueError("failed_count must be non-negative")
        if self.status == "passed" and self.failed_count > 0:
            raise ValueError("passed checks cannot have failed_count > 0")
        if self.status == "failed" and self.failed_count == 0:
            raise ValueError("failed checks must have failed_count > 0")

    def as_dict(self, *, include_failures: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "table": self.table,
            "type": self.type,
            "status": self.status,
            "failed_count": self.failed_count,
        }
        if self.column is not None:
            payload["column"] = self.column
        if include_failures and self.failures:
            payload["failures"] = [failure.as_dict() for failure in self.failures]
        return payload


@dataclass(frozen=True, slots=True)
class CheckRunResult:
    """Aggregate result for a `csvql check` invocation."""

    status: RunStatus
    checks: tuple[CheckResult, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        any_failed = any(check.status == "failed" for check in self.checks)
        expected_status: RunStatus = "failed" if any_failed else "passed"
        if self.status != expected_status:
            raise ValueError("run status must match child check statuses")

    @property
    def check_count(self) -> int:
        return len(self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "failed")

    @property
    def passed_count(self) -> int:
        return self.check_count - self.failed_count

    def as_dict(self, *, include_failures: bool) -> dict[str, object]:
        return {
            "status": self.status,
            "check_count": self.check_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "checks": [check.as_dict(include_failures=include_failures) for check in self.checks],
            "warnings": list(self.warnings),
        }
