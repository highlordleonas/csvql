from pathlib import Path

import pytest

from csvql.release_readiness import (
    select_built_wheel,
    version_strings_match,
)


def test_version_strings_match_requires_all_three_sources() -> None:
    assert version_strings_match("0.1.0", "0.1.0", "0.1.0") is True
    assert version_strings_match("0.1.0", "0.1.1", "0.1.0") is False


def test_select_built_wheel_returns_matching_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "csvql-0.1.0-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")

    assert select_built_wheel(tmp_path, "0.1.0") == wheel


def test_select_built_wheel_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        select_built_wheel(tmp_path, "0.1.0")
