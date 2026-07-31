from datetime import date
from pathlib import Path
from textwrap import indent

import pytest
import yaml

from csvql import project_config
from csvql.atomic_write import write_text_atomic
from csvql.exceptions import FileMissingError, ProjectConfigError
from csvql.models import TableSource
from csvql.project_config import (
    CONFIG_FILENAME,
    CURRENT_VERSION,
    SUPPORTED_VERSION,
    CatalogSourceDefinition,
    ProjectConfig,
    ProjectConfigV1,
    ProjectConfigV2,
    ProjectContext,
    ProjectTable,
    ProjectTableListing,
    ProjectTablesResult,
    ProjectTableV1,
    ProjectTableV2,
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
        config=ProjectConfigV2(version=CURRENT_VERSION, tables=()),
    )
    assert config_path.read_text(encoding="utf-8") == "version: 2\ntables: {}\n"
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "version": CURRENT_VERSION,
        "tables": {},
    }


def test_initialize_project_refuses_overwrite(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        initialize_project(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"


def test_initialize_project_no_force_preserves_catalog_created_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / CONFIG_FILENAME

    def create_concurrent_catalog_then_write(
        path: Path,
        content: str,
        *,
        overwrite: bool = True,
    ) -> None:
        assert overwrite is False
        path.write_text("concurrent-config\n", encoding="utf-8")
        write_text_atomic(path, content, overwrite=overwrite)

    monkeypatch.setattr(
        "csvql.project_config.write_text_atomic",
        create_concurrent_catalog_then_write,
    )

    with pytest.raises(ProjectConfigError, match="Project catalog already exists"):
        initialize_project(tmp_path, force=False)

    assert config_path.read_text(encoding="utf-8") == "concurrent-config\n"


def test_initialize_project_force_rewrites_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text("version: 1\ntables:\n  orders: old.csv\n", encoding="utf-8")

    context = initialize_project(tmp_path, force=True)

    assert context.config == ProjectConfigV2(version=CURRENT_VERSION, tables=())
    assert config_path.read_text(encoding="utf-8") == "version: 2\ntables: {}\n"


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
    config_path.write_text("version: 3\ntables: {}\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError):
        load_project(tmp_path)


def test_load_project_preserves_strict_version_1_model(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    original = "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n"
    config_path.write_text(original, encoding="utf-8")

    context = load_project(tmp_path)
    save_project(context)

    assert context.config == ProjectConfigV1(
        version=SUPPORTED_VERSION,
        tables=(ProjectTableV1(name="orders", path="data/orders.csv"),),
    )
    assert config_path.read_text(encoding="utf-8") == original


def test_load_project_accepts_normalized_version_2_source_intent(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 2\n"
        "tables:\n"
        "  orders:\n"
        "    source:\n"
        "      type: parquet\n"
        "      locator: data/orders\n"
        "      options:\n"
        "        partitioning: hive\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    assert context.config == ProjectConfigV2(
        version=CURRENT_VERSION,
        tables=(
            ProjectTableV2(
                name="orders",
                source=CatalogSourceDefinition(
                    source_type="parquet",
                    locator="data/orders",
                    options=(("partitioning", "hive"),),
                ),
            ),
        ),
    )
    assert project_config.project_tables_to_source_specs(context) == [
        project_config.SourceSpec(
            alias="orders",
            kind="parquet",
            locator="data/orders",
            anchor=tmp_path,
            options=(("partitioning", "hive"),),
        )
    ]


def test_load_project_version_2_normalizes_type_alias_and_rejects_bad_options(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 2\n"
        "tables:\n"
        "  workbook:\n"
        "    source:\n"
        "      type: xlsx\n"
        "      locator: workbook.xlsx\n"
        "      options:\n"
        "        header: true\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    assert isinstance(context.config, ProjectConfigV2)
    assert context.config.tables[0].source.source_type == "excel"

    config_path.write_text(
        "version: 2\n"
        "tables:\n"
        "  workbook:\n"
        "    source:\n"
        "      type: excel\n"
        "      locator: workbook.xlsx\n"
        "      options:\n"
        "        header: text\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigError) as error:
        load_project(tmp_path)
    assert error.value.code == "catalog.source_option_type"


def test_version_1_rejects_non_csv_add_without_writing(tmp_path: Path) -> None:
    parquet_path = tmp_path / "orders.parquet"
    parquet_path.write_bytes(b"PAR1")
    config_path = tmp_path / CONFIG_FILENAME
    original = "version: 1\ntables: {}\n"
    config_path.write_text(original, encoding="utf-8")
    context = load_project(tmp_path)

    with pytest.raises(ProjectConfigError) as error:
        add_project_table(
            context,
            "orders",
            str(parquet_path),
            source_type="parquet",
            invocation_dir=tmp_path,
        )

    assert error.value.code == "catalog.v1_migration_required"
    assert config_path.read_text(encoding="utf-8") == original


def test_version_2_add_persists_only_explicit_source_intent(tmp_path: Path) -> None:
    parquet_directory = tmp_path / "warehouse"
    parquet_directory.mkdir()
    context = initialize_project(tmp_path)

    updated = add_project_table(
        context,
        "warehouse",
        str(parquet_directory),
        source_type="parquet",
        options={"partitioning": "hive"},
        invocation_dir=tmp_path,
    )

    assert isinstance(updated.config, ProjectConfigV2)
    assert (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8") == (
        "version: 2\n"
        "tables:\n"
        "  warehouse:\n"
        "    source:\n"
        "      type: parquet\n"
        "      locator: warehouse\n"
        "      options:\n"
        "        partitioning: hive\n"
    )


def test_version_2_load_rejects_private_result_artifact_without_rewriting(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / f"localql-tui-v1-{'a' * 32}"
    workspace.mkdir()
    private_result = workspace / "query-1.result"
    private_result.write_bytes(b"private framed result")
    config_path = tmp_path / CONFIG_FILENAME
    original = yaml.safe_dump(
        {
            "version": CURRENT_VERSION,
            "tables": {
                "private_result": {
                    "source": {
                        "type": "parquet",
                        "locator": str(private_result),
                    }
                }
            },
        },
        sort_keys=False,
    )
    config_path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectConfigError) as error:
        load_project(tmp_path)

    assert error.value.code == "catalog.private_result_artifact"
    assert config_path.read_text(encoding="utf-8") == original


def test_version_2_add_rejects_private_result_artifact_without_writing(
    tmp_path: Path,
) -> None:
    context = initialize_project(tmp_path)
    config_path = tmp_path / CONFIG_FILENAME
    original = config_path.read_text(encoding="utf-8")
    workspace = tmp_path / f"localql-tui-v1-{'a' * 32}"
    workspace.mkdir()
    private_result = workspace / "query-1.result"
    private_result.write_bytes(b"private framed result")

    with pytest.raises(ProjectConfigError) as error:
        add_project_table(
            context,
            "private_result",
            str(private_result),
            source_type="parquet",
            invocation_dir=tmp_path,
        )

    assert error.value.code == "catalog.private_result_artifact"
    assert config_path.read_text(encoding="utf-8") == original
    assert private_result.read_bytes() == b"private framed result"


def test_version_2_save_rejects_private_result_artifact_without_writing(
    tmp_path: Path,
) -> None:
    context = initialize_project(tmp_path)
    config_path = tmp_path / CONFIG_FILENAME
    original = config_path.read_text(encoding="utf-8")
    private_result = (
        tmp_path / f"localql-tui-v1-{'a' * 32}" / ".preview-2-abcdef0123456789.result.tmp"
    )
    unsafe_context = ProjectContext(
        project_root=context.project_root,
        config_path=context.config_path,
        config=ProjectConfigV2(
            version=CURRENT_VERSION,
            tables=(
                ProjectTableV2(
                    name="private_result",
                    source=CatalogSourceDefinition(
                        source_type="json",
                        locator=str(private_result),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ProjectConfigError) as error:
        save_project(unsafe_context)

    assert error.value.code == "catalog.private_result_artifact"
    assert config_path.read_text(encoding="utf-8") == original


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


def test_load_project_rejects_case_colliding_table_aliases(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  Orders:\n"
        "    path: data/first.csv\n"
        "  orders:\n"
        "    path: data/second.csv\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="differ only by case"):
        load_project(tmp_path)


def test_load_project_treats_null_table_checks_as_empty_tuple(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n    checks:\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    assert context.config.tables == (ProjectTable(name="orders", path="data/orders.csv"),)
    assert context.config.tables[0].checks == ()


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
        '        column: " order_id "\n'
        "      - name: status_known\n"
        "        type: accepted_values\n"
        '        column: " status "\n'
        "        values: [paid, pending]\n"
        "      - name: expected_rows\n"
        "        type: row_count_between\n"
        "        min: 1\n"
        "        max: 10\n"
        "      - name: customer_exists\n"
        "        type: foreign_key\n"
        '        column: " customer_id "\n'
        "        references:\n"
        "          table: customers\n"
        '          column: " customer id "\n'
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
    assert orders.checks[0].column == " order_id "
    assert orders.checks[1].values == ("paid", "pending")
    assert orders.checks[2].min_value == 1
    assert orders.checks[2].max_value == 10
    assert orders.checks[3].column == " customer_id "
    assert orders.checks[3].references is not None
    assert orders.checks[3].references.table == "customers"
    assert orders.checks[3].references.column == " customer id "

    save_project(context)
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    saved_checks = saved["tables"]["orders"]["checks"]
    assert saved_checks[0]["column"] == " order_id "
    assert saved_checks[3]["column"] == " customer_id "
    assert saved_checks[3]["references"]["column"] == " customer id "


def test_load_project_accepts_date_scalars_for_check_values(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: ordered_at_min\n"
        "        type: min\n"
        "        column: ordered_at\n"
        "        value: 2024-01-01\n"
        "      - name: ordered_at_max\n"
        "        type: max\n"
        "        column: ordered_at\n"
        "        value: 2024-01-02\n"
        "      - name: ordered_at_known\n"
        "        type: accepted_values\n"
        "        column: ordered_at\n"
        "        values: [2024-01-01, 2024-01-02]\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    orders = context.config.tables[0]
    assert orders.checks[0].value == date(2024, 1, 1)
    assert orders.checks[1].value == date(2024, 1, 2)
    assert orders.checks[2].values == (date(2024, 1, 1), date(2024, 1, 2))

    save_project(context)
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    saved_checks = saved["tables"]["orders"]["checks"]
    assert saved_checks[0]["value"] == date(2024, 1, 1)
    assert saved_checks[1]["value"] == date(2024, 1, 2)
    assert saved_checks[2]["values"] == [date(2024, 1, 1), date(2024, 1, 2)]


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


def test_project_tables_to_source_specs_preserves_project_anchored_declarations(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=(project_root / CONFIG_FILENAME).resolve(),
        config=ProjectConfig(
            version=SUPPORTED_VERSION,
            tables=(
                ProjectTable("orders", "data/orders.csv"),
                ProjectTable("customers", "/external/customers.csv"),
            ),
        ),
    )

    specs = project_config.project_tables_to_source_specs(context)

    assert [(spec.alias, spec.kind, spec.locator, spec.anchor) for spec in specs] == [
        ("orders", "csv", "data/orders.csv", project_root.resolve()),
        ("customers", "csv", "/external/customers.csv", project_root.resolve()),
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


def test_save_project_creates_parent_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_path = project_root / "nested" / CONFIG_FILENAME
    context = ProjectContext(
        project_root=project_root.resolve(),
        config_path=config_path.resolve(),
        config=ProjectConfig(version=SUPPORTED_VERSION, tables=()),
    )

    save_project(context)

    assert config_path.read_text(encoding="utf-8") == "version: 1\ntables: {}\n"
    assert config_path.parent.is_dir()


def test_save_project_preserves_null_min_max_values(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\n"
        "tables:\n"
        "  orders:\n"
        "    path: data/orders.csv\n"
        "    checks:\n"
        "      - name: total_min\n"
        "        type: min\n"
        "        column: total_amount\n"
        "        value:\n",
        encoding="utf-8",
    )

    context = load_project(tmp_path)

    save_project(context)

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["tables"]["orders"]["checks"][0]["value"] is None


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

    assert updated_context.config.tables == (
        ProjectTableV2(
            name="orders",
            source=CatalogSourceDefinition(source_type="csv", locator="data/orders.csv"),
        ),
    )
    assert updated_context.config_path.read_text(encoding="utf-8") == (
        "version: 2\n"
        "tables:\n"
        "  orders:\n"
        "    source:\n"
        "      type: csv\n"
        "      locator: data/orders.csv\n"
    )


def test_version_one_catalog_round_trips_relative_table_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "orders.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")
    config_path = project_root / CONFIG_FILENAME
    config_path.write_text(
        "version: 1\ntables:\n  orders:\n    path: data/orders.csv\n",
        encoding="utf-8",
    )
    context = load_project(project_root)
    updated_context = add_project_table(
        context,
        "orders",
        "data/orders.csv",
        replace=True,
        invocation_dir=project_root,
    )

    reloaded_context = load_project(project_root)

    assert reloaded_context.config == updated_context.config
    assert reloaded_context.config.version == 1
    assert reloaded_context.config.tables == (
        ProjectTableV1(name="orders", path="data/orders.csv"),
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

    assert updated_context.config.tables == (
        ProjectTableV2(
            name="orders",
            source=CatalogSourceDefinition(source_type="csv", locator="data/orders.csv"),
        ),
    )
    assert updated_context.config_path.read_text(encoding="utf-8") == (
        "version: 2\n"
        "tables:\n"
        "  orders:\n"
        "    source:\n"
        "      type: csv\n"
        "      locator: data/orders.csv\n"
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
        ProjectTableV2(
            name="orders",
            source=CatalogSourceDefinition(
                source_type="csv",
                locator=str(csv_path.resolve()),
            ),
        ),
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

    assert context.config.tables == (
        ProjectTableV2(
            name="orders",
            source=CatalogSourceDefinition(source_type="csv", locator="data/orders.csv"),
        ),
    )


def test_add_project_table_rejects_case_variant_duplicate_without_replace(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    first_path = project_root / "data" / "first.csv"
    second_path = project_root / "data" / "second.csv"
    first_path.parent.mkdir(parents=True)
    first_path.write_text("id\n1\n", encoding="utf-8")
    second_path.write_text("id\n2\n", encoding="utf-8")
    context = initialize_project(project_root)
    context = add_project_table(
        context,
        "Orders",
        "data/first.csv",
        invocation_dir=project_root,
    )

    with pytest.raises(ProjectConfigError, match="already exists"):
        add_project_table(
            context,
            "orders",
            "data/second.csv",
            invocation_dir=project_root,
        )

    assert context.config.tables == (
        ProjectTableV2(
            name="Orders",
            source=CatalogSourceDefinition(source_type="csv", locator="data/first.csv"),
        ),
    )


def test_add_project_table_replace_matches_alias_case_insensitively(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    first_path = project_root / "data" / "first.csv"
    second_path = project_root / "data" / "second.csv"
    first_path.parent.mkdir(parents=True)
    first_path.write_text("id\n1\n", encoding="utf-8")
    second_path.write_text("id\n2\n", encoding="utf-8")
    context = initialize_project(project_root)
    context = add_project_table(
        context,
        "Orders",
        "data/first.csv",
        invocation_dir=project_root,
    )

    updated_context = add_project_table(
        context,
        "orders",
        "data/second.csv",
        replace=True,
        invocation_dir=project_root,
    )

    assert updated_context.config.tables == (
        ProjectTableV2(
            name="orders",
            source=CatalogSourceDefinition(source_type="csv", locator="data/second.csv"),
        ),
    )


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
        ProjectTableV2(
            name="customers",
            source=CatalogSourceDefinition(source_type="csv", locator="customers.csv"),
        ),
        ProjectTableV2(
            name="orders",
            source=CatalogSourceDefinition(source_type="csv", locator="data/orders_v2.csv"),
        ),
    )
    assert updated_context.config_path.read_text(encoding="utf-8") == (
        "version: 2\n"
        "tables:\n"
        "  customers:\n"
        "    source:\n"
        "      type: csv\n"
        "      locator: customers.csv\n"
        "  orders:\n"
        "    source:\n"
        "      type: csv\n"
        "      locator: data/orders_v2.csv\n"
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
