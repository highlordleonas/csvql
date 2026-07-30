from __future__ import annotations

import importlib
import sys
import zipfile
from pathlib import Path

import pytest

from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    AmbiguousSource,
    InvalidSource,
    SelectedSource,
    UnknownSource,
    UnsupportedSource,
    build_source_request,
    canonical_source_json_bytes,
)


def _detection_module():
    return importlib.import_module("csvql.source_detection")


def _builtin_service():
    registry_module = importlib.import_module("csvql.source_registry")
    identifiers_module = importlib.import_module("csvql.source_identifiers")
    return _detection_module().SourceDetectionService(
        registry_module.build_builtin_descriptor_registry(),
        identifiers_module.build_builtin_identifier_table(),
    )


def test_explicit_type_wins_over_conflicting_extension_without_provider_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "csvql.csv_adapter", raising=False)
    path = tmp_path / "orders.json"
    path.write_text("id,value\n1,alpha\n", encoding="utf-8")
    request = build_source_request(
        alias="orders",
        locator=str(path),
        explicit_type="CSV",
    )

    detected = _builtin_service().detect(request)

    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == "csv"
    assert detected.selection_reason == "explicit_type"
    assert detected.extension_evidence is None
    assert "csvql.csv_adapter" not in sys.modules


@pytest.mark.parametrize(
    ("filename", "expected_provider", "expected_extension"),
    (
        ("events.JSON", "json", ".json"),
        ("events.NDJSON", "ndjson", ".ndjson"),
        ("events.JSONL", "ndjson", ".jsonl"),
    ),
)
def test_json_family_extensions_select_deterministically_case_insensitively(
    filename: str,
    expected_provider: str,
    expected_extension: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / filename
    path.write_text('{"id": 1}\n', encoding="utf-8")

    detected = _builtin_service().detect(build_source_request(alias="events", locator=str(path)))

    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == expected_provider
    assert detected.source_kind == expected_provider
    assert detected.selection_reason == "extension"
    assert detected.extension_evidence == expected_extension


def test_home_relative_locator_expands_before_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    source = home / "orders.csv"
    source.write_text("id,value\n1,alpha\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    request = build_source_request(
        alias="orders",
        locator="~/orders.csv",
        anchor=tmp_path / "ignored",
    )

    detected = _builtin_service().detect(request)

    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == "csv"
    assert detected.selection_reason == "extension"


def test_home_relative_anchor_expands_at_request_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    source_dir = home / "project"
    source_dir.mkdir(parents=True)
    source = source_dir / "orders.csv"
    source.write_text("id,value\n1,alpha\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    request = build_source_request(
        alias="orders",
        locator=source.name,
        anchor=Path("~/project"),
    )

    detected = _builtin_service().detect(request)

    assert request.anchor == source_dir
    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == "csv"


def test_excel_extension_selects_without_import_or_workbook_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recognized extension is authoritative even before adapter activation."""

    monkeypatch.delitem(sys.modules, "csvql.excel_adapter", raising=False)
    path = tmp_path / "BOOK.XLSX"
    path.write_bytes(b"not inspected during extension selection")

    detected = _builtin_service().detect(build_source_request(alias="book", locator=str(path)))

    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == "excel"
    assert detected.selection_reason == "extension"
    assert detected.extension_evidence == ".xlsx"
    assert "csvql.excel_adapter" not in sys.modules


def test_extensionless_xlsx_evidence_requires_explicit_type(tmp_path: Path) -> None:
    """Bounded identification supplies evidence but never selects a provider."""

    path = tmp_path / "workbook"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")

    detected = _builtin_service().detect(build_source_request(alias="book", locator=str(path)))

    assert isinstance(detected, AmbiguousSource)
    assert "excel" in detected.candidates
    assert detected.required_action.kind == "specify_type"


def test_untyped_directory_is_ambiguous_even_when_name_has_parquet_suffix(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "warehouse.parquet"
    directory.mkdir()

    detected = _builtin_service().detect(
        build_source_request(alias="warehouse", locator=str(directory))
    )

    assert isinstance(detected, AmbiguousSource)
    assert detected.candidates == ("parquet",)
    assert detected.required_action.kind == "specify_type"


def test_explicit_parquet_type_selects_directory_without_recursive_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "warehouse"
    directory.mkdir()

    def unexpected_iteration(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Detection must not enumerate directory contents.")

    monkeypatch.setattr(Path, "iterdir", unexpected_iteration)
    detected = _builtin_service().detect(
        build_source_request(
            alias="warehouse",
            locator=str(directory),
            explicit_type="parquet",
        )
    )

    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == "parquet"
    assert detected.options_as_python() == {
        "partitioning": "none",
        "union_by_name": False,
    }


def test_one_identification_candidate_is_still_ambiguous(tmp_path: Path) -> None:
    registry_module = importlib.import_module("csvql.source_registry")
    identifiers_module = importlib.import_module("csvql.source_identifiers")

    class FutureIdentifier:
        provider_key = "future"
        identifier_key = "future.magic"

        def identify(self, locator, budget):
            return identifiers_module.IdentificationEvidence(
                provider_key="future",
                status=identifiers_module.IdentificationStatus.RECOGNIZED,
                evidence_kind="future_magic",
                stable_detail="recognized",
                bytes_read=0,
            )

    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="future",
                source_kind="future",
                identifier=registry_module.IdentifierRegistration("future.magic"),
                factory_key="future.factory",
            ),
        )
    )
    service = _detection_module().SourceDetectionService(
        registry,
        identifiers_module.IdentifierTable((FutureIdentifier(),)),
    )
    path = tmp_path / "extensionless"
    path.write_bytes(b"future")

    detected = service.detect(build_source_request(alias="future_data", locator=str(path)))

    assert isinstance(detected, AmbiguousSource)
    assert detected.candidates == ("future",)
    assert detected.required_action.kind == "specify_type"


def test_detection_composition_rejects_identifier_key_mismatch() -> None:
    registry_module = importlib.import_module("csvql.source_registry")
    identifiers_module = importlib.import_module("csvql.source_identifiers")
    from csvql.exceptions import ConfigurationFailure

    class MismatchedIdentifier:
        provider_key = "future"
        identifier_key = "future.actual"

        def identify(self, locator, budget):
            raise AssertionError("Composition must fail before identification.")

    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="future",
                source_kind="future",
                identifier=registry_module.IdentifierRegistration("future.expected"),
                factory_key="future.factory",
            ),
        )
    )

    with pytest.raises(ConfigurationFailure) as captured:
        _detection_module().SourceDetectionService(
            registry,
            identifiers_module.IdentifierTable((MismatchedIdentifier(),)),
        )

    assert tuple(finding.code for finding in captured.value.findings) == (
        "identifier_key_mismatch",
    )


def test_overlapping_text_evidence_lists_candidates_in_canonical_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records"
    path.write_text('{"id": 1}\n', encoding="utf-8")

    detected = _builtin_service().detect(build_source_request(alias="records", locator=str(path)))

    assert isinstance(detected, AmbiguousSource)
    assert detected.candidates == tuple(sorted(detected.candidates))
    assert {"json", "ndjson"}.issubset(detected.candidates)
    assert detected.required_action.provider_keys == detected.candidates


def test_incomplete_bounded_identification_requires_explicit_type(
    tmp_path: Path,
) -> None:
    registry_module = importlib.import_module("csvql.source_registry")
    identifiers_module = importlib.import_module("csvql.source_identifiers")
    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="json",
                source_kind="json",
                identifier=registry_module.IdentifierRegistration("json.document"),
                factory_key="builtin.json",
            ),
        )
    )
    service = _detection_module().SourceDetectionService(
        registry,
        identifiers_module.IdentifierTable((identifiers_module.JSONSourceIdentifier(),)),
        limits=identifiers_module.IdentificationLimits(
            per_identifier_bytes=8,
            aggregate_bytes=8,
            container_entries=1,
        ),
    )
    path = tmp_path / "large"
    path.write_text('{"records": [' + '"value",' * 20 + "]}", encoding="utf-8")

    detected = service.detect(build_source_request(alias="records", locator=str(path)))

    assert isinstance(detected, AmbiguousSource)
    assert detected.candidates == ("json",)
    assert detected.diagnostic.code.value == "source.ambiguous"
    assert detected.required_action.kind == "specify_type"


def test_definitive_no_match_is_unknown_and_missing_path_is_invalid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "binary"
    path.write_bytes(b"\x00\x01\x02\x03")
    service = _builtin_service()

    unknown = service.detect(build_source_request(alias="binary", locator=str(path)))
    missing = service.detect(
        build_source_request(alias="missing", locator=str(tmp_path / "missing"))
    )

    assert isinstance(unknown, UnknownSource)
    assert unknown.diagnostic.code.value == "source.unknown"
    assert isinstance(missing, InvalidSource)
    assert missing.diagnostic.code.value == "source.locator_shape_invalid"


def test_symlink_is_invalid_without_following_target(tmp_path: Path) -> None:
    target = tmp_path / "orders.csv"
    target.write_text("id\n1\n", encoding="utf-8")
    link = tmp_path / "orders-link"
    link.symlink_to(target)

    detected = _builtin_service().detect(build_source_request(alias="orders", locator=str(link)))

    assert isinstance(detected, InvalidSource)
    assert any(
        item.stable_detail == "symlink_not_followed" for item in detected.diagnostic.evidence
    )


def test_unsupported_xls_and_unknown_explicit_type_are_actionable(
    tmp_path: Path,
) -> None:
    xls = tmp_path / "legacy.xls"
    xls.write_bytes(b"legacy")
    source = tmp_path / "future.data"
    source.write_bytes(b"future")
    service = _builtin_service()

    unsupported_xls = service.detect(build_source_request(alias="legacy", locator=str(xls)))
    unsupported_type = service.detect(
        build_source_request(
            alias="future",
            locator=str(source),
            explicit_type="avro",
        )
    )

    assert isinstance(unsupported_xls, UnsupportedSource)
    assert unsupported_xls.diagnostic.code.value == "source.unsupported_excel_binary"
    assert isinstance(unsupported_type, UnsupportedSource)
    assert unsupported_type.diagnostic.code.value == "source.type_unknown"
    assert unsupported_type.required_action.kind == "choose_supported_type"


def test_descriptor_defaults_apply_once_and_invalid_static_options_do_not_select(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records.json"
    path.write_text("[]", encoding="utf-8")
    service = _builtin_service()

    selected = service.detect(
        build_source_request(
            alias="records",
            locator=str(path),
            options=(("sample_size", 10),),
        )
    )
    unknown_option = service.detect(
        build_source_request(
            alias="records",
            locator=str(path),
            options=(("sampleSize", 10),),
        )
    )
    wrong_kind = service.detect(
        build_source_request(
            alias="records",
            locator=str(path),
            options=(("sample_size", "ten"),),
        )
    )

    assert isinstance(selected, SelectedSource)
    assert selected.options_as_python() == {
        "maximum_depth": 10,
        "sample_size": 10,
    }
    assert isinstance(unknown_option, InvalidSource)
    assert isinstance(wrong_kind, InvalidSource)
    assert unknown_option.diagnostic.code.value == "source.request_invalid"
    assert wrong_kind.diagnostic.code.value == "source.request_invalid"


def test_identifier_exception_is_sanitized_and_does_not_stop_later_identifier(
    tmp_path: Path,
) -> None:
    registry_module = importlib.import_module("csvql.source_registry")
    identifiers_module = importlib.import_module("csvql.source_identifiers")

    class BrokenIdentifier:
        provider_key = "alpha"
        identifier_key = "alpha.magic"

        def identify(self, locator, budget):
            raise RuntimeError("sensitive parser detail")

    class RecognizingIdentifier:
        provider_key = "beta"
        identifier_key = "beta.magic"

        def identify(self, locator, budget):
            return identifiers_module.IdentificationEvidence(
                provider_key="beta",
                status=identifiers_module.IdentificationStatus.RECOGNIZED,
                evidence_kind="beta_magic",
                stable_detail="recognized",
                bytes_read=0,
            )

    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="alpha",
                source_kind="alpha",
                identifier=registry_module.IdentifierRegistration("alpha.magic"),
                factory_key="test.alpha",
            ),
            registry_module.SourceDescriptor(
                provider_key="beta",
                source_kind="beta",
                identifier=registry_module.IdentifierRegistration("beta.magic"),
                factory_key="test.beta",
            ),
        )
    )
    service = _detection_module().SourceDetectionService(
        registry,
        identifiers_module.IdentifierTable((BrokenIdentifier(), RecognizingIdentifier())),
    )
    path = tmp_path / "source"
    path.write_bytes(b"content")

    detected = service.detect(build_source_request(alias="source", locator=str(path)))

    assert isinstance(detected, AmbiguousSource)
    assert detected.candidates == ("alpha", "beta")
    serialized = canonical_source_json_bytes(detected.diagnostic.as_json_value())
    assert b"sensitive parser detail" not in serialized
    assert b"identifier_error" in serialized


def test_fake_future_provider_registers_without_detection_code_changes(
    tmp_path: Path,
) -> None:
    registry_module = importlib.import_module("csvql.source_registry")
    identifiers_module = importlib.import_module("csvql.source_identifiers")

    class AvroIdentifier:
        provider_key = "avro"
        identifier_key = "avro.container"

        def identify(self, locator, budget):
            return identifiers_module.IdentificationEvidence(
                provider_key="avro",
                status=identifiers_module.IdentificationStatus.NOT_RECOGNIZED,
                evidence_kind="avro_container",
                stable_detail="magic_mismatch",
                bytes_read=0,
            )

    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="avro",
                source_kind="avro",
                extensions=(".avro",),
                identifier=registry_module.IdentifierRegistration("avro.container"),
                factory_key="future.avro",
            ),
        )
    )
    service = _detection_module().SourceDetectionService(
        registry,
        identifiers_module.IdentifierTable((AvroIdentifier(),)),
    )
    path = tmp_path / "events.avro"
    path.write_bytes(b"Obj\x01")

    detected = service.detect(build_source_request(alias="events", locator=str(path)))

    assert isinstance(detected, SelectedSource)
    assert detected.provider_key == "avro"


def test_detection_cancellation_propagates(tmp_path: Path) -> None:
    path = tmp_path / "records"
    path.write_text('{"id": 1}\n', encoding="utf-8")
    token = OperationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        _builtin_service().detect(
            build_source_request(alias="records", locator=str(path)),
            operation=OperationContext(token=token),
        )
