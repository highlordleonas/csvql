"""Tests for private, stable source-layer error details."""

import csvql.exceptions as exceptions
from csvql.exceptions import SourceError


def test_source_error_is_available_for_private_source_boundaries() -> None:
    """Source foundations need a typed internal error distinct from public errors."""

    assert hasattr(exceptions, "SourceError")


def test_source_error_retains_stable_code_and_sanitized_context() -> None:
    """Source errors carry only structured boundary context, never raw failures."""

    error = SourceError(
        "source_bind_failed",
        "The source could not be bound.",
        kind="csv",
        alias="sales",
        capability="query",
    )

    assert error.code == "source_bind_failed"
    assert error.kind == "csv"
    assert error.alias == "sales"
    assert error.capability == "query"
    assert error.dependency is None
    assert error.extra is None
    assert error.suggestion is None


def test_missing_optional_dependency_contains_remediation_evidence() -> None:
    """Unavailable optional adapters identify the affected capability and remedy."""

    error = SourceError.missing_optional_dependency(
        kind="future",
        capability="profile",
        dependency="future-driver",
        extra="future",
    )

    assert error.code == "missing_optional_dependency"
    assert error.kind == "future"
    assert error.capability == "profile"
    assert error.dependency == "future-driver"
    assert error.extra == "future"
    assert error.suggestion == "Install the 'future' extra to enable this source capability."
