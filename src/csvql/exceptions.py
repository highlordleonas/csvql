"""Typed exceptions for CLI-friendly CSVQL failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from csvql.source import SourceDiagnostic

SourceErrorCode = Literal[
    "unknown_source_kind",
    "missing_optional_dependency",
    "unsupported_source_option",
    "source.dataset_changed",
    "source.dataset_manifest_limit",
    "source.dataset_symlink_rejected",
    "source.identity_strength_unavailable",
    "source.json_dependency_missing",
    "source.json_invalid",
    "source.json_record_not_object",
    "source.json_record_path_invalid",
    "source.json_record_path_missing",
    "source.json_record_path_not_array",
    "source.json_record_shape_invalid",
    "source.json_schema_cast_failed",
    "source.json_schema_invalid",
    "source.ndjson_invalid",
    "source.parquet_dataset_empty",
    "source.parquet_invalid",
    "source.parquet_schema_mismatch",
    "source.partitioning_invalid",
    "source_missing",
    "source_changed",
    "source_bind_failed",
    "source_cleanup_failed",
    "engine_session_tainted",
]


class CSVQLError(Exception):
    """Base error with a stable process exit code."""

    exit_code = 1

    def __init__(
        self,
        message: str,
        *,
        suggestion: str | None = None,
        diagnostic: SourceDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.diagnostic = diagnostic

    def as_dict(self, *, redaction: str = "safe") -> dict[str, object]:
        """Return a deterministic public failure payload."""

        payload: dict[str, object] = {
            "message": self.message,
            "suggestion": self.suggestion,
        }
        if self.diagnostic is not None:
            payload["diagnostic"] = {
                "version": 1,
                **self.diagnostic.as_dict(redaction=redaction),
            }
        return payload


class SourceError(CSVQLError):
    """Private error raised by the source-adapter boundary."""

    def __init__(
        self,
        code: SourceErrorCode,
        message: str,
        *,
        kind: str | None = None,
        alias: str | None = None,
        suggestion: str | None = None,
        diagnostic: SourceDiagnostic | None = None,
    ) -> None:
        """Create a source error with only structured boundary context."""

        super().__init__(
            message,
            suggestion=suggestion,
            diagnostic=diagnostic,
        )
        self.code = code
        self.kind = kind
        self.alias = alias


class SourceResolutionError(SourceError):
    """Failure while turning a selected source into resource-free facts."""


class SourceBindingError(SourceError):
    """Failure while binding a resolved source to one engine session."""


class SourceIdentityError(SourceError):
    """Failure to establish the required source reproducibility identity."""


class EngineSessionTaintedError(SourceError):
    """Failure caused by an engine session whose terminal state is uncertain."""


class SourceCleanupError(SourceError):
    """Failure while releasing one or more prepared source bindings."""


@dataclass(frozen=True, slots=True)
class ConfigurationFinding:
    """One deterministic application-composition defect."""

    code: str
    subject: str
    detail: str


class ConfigurationFailure(CSVQLError):
    """Raised when import-free source component composition is invalid."""

    def __init__(self, findings: tuple[ConfigurationFinding, ...]) -> None:
        ordered = tuple(
            sorted(
                findings,
                key=lambda finding: (finding.code, finding.subject, finding.detail),
            )
        )
        if not ordered:
            raise ValueError("ConfigurationFailure requires at least one finding.")
        super().__init__("LocalQL source-provider configuration is invalid.")
        self.findings = ordered


class SourceActivationError(CSVQLError):
    """Sanitized failure while activating one selected source provider."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider_key: str,
        dependency_key: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, suggestion=suggestion)
        self.code = code
        self.provider_key = provider_key
        self.dependency_key = dependency_key


class FileMissingError(CSVQLError):
    """Raised when a configured CSV path does not exist."""

    exit_code = 4


class TableMappingError(CSVQLError):
    """Raised when a CLI table mapping cannot be parsed or validated."""

    exit_code = 6


class QueryExecutionError(CSVQLError):
    """Raised when DuckDB rejects or fails a query."""

    exit_code = 1


class CSVInspectionError(CSVQLError):
    """Raised when CSV inspection or sampling fails."""

    exit_code = 7


class ProjectConfigError(CSVQLError):
    """Raised when project catalog discovery, parsing, or validation fails."""

    exit_code = 8

    def __init__(
        self,
        message: str,
        *,
        suggestion: str | None = None,
        code: str = "catalog.invalid",
        diagnostic: SourceDiagnostic | None = None,
    ) -> None:
        super().__init__(message, suggestion=suggestion, diagnostic=diagnostic)
        self.code = code


class SQLFileError(CSVQLError):
    """Raised when a saved SQL file cannot be used."""

    exit_code = 9


class ExportError(CSVQLError):
    """Raised when an export output path or format cannot be used."""

    exit_code = 10


class DataQualityCheckFailure(CSVQLError):
    """Raised when configured data-quality checks fail."""

    exit_code = 11


class DoctorFailure(CSVQLError):
    """Raised when `csvql doctor` finds project-health failures."""

    exit_code = 12
