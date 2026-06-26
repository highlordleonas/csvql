"""Typed exceptions for CLI-friendly CSVQL failures."""


class CSVQLError(Exception):
    """Base error with a stable process exit code."""

    exit_code = 1

    def __init__(self, message: str, *, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


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
