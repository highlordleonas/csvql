from __future__ import annotations

import gc
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from csvql.export import ExportFormat
from csvql.streaming_export import write_streaming_export

_MILLION_ROWS = 1_000_000


class _TrackedValue:
    def __init__(self, value: int, counter: dict[str, int]) -> None:
        self._value = value
        self._counter = counter
        counter["created"] += 1
        counter["live"] += 1
        counter["peak_live"] = max(counter["peak_live"], counter["live"])

    def __str__(self) -> str:
        return str(self._value)

    def __del__(self) -> None:
        self._counter["live"] -= 1


class _RollingMillionRowSource:
    def __init__(self, row_count: int) -> None:
        self.columns = ("row_id", "value")
        self.elapsed_ms = 42.0
        self._row_count = row_count
        self.iter_calls = 0
        self.close_calls = 0
        self.counter = {"created": 0, "live": 0, "peak_live": 0}

    def iter_rows(self) -> Iterator[tuple[object, ...]]:
        self.iter_calls += 1
        if self.iter_calls > 1:
            raise AssertionError("iter_rows called more than once")
        return _RollingIterator(self)


class _RollingIterator:
    def __init__(self, source: _RollingMillionRowSource) -> None:
        self._source = source
        self._index = 0

    def __iter__(self) -> _RollingIterator:
        return self

    def __next__(self) -> tuple[object, ...]:
        if self._index >= self._source._row_count:
            raise StopIteration
        row = (
            self._index,
            _TrackedValue(self._index, self._source.counter),
        )
        self._index += 1
        return row

    def close(self) -> None:
        self._source.close_calls += 1


@contextmanager
def _counting_atomic_output(*args: Any, **kwargs: Any) -> Iterator[Any]:
    del args, kwargs

    class CountingWriter:
        def __init__(self) -> None:
            self.write_calls = 0
            self.bytes_written = 0

        def write(self, content: str) -> int:
            self.write_calls += 1
            self.bytes_written += len(content)
            return len(content)

    yield CountingWriter()


@pytest.mark.parametrize("export_format", [ExportFormat.csv, ExportFormat.json])
def test_streaming_export_million_rows_does_not_accumulate_live_row_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    export_format: ExportFormat,
) -> None:
    output_path = tmp_path / f"result.{export_format.value}"
    source = _RollingMillionRowSource(_MILLION_ROWS)
    monkeypatch.setattr("csvql.streaming_export.atomic_text_output", _counting_atomic_output)

    summary = write_streaming_export(
        source,
        output_path,
        export_format=export_format,
        overwrite=False,
    )
    gc.collect()

    assert summary.row_count == _MILLION_ROWS
    assert summary.elapsed_ms == pytest.approx(42.0)
    assert source.iter_calls == 1
    assert source.close_calls == 1
    assert source.counter["created"] == _MILLION_ROWS
    assert source.counter["live"] == 0
    assert source.counter["peak_live"] <= 4
