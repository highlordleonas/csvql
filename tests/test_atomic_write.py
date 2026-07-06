from pathlib import Path

import pytest

from csvql.atomic_write import OperationCancelled, OperationToken, write_text_atomic


def test_write_text_atomic_writes_final_content(tmp_path: Path) -> None:
    output_path = tmp_path / "result.txt"

    write_text_atomic(output_path, "hello\n")

    assert output_path.read_text(encoding="utf-8") == "hello\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))


def test_write_text_atomic_preserves_previous_file_when_cancelled_before_replace(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.txt"
    output_path.write_text("old\n", encoding="utf-8")
    token = OperationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        write_text_atomic(output_path, "new\n", token=token)

    assert output_path.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".result.txt.*.tmp"))
