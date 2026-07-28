from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import duckdb
import pytest

from csvql.engine import CSVQLEngine
from csvql.operation import OperationContext, OperationToken
from csvql.source import (
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationStatus,
    PreparedSources,
    SelectedSource,
    build_source_request,
)
from csvql.source_coordinator import PreparationContext
from csvql.source_runtime import (
    build_default_source_components,
    default_activation_context,
)


@dataclass(frozen=True, slots=True)
class ProviderCase:
    provider_key: str
    filename: str


PROVIDER_CASES = (
    ProviderCase("csv", "orders.csv"),
    ProviderCase("parquet", "orders.parquet"),
)


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def _write_fixture(case: ProviderCase, path: Path) -> None:
    if case.provider_key == "csv":
        path.write_text(
            "id,value\n1,alpha\n2,beta\n3,beta\n",
            encoding="utf-8",
        )
        return
    connection = duckdb.connect(database=":memory:")
    try:
        connection.sql(
            """
            SELECT *
            FROM (VALUES (1, 'alpha'), (2, 'beta'), (3, 'beta'))
                AS rows(id, value)
            """
        ).write_parquet(str(path))
    finally:
        connection.close()


def _prepare(case: ProviderCase, tmp_path: Path) -> tuple[object, CSVQLEngine, PreparedSources]:
    path = tmp_path / case.filename
    _write_fixture(case, path)
    request = build_source_request(
        alias="orders",
        locator=path.name,
        anchor=path.parent,
    )
    operation = _operation()
    components = build_default_source_components()
    detected = components.detection.detect(request, operation=operation)
    assert isinstance(detected, SelectedSource)
    adapter = components.factory.activate(detected, default_activation_context())
    resolved = adapter.resolve(detected, operation)
    engine = CSVQLEngine(operation=operation)
    prepared = components.coordinator.prepare(
        (request,),
        engine,
        PreparationContext(
            operation=operation,
            activation=default_activation_context(),
        ),
        resolved_snapshots=(resolved,),
    )
    assert isinstance(prepared, PreparedSources)
    return components, engine, prepared


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.provider_key)
def test_provider_contract_is_queryable_reusable_immutable_and_idempotently_released(
    case: ProviderCase,
    tmp_path: Path,
) -> None:
    """Provider drift must not change engine behavior or lifecycle ownership."""

    components, engine, prepared = _prepare(case, tmp_path)
    try:
        resolved = prepared.resolved_sources[0]
        with pytest.raises(FrozenInstanceError):
            resolved.alias = "changed"  # type: ignore[misc]

        first = engine.query(
            """
            SELECT value, count(*) AS row_count
            FROM orders
            WHERE id >= 2
            GROUP BY value
            ORDER BY value
            """
        )
        second = engine.query("SELECT id FROM orders ORDER BY id DESC LIMIT 2")
        identity = components.coordinator.revalidate(
            prepared,
            IdentityRequirement(IdentityStrength.OBSERVATIONAL),
        )

        assert first.rows == (("beta", 2),)
        assert second.rows == ((3,), (2,))
        assert identity.results[0].status is IdentityValidationStatus.CONFIRMED
        assert components.coordinator.release(prepared).succeeded
        assert components.coordinator.release(prepared).already_closed is True
        assert engine.registered_aliases == ()
        assert engine.query("SELECT 1").rows == ((1,),)
    finally:
        engine.close()


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.provider_key)
def test_provider_contract_rejects_cross_thread_binding_use(
    case: ProviderCase,
    tmp_path: Path,
) -> None:
    """A binding must remain owned by its creating engine thread."""

    components, engine, prepared = _prepare(case, tmp_path)
    failures: list[BaseException] = []

    def revalidate_from_other_thread() -> None:
        try:
            prepared.bindings[0].revalidate(
                IdentityRequirement(IdentityStrength.OBSERVATIONAL),
                _operation(),
            )
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=revalidate_from_other_thread)
    thread.start()
    thread.join(timeout=2)
    try:
        assert len(failures) == 1
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.provider_key)
def test_provider_contract_defers_cleanup_until_execution_is_terminal(
    case: ProviderCase,
    tmp_path: Path,
) -> None:
    """Cleanup must not unregister a relation while a result stream owns it."""

    components, engine, prepared = _prepare(case, tmp_path)
    stream = engine.stream("SELECT * FROM orders")
    try:
        blocked = components.coordinator.release(prepared)
        assert blocked.succeeded is False
        assert prepared.is_closed is False
    finally:
        stream.close()
    try:
        assert components.coordinator.release(prepared).succeeded
    finally:
        engine.close()
