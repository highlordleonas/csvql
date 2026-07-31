import os
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
        str(Path("data/legacy.csv")),
        "data/catalog.csv",
        "data/cli.csv",
        str(Path("data/tui.csv")),
    )


def test_v12_source_options_freeze_nested_json_with_canonical_key_order() -> None:
    from csvql.source import canonical_source_options_bytes, freeze_source_options

    options = freeze_source_options(
        (
            ("schema", {"zeta": ["VARCHAR", None], "alpha": {"enabled": True}}),
            ("sample_size", 20_480),
        )
    )

    assert canonical_source_options_bytes(options) == (
        b'{"sample_size":20480,"schema":{"alpha":{"enabled":true},"zeta":["VARCHAR",null]}}'
    )


def test_v12_source_options_reject_values_that_cannot_be_reproduced() -> None:
    from csvql.source import freeze_source_options

    with pytest.raises(ValueError, match="Duplicate source option key"):
        freeze_source_options((("header", True), ("header", False)))
    with pytest.raises(TypeError, match="string keys"):
        freeze_source_options((("schema", {1: "BIGINT"}),))
    with pytest.raises(ValueError, match="finite"):
        freeze_source_options((("ratio", float("nan")),))
    with pytest.raises(TypeError, match="JSON-compatible"):
        freeze_source_options((("path", Path("orders.csv")),))


def test_v12_source_request_builder_is_provider_neutral_and_performs_no_path_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from csvql.source import build_source_request

    def unexpected_path_io(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("SourceRequest construction must not inspect the filesystem.")

    with monkeypatch.context() as path_io_guard:
        for method_name in ("exists", "is_dir", "is_file", "lstat", "stat"):
            path_io_guard.setattr(Path, method_name, unexpected_path_io)

        request = build_source_request(
            alias="CustomerOrders",
            locator="missing/orders.data",
            anchor=tmp_path / "project" / ".." / "project",
            explicit_type="json",
            options=(("schema", {"order_id": "VARCHAR"}),),
        )

    assert request.alias == "CustomerOrders"
    assert request.alias_key == "customerorders"
    assert request.locator == os.path.normpath("missing/orders.data")
    assert request.anchor == tmp_path / "project"
    assert request.explicit_type == "json"


def test_v12_source_request_excludes_surface_context_from_semantic_equality(
    tmp_path: Path,
) -> None:
    from csvql.source import SourceApplicationContext, build_source_request

    first = build_source_request(
        alias="Orders",
        locator="orders.csv",
        anchor=tmp_path,
        explicit_type=None,
    )
    second = build_source_request(
        alias="Orders",
        locator="orders.csv",
        anchor=tmp_path,
        explicit_type=None,
    )

    assert first == second
    assert SourceApplicationContext(surface="cli") != SourceApplicationContext(surface="tui")
    assert not hasattr(first, "surface")


def test_v12_source_request_rejects_invalid_aliases_and_empty_explicit_types(
    tmp_path: Path,
) -> None:
    from csvql.source import SourceRequest, build_source_request

    with pytest.raises(ValueError, match="valid unmodified SQL identifier"):
        build_source_request(alias="order-items", locator="orders.csv", anchor=tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        build_source_request(alias="__LOCALQL_work", locator="orders.csv", anchor=tmp_path)
    with pytest.raises(ValueError, match="explicit source type"):
        build_source_request(
            alias="orders",
            locator="orders.csv",
            anchor=tmp_path,
            explicit_type=" ",
        )
    with pytest.raises(ValueError, match="valid unmodified SQL identifier"):
        SourceRequest(
            alias="order-items",
            locator="orders.csv",
            anchor=tmp_path,
            explicit_type=None,
        )
    with pytest.raises(TypeError, match="JSON-compatible"):
        SourceRequest(
            alias="orders",
            locator="orders.csv",
            anchor=tmp_path,
            explicit_type=None,
            options=(("path", Path("orders.csv")),),  # type: ignore[arg-type]
        )


def test_v12_diagnostic_orders_evidence_and_redacts_absolute_source_references(
    tmp_path: Path,
) -> None:
    from csvql.source import (
        DiagnosticCode,
        DiagnosticEvidence,
        DiagnosticStage,
        RequiredAction,
        SourceDiagnostic,
        canonical_source_json_bytes,
    )

    diagnostic = SourceDiagnostic(
        code=DiagnosticCode.SOURCE_AMBIGUOUS,
        stage=DiagnosticStage.DETECTION,
        message="Bounded identification produced candidates.",
        safe_source_reference=str(tmp_path / "private" / "orders"),
        evidence=(
            DiagnosticEvidence("json", "signature", "object"),
            DiagnosticEvidence("csv", "record_shape", "two_rows"),
        ),
        required_action=RequiredAction("specify_type", ("csv", "json")),
    )

    assert tuple(item.provider_key for item in diagnostic.evidence) == ("csv", "json")
    serialized = canonical_source_json_bytes(diagnostic.as_json_value())
    assert str(tmp_path).encode() not in serialized
    assert b'"source":"orders"' in serialized
    assert b'"kind":"specify_type"' in serialized


def test_v12_required_action_rejects_invalid_provider_keys() -> None:
    from csvql.source import RequiredAction

    with pytest.raises(ValueError, match="provider key"):
        RequiredAction("specify_type", ("",))


def test_v12_detection_outcomes_are_structurally_distinct(tmp_path: Path) -> None:
    from csvql.source import (
        AmbiguousSource,
        DetectionResult,
        DiagnosticCode,
        DiagnosticStage,
        RequiredAction,
        SelectedSource,
        SourceDiagnostic,
        build_source_request,
    )
    from csvql.source_registry import DescriptorView

    request = build_source_request(alias="orders", locator="orders.csv", anchor=tmp_path)
    descriptor = DescriptorView(
        provider_key="csv",
        source_kind="csv",
        factory_key="builtin.csv",
        provider_interpretation_version="1",
    )
    selected: DetectionResult = SelectedSource(
        request=request,
        provider_key="csv",
        source_kind="csv",
        descriptor=descriptor,
        selection_reason="extension",
        extension_evidence=".csv",
        options=(),
    )
    ambiguous: DetectionResult = AmbiguousSource(
        request=request,
        diagnostic=SourceDiagnostic(
            code=DiagnosticCode.SOURCE_AMBIGUOUS,
            stage=DiagnosticStage.DETECTION,
            message="Explicit source type required.",
            safe_source_reference="orders.csv",
            required_action=RequiredAction("specify_type", ("csv",)),
        ),
        candidates=("csv",),
        required_action=RequiredAction("specify_type", ("csv",)),
    )

    assert type(selected) is SelectedSource
    assert type(ambiguous) is AmbiguousSource
    assert not hasattr(selected, "required_action")
    assert not hasattr(ambiguous, "descriptor")


def test_v12_source_identity_excludes_alias_but_changes_with_semantics() -> None:
    from csvql.source import (
        IdentityStrength,
        ObservedFileFacts,
        build_source_identity,
        freeze_source_options,
    )

    observed = ObservedFileFacts(size_bytes=128, modified_time_ns=1_234_567_890)
    first = build_source_identity(
        provider_key="csv",
        source_kind="csv",
        canonical_locator="/data/orders.csv",
        semantic_options=freeze_source_options((("header", True),)),
        provider_interpretation_version="1",
        strength=IdentityStrength.OBSERVATIONAL,
        observed_file=observed,
    )
    same = build_source_identity(
        provider_key="csv",
        source_kind="csv",
        canonical_locator="/data/orders.csv",
        semantic_options=freeze_source_options((("header", True),)),
        provider_interpretation_version="1",
        strength=IdentityStrength.OBSERVATIONAL,
        observed_file=observed,
    )
    changed = build_source_identity(
        provider_key="csv",
        source_kind="csv",
        canonical_locator="/data/orders.csv",
        semantic_options=freeze_source_options((("header", False),)),
        provider_interpretation_version="1",
        strength=IdentityStrength.OBSERVATIONAL,
        observed_file=observed,
    )

    assert first == same
    assert first.digest != changed.digest
    assert first.strength is IdentityStrength.OBSERVATIONAL


def test_v12_source_identity_excludes_declared_sensitive_option_values() -> None:
    from csvql.source import (
        IdentityStrength,
        build_source_identity,
        freeze_source_options,
    )

    first = build_source_identity(
        provider_key="future",
        source_kind="future",
        canonical_locator="/data/source",
        semantic_options=freeze_source_options(
            (("mode", "stable"), ("credential", "first-sensitive-value"))
        ),
        sensitive_option_keys=("credential",),
        provider_interpretation_version="1",
        strength=IdentityStrength.OBSERVATIONAL,
    )
    second = build_source_identity(
        provider_key="future",
        source_kind="future",
        canonical_locator="/data/source",
        semantic_options=freeze_source_options(
            (("credential", "second-sensitive-value"), ("mode", "stable"))
        ),
        sensitive_option_keys=("credential",),
        provider_interpretation_version="1",
        strength=IdentityStrength.OBSERVATIONAL,
    )

    assert first == second
