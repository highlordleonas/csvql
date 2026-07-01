"""In-memory session state for the CSVQL menu TUI."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from csvql.exceptions import TableMappingError
from csvql.models import QueryResult, TableSource
from csvql.table_mapping import validate_table_alias

SourceOrigin = Literal["argument", "catalog", "session"]


@dataclass(frozen=True, slots=True)
class TUISource:
    """A source available to the TUI session."""

    name: str
    path: Path
    origin: SourceOrigin

    def __post_init__(self) -> None:
        validated_name = validate_table_alias(self.name)
        object.__setattr__(self, "name", validated_name)

    def as_table_source(self) -> TableSource:
        """Convert the TUI source into a DuckDB registration source."""

        return TableSource(name=self.name, path=self.path)


@dataclass(slots=True)
class TUISessionState:
    """Mutable session state for the CSVQL menu TUI."""

    _sources: list[TUISource] = field(default_factory=list)
    _selected_alias: str | None = None
    last_result: QueryResult | None = None

    @property
    def sources(self) -> tuple[TUISource, ...]:
        return tuple(self._sources)

    @property
    def table_sources(self) -> tuple[TableSource, ...]:
        return tuple(source.as_table_source() for source in self._sources)

    @property
    def selected_alias(self) -> str | None:
        return self._selected_alias

    def add_source(self, source: TUISource) -> None:
        """Add a source and select it if the session is empty."""

        if self._find_source_index(source.name) is not None:
            raise TableMappingError(
                f"Duplicate table alias '{source.name}'.",
                suggestion="Choose a unique alias for each TUI source.",
            )

        self._sources.append(source)
        if self._selected_alias is None:
            self._selected_alias = source.name

    def remove_source(self, alias: str) -> TUISource:
        """Remove a source by alias, update selection, and return it."""

        index = self._require_source_index(alias)
        removed_source = self._sources.pop(index)
        if (
            self._selected_alias is not None
            and self._selected_alias.casefold() == removed_source.name.casefold()
        ):
            self._selected_alias = self._sources[0].name if self._sources else None
        return removed_source

    def get_source(self, alias: str) -> TUISource:
        """Return a source by alias."""

        return self._sources[self._require_source_index(alias)]

    def select_source(self, alias: str) -> TUISource:
        """Select a source by alias and return it."""

        source = self.get_source(alias)
        self._selected_alias = source.name
        return source

    def selected_source(self) -> TUISource | None:
        """Return the selected source, if any."""

        if self._selected_alias is None:
            return None
        return self.get_source(self._selected_alias)

    def set_last_result(self, result: QueryResult) -> None:
        """Store the most recent query result."""

        self.last_result = result

    def _find_source_index(self, alias: str) -> int | None:
        alias_key = alias.casefold()
        for index, source in enumerate(self._sources):
            if source.name.casefold() == alias_key:
                return index
        return None

    def _require_source_index(self, alias: str) -> int:
        index = self._find_source_index(alias)
        if index is None:
            raise TableMappingError(
                f"Source alias '{alias}' is not loaded in the TUI session.",
                suggestion="Choose a loaded source alias from source manager.",
            )
        return index
