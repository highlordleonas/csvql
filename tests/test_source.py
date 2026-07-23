from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError, SourceError
from csvql.models import TableSource
from csvql.source import (
    SourceSpec,
    source_alias_collision_key,
    source_from_path,
    source_options,
    source_spec_from_catalog_table,
    source_spec_from_cli_mapping,
    source_spec_from_table_source,
    source_spec_from_tui_source,
)


def test_source_from_path_records_file_metadata(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = source_from_path(str(csv_path))

    assert source.path == csv_path
    assert source.display_path == str(csv_path)
    assert source.fingerprint.version == 1
    assert source.fingerprint.size_bytes == csv_path.stat().st_size
    assert source.fingerprint.modified_at
    assert source.to_json_summary()["fingerprint"]["version"] == 1


def test_source_from_path_resolves_relative_paths(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,email\nCUST-1,a@example.com\n", encoding="utf-8")

    source = source_from_path("customers.csv", base_dir=tmp_path)

    assert source.path == csv_path
    assert source.display_path == "customers.csv"


def test_source_from_path_keeps_relative_locator_when_anchored(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "customers.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("customer_id,email\nCUST-1,a@example.com\n", encoding="utf-8")

    source = source_from_path("data/customers.csv", base_dir=project_root)

    assert source.path == csv_path
    assert source.display_path == "data/customers.csv"


def test_source_from_path_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileMissingError):
        source_from_path("missing.csv", base_dir=tmp_path)


def test_source_spec_preserves_exact_alias_and_exposes_casefolded_collision_key(
    tmp_path: Path,
) -> None:
    spec = SourceSpec(alias="CustomerOrders", kind="csv", locator="orders.csv", anchor=tmp_path)

    assert spec.alias == "CustomerOrders"
    assert spec.alias_key == "customerorders"
    assert source_alias_collision_key("CUSTOMERORDERS") == spec.alias_key


def test_source_spec_rejects_reserved_internal_alias_case_insensitively(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reserved"):
        SourceSpec(alias="__LOCALQL_work", kind="csv", locator="orders.csv", anchor=tmp_path)


@pytest.mark.parametrize("kind", ["CSV", "csv-file", "", " csv"])
def test_source_spec_rejects_unstable_kind_names(tmp_path: Path, kind: str) -> None:
    with pytest.raises(ValueError, match="kind"):
        SourceSpec(alias="orders", kind=kind, locator="orders.csv", anchor=tmp_path)


def test_source_spec_requires_an_explicit_path_anchor(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="anchor"):
        SourceSpec(alias="orders", kind="csv", locator="orders.csv", anchor=str(tmp_path))  # type: ignore[arg-type]


def test_source_spec_captures_relative_anchor_independently_of_later_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    spec = SourceSpec(
        alias="orders",
        kind="csv",
        locator="data/orders.csv",
        anchor=Path("project"),
    )
    later_cwd = tmp_path / "later"
    later_cwd.mkdir()

    monkeypatch.chdir(later_cwd)

    assert spec.anchor == (tmp_path / "project").resolve()
    assert spec.anchor.is_absolute()
    assert spec.locator == "data/orders.csv"


def test_source_options_are_sorted_immutable_and_reject_duplicates(tmp_path: Path) -> None:
    options = source_options((("zeta", 2), ("alpha", True)))
    spec = SourceSpec(
        alias="future", kind="future", locator="value", anchor=tmp_path, options=options
    )

    assert spec.options == (("alpha", True), ("zeta", 2))
    with pytest.raises(FrozenInstanceError):
        spec.alias = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="Duplicate source option"):
        source_options((("header", True), ("header", False)))


def test_csv_source_spec_rejects_every_non_empty_option(tmp_path: Path) -> None:
    with pytest.raises(SourceError) as error:
        SourceSpec(
            alias="orders",
            kind="csv",
            locator="orders.csv",
            anchor=tmp_path,
            options=(("header", True),),
        )

    assert error.value.code == "unsupported_source_option"
    assert error.value.kind == "csv"
    assert error.value.alias == "orders"


def test_legacy_table_source_conversion_preserves_return_type_and_anchor(tmp_path: Path) -> None:
    table_source = TableSource(name="Orders", path=tmp_path / "orders.csv")

    spec = source_spec_from_table_source(table_source)

    assert isinstance(table_source, TableSource)
    assert spec == SourceSpec(
        alias="Orders",
        kind="csv",
        locator=str(table_source.path),
        anchor=tmp_path,
    )


def test_cli_mapping_conversion_preserves_locator_and_explicit_anchor(tmp_path: Path) -> None:
    spec = source_spec_from_cli_mapping(
        alias="Orders",
        path_value="data/orders.csv",
        anchor=tmp_path,
    )

    assert spec.alias == "Orders"
    assert spec.locator == "data/orders.csv"
    assert spec.anchor == tmp_path


def test_all_source_spec_conversions_capture_anchors_before_later_cwd_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CatalogEntry:
        name = "catalog_orders"
        path = "data/catalog.csv"

    class TUIFacade:
        name = "tui_orders"
        path = Path("data/tui.csv")

    monkeypatch.chdir(tmp_path)
    specs = (
        source_spec_from_table_source(
            TableSource(name="legacy_orders", path=Path("data/legacy.csv")),
            anchor=Path("legacy_project"),
        ),
        source_spec_from_catalog_table(
            CatalogEntry(),
            project_root=Path("catalog_project"),
        ),
        source_spec_from_cli_mapping(
            alias="cli_orders",
            path_value="data/cli.csv",
            anchor=Path("cli_invocation"),
        ),
        source_spec_from_tui_source(
            TUIFacade(),
            anchor=Path("tui_session"),
        ),
    )
    later_cwd = tmp_path / "later"
    later_cwd.mkdir()

    monkeypatch.chdir(later_cwd)

    assert tuple(spec.anchor for spec in specs) == (
        (tmp_path / "legacy_project").resolve(),
        (tmp_path / "catalog_project").resolve(),
        (tmp_path / "cli_invocation").resolve(),
        (tmp_path / "tui_session").resolve(),
    )
    assert tuple(spec.locator for spec in specs) == (
        "data/legacy.csv",
        "data/catalog.csv",
        "data/cli.csv",
        "data/tui.csv",
    )
