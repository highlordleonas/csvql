"""Full-scan CSV profiling compatibility service."""

from csvql.engine import CSVQLEngine
from csvql.exceptions import CSVInspectionError, CSVQLError
from csvql.models import ProfileResult
from csvql.operation import OperationCancelled
from csvql.source import CSVSource
from csvql.source_operations import SourceOperations, _resolved_source_from_csv


def profile_csv_source(source: CSVSource) -> ProfileResult:
    """Profile a CSV source with DuckDB-controlled aggregate SQL."""

    try:
        with CSVQLEngine() as engine:
            return SourceOperations(
                engine,
                _resolved_source_from_csv(source),
            ).profile()
    except OperationCancelled:
        raise
    except CSVQLError as exc:
        raise CSVInspectionError(
            f"Failed to profile CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
