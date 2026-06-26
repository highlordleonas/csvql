"""CSVQL public package interface."""

from csvql.engine import CSVQLEngine
from csvql.models import QueryResult, TableSource

__all__ = ["CSVQLEngine", "QueryResult", "TableSource"]

__version__ = "0.1.0"
