"""CSVQL public package interface."""

from csvql.api import CSVQLSession
from csvql.engine import CSVQLEngine
from csvql.export import ExportFormat
from csvql.models import InspectResult, ProfileResult, QueryResult, SampleResult, TableSource
from csvql.project_config import ProjectTablesResult
from csvql.quality import CheckRunResult

__all__ = [
    "CSVQLEngine",
    "CSVQLSession",
    "CheckRunResult",
    "ExportFormat",
    "InspectResult",
    "ProfileResult",
    "ProjectTablesResult",
    "QueryResult",
    "SampleResult",
    "TableSource",
]

__version__ = "1.0.4"
