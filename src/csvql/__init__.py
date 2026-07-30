"""CSVQL public package interface."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from csvql.api import CSVQLSession
    from csvql.engine import CSVQLEngine
    from csvql.export import ExportFormat
    from csvql.models import (
        InspectResult,
        ProfileResult,
        QueryResult,
        SampleResult,
        SourceDefinition,
        TableSource,
    )
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
    "SourceDefinition",
    "TableSource",
]

__version__ = "1.1.1"

_PUBLIC_IMPORTS = {
    "CSVQLEngine": ("csvql.engine", "CSVQLEngine"),
    "CSVQLSession": ("csvql.api", "CSVQLSession"),
    "CheckRunResult": ("csvql.quality", "CheckRunResult"),
    "ExportFormat": ("csvql.export", "ExportFormat"),
    "InspectResult": ("csvql.models", "InspectResult"),
    "ProfileResult": ("csvql.models", "ProfileResult"),
    "ProjectTablesResult": ("csvql.project_config", "ProjectTablesResult"),
    "QueryResult": ("csvql.models", "QueryResult"),
    "SampleResult": ("csvql.models", "SampleResult"),
    "SourceDefinition": ("csvql.models", "SourceDefinition"),
    "TableSource": ("csvql.models", "TableSource"),
}


def __getattr__(name: str) -> object:
    """Load one retained public symbol without importing provider runtime eagerly."""

    target = _PUBLIC_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'csvql' has no attribute {name!r}")
    module_name, symbol_name = target
    value = getattr(import_module(module_name), symbol_name)
    globals()[name] = value
    return value
