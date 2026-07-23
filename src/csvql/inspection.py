"""CSV inspection and sampling compatibility services."""

from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVInspectionError, CSVQLError
from csvql.models import InspectResult, SampleResult
from csvql.operation import OperationCancelled
from csvql.source import CSVSource
from csvql.source_operations import SourceOperations, _resolved_source_from_csv


def inspect_csv_source(source: CSVSource, *, exact: bool = False) -> InspectResult:
    """Inspect a CSV source and return schema, dialect, and row-count status."""

    try:
        with CSVQLEngine() as engine:
            return SourceOperations(engine, _resolved_source_from_csv(source)).inspect(exact=exact)
    except OperationCancelled:
        raise
    except CSVQLError as exc:
        raise CSVInspectionError(
            f"Failed to inspect CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc


def sample_csv_source(source: CSVSource, *, limit: int = 10) -> SampleResult:
    """Return a bounded row sample from a CSV source."""

    if limit <= 0:
        raise ValueError("Sample limit must be greater than zero.")

    try:
        with CSVQLEngine() as engine:
            return SourceOperations(engine, _resolved_source_from_csv(source)).sample(limit=limit)
    except OperationCancelled:
        raise
    except CSVQLError as exc:
        raise CSVInspectionError(
            f"Failed to sample CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
