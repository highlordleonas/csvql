from __future__ import annotations

import os
import stat
import struct
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from math import isnan
from pathlib import Path
from uuid import UUID

import pytest

from csvql.result_codec import encode_row_payload
from csvql.result_spool import (
    FOOTER_FRAME,
    SPOOL_MAGIC,
    SPOOL_VERSION,
    ResultSpoolError,
    ResultSpoolReader,
    ResultSpoolWriter,
)


def _reader_for(spool_path: Path) -> ResultSpoolReader:
    return ResultSpoolReader.from_file(spool_path.open("rb"))


def _observed_value_families_row() -> tuple[object, ...]:
    return (
        None,
        True,
        False,
        0,
        -(2**63),
        2**100,
        1.25,
        float("inf"),
        float("-inf"),
        float("nan"),
        Decimal("1234567890.123456789"),
        "plain text",
        b"\x00\xffbytes",
        date(2026, 7, 23),
        time(12, 34, 56, 789123),
        datetime(2026, 7, 23, 12, 34, 56, 789123),
        datetime(2026, 7, 23, 12, 34, 56, 789123, tzinfo=UTC),
        timedelta(days=2, seconds=3, microseconds=4),
        UUID("12345678-1234-5678-1234-567812345678"),
        ["alpha", 1, None],
        {"left": 1, "right": [Decimal("2.5"), {"nested": True}]},
        (
            {"events": [datetime(2026, 7, 23, 12, 0, tzinfo=UTC), None]},
            [UUID("87654321-4321-8765-4321-876543218765"), {"delta": timedelta(seconds=5)}],
        ),
    )


def _write_spool(
    tmp_path: Path,
    *,
    columns: tuple[str, ...] = ("id",),
    rows: tuple[tuple[object, ...], ...] = ((1,),),
) -> tuple[Path, object]:
    staging_path = tmp_path / ".query-1-aaaaaaaaaaaaaaaa.result.tmp"
    final_path = tmp_path / "query-1.result"
    writer = ResultSpoolWriter(
        staging_path=staging_path,
        final_path=final_path,
        columns=columns,
    )
    for row in rows:
        writer.append_payload(encode_row_payload(row))
    metadata = writer.commit()
    return final_path, metadata


def test_result_spool_round_trips_all_observed_value_families(tmp_path: Path) -> None:
    row = _observed_value_families_row()
    spool_path, metadata = _write_spool(
        tmp_path,
        columns=tuple(f"c{index}" for index in range(len(row))),
        rows=(row,),
    )

    reader = _reader_for(spool_path)
    decoded = tuple(reader.iter_rows())

    assert reader.columns == metadata.columns
    assert metadata.row_count == 1
    assert metadata.logical_bytes == spool_path.stat().st_size
    assert decoded[0][:9] == row[:9]
    assert isnan(decoded[0][9])
    assert decoded[0][10:] == row[10:]


def test_result_spool_round_trips_zero_rows_with_exact_eof(tmp_path: Path) -> None:
    spool_path, metadata = _write_spool(tmp_path, columns=("left", "right"), rows=())

    reader = _reader_for(spool_path)

    assert reader.columns == ("left", "right")
    assert tuple(reader.iter_rows()) == ()
    assert metadata.row_count == 0
    assert spool_path.read_bytes().endswith(struct.pack(">BQ", FOOTER_FRAME, 0))


def test_result_spool_writer_uses_owner_only_staging_and_atomic_final_name(tmp_path: Path) -> None:
    staging_path = tmp_path / ".query-7-aaaaaaaaaaaaaaaa.result.tmp"
    final_path = tmp_path / "query-7.result"
    writer = ResultSpoolWriter(
        staging_path=staging_path,
        final_path=final_path,
        columns=("id",),
    )

    writer.append_payload(encode_row_payload((1,)))
    writer.commit()

    assert not staging_path.exists()
    assert final_path.exists()
    if os.name != "nt":
        assert stat.S_IMODE(final_path.stat().st_mode) == 0o600


def test_result_spool_reader_rejects_truncated_footer(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    spool_path.write_bytes(spool_path.read_bytes()[:-1])

    with pytest.raises(ResultSpoolError, match="invalid row frame length"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_bad_magic(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    data[: len(SPOOL_MAGIC)] = b"XXXXX"
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="unsupported spool magic"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_unknown_version(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    data[5] = SPOOL_VERSION + 1
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="unsupported spool version"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_truncated_header(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    spool_path.write_bytes(spool_path.read_bytes()[:4])

    with pytest.raises(ResultSpoolError, match="truncated header"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_truncated_schema_metadata(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    data[6:14] = struct.pack(">Q", 10_000)
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="invalid schema length"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_malformed_utf8_schema(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, columns=("id",), rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    schema_offset = 14
    name_length_offset = schema_offset + 8
    data[name_length_offset + 8 + 1] = 0xFF
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="malformed schema metadata"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_unknown_frame_type(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    frame_offset = len(data) - 9 - 9 - len(encode_row_payload((1,)))
    data[frame_offset] = 3
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="unsupported frame type"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_impossible_frame_length_before_allocation(
    tmp_path: Path,
) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    footer_offset = len(data) - 9
    frame_header_start = footer_offset - (9 + len(encode_row_payload((1,))))
    data[frame_header_start + 1 : frame_header_start + 9] = struct.pack(">Q", 2**63)
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="invalid row frame length"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_truncated_row_payload(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    data = data[:-10]
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="invalid row frame length"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_footer_count_mismatch(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    data[-8:] = struct.pack(">Q", 2)
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="footer row count mismatch"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_trailing_bytes(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    spool_path.write_bytes(spool_path.read_bytes() + b"x")

    with pytest.raises(ResultSpoolError, match="trailing bytes"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_malformed_row_payload(tmp_path: Path) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    footer_offset = len(data) - 9
    payload = b"\xffnot-a-valid-row-payload"
    frame_start = footer_offset - (9 + len(encode_row_payload((1,))))
    data[frame_start + 9 : footer_offset] = payload
    data[frame_start + 1 : frame_start + 9] = struct.pack(">Q", len(payload))
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="malformed row payload"):
        tuple(_reader_for(spool_path).iter_rows())


@pytest.mark.parametrize(
    ("columns", "row"),
    [
        (("left", "right"), (1,)),
        (("left", "right"), (1, 2, 3)),
    ],
)
def test_result_spool_reader_rejects_schema_arity_mismatch(
    tmp_path: Path,
    columns: tuple[str, ...],
    row: tuple[object, ...],
) -> None:
    spool_path, _metadata = _write_spool(tmp_path, columns=columns, rows=(row,))

    with pytest.raises(ResultSpoolError, match="malformed row payload"):
        next(_reader_for(spool_path).iter_rows())


def test_result_spool_reader_rejects_frame_length_that_consumes_footer(
    tmp_path: Path,
) -> None:
    spool_path, _metadata = _write_spool(tmp_path, rows=((1,),))
    data = bytearray(spool_path.read_bytes())
    footer_offset = len(data) - 9
    frame_header_start = footer_offset - (9 + len(encode_row_payload((1,))))
    remaining_after_frame_length = footer_offset - (frame_header_start + 9)
    data[frame_header_start + 1 : frame_header_start + 9] = struct.pack(
        ">Q",
        remaining_after_frame_length + 1,
    )
    spool_path.write_bytes(data)

    with pytest.raises(ResultSpoolError, match="invalid row frame length"):
        tuple(_reader_for(spool_path).iter_rows())


def test_result_spool_writer_rollback_deletes_only_staging_file(tmp_path: Path) -> None:
    staging_path = tmp_path / ".query-8-aaaaaaaaaaaaaaaa.result.tmp"
    final_path = tmp_path / "query-8.result"
    foreign_path = tmp_path / "foreign.txt"
    foreign_path.write_text("retain", encoding="utf-8")
    writer = ResultSpoolWriter(
        staging_path=staging_path,
        final_path=final_path,
        columns=("id",),
    )

    writer.append_payload(encode_row_payload((1,)))
    writer.rollback()

    assert not staging_path.exists()
    assert not final_path.exists()
    assert foreign_path.read_text(encoding="utf-8") == "retain"


def test_result_spool_writer_rejects_foreign_final_without_overwrite(tmp_path: Path) -> None:
    staging_path = tmp_path / ".query-9-aaaaaaaaaaaaaaaa.result.tmp"
    final_path = tmp_path / "query-9.result"
    foreign_bytes = b"foreign-final"
    final_path.write_bytes(foreign_bytes)
    writer = ResultSpoolWriter(
        staging_path=staging_path,
        final_path=final_path,
        columns=("id",),
    )

    writer.append_payload(encode_row_payload((1,)))

    with pytest.raises(FileExistsError):
        writer.commit()

    assert final_path.read_bytes() == foreign_bytes
    assert not staging_path.exists()
