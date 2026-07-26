from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import cast

import duckdb
import pytest

from csvql.exceptions import SourceError
from csvql.models import DialectInfo
from csvql.operation import OperationContext
from csvql.source import (
    SOURCE_CAPABILITY_OPERATIONS,
    CapabilityState,
    ResolvedSource,
    SourceCapabilities,
    SourceCapabilityStatus,
    SourceSpec,
)
from csvql.source_adapter import (
    AdapterInspectionMetadata,
    PreparedBinding,
    SourceAdapter,
    SourceAdapterDescriptor,
    SourceAdapterRegistry,
    require_capability,
)


def _capabilities(
    *,
    query_state: CapabilityState = "available",
    query_reason: str | None = None,
    query_remediation: str | None = None,
) -> SourceCapabilities:
    return SourceCapabilities(
        statuses=(
            SourceCapabilityStatus(
                operation="query",
                state=query_state,
                reason_code=query_reason,
                remediation=query_remediation,
            ),
            SourceCapabilityStatus(
                operation="inspect",
                state="unsupported",
                reason_code="operation_not_supported",
            ),
            SourceCapabilityStatus(
                operation="sample",
                state="unsupported",
                reason_code="operation_not_supported",
            ),
            SourceCapabilityStatus(
                operation="profile",
                state="unsupported",
                reason_code="operation_not_supported",
            ),
            SourceCapabilityStatus(
                operation="exact_count",
                state="unsupported",
                reason_code="operation_not_supported",
            ),
            SourceCapabilityStatus(
                operation="change_detection",
                state="unsupported",
                reason_code="operation_not_supported",
            ),
            SourceCapabilityStatus(
                operation="interruptible",
                state="unsupported",
                reason_code="operation_not_supported",
            ),
        )
    )


def _multi_capabilities(
    *,
    available: tuple[str, ...],
    unavailable: dict[str, tuple[str, str | None]] | None = None,
    unsupported: tuple[str, ...] = (),
) -> SourceCapabilities:
    unavailable = unavailable or {}
    statuses: list[SourceCapabilityStatus] = []
    for operation in SOURCE_CAPABILITY_OPERATIONS:
        if operation in available:
            statuses.append(SourceCapabilityStatus(operation=operation, state="available"))
            continue
        if operation in unavailable:
            reason_code, remediation = unavailable[operation]
            statuses.append(
                SourceCapabilityStatus(
                    operation=operation,
                    state="unavailable",
                    reason_code=reason_code,
                    remediation=remediation,
                )
            )
            continue
        reason_code = "operation_not_supported"
        remediation = None
        if operation in unsupported:
            reason_code = "operation_not_supported"
        statuses.append(
            SourceCapabilityStatus(
                operation=operation,
                state="unsupported",
                reason_code=reason_code,
                remediation=remediation,
            )
        )
    return SourceCapabilities(statuses=tuple(statuses))


class _Binding:
    def __init__(self, source: ResolvedSource) -> None:
        self._source = source
        self._closed = False

    @property
    def alias(self) -> str:
        return self._source.spec.alias

    @property
    def source(self) -> ResolvedSource:
        return self._source

    @property
    def capabilities(self) -> SourceCapabilities:
        return self._source.capabilities

    def close(self) -> None:
        self._closed = True


class _Adapter:
    def __init__(self, descriptor: SourceAdapterDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> SourceAdapterDescriptor:
        return self._descriptor

    def validate_options(self, spec: SourceSpec) -> None:
        raise NotImplementedError

    def resolve(self, spec: SourceSpec, context: OperationContext) -> ResolvedSource:
        raise NotImplementedError

    def bind(
        self,
        connection: duckdb.DuckDBPyConnection,
        source: ResolvedSource,
        context: OperationContext,
    ) -> PreparedBinding:
        return _Binding(source)

    def inspect_metadata(
        self,
        source: ResolvedSource,
        context: OperationContext,
    ) -> AdapterInspectionMetadata:
        return AdapterInspectionMetadata(
            dialect=DialectInfo(
                delimiter=None,
                quote=None,
                escape=None,
                header=None,
                encoding=None,
            )
        )


def _unexpected_factory() -> SourceAdapter:
    raise AssertionError("Factory must not be called.")


def test_descriptor_inspection_is_immutable_and_does_not_call_factory() -> None:
    factory_calls: list[str] = []
    descriptor: SourceAdapterDescriptor

    def factory() -> SourceAdapter:
        factory_calls.append("called")
        return _Adapter(descriptor)

    descriptor = SourceAdapterDescriptor(
        kind="csv",
        access_mode="read_only",
        capabilities=_capabilities(),
        dependency=None,
        extra=None,
        factory=factory,
    )
    registry = SourceAdapterRegistry((descriptor,))

    assert registry.descriptor("csv") is descriptor
    assert factory_calls == []
    with pytest.raises(FrozenInstanceError):
        descriptor.kind = "changed"  # type: ignore[misc]


def test_descriptor_rejects_unstable_kind_names() -> None:
    with pytest.raises(ValueError, match="kind"):
        SourceAdapterDescriptor(
            "future-kind",
            "read_only",
            _capabilities(),
            "future-runtime",
            "future",
            _unexpected_factory,
        )


def test_registry_constructs_only_the_selected_factory() -> None:
    calls: list[str] = []
    csv_descriptor: SourceAdapterDescriptor
    future_descriptor: SourceAdapterDescriptor

    def csv_factory() -> SourceAdapter:
        calls.append("csv")
        return _Adapter(csv_descriptor)

    def future_factory() -> SourceAdapter:
        calls.append("future")
        return _Adapter(future_descriptor)

    csv_descriptor = SourceAdapterDescriptor(
        "csv", "read_only", _capabilities(), None, None, csv_factory
    )
    future_descriptor = SourceAdapterDescriptor(
        "future", "read_only", _capabilities(), "future-runtime", "future", future_factory
    )
    registry = SourceAdapterRegistry((csv_descriptor, future_descriptor))

    adapter = registry.create("csv", capability="query")

    assert adapter.descriptor.kind == "csv"
    assert calls == ["csv"]


def test_known_missing_optional_dependency_is_truthful_without_calling_factory() -> None:
    calls: list[str] = []

    def missing_factory() -> SourceAdapter:
        calls.append("future")
        return cast(SourceAdapter, object())

    descriptor = SourceAdapterDescriptor(
        "future",
        "read_only",
        _capabilities(
            query_state="unavailable",
            query_reason="runtime_missing",
            query_remediation="Install the 'future' extra to enable this source capability.",
        ),
        "future_runtime",
        "future",
        missing_factory,
    )
    registry = SourceAdapterRegistry((descriptor,))

    reported = registry.descriptor("future").capabilities.status_for("query")

    assert reported.state == "unavailable"
    assert reported.reason_code == "runtime_missing"
    assert reported.remediation == "Install the 'future' extra to enable this source capability."
    with pytest.raises(SourceError) as error:
        registry.create("future", capability="query")

    assert error.value.code == "missing_optional_dependency"
    assert calls == []


def test_registry_normalizes_known_missing_runtime_for_all_available_capabilities() -> None:
    def missing_factory() -> SourceAdapter:
        raise AssertionError("Factory must not be called for a known missing runtime.")

    descriptor = SourceAdapterDescriptor(
        "future",
        "read_only",
        _multi_capabilities(
            available=("inspect", "sample"),
            unavailable={
                "query": (
                    "runtime_missing",
                    "Install the 'future' extra to enable this source capability.",
                )
            },
        ),
        "future_runtime",
        "future",
        missing_factory,
    )
    registry = SourceAdapterRegistry((descriptor,))

    for operation in ("query", "inspect", "sample"):
        reported = registry.descriptor("future").capabilities.status_for(operation)
        assert reported.state == "unavailable"
        assert reported.reason_code == "runtime_missing"
        assert (
            reported.remediation == "Install the 'future' extra to enable this source capability."
        )
        with pytest.raises(SourceError) as error:
            registry.create("future", capability=operation)
        assert error.value.code == "missing_optional_dependency"
        assert error.value.capability == operation

    with pytest.raises(SourceError) as unsupported_error:
        registry.create("future", capability="profile")

    assert unsupported_error.value.code == "unsupported_capability"
    assert unsupported_error.value.capability == "profile"


def test_missing_selected_optional_dependency_is_stable_and_does_not_break_other_kind() -> None:
    csv_descriptor: SourceAdapterDescriptor

    def csv_factory() -> SourceAdapter:
        return _Adapter(csv_descriptor)

    def missing_factory() -> SourceAdapter:
        raise ModuleNotFoundError(
            "No module named 'future_runtime'",
            name="future_runtime",
        )

    csv_descriptor = SourceAdapterDescriptor(
        "csv", "read_only", _capabilities(), None, None, csv_factory
    )
    future_descriptor = SourceAdapterDescriptor(
        "future",
        "read_only",
        _capabilities(),
        "future_runtime",
        "future",
        missing_factory,
    )
    registry = SourceAdapterRegistry((csv_descriptor, future_descriptor))

    with pytest.raises(SourceError) as error:
        registry.create("future", capability="query")

    assert error.value.code == "missing_optional_dependency"
    assert error.value.kind == "future"
    assert error.value.capability == "query"
    assert error.value.dependency == "future_runtime"
    assert error.value.extra == "future"
    assert error.value.suggestion == "Install the 'future' extra to enable this source capability."
    assert registry.create("csv", capability="query").descriptor.kind == "csv"


def test_missing_selected_optional_dependency_updates_descriptor_truth_after_invocation() -> None:
    calls: list[str] = []

    def missing_factory() -> SourceAdapter:
        calls.append("future")
        raise ModuleNotFoundError(
            "No module named 'future_runtime'",
            name="future_runtime",
        )

    descriptor = SourceAdapterDescriptor(
        "future",
        "read_only",
        _multi_capabilities(
            available=("query", "inspect", "sample"),
            unsupported=("profile", "exact_count", "change_detection", "interruptible"),
        ),
        "future_runtime",
        "future",
        missing_factory,
    )
    registry = SourceAdapterRegistry((descriptor,))

    before_query = registry.descriptor("future").capabilities.status_for("query")
    before_inspect = registry.descriptor("future").capabilities.status_for("inspect")

    assert before_query.state == "available"
    assert before_inspect.state == "available"
    with pytest.raises(SourceError) as first_error:
        registry.create("future", capability="query")
    with pytest.raises(SourceError) as second_error:
        registry.create("future", capability="query")
    with pytest.raises(SourceError) as inspect_error:
        registry.create("future", capability="inspect")
    with pytest.raises(SourceError) as sample_error:
        registry.create("future", capability="sample")

    after_query = registry.descriptor("future").capabilities.status_for("query")
    after_inspect = registry.descriptor("future").capabilities.status_for("inspect")
    after_sample = registry.descriptor("future").capabilities.status_for("sample")

    assert first_error.value.code == "missing_optional_dependency"
    assert second_error.value.code == "missing_optional_dependency"
    assert inspect_error.value.code == "missing_optional_dependency"
    assert inspect_error.value.capability == "inspect"
    assert sample_error.value.code == "missing_optional_dependency"
    assert sample_error.value.capability == "sample"
    for after in (after_query, after_inspect, after_sample):
        assert after.state == "unavailable"
        assert after.reason_code == "runtime_missing"
        assert after.remediation == "Install the 'future' extra to enable this source capability."
    assert calls == ["future"]


@pytest.mark.parametrize(
    ("factory_error", "expected_type"),
    [
        (
            ModuleNotFoundError(
                "No module named 'unrelated_runtime'",
                name="unrelated_runtime",
            ),
            ModuleNotFoundError,
        ),
        (ImportError("cannot import name 'Client'"), ImportError),
    ],
)
def test_registry_reraises_unattributable_factory_import_failures(
    factory_error: ImportError,
    expected_type: type[ImportError],
) -> None:
    def broken_factory() -> SourceAdapter:
        raise factory_error

    descriptor = SourceAdapterDescriptor(
        "future",
        "read_only",
        _capabilities(),
        "future_runtime",
        "future",
        broken_factory,
    )

    with pytest.raises(expected_type) as error:
        SourceAdapterRegistry((descriptor,)).create("future", capability="query")

    assert error.value is factory_error


def test_registry_preserves_truth_after_unrelated_missing_module_failure() -> None:
    def broken_factory() -> SourceAdapter:
        raise ModuleNotFoundError(
            "No module named 'unrelated_runtime'",
            name="unrelated_runtime",
        )

    descriptor = SourceAdapterDescriptor(
        "future",
        "read_only",
        _capabilities(),
        "future_runtime",
        "future",
        broken_factory,
    )
    registry = SourceAdapterRegistry((descriptor,))

    with pytest.raises(ModuleNotFoundError, match="unrelated_runtime"):
        registry.create("future", capability="query")

    reported = registry.descriptor("future").capabilities.status_for("query")

    assert reported.state == "available"


def test_require_capability_distinguishes_unavailable_from_unsupported() -> None:
    unavailable = _capabilities(
        query_state="unavailable",
        query_reason="runtime_missing",
        query_remediation="Install the selected source extra.",
    )
    unsupported = _capabilities(
        query_state="unsupported",
        query_reason="operation_not_supported",
        query_remediation="Choose a source that supports query.",
    )

    with pytest.raises(SourceError) as unavailable_error:
        require_capability(unavailable, "query", kind="future", alias="orders")
    with pytest.raises(SourceError) as unsupported_error:
        require_capability(unsupported, "query", kind="future", alias="orders")

    assert unavailable_error.value.code == "unsupported_capability"
    assert unavailable_error.value.message == (
        "Source capability 'query' is unavailable (runtime_missing)."
    )
    assert unavailable_error.value.suggestion == "Install the selected source extra."
    assert unsupported_error.value.code == "unsupported_capability"
    assert unsupported_error.value.message == (
        "Source capability 'query' is unsupported (operation_not_supported)."
    )
    assert unsupported_error.value.suggestion == "Choose a source that supports query."


def test_source_capabilities_require_every_operation_exactly_once() -> None:
    statuses = _capabilities().statuses

    with pytest.raises(ValueError, match="exact source capability map"):
        SourceCapabilities(statuses=statuses[:-1])
    with pytest.raises(ValueError, match="Duplicate source capability"):
        SourceCapabilities(statuses=(*statuses, statuses[0]))


@pytest.mark.parametrize("reason_code", [None, "", "Runtime Missing", "runtime-missing"])
@pytest.mark.parametrize("state", ["unavailable", "unsupported"])
def test_non_available_capabilities_require_stable_reason_codes(
    state: CapabilityState,
    reason_code: str | None,
) -> None:
    with pytest.raises(ValueError, match="reason code"):
        SourceCapabilityStatus(
            operation="query",
            state=state,
            reason_code=reason_code,
        )


def test_status_for_returns_a_definite_status_from_exhaustive_report() -> None:
    capabilities = _capabilities()

    status: SourceCapabilityStatus = capabilities.status_for("query")

    assert status.operation == "query"
    assert status.state == "available"


def test_registry_rejects_duplicate_kinds() -> None:
    descriptor = SourceAdapterDescriptor(
        "csv",
        "read_only",
        _capabilities(),
        None,
        None,
        _unexpected_factory,
    )

    with pytest.raises(ValueError, match="Duplicate source adapter kind"):
        SourceAdapterRegistry((descriptor, descriptor))


def test_registry_rejects_unknown_kinds_with_stable_source_error() -> None:
    registry = SourceAdapterRegistry(())

    with pytest.raises(SourceError) as error:
        registry.descriptor("unknown")

    assert error.value.code == "unknown_source_kind"
    assert error.value.kind == "unknown"


def test_source_operation_map_excludes_export_and_catalog_persistence() -> None:
    operations = tuple(status.operation for status in _capabilities().statuses)

    assert operations == SOURCE_CAPABILITY_OPERATIONS
    assert "export" not in operations
    assert "catalog_persistence" not in operations
