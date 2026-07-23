"""Private row-payload codec for LocalQL-managed preview storage."""

from __future__ import annotations

import pickle

ROW_PAYLOAD_VERSION = 1


class RowPayloadCodecError(ValueError):
    """Raised when a LocalQL-managed row payload cannot be decoded safely."""


def encode_row_payload(row: tuple[object, ...]) -> bytes:
    """Encode one LocalQL row payload with an explicit version prefix."""

    return bytes((ROW_PAYLOAD_VERSION,)) + pickle.dumps(row, protocol=5)


def decode_row_payload(payload: bytes) -> tuple[object, ...]:
    """Decode one LocalQL-managed row payload and reject unknown shapes."""

    if not payload:
        raise RowPayloadCodecError("Unsupported row payload version")
    version = payload[0]
    if version != ROW_PAYLOAD_VERSION:
        raise RowPayloadCodecError("Unsupported row payload version")
    try:
        decoded = pickle.loads(payload[1:])
    except (
        pickle.PickleError,
        EOFError,
        ImportError,
        IndexError,
        ValueError,
        TypeError,
        AttributeError,
    ) as exc:
        raise RowPayloadCodecError("Malformed row payload") from exc
    if not isinstance(decoded, tuple):
        raise RowPayloadCodecError("Malformed row payload")
    return decoded
