"""Streaming export writers for one-shot query result sources."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from rich.cells import cell_len, chop_cells, set_cell_size

from csvql.atomic_write import OperationCancelled, OperationToken, atomic_text_output
from csvql.exceptions import ExportError
from csvql.export import ExportFormat, _format_csv_cell, _format_markdown_cell
from csvql.terminal_text import terminal_safe_text

_TEXT_STAGE_MARKER = {"format": "localql.streaming_export.text_rows.v1"}


class ExportRowSource(Protocol):
    @property
    def columns(self) -> tuple[str, ...]: ...

    def iter_rows(self) -> Iterator[tuple[object, ...]]: ...

    @property
    def elapsed_ms(self) -> float: ...


@dataclass(frozen=True, slots=True)
class ExportSummary:
    row_count: int
    elapsed_ms: float


def write_streaming_export(
    source: ExportRowSource,
    path: Path,
    *,
    export_format: ExportFormat,
    overwrite: bool,
    token: OperationToken | None = None,
) -> ExportSummary:
    """Write an export directly from a one-shot row source."""

    try:
        if export_format is ExportFormat.csv:
            return _write_csv_export(source, path, overwrite=overwrite, token=token)
        if export_format is ExportFormat.json:
            return _write_json_export(source, path, overwrite=overwrite, token=token)
        if export_format is ExportFormat.markdown:
            return _write_markdown_export(source, path, overwrite=overwrite, token=token)
        if export_format is ExportFormat.text:
            return _write_text_export(source, path, overwrite=overwrite, token=token)
    except OperationCancelled:
        raise
    except FileExistsError as exc:
        raise ExportError(
            f"Export output already exists: {path}",
            suggestion="Pass --force to overwrite it or choose a different output path.",
        ) from exc
    except OSError as exc:
        raise ExportError(
            f"Failed to write export output: {path}",
            suggestion="Check that the output path is writable.",
        ) from exc
    raise ExportError(
        f"Unsupported export format: {export_format}",
        suggestion="Use csv, json, markdown, or text.",
    )


def _write_csv_export(
    source: ExportRowSource,
    path: Path,
    *,
    overwrite: bool,
    token: OperationToken | None,
) -> ExportSummary:
    with atomic_text_output(path, newline="", overwrite=overwrite, token=token) as output:
        with _owned_source_iterator(source) as iterator:
            writer = csv.writer(output)
            writer.writerow(tuple(_format_csv_cell(column) for column in source.columns))
            row_count = 0
            for row in _iter_rows(iterator, token=token):
                writer.writerow(tuple(_format_csv_cell(value) for value in row))
                row_count += 1
    return ExportSummary(row_count=row_count, elapsed_ms=source.elapsed_ms)


def _write_json_export(
    source: ExportRowSource,
    path: Path,
    *,
    overwrite: bool,
    token: OperationToken | None,
) -> ExportSummary:
    with atomic_text_output(path, newline="", overwrite=overwrite, token=token) as output:
        with _owned_source_iterator(source) as iterator:
            output.write("{\n")
            output.write(f'  "columns": {_json_dumps(list(source.columns))},\n')
            output.write('  "rows": [\n')
            row_count = 0
            for row in _iter_rows(iterator, token=token):
                if row_count > 0:
                    output.write(",\n")
                output.write(f"    {_json_dumps(dict(zip(source.columns, row, strict=True)))}")
                row_count += 1
            output.write("\n  ],\n")
            output.write(f'  "row_count": {row_count},\n')
            output.write(f'  "elapsed_ms": {round(source.elapsed_ms, 3)}\n')
            output.write("}\n")
    return ExportSummary(row_count=row_count, elapsed_ms=source.elapsed_ms)


def _write_markdown_export(
    source: ExportRowSource,
    path: Path,
    *,
    overwrite: bool,
    token: OperationToken | None,
) -> ExportSummary:
    with atomic_text_output(path, newline="", overwrite=overwrite, token=token) as output:
        with _owned_source_iterator(source) as iterator:
            header = (
                "| " + " | ".join(_format_markdown_cell(column) for column in source.columns) + " |"
            )
            separator = "| " + " | ".join("---" for _ in source.columns) + " |"
            output.write(header)
            output.write("\n")
            output.write(separator)
            output.write("\n")
            row_count = 0
            for row in _iter_rows(iterator, token=token):
                output.write("| ")
                output.write(" | ".join(_format_markdown_cell(value) for value in row))
                output.write(" |\n")
                row_count += 1
    return ExportSummary(row_count=row_count, elapsed_ms=source.elapsed_ms)


def _write_text_export(
    source: ExportRowSource,
    path: Path,
    *,
    overwrite: bool,
    token: OperationToken | None,
) -> ExportSummary:
    stage_path: Path | None = None
    primary_error: BaseException | None = None
    try:
        row_count, widths, stage_path = _stage_text_rows(source, path, token=token)
        with atomic_text_output(path, newline="", overwrite=overwrite, token=token) as output:
            _render_staged_text_table(
                output,
                stage_path,
                columns=source.columns,
                widths=widths,
                row_count=row_count,
                elapsed_ms=source.elapsed_ms,
                token=token,
            )
            _cleanup_stage_file(stage_path, primary=None)
            stage_path = None
        return ExportSummary(row_count=row_count, elapsed_ms=source.elapsed_ms)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if stage_path is not None:
            _cleanup_stage_file(stage_path, primary=primary_error)


@contextmanager
def _owned_source_iterator(source: ExportRowSource) -> Iterator[Iterator[tuple[object, ...]]]:
    iterator = source.iter_rows()
    primary_error: BaseException | None = None
    try:
        yield iterator
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        _close_iterator(iterator, primary=primary_error)


def _iter_rows(
    iterator: Iterator[tuple[object, ...]],
    *,
    token: OperationToken | None,
) -> Iterator[tuple[object, ...]]:
    while True:
        if token is not None:
            token.raise_if_cancelled()
        try:
            yield next(iterator)
        except StopIteration:
            break


def _close_iterator(
    iterator: Iterator[tuple[object, ...]],
    *,
    primary: BaseException | None,
) -> None:
    close = getattr(iterator, "close", None)
    if close is None:
        return
    try:
        close()
    except BaseException:
        if primary is None:
            raise


def _stage_text_rows(
    source: ExportRowSource,
    path: Path,
    *,
    token: OperationToken | None,
) -> tuple[int, tuple[int, ...], Path]:
    stage_fd, stage_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".stream.tmp",
        dir=path.parent,
        text=True,
    )
    stage_path = Path(stage_name)
    row_count = 0
    widths = [cell_len(terminal_safe_text(column)) for column in source.columns]
    try:
        try:
            stage = os.fdopen(stage_fd, "w", encoding="utf-8", newline="")
        except BaseException:
            try:
                os.close(stage_fd)
            except OSError:
                pass
            raise
        with stage:
            with _owned_source_iterator(source) as iterator:
                stage.write(_json_dumps(_TEXT_STAGE_MARKER))
                stage.write("\n")
                for row in _iter_rows(iterator, token=token):
                    sanitized = tuple(terminal_safe_text(value) for value in row)
                    for index, cell in enumerate(sanitized):
                        if index >= len(widths):
                            widths.append(cell_len(cell))
                        else:
                            widths[index] = max(widths[index], cell_len(cell))
                    stage.write(_json_dumps(list(sanitized)))
                    stage.write("\n")
                    row_count += 1
    except BaseException:
        try:
            stage_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return row_count, tuple(widths), stage_path


def _render_staged_text_table(
    output: TextIO,
    stage_path: Path,
    *,
    columns: tuple[str, ...],
    widths: tuple[int, ...],
    row_count: int,
    elapsed_ms: float,
    token: OperationToken | None,
) -> None:
    if token is not None:
        token.raise_if_cancelled()

    if not columns:
        output.write("\n")
        output.write(f"{row_count} row(s) in {elapsed_ms:.2f} ms\n")
        return

    table_widths = _fit_table_widths(columns, widths, max_width=120)
    header_cells = [terminal_safe_text(column) for column in columns]

    output.write(_border_line("┏", "┳", "┓", "━", table_widths))
    output.write("\n")
    output.write(_row_line("┃", "┃", "┃", header_cells, table_widths))
    output.write("\n")
    output.write(_border_line("┡", "╇", "┩", "━", table_widths))
    output.write("\n")

    with stage_path.open("r", encoding="utf-8", newline="") as stage:
        marker = stage.readline()
        if _json_loads(marker) != _TEXT_STAGE_MARKER:
            raise RuntimeError("Invalid LocalQL text export staging marker.")
        for line in stage:
            if token is not None:
                token.raise_if_cancelled()
            cells = _json_loads(line)
            if not isinstance(cells, list) or len(cells) != len(columns):
                raise RuntimeError("Invalid LocalQL text export staging row.")
            _write_wrapped_row(output, [str(cell) for cell in cells], table_widths)

    output.write(_border_line("└", "┴", "┘", "─", table_widths))
    output.write("\n")
    output.write(f"{row_count} row(s) in {elapsed_ms:.2f} ms\n")


def _fit_table_widths(
    columns: tuple[str, ...],
    widths: tuple[int, ...],
    *,
    max_width: int,
) -> tuple[int, ...]:
    if not columns:
        return ()

    fitted = [
        max(cell_len(terminal_safe_text(column)), width)
        for column, width in zip(columns, widths, strict=True)
    ]
    border_width = sum(fitted) + (3 * len(fitted)) + 1
    if border_width <= max_width:
        return tuple(fitted)

    minimums = [1] * len(fitted)
    while sum(fitted) + (3 * len(fitted)) + 1 > max_width:
        widest = max(range(len(fitted)), key=fitted.__getitem__)
        if fitted[widest] == minimums[widest]:
            break
        fitted[widest] -= 1
    return tuple(fitted)


def _border_line(left: str, join: str, right: str, fill: str, widths: tuple[int, ...]) -> str:
    return left + join.join(fill * (width + 2) for width in widths) + right


def _row_line(
    left: str,
    separator: str,
    right: str,
    cells: list[str],
    widths: tuple[int, ...],
) -> str:
    padded = [" " + set_cell_size(cell, widths[index]) + " " for index, cell in enumerate(cells)]
    return left + separator.join(padded) + right


def _write_wrapped_row(output: TextIO, cells: list[str], widths: tuple[int, ...]) -> None:
    chunks = [
        chop_cells(cell, width) or [""]
        for cell, width in zip(cells, widths, strict=True)
    ]
    line_count = max(len(parts) for parts in chunks)
    for line_index in range(line_count):
        output.write(
            _row_line(
                "│",
                "│",
                "│",
                [parts[line_index] if line_index < len(parts) else "" for parts in chunks],
                widths,
            )
        )
        output.write("\n")


def _cleanup_stage_file(path: Path, *, primary: BaseException | None) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        if primary is None:
            raise


def _json_dumps(value: object) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def _json_loads(text: str) -> object:
    return json.loads(text)
