from __future__ import annotations

import importlib
import sys
from dataclasses import FrozenInstanceError, fields, replace

import pytest


def _registry_module():
    return importlib.import_module("csvql.source_registry")


def test_builtin_descriptor_registry_is_import_free_and_declares_all_v12_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "csvql.csv_adapter", raising=False)

    registry_module = _registry_module()
    registry = registry_module.build_builtin_descriptor_registry()

    assert registry.provider_keys == ("csv", "excel", "json", "ndjson", "parquet")
    assert registry.match_extension("ORDERS.CSV")[1] == ".csv"
    assert registry.match_extension("events.JSONL")[0].provider_key == "ndjson"
    assert registry.match_extension("warehouse.PARQ")[0].provider_key == "parquet"
    assert registry.match_extension("book.XLSX")[0].provider_key == "excel"
    assert "csvql.csv_adapter" not in sys.modules
    assert all(
        not callable(getattr(descriptor, field.name))
        for descriptor in registry.descriptors
        for field in fields(descriptor)
    )


def test_builtin_descriptors_encode_approved_static_defaults_once() -> None:
    registry = _registry_module().build_builtin_descriptor_registry()

    parquet = registry.descriptor("parquet")
    json_descriptor = registry.descriptor("json")
    excel = registry.descriptor("excel")

    assert parquet.option_defaults_as_python() == {
        "partitioning": "none",
        "union_by_name": False,
    }
    assert json_descriptor.option_defaults_as_python() == {
        "maximum_object_size": 16_777_216,
        "record_mode": "array",
        "sample_size": 20_480,
    }
    assert excel.option_defaults_as_python() == {
        "header": True,
        "stop_at_empty": False,
        "type_mode": "text",
    }
    assert "ignore_errors" not in {option.key for option in excel.options}


def test_registry_uses_longest_compound_suffix_without_registration_order() -> None:
    registry_module = _registry_module()
    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="short",
                source_kind="short",
                extensions=(".data",),
                factory_key="test.short",
            ),
            registry_module.SourceDescriptor(
                provider_key="long",
                source_kind="long",
                extensions=(".records.data",),
                factory_key="test.long",
            ),
        )
    )

    descriptor, extension = registry.match_extension("orders.RECORDS.DATA")

    assert descriptor.provider_key == "long"
    assert extension == ".records.data"


def test_registry_rejects_duplicate_normalized_extensions_within_one_descriptor() -> None:
    registry_module = _registry_module()
    from csvql.exceptions import ConfigurationFailure

    descriptor = registry_module.SourceDescriptor(
        provider_key="future",
        source_kind="future",
        extensions=(".DATA", ".data"),
        factory_key="future.factory",
    )

    with pytest.raises(ConfigurationFailure) as captured:
        registry_module.DescriptorRegistry.build((descriptor,))

    assert tuple((finding.code, finding.subject) for finding in captured.value.findings) == (
        ("duplicate_extension", ".data"),
    )


def test_registry_rejects_all_conflicts_in_deterministic_order() -> None:
    registry_module = _registry_module()
    from csvql.exceptions import ConfigurationFailure

    descriptors = (
        registry_module.SourceDescriptor(
            provider_key="zeta",
            source_kind="shared",
            aliases=("duplicate",),
            extensions=(".same",),
            factory_key="same.factory",
        ),
        registry_module.SourceDescriptor(
            provider_key="alpha",
            source_kind="shared",
            aliases=("duplicate",),
            extensions=(".SAME",),
            factory_key="same.factory",
        ),
    )

    with pytest.raises(ConfigurationFailure) as captured:
        registry_module.DescriptorRegistry.build(descriptors)

    codes_and_subjects = tuple(
        (finding.code, finding.subject) for finding in captured.value.findings
    )
    assert codes_and_subjects == tuple(sorted(codes_and_subjects))
    assert {finding.code for finding in captured.value.findings} >= {
        "duplicate_extension",
        "duplicate_factory_key",
        "duplicate_source_alias",
        "duplicate_source_kind",
    }


def test_registry_rejects_more_than_sixteen_active_identifiers() -> None:
    registry_module = _registry_module()
    from csvql.exceptions import ConfigurationFailure

    descriptors = tuple(
        registry_module.SourceDescriptor(
            provider_key=f"future{i}",
            source_kind=f"future{i}",
            identifier=registry_module.IdentifierRegistration(f"future{i}.signature"),
            factory_key=f"future{i}.factory",
        )
        for i in range(17)
    )

    with pytest.raises(ConfigurationFailure) as captured:
        registry_module.DescriptorRegistry.build(descriptors)

    assert tuple(finding.code for finding in captured.value.findings) == (
        "identifier_limit_exceeded",
    )


def test_registry_rejects_invalid_option_metadata_without_importing_provider() -> None:
    registry_module = _registry_module()
    from csvql.exceptions import ConfigurationFailure

    descriptor = registry_module.SourceDescriptor(
        provider_key="future",
        source_kind="future",
        options=(
            registry_module.SourceOptionDefinition(
                key="Header",
                value_kind="boolean",
                has_default=True,
                default=True,
                sensitive=True,
                affects_identity=True,
            ),
            registry_module.SourceOptionDefinition(
                key="Header",
                value_kind="unknown",
            ),
        ),
        factory_key="future.factory",
    )

    with pytest.raises(ConfigurationFailure) as captured:
        registry_module.DescriptorRegistry.build((descriptor,))

    assert {finding.code for finding in captured.value.findings} >= {
        "duplicate_option_key",
        "invalid_option_key",
        "invalid_option_kind",
        "sensitive_identity_option",
    }


def test_registry_aggregates_non_json_and_non_finite_option_defaults() -> None:
    registry_module = _registry_module()
    from csvql.exceptions import ConfigurationFailure

    descriptor = registry_module.SourceDescriptor(
        provider_key="future",
        source_kind="future",
        options=(
            registry_module.SourceOptionDefinition(
                key="path",
                value_kind="string",
                has_default=True,
                default=object(),
            ),
            registry_module.SourceOptionDefinition(
                key="ratio",
                value_kind="number",
                has_default=True,
                default=float("inf"),
            ),
        ),
        factory_key="future.factory",
    )

    with pytest.raises(ConfigurationFailure) as captured:
        registry_module.DescriptorRegistry.build((descriptor,))

    assert tuple((finding.code, finding.subject) for finding in captured.value.findings) == (
        ("invalid_option_default", "future.path"),
        ("invalid_option_default", "future.ratio"),
    )


def test_descriptor_views_are_immutable_and_hide_runtime_constructors() -> None:
    registry_module = _registry_module()
    descriptor = registry_module.build_builtin_descriptor_registry().descriptor("csv")

    with pytest.raises(FrozenInstanceError):
        descriptor.provider_key = "changed"  # type: ignore[misc]
    assert not hasattr(descriptor, "adapter_class")
    assert not hasattr(descriptor, "constructor")
    assert not hasattr(descriptor, "module")


def test_unsupported_xls_hint_is_distinct_from_xlsx_registration() -> None:
    registry_module = _registry_module()
    registry = registry_module.build_builtin_descriptor_registry()

    hint = registry.match_unsupported_extension("legacy.xls")

    assert hint is not None
    assert hint.extension == ".xls"
    assert hint.diagnostic_code == "source.unsupported_excel_binary"
    assert registry.match_extension("legacy.xls") is None


def test_fake_future_descriptor_participates_without_registry_source_changes() -> None:
    registry_module = _registry_module()
    builtin_registry = registry_module.build_builtin_descriptor_registry()
    future = registry_module.SourceDescriptor(
        provider_key="avro",
        source_kind="avro",
        aliases=("apache_avro",),
        extensions=(".avro",),
        identifier=registry_module.IdentifierRegistration("avro.object_container"),
        factory_key="future.avro",
        provider_interpretation_version="1",
    )
    registry = registry_module.DescriptorRegistry.build(
        (*builtin_registry.source_descriptors, future),
        unsupported_extensions=builtin_registry.unsupported_extensions,
    )

    assert registry.resolve_type("APACHE_AVRO").provider_key == "avro"
    assert registry.match_extension("events.avro")[0].provider_key == "avro"
    assert registry.provider_keys[-1] == "parquet"


def test_descriptor_factory_composition_reports_missing_orphan_and_mismatch_together() -> None:
    registry_module = _registry_module()
    from csvql.exceptions import ConfigurationFailure

    registry = registry_module.DescriptorRegistry.build(
        (
            registry_module.SourceDescriptor(
                provider_key="csv",
                source_kind="csv",
                factory_key="builtin.csv",
            ),
            registry_module.SourceDescriptor(
                provider_key="json",
                source_kind="json",
                factory_key="builtin.json",
            ),
        )
    )
    registrations = (
        registry_module.ProviderFactoryKey("csv", "wrong.csv"),
        registry_module.ProviderFactoryKey("orphan", "future.orphan"),
    )

    with pytest.raises(ConfigurationFailure) as captured:
        registry_module.validate_descriptor_factory_composition(registry, registrations)

    assert tuple(finding.code for finding in captured.value.findings) == (
        "factory_key_mismatch",
        "missing_factory_registration",
        "orphan_factory_registration",
    )


def test_registry_source_descriptors_are_independent_immutable_values() -> None:
    registry_module = _registry_module()
    registry = registry_module.build_builtin_descriptor_registry()
    original = registry.source_descriptors[0]

    changed = replace(original, extensions=(".changed",))

    assert registry.source_descriptors[0] is original
    assert changed.extensions == (".changed",)
