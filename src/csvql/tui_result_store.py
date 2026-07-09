"""Session-local result storage for the CSVQL TUI."""

from __future__ import annotations

import pickle
import tempfile
from dataclasses import dataclass
from pathlib import Path

from csvql.models import QueryResult

TUI_RESULT_SPILL_ROW_THRESHOLD = 10_000
TUI_RESULT_SPILL_CELL_THRESHOLD = 250_000


@dataclass(frozen=True, slots=True)
class TUIResultHandle:
    """Reference to a stored TUI query result."""

    sequence: int
    is_spilled: bool
    temp_path: Path | None = None


@dataclass(frozen=True, slots=True)
class TUIStoredResult:
    """Stored full result plus its lookup handle."""

    handle: TUIResultHandle
    result: QueryResult | None = None


class TUIResultStore:
    """Store small results in memory and large results in session temp files."""

    def __init__(self, *, temp_root: Path | None = None) -> None:
        self._memory_results: dict[int, QueryResult] = {}
        self._temp_dir = tempfile.TemporaryDirectory(
            prefix="csvql-tui-results-",
            dir=str(temp_root) if temp_root is not None else None,
        )
        self._temp_paths: set[Path] = set()

    def put(self, result: QueryResult, *, sequence: int) -> TUIResultHandle:
        """Store a result and return a session-local handle."""

        if _should_spill(result):
            temp_path = Path(self._temp_dir.name) / f"query-{sequence}.pickle"
            with temp_path.open("wb") as file:
                pickle.dump(result, file, protocol=pickle.HIGHEST_PROTOCOL)
            self._temp_paths.add(temp_path)
            return TUIResultHandle(sequence=sequence, is_spilled=True, temp_path=temp_path)

        self._memory_results[sequence] = result
        return TUIResultHandle(sequence=sequence, is_spilled=False)

    def get(self, handle: TUIResultHandle) -> QueryResult:
        """Load a stored result by handle."""

        if not handle.is_spilled:
            return self._memory_results[handle.sequence]
        if handle.temp_path is None:
            raise KeyError(f"Missing temp path for result {handle.sequence}.")
        if handle.temp_path not in self._temp_paths:
            raise KeyError(f"Unknown temp path for result {handle.sequence}.")

        # Pickle is used only for session-owned spill files created by this store.
        # Unknown paths are rejected before this point so foreign files are never
        # deserialized through a forged handle.
        with handle.temp_path.open("rb") as file:
            loaded = pickle.load(file)
        if not isinstance(loaded, QueryResult):
            raise TypeError(f"Unexpected stored result type: {type(loaded).__name__}")
        return loaded

    def cleanup(self) -> None:
        """Remove any spilled temp files and release the session temp directory."""

        for path in tuple(self._temp_paths):
            path.unlink(missing_ok=True)
        self._temp_paths.clear()
        self._temp_dir.cleanup()


def _should_spill(result: QueryResult) -> bool:
    if result.row_count > TUI_RESULT_SPILL_ROW_THRESHOLD:
        return True
    return result.row_count * len(result.columns) > TUI_RESULT_SPILL_CELL_THRESHOLD
