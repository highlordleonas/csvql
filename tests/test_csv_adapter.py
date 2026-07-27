from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from csvql.adapter_factory import ProviderActivationFacts
from csvql.exceptions import (
    EngineSessionTaintedError,
    SourceBindingError,
    SourceCleanupError,
    SourceResolutionError,
)
from csvql.operation import OperationContext, OperationToken
from csvql.source import (
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationStatus,
    SelectedSource,
    build_source_request,
)
from csvql.source_adapter import BindingContext, BindingState
from csvql.source_registry import build_builtin_descriptor_registry


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def _selected_csv(path: Path, *, alias: str = "orders") -> SelectedSource:
    descriptor = build_builtin_descriptor_registry().descriptor("csv")
    request = build_source_request(
        alias=alias,
        locator=path.name,
        anchor=path.parent,
        explicit_type="csv",
    )
    return SelectedSource(
        request=request,
        provider_key="csv",
        source_kind="csv",
        descriptor=descriptor,
        selection_reason="explicit_type",
        extension_evidence=None,
        options=(),
    )


def _adapter():
    from csvql.csv_adapter import _create_csv_adapter

    return _create_csv_adapter(
        activation_facts=ProviderActivationFacts(
            provider_key="csv",
            adapter_implementation_version="1",
            duckdb_version=duckdb.__version__,
        )
    )


class _EngineSession:
    session_id = "test-session"

    def __init__(self) -> None:
        self.connection = duckdb.connect(database=":memory:")
        self.has_active_execution = False
        self.is_tainted = False
        self._registrations: dict[object, object] = {}

    def assert_session_access(self) -> None:
        return

    def preflight_aliases(self, aliases: tuple[str, ...]) -> None:
        assert len(aliases) == len({alias.casefold() for alias in aliases})

    def register_relation(
        self,
        *,
        alias: str,
        register: object,
        unregister: object,
        operation: OperationContext,
    ) -> object:
        operation.checkpoint()
        register(self.connection)
        token = object()
        self._registrations[token] = unregister
        return token

    def unregister_relation(
        self,
        registration_token: object,
        *,
        operation: OperationContext,
    ) -> None:
        operation.checkpoint()
        unregister = self._registrations.pop(registration_token, None)
        if unregister is not None:
            unregister(self.connection)

    def close(self) -> None:
        self.connection.close()


def test_csv_resolution_records_identity_and_bounded_dialect_evidence(
    tmp_path: Path,
) -> None:
    """Dropping interpretation facts would make later results unexplainable."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "id;value\n1;alpha\n2;beta\n3;gamma\n",
        encoding="utf-8",
    )

    resolved = _adapter().resolve(_selected_csv(csv_path), _operation())

    facts = {key: value for key, value in resolved.provider_facts.items}
    assert resolved.provider_key == "csv"
    assert resolved.source_kind == "csv"
    assert resolved.alias == "orders"
    assert resolved.canonical_locator == str(csv_path.resolve())
    assert resolved.identity.strength is IdentityStrength.OBSERVATIONAL
    assert facts["size_bytes"] == csv_path.stat().st_size
    assert facts["modified_time_ns"] == csv_path.stat().st_mtime_ns
    assert facts["dialect_delimiter"] == ";"
    assert facts["dialect_header"] is True
    assert facts["dialect_encoding"] == "utf-8"


def test_csv_resolution_reports_missing_locator_without_exposing_canonical_path(
    tmp_path: Path,
) -> None:
    """Raw missing-path details must not cross the adapter boundary."""

    missing_path = tmp_path / "private" / "missing.csv"

    with pytest.raises(SourceResolutionError) as error:
        _adapter().resolve(_selected_csv(missing_path), _operation())

    assert error.value.code == "source_missing"
    assert str(missing_path) not in error.value.message


def test_csv_resolution_rejects_private_tui_result_spool_artifact(
    tmp_path: Path,
) -> None:
    """A private framed result is not a CSV source even with an explicit override."""

    workspace = tmp_path / f"localql-tui-v1-{'a' * 32}"
    workspace.mkdir()
    private_result = workspace / "query-1.result"
    private_result.write_bytes(b"private framed result")

    with pytest.raises(SourceResolutionError, match="private result storage") as error:
        _adapter().resolve(_selected_csv(private_result), _operation())

    assert error.value.code == "source_missing"


def test_csv_resolution_accepts_committed_derived_csv(
    tmp_path: Path,
) -> None:
    """Committed result CSVs are normal sources, not private spool artifacts."""

    derived = tmp_path / ".csvql" / "results" / "derived_ids.csv"
    derived.parent.mkdir(parents=True)
    derived.write_text("id\n1\n", encoding="utf-8")

    resolved = _adapter().resolve(_selected_csv(derived), _operation())

    assert resolved.canonical_locator == str(derived.resolve())


def test_csv_binding_is_session_scoped_revalidates_and_closes_idempotently(
    tmp_path: Path,
) -> None:
    """A binding must own only its relation and expose source changes before reuse."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id,value\n1,alpha\n", encoding="utf-8")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_csv(csv_path), operation)
    engine = _EngineSession()
    try:
        binding = adapter.bind(
            resolved,
            engine,
            BindingContext(operation=operation),
        )

        assert binding.state is BindingState.IDLE
        assert engine.connection.execute("SELECT * FROM orders").fetchall() == [(1, "alpha")]
        confirmed = binding.revalidate(
            IdentityRequirement(IdentityStrength.OBSERVATIONAL),
            operation,
        )
        assert confirmed.status is IdentityValidationStatus.CONFIRMED

        csv_path.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")
        changed = binding.revalidate(
            IdentityRequirement(IdentityStrength.OBSERVATIONAL),
            operation,
        )
        assert changed.status is IdentityValidationStatus.CHANGED

        binding.close(_operation())
        binding.close(_operation())
        assert binding.state is BindingState.CLOSED
        with pytest.raises(duckdb.Error):
            engine.connection.execute("SELECT * FROM orders")
        assert engine.connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        engine.close()


def test_csv_binding_rejects_cleanup_while_the_session_is_executing(
    tmp_path: Path,
) -> None:
    """Closing an in-use relation would violate the engine terminal barrier."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_csv(csv_path), operation)
    engine = _EngineSession()
    try:
        binding = adapter.bind(
            resolved,
            engine,
            BindingContext(operation=operation),
        )
        engine.has_active_execution = True

        with pytest.raises(SourceBindingError) as error:
            binding.close(_operation())

        assert error.value.code == "source_bind_failed"
        assert binding.state is BindingState.IN_USE
    finally:
        engine.has_active_execution = False
        binding.close(_operation())
        engine.close()


def test_csv_binding_rejects_cleanup_from_a_tainted_session(
    tmp_path: Path,
) -> None:
    """A tainted session must retain its registrations for owner-level shutdown."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_csv(csv_path), operation)
    engine = _EngineSession()
    binding = adapter.bind(
        resolved,
        engine,
        BindingContext(operation=operation),
    )
    try:
        engine.is_tainted = True

        with pytest.raises(EngineSessionTaintedError) as error:
            binding.close(_operation())

        assert error.value.code == "engine_session_tainted"
        assert binding.state is BindingState.IDLE
    finally:
        engine.is_tainted = False
        binding.close(_operation())
        engine.close()


def test_csv_binding_reports_unregister_failure_as_cleanup_failure(
    tmp_path: Path,
) -> None:
    """Provider cleanup defects must not be mislabeled as binding failures."""

    class CleanupFailingEngine(_EngineSession):
        def unregister_relation(
            self,
            registration_token: object,
            *,
            operation: OperationContext,
        ) -> None:
            del registration_token, operation
            raise duckdb.Error("private cleanup detail")

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_csv(csv_path), operation)
    engine = CleanupFailingEngine()
    binding = adapter.bind(
        resolved,
        engine,
        BindingContext(operation=operation),
    )
    try:
        with pytest.raises(SourceCleanupError) as error:
            binding.close(_operation())

        assert error.value.code == "source_cleanup_failed"
        assert "private cleanup detail" not in error.value.message
    finally:
        engine.close()


def test_csv_adapter_module_has_no_legacy_registry_or_capability_surface() -> None:
    """A second registry would let new providers bypass descriptor/factory validation."""

    import csvql.csv_adapter as module

    assert {
        "CSV_CAPABILITIES",
        "CSV_ADAPTER_DESCRIPTOR",
        "DEFAULT_SOURCE_ADAPTER_REGISTRY",
    }.isdisjoint(module.__dict__)
