import csv
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.cells import cell_len

from csvql.atomic_write import OperationCancelled, OperationToken, atomic_text_output
from csvql.exceptions import ExportError
from csvql.export import ExportFormat
from csvql.streaming_export import write_streaming_export
from csvql.terminal_text import terminal_safe_text


class _IteratorClosed(Exception):
    pass


class _OneShotIterator:
    def __init__(
        self,
        rows: Iterator[tuple[object, ...]],
        *,
        token: OperationToken | None = None,
        cancel_after_rows: int | None = None,
        fail_after_rows: int | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self._rows = rows
        self._token = token
        self._cancel_after_rows = cancel_after_rows
        self._fail_after_rows = fail_after_rows
        self._close_error = close_error
        self._index = 0
        self.close_calls = 0

    def __iter__(self) -> "_OneShotIterator":
        return self

    def __next__(self) -> tuple[object, ...]:
        if self._fail_after_rows is not None and self._index >= self._fail_after_rows:
            raise RuntimeError(f"row failure at {self._index}")
        if self._cancel_after_rows is not None and self._index >= self._cancel_after_rows:
            if self._token is None:
                raise AssertionError("cancel_after_rows requires a token")
            self._token.cancel()
        row = next(self._rows)
        self._index += 1
        return row

    def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _OneShotSource:
    def __init__(
        self,
        columns: tuple[str, ...],
        rows: Iterator[tuple[object, ...]] | list[tuple[object, ...]],
        *,
        elapsed_ms: float = 1.234,
        token: OperationToken | None = None,
        cancel_after_rows: int | None = None,
        fail_after_rows: int | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.columns = columns
        self.elapsed_ms = elapsed_ms
        self._iterator = _OneShotIterator(
            iter(rows),
            token=token,
            cancel_after_rows=cancel_after_rows,
            fail_after_rows=fail_after_rows,
            close_error=close_error,
        )
        self.iter_calls = 0

    def iter_rows(self) -> Iterator[tuple[object, ...]]:
        self.iter_calls += 1
        if self.iter_calls > 1:
            raise AssertionError("iter_rows called more than once")
        return self._iterator


def _csv_rows(path: Path) -> list[list[str]]:
    return list(csv.reader(StringIO(path.read_text(encoding="utf-8"))))


def _lazy_rows(count: int) -> Iterator[tuple[int, str]]:
    for index in range(count):
        yield (index, f"value-{index}")


@contextmanager
def _failing_atomic_output(
    events: list[str],
    *,
    fail_after_writes: int,
) -> Iterator[Any]:
    class RecordingWriter:
        def __init__(self) -> None:
            self.write_calls = 0

        def write(self, content: str) -> int:
            self.write_calls += 1
            events.append(f"write:{self.write_calls}")
            if self.write_calls > fail_after_writes:
                raise RuntimeError("disk full")
            return len(content)

    events.append("enter")
    try:
        yield RecordingWriter()
    except BaseException as exc:
        events.append(f"exit:{type(exc).__name__}")
        raise
    else:
        events.append("exit:none")


def test_streaming_csv_export_consumes_one_shot_source_once(tmp_path: Path) -> None:
    output_path = tmp_path / "result.csv"
    source = _OneShotSource(
        ("=formula", "note", "amount"),
        [
            ("=1+1", "pipe | value", 20.5),
            ("Blair", "line\nbreak", None),
        ],
    )

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.csv,
        overwrite=False,
    )

    assert summary.row_count == 2
    assert summary.elapsed_ms == pytest.approx(1.234)
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert _csv_rows(output_path) == [
        ["'=formula", "note", "amount"],
        ["'=1+1", "pipe | value", "20.5"],
        ["Blair", "line\nbreak", ""],
    ]


def test_streaming_json_export_preserves_shape_and_rounds_elapsed_ms(tmp_path: Path) -> None:
    output_path = tmp_path / "result.json"
    marker = object()
    source = _OneShotSource(
        ("when", "value"),
        [("2026-07-23", marker), ("later", None)],
        elapsed_ms=1.23456,
    )

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.json,
        overwrite=False,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary.row_count == 2
    assert payload == {
        "columns": ["when", "value"],
        "elapsed_ms": 1.235,
        "row_count": 2,
        "rows": [
            {"when": "2026-07-23", "value": str(marker)},
            {"when": "later", "value": None},
        ],
    }
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1


def test_streaming_markdown_export_preserves_existing_escaping(tmp_path: Path) -> None:
    output_path = tmp_path / "result.md"
    source = _OneShotSource(
        ("<b>name</b>",),
        [("<img src=x onerror=alert(1)>|line\nbreak&more",), (None,)],
    )

    write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.markdown,
        overwrite=False,
    )

    assert output_path.read_text(encoding="utf-8") == (
        "| &lt;b&gt;name&lt;/b&gt; |\n"
        "| --- |\n"
        "| &lt;img src=x onerror=alert(1)&gt;\\|line<br>break&amp;more |\n"
        "|  |\n"
    )
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1


def test_streaming_text_export_uses_sidecar_second_pass_without_rerunning_source(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    keep_path = tmp_path / "keep.txt"
    keep_path.write_text("keep\n", encoding="utf-8")
    source = _OneShotSource(
        ("name", "note"),
        [("Alex", "line\nbreak"), ("Blair", "\x1b[31mred\x1b[0m")],
        elapsed_ms=1.234,
    )

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.text,
        overwrite=False,
    )

    output = output_path.read_text(encoding="utf-8")
    assert summary.row_count == 2
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert "line\\x0abreak" in output
    assert "\\x1b[31mred\\x1b[0m" in output
    assert all(cell_len(line) <= 120 for line in output.splitlines())
    assert output.endswith("2 row(s) in 1.23 ms\n")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt", "result.txt"]


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    [
        (ExportFormat.csv, ".csv"),
        (ExportFormat.json, ".json"),
        (ExportFormat.markdown, ".md"),
        (ExportFormat.text, ".txt"),
    ],
)
def test_streaming_export_zero_rows_keeps_columns_and_reports_empty_summary(
    tmp_path: Path,
    export_format: ExportFormat,
    suffix: str,
) -> None:
    output_path = tmp_path / f"result{suffix}"
    source = _OneShotSource(("alpha", "beta"), [])

    summary = write_streaming_export(
        source,
        output_path,
        export_format=export_format,
        overwrite=False,
    )

    assert summary.row_count == 0
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    if export_format is ExportFormat.csv:
        assert _csv_rows(output_path) == [["alpha", "beta"]]
    elif export_format is ExportFormat.json:
        assert json.loads(output_path.read_text(encoding="utf-8"))["rows"] == []
    elif export_format is ExportFormat.markdown:
        assert output_path.read_text(encoding="utf-8") == "| alpha | beta |\n| --- | --- |\n"
    else:
        assert output_path.read_text(encoding="utf-8") == (
            "┏━━━━━━━┳━━━━━━┓\n"
            "┃ alpha ┃ beta ┃\n"
            "┡━━━━━━━╇━━━━━━┩\n"
            "└───────┴──────┘\n"
            "0 row(s) in 1.23 ms\n"
        )


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_streaming_export_cleans_up_output_and_sidecar_when_row_iteration_fails(
    tmp_path: Path,
    export_format: ExportFormat,
) -> None:
    suffix = {
        ExportFormat.csv: ".csv",
        ExportFormat.json: ".json",
        ExportFormat.markdown: ".md",
        ExportFormat.text: ".txt",
    }[export_format]
    output_path = tmp_path / f"result{suffix}"
    keep_path = tmp_path / "keep.txt"
    keep_path.write_text("keep\n", encoding="utf-8")
    source = _OneShotSource(
        ("id", "value"),
        [(1, "a"), (2, "b"), (3, "c")],
        fail_after_rows=2,
    )

    with pytest.raises(RuntimeError, match="row failure at 2"):
        write_streaming_export(
            source,
            output_path,
            export_format=export_format,
            overwrite=False,
        )

    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt"]


def test_streaming_export_checks_cancellation_during_iteration_and_cleans_up(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.json"
    token = OperationToken()
    source = _OneShotSource(
        ("id",),
        [(1,), (2,), (3,)],
        token=token,
        cancel_after_rows=1,
    )

    with pytest.raises(OperationCancelled):
        write_streaming_export(
            source,
            output_path,
            export_format=ExportFormat.json,
            overwrite=False,
            token=token,
        )

    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert not output_path.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == []


def test_streaming_export_no_overwrite_race_preserves_existing_file_and_cleans_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.csv"
    output_path.write_text("existing\n", encoding="utf-8")
    source = _OneShotSource(("id",), [(1,), (2,)])

    def fail_link(source_path: Path, target_path: Path) -> None:
        del source_path, target_path
        raise FileExistsError(output_path.name)

    monkeypatch.setattr("csvql.atomic_write.os.link", fail_link)

    with pytest.raises(ExportError, match="Export output already exists"):
        write_streaming_export(
            source,
            output_path,
            export_format=ExportFormat.csv,
            overwrite=False,
        )

    assert output_path.read_text(encoding="utf-8") == "existing\n"
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["result.csv"]


def test_streaming_export_closes_iterator_before_rolling_back_failed_destination_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.csv"
    source = _OneShotSource(("id",), [(1,), (2,)])
    events: list[str] = []

    def record_close() -> None:
        events.append("iterator-close")
        source._iterator.close_calls += 1

    source._iterator.close = record_close  # type: ignore[method-assign]
    monkeypatch.setattr(
        "csvql.streaming_export.atomic_text_output",
        lambda *args, **kwargs: _failing_atomic_output(events, fail_after_writes=1),
    )

    with pytest.raises(RuntimeError, match="disk full"):
        write_streaming_export(
            source,
            output_path,
            export_format=ExportFormat.csv,
            overwrite=False,
        )

    assert events == ["enter", "write:1", "write:2", "iterator-close", "exit:RuntimeError"]
    assert not output_path.exists()


def test_streaming_export_closes_iterator_before_successful_destination_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.csv"
    source = _OneShotSource(("id",), [(1,), (2,)])
    events: list[str] = []

    def record_close() -> None:
        events.append("iterator-close")
        source._iterator.close_calls += 1

    source._iterator.close = record_close  # type: ignore[method-assign]

    @contextmanager
    def recording_atomic_output(*args: object, **kwargs: object) -> Iterator[Any]:
        del args, kwargs

        class RecordingWriter:
            def write(self, content: str) -> int:
                events.append(f"write:{len(content)}")
                return len(content)

        events.append("enter")
        try:
            yield RecordingWriter()
        except BaseException as exc:
            events.append(f"exit:{type(exc).__name__}")
            raise
        else:
            events.append("exit:none")

    monkeypatch.setattr("csvql.streaming_export.atomic_text_output", recording_atomic_output)

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.csv,
        overwrite=False,
    )

    assert summary.row_count == 2
    assert events[0] == "enter"
    assert events[-2:] == ["iterator-close", "exit:none"]
    assert source._iterator.close_calls == 1
    assert not output_path.exists()


def test_streaming_export_preserves_primary_failure_when_iterator_close_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.csv"
    source = _OneShotSource(
        ("id",),
        [(1,), (2,)],
        close_error=_IteratorClosed("close failed"),
    )
    monkeypatch.setattr(
        "csvql.streaming_export.atomic_text_output",
        lambda *args, **kwargs: _failing_atomic_output([], fail_after_writes=1),
    )

    with pytest.raises(RuntimeError, match="disk full"):
        write_streaming_export(
            source,
            output_path,
            export_format=ExportFormat.csv,
            overwrite=False,
        )

    assert source._iterator.close_calls == 1
    assert not output_path.exists()


def test_streaming_export_fails_closed_when_successful_iteration_close_fails(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.csv"
    source = _OneShotSource(
        ("id",),
        [(1,), (2,)],
        close_error=_IteratorClosed("close failed"),
    )

    with pytest.raises(_IteratorClosed, match="close failed"):
        write_streaming_export(
            source,
            output_path,
            export_format=ExportFormat.csv,
            overwrite=False,
        )

    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert not output_path.exists()


def test_streaming_text_export_large_lazy_generator_emits_each_row_exactly_once(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    source = _OneShotSource(("id", "value"), _lazy_rows(500), elapsed_ms=9.876)

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.text,
        overwrite=False,
    )

    output = output_path.read_text(encoding="utf-8")
    extracted = {
        int(match.group(1)): match.group(2)
        for match in re.finditer(r"│\s*(\d+)\s*│\s*(value-\d+)\s*│", output)
    }
    assert summary.row_count == 500
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert output.endswith("500 row(s) in 9.88 ms\n")
    assert len(extracted) == 500
    assert extracted[2] == "value-2"
    assert extracted[20] == "value-20"
    assert all(cell_len(line) <= 120 for line in output.splitlines())


def test_streaming_text_export_caps_terminal_width_for_wide_unicode_cells(tmp_path: Path) -> None:
    output_path = tmp_path / "result.txt"
    wide_value = ("表" * 60) + "\n" + ("\x1b[31mCTRL\x1b[0m") + ("表" * 60)
    source = _OneShotSource(
        ("id", "wide"),
        [(1, wide_value)],
        elapsed_ms=2.5,
    )

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.text,
        overwrite=False,
    )

    output = output_path.read_text(encoding="utf-8")
    lines = output.splitlines()
    wrapped_segments = [line.split("│")[2].strip() for line in lines if line.startswith("│")]

    assert summary.row_count == 1
    assert all(cell_len(line) <= 120 for line in lines)
    assert "".join(wrapped_segments) == terminal_safe_text(wide_value)
    assert output.endswith("1 row(s) in 2.50 ms\n")


def test_streaming_text_export_wraps_long_header_without_loss(tmp_path: Path) -> None:
    output_path = tmp_path / "result.txt"
    header = ("表" * 40) + "\n" + "\x1b[31mHDR\x1b[0m" + ("表" * 40)
    source = _OneShotSource(
        (header, "short"),
        [("value", "ok")],
    )

    write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.text,
        overwrite=False,
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    header_lines: list[str] = []
    for line in lines[1:]:
        if line.startswith("┡"):
            break
        if line.startswith("┃"):
            header_lines.append(line)

    reconstructed_header = "".join(part.split("┃")[1].strip() for part in header_lines)

    assert all(cell_len(line) <= 120 for line in lines)
    assert reconstructed_header == terminal_safe_text(header)


def test_streaming_text_export_long_form_fallback_cleans_sidecar_pre_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "result.txt"
    columns = tuple(f"col_{index:02d}" for index in range(41))
    row = tuple(f"value_{index:02d}" for index in range(41))
    source = _OneShotSource(columns, [row], elapsed_ms=4.25)
    stage_absent_on_exit: list[bool] = []

    @contextmanager
    def recording_atomic_output(*args: Any, **kwargs: Any) -> Iterator[Any]:
        with atomic_text_output(*args, **kwargs) as output:
            try:
                yield output
            finally:
                stage_absent_on_exit.append(not any(tmp_path.glob(".result.txt.*.stream.tmp")))

    monkeypatch.setattr("csvql.streaming_export.atomic_text_output", recording_atomic_output)

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.text,
        overwrite=False,
    )

    output = output_path.read_text(encoding="utf-8")
    lines = output.splitlines()

    assert summary.row_count == 1
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert stage_absent_on_exit == [True]
    assert all(cell_len(line) <= 120 for line in lines)
    assert "row" in output and "column" in output and "value" in output
    for token in columns + row:
        assert token in output
    assert not any(tmp_path.glob(".result.txt.*.stream.tmp"))


def test_streaming_text_export_long_form_zero_rows_preserves_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "result.txt"
    columns = tuple(f"col_{index:02d}" for index in range(41))
    source = _OneShotSource(columns, [], elapsed_ms=3.0)

    summary = write_streaming_export(
        source,
        output_path,
        export_format=ExportFormat.text,
        overwrite=False,
    )

    output = output_path.read_text(encoding="utf-8")
    lines = output.splitlines()

    assert summary.row_count == 0
    assert source.iter_calls == 1
    assert source._iterator.close_calls == 1
    assert all(cell_len(line) <= 120 for line in lines)
    for column in columns:
        assert column in output
    assert output.endswith("0 row(s) in 3.00 ms\n")
