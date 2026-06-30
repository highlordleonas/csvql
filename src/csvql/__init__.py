"""CSVQL public package interface."""

from csvql.api import CSVQLSession
from csvql.engine import CSVQLEngine
from csvql.models import QueryResult, TableSource

__all__ = ["CSVQLEngine", "CSVQLSession", "QueryResult", "TableSource"]

__version__ = "0.1.0"
