"""Tests for private, stable source-layer error details."""

import csvql.exceptions as exceptions
from csvql.exceptions import (
    EngineSessionTaintedError,
    SourceActivationError,
    SourceBindingError,
    SourceCleanupError,
    SourceError,
    SourceIdentityError,
    SourceResolutionError,
)
from csvql.source import DiagnosticCode


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
    )

    assert error.code == "source_bind_failed"
    assert error.kind == "csv"
    assert error.alias == "sales"
    assert error.suggestion is None


def test_optional_dependency_failure_is_provider_activation_evidence() -> None:
    """Dependency availability belongs to selected-provider activation."""

    error = SourceActivationError(
        "source.activation_dependency_missing",
        "The selected source provider dependency is unavailable.",
        provider_key="future",
        dependency_key="future-driver",
        suggestion="Install the LocalQL future provider extra.",
    )

    assert error.code == "source.activation_dependency_missing"
    assert error.provider_key == "future"
    assert error.dependency_key == "future-driver"
    assert error.suggestion == "Install the LocalQL future provider extra."


def test_excel_diagnostics_use_provider_specific_stable_codes() -> None:
    """Surfaces need to distinguish workbook, sheet, range, and inference failures."""

    assert {
        DiagnosticCode.SOURCE_EXCEL_INVALID.value,
        DiagnosticCode.SOURCE_EXCEL_METADATA_LIMIT.value,
        DiagnosticCode.SOURCE_EXCEL_SHEET_MISSING.value,
        DiagnosticCode.SOURCE_EXCEL_SHEET_AMBIGUOUS.value,
        DiagnosticCode.SOURCE_EXCEL_RANGE_INVALID.value,
        DiagnosticCode.SOURCE_EXCEL_RANGE_REQUIRED.value,
        DiagnosticCode.SOURCE_EXCEL_SCHEMA_INFERENCE_FAILED.value,
    } == {
        "source.excel_invalid",
        "source.excel_metadata_limit",
        "source.excel_sheet_missing",
        "source.excel_sheet_ambiguous",
        "source.excel_range_invalid",
        "source.excel_range_required",
        "source.excel_schema_inference_failed",
    }


def test_lifecycle_failure_classes_remain_source_errors() -> None:
    """Callers may handle a broad source error or one lifecycle boundary."""

    cases = (
        SourceResolutionError(
            "source_missing",
            "Resolution failed.",
        ),
        SourceBindingError(
            "source_bind_failed",
            "Binding failed.",
        ),
        SourceIdentityError(
            "source_changed",
            "Identity changed.",
        ),
        EngineSessionTaintedError(
            "engine_session_tainted",
            "Session is tainted.",
        ),
        SourceCleanupError(
            "source_cleanup_failed",
            "Cleanup failed.",
        ),
    )

    assert all(isinstance(error, SourceError) for error in cases)
    assert [error.code for error in cases] == [
        "source_missing",
        "source_bind_failed",
        "source_changed",
        "engine_session_tainted",
        "source_cleanup_failed",
    ]
