from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.source_resolver import resolve_path_or_catalog_source


def _write_csv(path: Path, content: str = "id,value\n1,2\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolve_path_or_catalog_source_treats_path_looking_input_as_path(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "data" / "orders.csv"
    _write_csv(csv_path)

    source = resolve_path_or_catalog_source("data/orders.csv", base_dir=tmp_path)

    assert source.path == csv_path.resolve()
    assert source.display_path == "data/orders.csv"


def test_resolve_path_or_catalog_source_resolves_catalog_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "data" / "orders.csv"
    _write_csv(csv_path)
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )

    source = resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert source.path == csv_path.resolve()
    assert source.display_path == "orders"


def test_resolve_path_or_catalog_source_falls_back_to_path_error_for_unknown_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: 1\ntables: {}\n", encoding="utf-8")

    with pytest.raises(FileMissingError) as exc_info:
        resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert "CSV file not found: orders" in exc_info.value.message


def test_resolve_path_or_catalog_source_preserves_invalid_catalog_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".csvql.yml").write_text("version: [1\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as exc_info:
        resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert "Invalid YAML" in exc_info.value.message
