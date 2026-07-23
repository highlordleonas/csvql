from __future__ import annotations

from pytest import raises

from csvql.bounded_result import (
    DEFAULT_INTERACTIVE_ROW_LIMIT,
    MAX_PREVIEW_PAYLOAD_BYTES,
    BoundedQueryResult,
    PreviewAccumulator,
    PreviewPolicy,
)


def test_preview_policy_defaults_match_contract() -> None:
    policy = PreviewPolicy()

    assert policy.row_limit == DEFAULT_INTERACTIVE_ROW_LIMIT
    assert policy.payload_limit_bytes == MAX_PREVIEW_PAYLOAD_BYTES


def test_preview_policy_requires_positive_limits() -> None:
    with raises(ValueError, match="row_limit must be positive"):
        PreviewPolicy(row_limit=0)

    with raises(ValueError, match="row_limit must be positive"):
        PreviewPolicy(row_limit=-1)

    with raises(ValueError, match="payload_limit_bytes must be positive"):
        PreviewPolicy(payload_limit_bytes=0)

    with raises(ValueError, match="payload_limit_bytes must be positive"):
        PreviewPolicy(payload_limit_bytes=-1)


def test_preview_accumulator_accepts_exact_row_limit_without_truncation() -> None:
    accumulator = PreviewAccumulator(
        columns=("id",),
        elapsed_ms=1.5,
        policy=PreviewPolicy(row_limit=2, payload_limit_bytes=20),
    )

    assert accumulator.consider((1,), b"abc") is True
    assert accumulator.consider((2,), b"def") is True

    result = accumulator.finish()

    assert result == BoundedQueryResult(
        columns=("id",),
        rows=((1,), (2,)),
        elapsed_ms=1.5,
        preview_payload_bytes=6,
        has_more_rows=False,
        truncation_reason=None,
    )


def test_preview_accumulator_omits_row_that_would_exceed_byte_limit() -> None:
    accumulator = PreviewAccumulator(
        columns=("id",),
        elapsed_ms=2.5,
        policy=PreviewPolicy(row_limit=3, payload_limit_bytes=10),
    )

    assert accumulator.consider((1,), b"abcd") is True
    assert accumulator.consider((2,), b"efgh") is True
    assert accumulator.consider((3,), b"ijk") is False

    result = accumulator.finish()

    assert result == BoundedQueryResult(
        columns=("id",),
        rows=((1,), (2,)),
        elapsed_ms=2.5,
        preview_payload_bytes=8,
        has_more_rows=True,
        truncation_reason="byte_limit",
    )


def test_preview_accumulator_accepts_row_that_exactly_fills_byte_limit() -> None:
    accumulator = PreviewAccumulator(
        columns=("id",),
        elapsed_ms=3.0,
        policy=PreviewPolicy(row_limit=3, payload_limit_bytes=7),
    )

    assert accumulator.consider((1,), b"abc") is True
    assert accumulator.consider((2,), b"defg") is True

    result = accumulator.finish()

    assert result.preview_payload_bytes == 7
    assert result.rows == ((1,), (2,))
    assert result.has_more_rows is False
    assert result.truncation_reason is None


def test_preview_accumulator_records_first_truncation_reason() -> None:
    accumulator = PreviewAccumulator(
        columns=("id",),
        elapsed_ms=1.0,
        policy=PreviewPolicy(row_limit=1, payload_limit_bytes=100),
    )

    assert accumulator.consider((1,), b"a") is True
    assert accumulator.consider((2,), b"b") is False
    assert accumulator.consider((3,), b"c" * 200) is False

    result = accumulator.finish()

    assert result.rows == ((1,),)
    assert result.preview_payload_bytes == 1
    assert result.has_more_rows is True
    assert result.truncation_reason == "row_limit"


def test_preview_accumulator_keeps_first_byte_limit_truncation_reason() -> None:
    accumulator = PreviewAccumulator(
        columns=("id",),
        elapsed_ms=4.0,
        policy=PreviewPolicy(row_limit=5, payload_limit_bytes=3),
    )

    assert accumulator.consider((1,), b"abcd") is False
    assert accumulator.consider((2,), b"b") is False

    result = accumulator.finish()

    assert result.rows == ()
    assert result.preview_payload_bytes == 0
    assert result.has_more_rows is True
    assert result.truncation_reason == "byte_limit"
