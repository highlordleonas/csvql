from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import duckdb
import pytest

import csvql.csv_adapter as csv_adapter_module
from csvql import CSVQLEngine
from csvql.csv_adapter import (
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
    SNIFF_BYTES,
    CSVSourceAdapter,
)
from csvql.exceptions import SourceError, TableMappingError
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    SOURCE_CAPABILITY_OPERATIONS,
    ResolvedSource,
    SourceCapabilities,
    SourceCapability,
    SourceCapabilityStatus,
    SourceSpec,
    source_from_path,
)
from csvql.source_adapter import SourceAdapter, SourceAdapterDescriptor, SourceAdapterRegistry
from csvql.source_operations import SourceOperations
from csvql.table_mapping import (
    parse_table_mapping,
    source_from_single_csv,
    validate_table_alias,
)


def _context() -> OperationContext:
    return OperationContext(token=OperationToken())


def _write_csv(path: Path, content: str = "id,value\n1,alpha\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _resolved_csv(
    path: Path,
    *,
    alias: str = "Orders",
    locator: str | None = None,
    anchor: Path | None = None,
):
    return CSVSourceAdapter().resolve(
        SourceSpec(
            alias=alias,
            kind="csv",
            locator=locator or str(path),
            anchor=anchor or path.parent,
        ),
        _context(),
    )


def test_default_registry_contains_only_the_production_csv_adapter() -> None:
    descriptor = DEFAULT_SOURCE_ADAPTER_REGISTRY.descriptor("csv")

    assert descriptor.kind == "csv"
    assert descriptor.access_mode == "read_only"
    assert descriptor.dependency is None
    assert descriptor.extra is None
    assert tuple(status.operation for status in descriptor.capabilities.statuses) == (
        SOURCE_CAPABILITY_OPERATIONS
    )
    assert all(status.state == "available" for status in descriptor.capabilities.statuses)
    assert isinstance(
        DEFAULT_SOURCE_ADAPTER_REGISTRY.create("csv", capability="query"),
        CSVSourceAdapter,
    )
    with pytest.raises(SourceError) as error:
        DEFAULT_SOURCE_ADAPTER_REGISTRY.descriptor("future")
    assert error.value.code == "unknown_source_kind"


def test_descriptor_available_capabilities_are_truthful_for_valid_csv(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    descriptor = DEFAULT_SOURCE_ADAPTER_REGISTRY.descriptor("csv")
    observed = {status.operation: status.state for status in descriptor.capabilities.statuses}

    with CSVQLEngine(registry=DEFAULT_SOURCE_ADAPTER_REGISTRY) as engine:
        engine.prepare_sources((resolved,))
        query_result = engine.query("SELECT id, value FROM Orders ORDER BY id")

    with CSVQLEngine(registry=DEFAULT_SOURCE_ADAPTER_REGISTRY) as engine:
        operations = SourceOperations(engine, resolved)
        inspect_result = operations.inspect()
        exact_inspect_result = operations.inspect(exact=True)
        sample_result = operations.sample(limit=1)
        profile_result = operations.profile()

    assert observed == {operation: "available" for operation in SOURCE_CAPABILITY_OPERATIONS}
    assert query_result.rows == ((1, "alpha"),)
    assert [column.name for column in inspect_result.columns] == ["id", "value"]
    assert exact_inspect_result.row_count.value == 1
    assert sample_result.rows == ((1, "alpha"),)
    assert profile_result.row_count == 1


def test_descriptor_change_detection_capability_detects_post_submission_mutation(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    csv_path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
    connection = duckdb.connect(database=":memory:")
    try:
        with pytest.raises(SourceError) as error:
            CSVSourceAdapter().bind(connection, resolved, _context())
    finally:
        connection.close()

    assert (
        DEFAULT_SOURCE_ADAPTER_REGISTRY.descriptor("csv")
        .capabilities.status_for("change_detection")
        .state
        == "available"
    )
    assert error.value.code == "source_changed"


def test_descriptor_interruptible_capability_observes_cancellation(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    context = _context()
    calls: list[str] = []

    class FakeRelation:
        def create_view(self, alias: str, *, replace: bool) -> None:
            calls.append(f"create:{alias}:{replace}")
            context.token.cancel()

    class FakeConnection:
        def read_csv(self, locator: str, *, auto_detect: bool, header: bool) -> FakeRelation:
            calls.append(f"read:{locator}:{auto_detect}:{header}")
            return FakeRelation()

        def execute(self, sql: str) -> None:
            calls.append(sql)

    with pytest.raises(OperationCancelled):
        CSVSourceAdapter().bind(
            cast(duckdb.DuckDBPyConnection, FakeConnection()),
            resolved,
            context,
        )

    assert (
        DEFAULT_SOURCE_ADAPTER_REGISTRY.descriptor("csv")
        .capabilities.status_for("interruptible")
        .state
        == "available"
    )
    assert calls == [
        f"read:{csv_path.resolve()}:True:True",
        "create:Orders:False",
        'DROP VIEW IF EXISTS "Orders"',
    ]


@pytest.mark.parametrize(
    ("state", "reason_code", "remediation"),
    [
        ("unavailable", "adapter_runtime_pending", "Retry after the adapter is installed."),
        ("unsupported", "operation_not_supported", "Choose a source with query support."),
    ],
)
def test_descriptor_non_available_capabilities_raise_exact_stable_reasons(
    state: str,
    reason_code: str,
    remediation: str,
) -> None:
    descriptor = SourceAdapterDescriptor(
        kind="future",
        access_mode="read_only",
        capabilities=SourceCapabilities(
            tuple(
                SourceCapabilityStatus(
                    operation=operation,
                    state=state if operation == "query" else "available",
                    reason_code=reason_code if operation == "query" else None,
                    remediation=remediation if operation == "query" else None,
                )
                for operation in SOURCE_CAPABILITY_OPERATIONS
            )
        ),
        dependency=None,
        extra=None,
        factory=lambda: cast(SourceAdapter, object()),
    )

    with pytest.raises(SourceError) as error:
        SourceAdapterRegistry((descriptor,)).create("future", capability="query")

    assert error.value.code == "unsupported_capability"
    assert error.value.kind == "future"
    assert error.value.capability == "query"
    assert error.value.message == f"Source capability 'query' is {state} ({reason_code})."
    assert error.value.suggestion == remediation


def test_legacy_source_facade_resolves_through_the_default_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    calls: list[tuple[str, str]] = []
    default_registry = csv_adapter_module.DEFAULT_SOURCE_ADAPTER_REGISTRY

    class RecordingRegistry:
        def create(self, kind: str, *, capability: SourceCapability):
            calls.append((kind, capability))
            return default_registry.create(kind, capability=capability)

    monkeypatch.setattr(
        csv_adapter_module,
        "DEFAULT_SOURCE_ADAPTER_REGISTRY",
        RecordingRegistry(),
    )

    source = source_from_path("orders.csv", base_dir=tmp_path)

    assert source.path == csv_path.resolve()
    assert calls == [("csv", "query")]


def test_resolve_uses_the_captured_anchor_after_process_cwd_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    csv_path = project_root / "data" / "orders.csv"
    _write_csv(csv_path)
    monkeypatch.chdir(tmp_path)
    spec = SourceSpec(
        alias="Orders",
        kind="csv",
        locator="data/orders.csv",
        anchor=Path("project"),
    )
    later_cwd = tmp_path / "later"
    later_cwd.mkdir()
    monkeypatch.chdir(later_cwd)

    resolved = CSVSourceAdapter().resolve(spec, _context())

    assert resolved.canonical_locator == str(csv_path.resolve())
    assert resolved.spec.locator == "data/orders.csv"


def test_resolve_captures_version_size_and_utc_mtime_fingerprint(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)

    resolved = _resolved_csv(csv_path)

    assert resolved.fingerprint is not None
    assert resolved.fingerprint.version == 1
    assert resolved.fingerprint.size_bytes == csv_path.stat().st_size
    assert resolved.fingerprint.modified_at.endswith("+00:00")


def test_resolve_reports_sanitized_source_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "private" / "missing.csv"

    with pytest.raises(SourceError) as error:
        _resolved_csv(missing_path)

    assert error.value.code == "source_missing"
    assert error.value.alias == "Orders"
    assert str(missing_path) not in error.value.message


def test_resolve_sanitizes_invalid_locator_details(tmp_path: Path) -> None:
    unsafe_locator = "\0private-locator"
    spec = SourceSpec(
        alias="Orders",
        kind="csv",
        locator=unsafe_locator,
        anchor=tmp_path,
    )

    with pytest.raises(SourceError) as error:
        CSVSourceAdapter().resolve(spec, _context())

    assert error.value.code == "source_missing"
    assert unsafe_locator not in error.value.message


def test_bind_reports_source_missing_when_file_disappears(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    csv_path.unlink()
    connection = duckdb.connect(database=":memory:")
    try:
        with pytest.raises(SourceError) as error:
            CSVSourceAdapter().bind(connection, resolved, _context())
    finally:
        connection.close()

    assert error.value.code == "source_missing"
    assert str(csv_path) not in error.value.message


def test_bind_revalidates_the_complete_submission_fingerprint(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    csv_path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
    connection = duckdb.connect(database=":memory:")
    try:
        with pytest.raises(SourceError) as error:
            CSVSourceAdapter().bind(connection, resolved, _context())
    finally:
        connection.close()

    assert error.value.code == "source_changed"
    assert error.value.alias == "Orders"
    assert str(csv_path) not in error.value.message


def test_bind_compares_fingerprint_version_before_reading_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    assert resolved.fingerprint is not None
    changed = replace(
        resolved,
        fingerprint=replace(resolved.fingerprint, version=resolved.fingerprint.version + 1),
    )

    _assert_source_changed_before_read(changed)


def test_bind_compares_fingerprint_size_before_reading_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    original_stat = csv_path.stat()
    csv_path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
    os.utime(
        csv_path,
        ns=(csv_path.stat().st_atime_ns, original_stat.st_mtime_ns),
    )
    assert resolved.fingerprint is not None
    assert csv_path.stat().st_size != resolved.fingerprint.size_bytes

    _assert_source_changed_before_read(resolved)


def test_bind_compares_fingerprint_mtime_before_reading_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    original_stat = csv_path.stat()
    os.utime(
        csv_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 2_000_000_000),
    )
    assert resolved.fingerprint is not None
    assert csv_path.stat().st_size == resolved.fingerprint.size_bytes

    _assert_source_changed_before_read(resolved)


def _assert_source_changed_before_read(resolved: ResolvedSource) -> None:
    read_calls: list[str] = []

    class UnreadConnection:
        def read_csv(self, *args: object, **kwargs: object) -> object:
            read_calls.append("read_csv")
            raise AssertionError("read_csv must not run before fingerprint revalidation.")

    with pytest.raises(SourceError) as error:
        CSVSourceAdapter().bind(
            cast(duckdb.DuckDBPyConnection, UnreadConnection()),
            resolved,
            _context(),
        )

    assert error.value.code == "source_changed"
    assert read_calls == []


def test_validate_options_accepts_only_empty_csv_options_without_echoing_values(
    tmp_path: Path,
) -> None:
    adapter = CSVSourceAdapter()
    spec = SourceSpec(alias="Orders", kind="csv", locator="orders.csv", anchor=tmp_path)
    adapter.validate_options(spec)
    object.__setattr__(spec, "options", (("unsafe", "private-value"),))

    with pytest.raises(SourceError) as error:
        adapter.validate_options(spec)

    assert error.value.code == "unsupported_source_option"
    assert "unsafe" not in error.value.message
    assert "private-value" not in error.value.message


def test_bind_uses_exact_duckdb_csv_defaults_and_never_closes_connection(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path, alias="CustomerOrders")
    calls: list[tuple[object, ...]] = []

    class FakeRelation:
        def create_view(self, alias: str, *, replace: bool) -> None:
            calls.append(("create_view", alias, replace))

    class FakeConnection:
        def read_csv(
            self,
            locator: str,
            *,
            auto_detect: bool,
            header: bool,
        ) -> FakeRelation:
            calls.append(("read_csv", locator, auto_detect, header))
            return FakeRelation()

        def execute(self, sql: str) -> None:
            calls.append(("execute", sql))

        def close(self) -> None:
            calls.append(("close",))

    connection = FakeConnection()
    binding = CSVSourceAdapter().bind(
        cast(duckdb.DuckDBPyConnection, connection),
        resolved,
        _context(),
    )

    assert binding.alias == "CustomerOrders"
    assert binding.source is resolved
    assert binding.capabilities is resolved.capabilities
    assert calls == [
        ("read_csv", str(csv_path.resolve()), True, True),
        ("create_view", "CustomerOrders", False),
    ]
    binding.close()
    binding.close()
    assert calls == [
        ("read_csv", str(csv_path.resolve()), True, True),
        ("create_view", "CustomerOrders", False),
        ("execute", 'DROP VIEW IF EXISTS "CustomerOrders"'),
    ]


def test_binding_cleanup_retries_after_a_transient_drop_failure(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    execute_calls: list[str] = []

    class FakeRelation:
        def create_view(self, alias: str, *, replace: bool) -> None:
            return None

    class RetryableConnection:
        def read_csv(
            self,
            locator: str,
            *,
            auto_detect: bool,
            header: bool,
        ) -> FakeRelation:
            return FakeRelation()

        def execute(self, sql: str) -> None:
            execute_calls.append(sql)
            if len(execute_calls) == 1:
                raise duckdb.Error("private cleanup detail")

        def close(self) -> None:
            raise AssertionError("The adapter must not close the engine connection.")

    binding = CSVSourceAdapter().bind(
        cast(duckdb.DuckDBPyConnection, RetryableConnection()),
        resolved,
        _context(),
    )

    with pytest.raises(SourceError) as error:
        binding.close()
    assert error.value.code == "source_bind_failed"
    assert "private cleanup detail" not in error.value.message

    binding.close()
    binding.close()

    assert execute_calls == [
        'DROP VIEW IF EXISTS "Orders"',
        'DROP VIEW IF EXISTS "Orders"',
    ]


def test_bind_does_not_replace_an_existing_alias(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path, alias="Orders")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute('CREATE VIEW "Orders" AS SELECT 99 AS id')

        with pytest.raises(SourceError) as error:
            CSVSourceAdapter().bind(connection, resolved, _context())

        assert error.value.code == "source_bind_failed"
        assert connection.execute('SELECT id FROM "Orders"').fetchone() == (99,)
    finally:
        connection.close()


def test_bind_sanitizes_duckdb_failure_details(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)

    class FailingConnection:
        def read_csv(self, *args: object, **kwargs: object) -> object:
            raise duckdb.InvalidInputException("internal dependency detail /private/path")

    with pytest.raises(SourceError) as error:
        CSVSourceAdapter().bind(
            cast(duckdb.DuckDBPyConnection, FailingConnection()),
            resolved,
            _context(),
        )

    assert error.value.code == "source_bind_failed"
    assert "internal dependency detail" not in error.value.message
    assert "/private/path" not in error.value.message


def test_bind_cleans_up_when_cancellation_is_observed_after_registration(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    context = _context()
    calls: list[tuple[object, ...]] = []

    class FakeRelation:
        def create_view(self, alias: str, *, replace: bool) -> None:
            calls.append(("create_view", alias, replace))
            context.token.cancel()

    class FakeConnection:
        def read_csv(
            self,
            locator: str,
            *,
            auto_detect: bool,
            header: bool,
        ) -> FakeRelation:
            calls.append(("read_csv", locator, auto_detect, header))
            return FakeRelation()

        def execute(self, sql: str) -> None:
            calls.append(("execute", sql))

    with pytest.raises(OperationCancelled):
        CSVSourceAdapter().bind(
            cast(duckdb.DuckDBPyConnection, FakeConnection()),
            resolved,
            context,
        )

    assert calls == [
        ("read_csv", str(csv_path.resolve()), True, True),
        ("create_view", "Orders", False),
        ("execute", 'DROP VIEW IF EXISTS "Orders"'),
    ]


def test_inspect_metadata_reads_exactly_the_bounded_raw_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)
    resolved = _resolved_csv(csv_path)
    read_sizes: list[int] = []

    class FakeFile:
        def __enter__(self) -> FakeFile:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def read(self, size: int = -1) -> str:
            read_sizes.append(size)
            return "order_id,total_amount\nORD-1,12.34\n"

    def fake_open(self: Path, *args: object, **kwargs: object) -> FakeFile:
        return FakeFile()

    monkeypatch.setattr(Path, "open", fake_open, raising=True)

    metadata = CSVSourceAdapter().inspect_metadata(resolved, _context())

    assert read_sizes == [SNIFF_BYTES]
    assert metadata.dialect.delimiter == ","
    assert metadata.dialect.header is True
    assert metadata.dialect.encoding == "utf-8"
    assert metadata.warnings == ()


@pytest.mark.parametrize(
    ("sample", "warning"),
    [
        ("", "CSV file is empty; dialect detection used default values."),
        ("abc\ndefgh", "Could not detect CSV dialect from the bounded sample."),
    ],
)
def test_inspect_metadata_preserves_legacy_dialect_warning_text(
    tmp_path: Path,
    sample: str,
    warning: str,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path, sample)
    resolved = _resolved_csv(csv_path)

    metadata = CSVSourceAdapter().inspect_metadata(resolved, _context())

    assert metadata.warnings == (warning,)


def test_table_mapping_boundaries_reject_reserved_aliases_as_cli_errors(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "orders.csv"
    _write_csv(csv_path)

    with pytest.raises(TableMappingError, match="reserved"):
        validate_table_alias("__LOCALQL_orders")
    with pytest.raises(TableMappingError, match="reserved"):
        parse_table_mapping(f"__localql_orders={csv_path}")


def test_single_csv_derives_normalized_alias_from_leading_underscore_filename(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "__localql_orders.csv"
    _write_csv(csv_path)

    source = source_from_single_csv(str(csv_path))

    assert source.name == "localql_orders"
    assert source.path == csv_path.resolve()


def test_single_csv_derives_legacy_alias_from_the_canonical_symlink_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "canonical-orders.csv"
    _write_csv(target)
    input_alias = tmp_path / "input.csv"
    try:
        input_alias.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    source = source_from_single_csv(str(input_alias))

    assert source.name == "canonical_orders"
    assert source.path == target.resolve()


def test_single_csv_derives_normalized_alias_from_canonical_symlink_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "__localql_private.csv"
    _write_csv(target)
    input_alias = tmp_path / "safe-input.csv"
    try:
        input_alias.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    source = source_from_single_csv(str(input_alias))

    assert source.name == "localql_private"
    assert source.path == target.resolve()


def test_single_csv_uses_one_coherent_snapshot_when_symlink_retargets_after_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_target = tmp_path / "first-orders.csv"
    second_target = tmp_path / "second-customers.csv"
    _write_csv(first_target, "id,value\n1,first\n")
    _write_csv(second_target, "id,value\n1,second-target-is-larger\n")
    input_alias = tmp_path / "input.csv"
    try:
        input_alias.symlink_to(first_target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    create_calls: list[tuple[str, SourceCapability]] = []
    snapshots: list[ResolvedSource] = []
    default_registry = csv_adapter_module.DEFAULT_SOURCE_ADAPTER_REGISTRY

    class RetargetingAdapter:
        def __init__(self, delegate: SourceAdapter) -> None:
            self._delegate = delegate

        def resolve(
            self,
            spec: SourceSpec,
            context: OperationContext,
        ) -> ResolvedSource:
            resolved = self._delegate.resolve(spec, context)
            snapshots.append(resolved)
            if len(snapshots) == 1:
                input_alias.unlink()
                input_alias.symlink_to(second_target)
            return resolved

    class RetargetingRegistry:
        def create(self, kind: str, *, capability: SourceCapability):
            create_calls.append((kind, capability))
            return RetargetingAdapter(default_registry.create(kind, capability=capability))

    monkeypatch.setattr(
        csv_adapter_module,
        "DEFAULT_SOURCE_ADAPTER_REGISTRY",
        RetargetingRegistry(),
    )

    source = source_from_single_csv(str(input_alias))

    assert create_calls == [("csv", "query")]
    assert len(snapshots) == 1
    assert snapshots[0].canonical_locator == str(first_target.resolve())
    assert snapshots[0].fingerprint is not None
    assert snapshots[0].fingerprint.size_bytes == first_target.stat().st_size
    assert source.name == "first_orders"
    assert source.path == first_target.resolve()
