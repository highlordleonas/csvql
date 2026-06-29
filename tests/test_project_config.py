from pathlib import Path
from textwrap import indent

import pytest
import yaml

from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.models import TableSource
from csvql.project_config import (
    CONFIG_FILENAME,
    SUPPORTED_VERSION,
    ProjectConfig,
    ProjectContext,
    ProjectTable,
    ProjectTableListing,
    ProjectTablesResult,
    add_project_table,
    build_project_tables_result,
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


@pytest.mark.parametrize("payload", ["version: true\ntables: {}\n", "version: 1.0\ntables: {}\n"])
def test_load_project_rejects_non_integer_version(
    tmp_path: Path,
    payload: str,
) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_missing_version(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("tables: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_mixed_type_unsupported_top_level_keys(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables: {}\n1: bad\nz: also_bad\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "version: 1\n",
        "version: 1\ntables: []\n",
        "- version: 1\n- tables: {}\n",
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


def test_load_project_accepts_nested_table_entries(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    assert context.config == ProjectConfig(
        version=SUPPORTED_VERSION,
        tables=(ProjectTable(name="orders", path="data/orders.csv"),),
    )


def test_load_project_accepts_table_checks(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: order_id_required\n"
        "        type: not_null\n"
        "        column: order_id\n"
        "      - name: status_known\n"
        "        type: accepted_values\n"
        "        column: status\n"
        "        values: [paid, pending]\n"
        "      - name: expected_rows\n"
        "        type: row_count_between\n"
        "        min: 1\n"
        "        max: 10\n"
        "      - name: customer_exists\n"
        "        type: foreign_key\n"
        "        column: customer_id\n"
        "        references:\n"
        "          table: customers\n"
        "          column: customer_id\n"
        "  customers:\n"
        "    path: data/customers.csv\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    orders = context.config.tables[0]
    assert orders.name == "orders"
    assert [check.name for check in orders.checks] == [
        "order_id_required",
        "status_known",
        "expected_rows",
        "customer_exists",
    ]
    assert orders.checks[1].values == ("paid", "pending")
    assert orders.checks[2].min_value == 1
    assert orders.checks[2].max_value == 10
    assert orders.checks[3].references is not None
    assert orders.checks[3].references.table == "customers"


def test_load_project_rejects_duplicate_check_names(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: duplicate\n"
        "        type: not_null\n"
        "        column: order_id\n"
        "      - name: duplicate\n"
        "        type: unique\n"
        "        column: order_id\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_missing_foreign_key_reference_table(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: customer_exists\n"
        "        type: foreign_key\n"
        "        column: customer_id\n"
        "        references:\n"
        "          table: customers\n"
        "          column: customer_id\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "checks: {}\n",
        "checks:\n  - type: not_null\n    column: order_id\n",
        "checks:\n  - name: bad\n    column: order_id\n",
        "checks:\n  - name: bad name\n    type: not_null\n    column: order_id\n",
        "checks:\n  - name: bad\n    type: not_null\n",
        "checks:\n  - name: bad\n    type: accepted_values\n    column: status\n    values: []\n",
        (
            "checks:\n  - name: bad\n    type: accepted_values\n    column: status\n"
            "    values: [paid, {bad: shape}]\n"
        ),
        "checks:\n  - name: bad\n    type: row_count_between\n",
        "checks:\n  - name: bad\n    type: row_count_between\n    min: 10\n    max: 1\n",
        (
            "checks:\n  - name: bad\n    type: min\n    column: total_amount\n"
            "    value: {bad: shape}\n"
        ),
        "checks:\n  - name: bad\n    type: max\n    column: total_amount\n    value: [1, 2]\n",
        "checks:\n  - name: bad\n    type: foreign_key\n    column: customer_id\n",
        (
            "checks:\n  - name: bad\n    type: foreign_key\n    column: customer_id\n"
            "    references: {table: bad-table, column: customer_id}\n"
        ),
        (
            "checks:\n  - name: bad\n    type: not_null\n    column: order_id\n"
            "    1: numeric_key\n    z: string_key\n"
        ),
        (
            "checks:\n  - name: bad\n    type: foreign_key\n    column: customer_id\n"
            "    references: {table: customers}\n"
        ),
        (
            "checks:\n  - name: bad\n    type: foreign_key\n    column: customer_id\n"
            "    references:\n      table: customers\n      column: customer_id\n"
            "      1: numeric_key\n      z: string_key\n"
        ),
    ],
)
def test_load_project_rejects_invalid_table_checks(
    tmp_path: Path,
    payload: str,
) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        f"version: 1\ntables:\n  orders:\n    path: data/orders.csv\n{indent(payload, '    ')}",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_flat_table_entries(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders: data/orders.csv\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_invalid_nested_table_alias(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\ntables:\n  order-items:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_nested_table_entry_without_path(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "version: 1\ntables:\n  orders:\n",
        "version: 1\ntables:\n  orders:\n    path:\n",
        "version: 1\ntables:\n  orders:\n    path: 123\n",
        "version: 1\ntables:\n  orders:\n    path: ''\n",
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n    format: csv\n",
    ],
)
def test_load_project_rejects_invalid_table_entries(tmp_path: Path, payload: str) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_rejects_non_string_path(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders:\n    path: 123\n", encoding="utf-8")

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
        "version: 1\ntables:\n  alpha:\n    path: alpha.csv\n  zeta:\n    path: zeta.csv\n"
    )


def test_add_project_table_replace_preserves_checks_for_same_table(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    orders_path = project_root / "data" / "orders_v2.csv"
    orders_path.parent.mkdir(parents=True)
    orders_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    config_path = project_root / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: order_id_required\n"
        "        type: not_null\n"
        "        column: order_id\n",
        encoding="utf-8",
    )

    context = load_project(project_root)
    updated_context = add_project_table(
        context,
        "orders",
        "data/orders_v2.csv",
        replace=True,
        invocation_dir=project_root,
    )

    orders = updated_context.config.tables[0]
    assert orders.path == "data/orders_v2.csv"
    assert [check.name for check in orders.checks] == ["order_id_required"]


def test_add_project_table_stores_project_relative_path_for_internal_file(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = initialize_project(project_root)

    updated_context = add_project_table(
        context,
        "orders",
        "data/orders.csv",
        invocation_dir=project_root,
    )

    assert updated_context.config.tables == (ProjectTable(name="orders", path="data/orders.csv"),)
    assert updated_context.config_path.read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n"
    )


def test_add_project_table_uses_invocation_dir_for_relative_input(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    invocation_dir = project_root / "nested" / "cli"
    csv_path = project_root / "data" / "orders.csv"
    invocation_dir.mkdir(parents=True)
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = initialize_project(project_root)

    updated_context = add_project_table(
        context,
        "orders",
        "../../data/orders.csv",
        invocation_dir=invocation_dir,
    )

    assert updated_context.config.tables == (ProjectTable(name="orders", path="data/orders.csv"),)
    assert updated_context.config_path.read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n"
    )


def test_add_project_table_stores_absolute_path_for_external_file(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    external_dir = tmp_path / "external"
    csv_path = external_dir / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = initialize_project(project_root)

    updated_context = add_project_table(
        context,
        "orders",
        str(csv_path),
        invocation_dir=project_root,
    )

    assert updated_context.config.tables == (
        ProjectTable(name="orders", path=str(csv_path.resolve())),
    )


def test_add_project_table_propagates_missing_file_error(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    context = initialize_project(project_root)

    with pytest.raises(FileMissingError):
        add_project_table(
            context,
            "orders",
            "data/orders.csv",
            invocation_dir=project_root,
        )


def test_add_project_table_rejects_duplicate_without_replace(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = initialize_project(project_root)
    context = add_project_table(context, "orders", "data/orders.csv", invocation_dir=project_root)

    with pytest.raises(ProjectConfigError):
        add_project_table(
            context,
            "orders",
            "data/orders.csv",
            invocation_dir=project_root,
        )

    assert context.config.tables == (ProjectTable(name="orders", path="data/orders.csv"),)


def test_add_project_table_replace_updates_only_matching_table(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    orders_path = project_root / "data" / "orders.csv"
    replacement_path = project_root / "data" / "orders_v2.csv"
    customers_path = project_root / "customers.csv"
    for csv_path in (orders_path, replacement_path, customers_path):
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("id,value\n1,2\n", encoding="utf-8")
    context = initialize_project(project_root)
    context = add_project_table(context, "customers", "customers.csv", invocation_dir=project_root)
    context = add_project_table(context, "orders", "data/orders.csv", invocation_dir=project_root)

    updated_context = add_project_table(
        context,
        "orders",
        "data/orders_v2.csv",
        replace=True,
        invocation_dir=project_root,
    )

    assert updated_context.config.tables == (
        ProjectTable(name="customers", path="customers.csv"),
        ProjectTable(name="orders", path="data/orders_v2.csv"),
    )
    assert updated_context.config_path.read_text(encoding="utf-8") == (
        "version: 1\ntables:\n  customers:\n    path: customers.csv\n"
        "  orders:\n    path: data/orders_v2.csv\n"
    )


def test_save_project_preserves_checks_when_replacing_unrelated_table(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    customers_path = project_root / "data" / "customers_v2.csv"
    customers_path.parent.mkdir(parents=True)
    customers_path.write_text("customer_id,email\nCUST-1,a@example.com\n", encoding="utf-8")
    config_path = project_root / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: order_id_required\n"
        "        type: not_null\n"
        "        column: order_id\n"
        "  customers:\n"
        "    path: data/customers.csv\n",
        encoding="utf-8",
    )

    context = load_project(project_root)
    updated_context = add_project_table(
        context,
        "customers",
        "data/customers_v2.csv",
        replace=True,
        invocation_dir=project_root,
    )

    orders = next(table for table in updated_context.config.tables if table.name == "orders")
    assert [check.name for check in orders.checks] == ["order_id_required"]
    saved_text = updated_context.config_path.read_text(encoding="utf-8")
    assert "customers:\n    path: data/customers_v2.csv" in saved_text
    assert "orders:\n    path: data/orders.csv" in saved_text
    assert "checks:\n" in saved_text
    assert "order_id_required" in saved_text


def test_build_project_tables_result_returns_sorted_resolved_listings(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    config_path = project_root / CONFIG_FILENAME
    alpha_path = project_root / "alpha.csv"
    zeta_path = project_root / "zeta.csv"
    alpha_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_path.write_text("id,value\n1,2\n", encoding="utf-8")
    zeta_path.write_text("id,value\n3,4\n", encoding="utf-8")
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION,
            tables=(
                ProjectTable(name="zeta", path="zeta.csv"),
                ProjectTable(name="alpha", path="alpha.csv"),
            ),
        ),
    )

    result = build_project_tables_result(context)

    assert result == ProjectTablesResult(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        tables=(
            ProjectTableListing(
                name="alpha",
                path="alpha.csv",
                resolved_path=alpha_path.resolve(),
            ),
            ProjectTableListing(
                name="zeta",
                path="zeta.csv",
                resolved_path=zeta_path.resolve(),
            ),
        ),
    )


def test_build_project_tables_result_includes_table_name_when_file_missing(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    config_path = project_root / CONFIG_FILENAME
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION,
            tables=(ProjectTable(name="orders", path="data/orders.csv"),),
        ),
    )

    with pytest.raises(FileMissingError, match="project catalog table 'orders'"):
        build_project_tables_result(context)


def test_project_tables_to_sources_includes_table_name_when_file_missing(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    config_path = project_root / CONFIG_FILENAME
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION,
            tables=(ProjectTable(name="orders", path="data/orders.csv"),),
        ),
    )

    with pytest.raises(FileMissingError, match="project catalog table 'orders'"):
        project_tables_to_sources(context)


def test_add_project_table_rejects_invalid_alias(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    context = initialize_project(project_root)

    with pytest.raises(ProjectConfigError):
        add_project_table(
            context,
            "order-items",
            "data/orders.csv",
            invocation_dir=project_root,
        )
