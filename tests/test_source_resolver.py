from pathlib import Path

import pytest

import csvql.source_resolver as source_resolver_module
from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.project_config import ProjectConfig, ProjectContext, ProjectTable
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


def test_resolve_path_or_catalog_source_matches_catalog_alias_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "data" / "orders.csv"
    _write_csv(csv_path)
    (tmp_path / ".csvql.yml").write_text(
        "version: 1\ntables:\n  Orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )

    source = resolve_path_or_catalog_source("orders", base_dir=tmp_path)

    assert source.path == csv_path.resolve()
    assert source.display_path == "orders"


def test_catalog_alias_resolution_uses_the_project_anchor_not_process_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "orders.csv"
    _write_csv(csv_path)
    (project_root / ".csvql.yml").write_text(
        "version: 1\ntables:\n  Orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    source = resolve_path_or_catalog_source("orders", base_dir=project_root)
    monkeypatch.chdir(tmp_path / "project" / "data")

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


def test_catalog_resolution_translates_reserved_source_alias_to_project_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    context = ProjectContext(
        project_root=tmp_path,
        config_path=tmp_path / ".csvql.yml",
        config=ProjectConfig(
            version=1,
            tables=(ProjectTable(name="__LOCALQL_orders", path="orders.csv"),),
        ),
    )
    monkeypatch.setattr(source_resolver_module, "load_project", lambda _: context)

    with pytest.raises(ProjectConfigError) as error:
        resolve_path_or_catalog_source("__localql_orders", base_dir=tmp_path)

    assert error.value.message == "Invalid project catalog table alias '__LOCALQL_orders'."
    assert error.value.suggestion == (
        "Rename the table; aliases beginning with '__localql_' are reserved for LocalQL."
    )
