"""Typed exceptions for CLI-friendly CSVQL failures."""

from typing import Literal

SourceErrorCode = Literal[
    "unknown_source_kind",
    "missing_optional_dependency",
    "unsupported_source_option",
    "source_missing",
    "source_changed",
    "unsupported_capability",
    "source_bind_failed",
]


class CSVQLError(Exception):
    """Base error with a stable process exit code."""

    exit_code = 1

    def __init__(self, message: str, *, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


class SourceError(CSVQLError):
    """Private error raised by the source-adapter boundary."""

    def __init__(
        self,
        code: SourceErrorCode,
        message: str,
        *,
        kind: str | None = None,
        alias: str | None = None,
        capability: str | None = None,
        dependency: str | None = None,
        extra: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Create a source error with only structured boundary context."""

        super().__init__(message, suggestion=suggestion)
        self.code = code
        self.kind = kind
        self.alias = alias
        self.capability = capability
        self.dependency = dependency
        self.extra = extra

    @classmethod
    def missing_optional_dependency(
        cls,
        *,
        kind: str,
        capability: str,
        dependency: str,
        extra: str,
    ) -> "SourceError":
        """Build an actionable error for an unavailable optional adapter runtime."""

        return cls(
            "missing_optional_dependency",
            "The requested source capability requires an optional dependency.",
            kind=kind,
            capability=capability,
            dependency=dependency,
            extra=extra,
            suggestion=f"Install the '{extra}' extra to enable this source capability.",
        )


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
