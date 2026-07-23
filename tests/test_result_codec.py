from __future__ import annotations

import pickle
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from math import isnan
from uuid import UUID

import pytest

from csvql.result_codec import (
    ROW_PAYLOAD_VERSION,
    RowPayloadCodecError,
    decode_row_payload,
    encode_row_payload,
)


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


def test_row_payload_round_trips_all_observed_value_families() -> None:
    row = _observed_value_families_row()

    decoded = decode_row_payload(encode_row_payload(row))

    assert decoded[:9] == row[:9]
    assert isnan(decoded[9])
    assert decoded[10:-1] == row[10:-1]
    assert decoded[-1] == row[-1]
    assert decoded[7] == float("inf")
    assert decoded[8] == float("-inf")


def test_row_payload_decoder_rejects_unknown_version() -> None:
    row = ("value", 1)
    payload = bytes([ROW_PAYLOAD_VERSION + 1]) + encode_row_payload(row)[1:]

    with pytest.raises(RowPayloadCodecError, match="Unsupported row payload version"):
        decode_row_payload(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "Unsupported row payload version"),
        (bytes([ROW_PAYLOAD_VERSION]) + b"not-a-pickle", "Malformed row payload"),
        (
            bytes([ROW_PAYLOAD_VERSION]) + pickle.dumps(["value"], protocol=5),
            "Malformed row payload",
        ),
    ],
)
def test_row_payload_decoder_rejects_malformed_payload_shapes(payload: bytes, message: str) -> None:
    with pytest.raises(RowPayloadCodecError, match=message):
        decode_row_payload(payload)
