from pathlib import Path

import pytest

from csvql.exceptions import ProjectConfigError, TableMappingError
from csvql.project_config import CONFIG_FILENAME, initialize_project
from csvql.tui_state import TUISessionState, TUISource
from csvql.tui_workflows import build_initial_state


def _write_csv(path: Path, content: str = "id,value\n1,alpha\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_build_initial_state_without_catalog_or_args_returns_empty_state(
    tmp_path: Path,
) -> None:
    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=tmp_path)

    assert state == TUISessionState()
    assert state.sources == ()
    assert state.selected_alias is None


def test_build_initial_state_loads_catalog_sources_with_resolved_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_csv(project_root / "data" / "orders.csv")
    _write_csv(project_root / "data" / "customers.csv")
    initialize_project(project_root)
    (project_root / CONFIG_FILENAME).write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "  customers:\n"
        "    path: data/customers.csv\n",
        encoding="utf-8",
    )

    state = build_initial_state(csv_path=None, table_mappings=(), start_dir=project_root)

    assert state.sources == (
        TUISource(
            name="orders",
            path=(project_root / "data" / "orders.csv").resolve(),
            origin="catalog",
        ),
        TUISource(
            name="customers",
            path=(project_root / "data" / "customers.csv").resolve(),
            origin="catalog",
        ),
    )
    assert state.selected_alias == "orders"


def test_build_initial_state_loads_single_csv_argument_with_derived_alias(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "sales-2026.csv")

    state = build_initial_state(csv_path=str(csv_path), table_mappings=(), start_dir=tmp_path)

    assert state.sources == (
        TUISource(name="sales_2026", path=csv_path.resolve(), origin="argument"),
    )
    assert state.selected_alias == "sales_2026"


def test_build_initial_state_loads_table_mappings_in_argument_order(
    tmp_path: Path,
) -> None:
    first_csv = _write_csv(tmp_path / "first.csv")
    second_csv = _write_csv(tmp_path / "second.csv")

    state = build_initial_state(
        csv_path=None,
        table_mappings=(f"first={first_csv}", f"second={second_csv}"),
        start_dir=tmp_path,
    )

    assert state.sources == (
        TUISource(name="first", path=first_csv.resolve(), origin="argument"),
        TUISource(name="second", path=second_csv.resolve(), origin="argument"),
    )
    assert state.selected_alias == "first"


def test_build_initial_state_rejects_duplicate_aliases_between_csv_and_mapping(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(tmp_path / "orders.csv")
    duplicate_csv = _write_csv(tmp_path / "duplicate.csv")

    with pytest.raises(
        TableMappingError,
        match=r"Duplicate table alias 'orders'",
    ):
        build_initial_state(
            csv_path=str(csv_path),
            table_mappings=(f"orders={duplicate_csv}",),
            start_dir=tmp_path,
        )


def test_build_initial_state_propagates_invalid_catalog_yaml(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / CONFIG_FILENAME).write_text("version: [1\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match=r"Invalid YAML"):
        build_initial_state(csv_path=None, table_mappings=(), start_dir=project_root)
