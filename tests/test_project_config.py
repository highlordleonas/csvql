from pathlib import Path

import pytest
import yaml

from csvql.exceptions import ProjectConfigError
from csvql.models import TableSource
from csvql.project_config import (
    CONFIG_FILENAME,
    SUPPORTED_VERSION,
    ProjectConfig,
    ProjectContext,
    ProjectTable,
    discover_project,
    initialize_project,
    load_project,
    project_tables_to_sources,
    resolve_catalog_path,
    save_project,
)


def test_initialize_project_writes_default_config_and_returns_context(tmp_path: Path) -> None:
    context = initialize_project(tmp_path)
    config_path = tmp_path / CONFIG_FILENAME

    assert context == ProjectContext(
        project_root=tmp_path.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(version=SUPPORTED_VERSION, tables=()),
    )
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "version": SUPPORTED_VERSION,
        "tables": {},
    }


def test_initialize_project_refuses_overwrite(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        initialize_project(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"


def test_initialize_project_force_rewrites_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders: old.csv\n", encoding="utf-8")

    context = initialize_project(tmp_path, force=True)

    assert context.config == ProjectConfig(version=SUPPORTED_VERSION, tables=())
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"


def test_discover_project_walks_up_from_subdirectory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    nested_dir = project_root / "nested" / "deeper"
    nested_dir.mkdir(parents=True)
    (project_root / CONFIG_FILENAME).write_text("version: 1\ntables: {}\n", encoding="utf-8")

    discovered_root, config_path = discover_project(nested_dir)

    assert discovered_root == project_root.resolve()
    assert config_path == (project_root / CONFIG_FILENAME).resolve()


def test_discover_project_raises_when_config_missing(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigError):
        discover_project(tmp_path)


def test_load_project_wraps_invalid_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: [1\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_empty_file(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_unsupported_version(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 2\ntables: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "version: 1\n",
        "version: 1\ntables: []\n",
    ],
)
def test_load_project_rejects_missing_or_non_mapping_tables(
    tmp_path: Path,
    payload: str,
) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "version: 1\ntables:\n  order-items: data/orders.csv\n",
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n",
        "version: 1\ntables:\n  orders:\n",
    ],
)
def test_load_project_rejects_invalid_table_entries(tmp_path: Path, payload: str) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_non_string_path(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders: 123\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_resolve_catalog_path_uses_project_root_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / CONFIG_FILENAME
    csv_path = project_root / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION, tables=(ProjectTable("orders", "data/orders.csv"),)
        ),
    )
    monkeypatch.chdir(tmp_path)

    resolved = resolve_catalog_path(ProjectTable("orders", "data/orders.csv"), context)

    assert resolved == csv_path.resolve()


def test_project_tables_to_sources_returns_validated_table_sources(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / CONFIG_FILENAME
    orders_path = project_root / "data" / "orders.csv"
    customers_path = project_root / "customers.csv"
    orders_path.parent.mkdir(parents=True)
    orders_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    customers_path.write_text("customer_id,email\nCUST-1,a@example.com\n", encoding="utf-8")
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION,
            tables=(
                ProjectTable("orders", "data/orders.csv"),
                ProjectTable("customers", str(customers_path.resolve())),
            ),
        ),
    )

    sources = project_tables_to_sources(context)

    assert sources == [
        TableSource(name="orders", path=orders_path.resolve()),
        TableSource(name="customers", path=customers_path.resolve()),
    ]


def test_save_project_persists_sorted_tables(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / CONFIG_FILENAME
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION,
            tables=(
                ProjectTable("zeta", "zeta.csv"),
                ProjectTable("alpha", "alpha.csv"),
            ),
        ),
    )

    save_project(context)

    assert config_path.read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  alpha: alpha.csv\n  zeta: zeta.csv\n"
    )
