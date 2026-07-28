from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

from csvql.adapter_factory import ProviderActivationFacts
from csvql.engine import CSVQLEngine
from csvql.exceptions import (
    SourceBindingError,
    SourceIdentityError,
    SourceResolutionError,
)
from csvql.operation import OperationCancelled, OperationContext, OperationToken
from csvql.source import (
    FrozenJSONArray,
    FrozenJSONObject,
    FrozenJSONValue,
    IdentityRequirement,
    IdentityStrength,
    IdentityValidationStatus,
    SelectedSource,
    SourcePreparationFailure,
    build_source_request,
)
from csvql.source_adapter import BindingContext, BindingState
from csvql.source_detection import SourceDetectionService
from csvql.source_identifiers import build_builtin_identifier_table
from csvql.source_registry import build_builtin_descriptor_registry
from csvql.source_runtime import prepare_source_requests


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def _write_parquet(
    path: Path,
    query: str,
    *,
    row_group_size: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        relation = connection.sql(query)
        if row_group_size is None:
            relation.write_parquet(str(path))
        else:
            relation.write_parquet(str(path), row_group_size=row_group_size)
    finally:
        connection.close()


def _selected_parquet(
    path: Path,
    *,
    alias: str = "warehouse",
    explicit: bool = True,
    options: tuple[tuple[str, object], ...] = (),
) -> SelectedSource:
    request = build_source_request(
        alias=alias,
        locator=path.name if path.parent != path else str(path),
        anchor=path.parent,
        explicit_type="parquet" if explicit else None,
        options=options,
    )
    detected = SourceDetectionService(
        build_builtin_descriptor_registry(),
        build_builtin_identifier_table(),
    ).detect(request)
    assert isinstance(detected, SelectedSource)
    return detected


def _adapter():
    from csvql.parquet_adapter import _create_parquet_adapter

    return _create_parquet_adapter(
        activation_facts=ProviderActivationFacts(
            provider_key="parquet",
            adapter_implementation_version="1",
            duckdb_version=duckdb.__version__,
        )
    )


def _thaw(value: FrozenJSONValue) -> object:
    if isinstance(value, FrozenJSONArray):
        return [_thaw(item) for item in value.values]
    if isinstance(value, FrozenJSONObject):
        return {key: _thaw(item) for key, item in value.items}
    return value


def _facts(resolved: object) -> dict[str, object]:
    return {
        key: _thaw(value)
        for key, value in resolved.provider_facts.items  # type: ignore[union-attr]
    }


class _EngineSession:
    session_id = "parquet-test-session"

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


def test_duckdb_characterization_accepts_an_ordered_parquet_path_list(
    tmp_path: Path,
) -> None:
    """The provider must bind exact members rather than delegating to a glob."""

    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    _write_parquet(first, "SELECT 1::INTEGER AS id")
    _write_parquet(second, "SELECT 2::INTEGER AS id")
    connection = duckdb.connect(database=":memory:")
    try:
        relation = connection.read_parquet(
            [str(second), str(first)],
            hive_partitioning=False,
            union_by_name=False,
        )

        assert relation.fetchall() == [(2,), (1,)]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("name", "explicit"),
    (
        ("orders.parquet", False),
        ("orders.PARQUET", False),
        ("orders.parq", False),
        ("orders", True),
    ),
)
def test_parquet_file_resolution_records_reproducible_observational_facts(
    tmp_path: Path,
    name: str,
    explicit: bool,
) -> None:
    """Extensionless explicit files and extension-selected files share one contract."""

    path = tmp_path / name
    _write_parquet(path, "SELECT 1::INTEGER AS id, 'alpha'::VARCHAR AS value")

    resolved = _adapter().resolve(
        _selected_parquet(path, explicit=explicit),
        _operation(),
    )
    facts = _facts(resolved)

    assert resolved.provider_key == "parquet"
    assert resolved.source_kind == "parquet"
    assert resolved.locator_shape == "file"
    assert resolved.canonical_locator == str(path.resolve())
    assert resolved.identity.strength is IdentityStrength.OBSERVATIONAL
    assert dict(resolved.semantic_options) == {
        "partitioning": "none",
        "union_by_name": False,
    }
    assert facts["member_count"] == 1
    assert facts["size_bytes"] == path.stat().st_size
    assert facts["modified_time_ns"] == path.stat().st_mtime_ns
    assert len(str(facts["manifest_digest"])) == 64


def test_parquet_resolution_rejects_corrupt_magic_or_footer(tmp_path: Path) -> None:
    """An explicit override must not turn arbitrary bytes into a Parquet source."""

    path = tmp_path / "corrupt"
    path.write_bytes(b"PAR1not-a-valid-footerPAR0")

    with pytest.raises(SourceResolutionError) as error:
        _adapter().resolve(_selected_parquet(path), _operation())

    assert error.value.code == "source.parquet_invalid"


def test_parquet_resolution_failure_produces_one_shared_actionable_diagnostic(
    tmp_path: Path,
) -> None:
    """Every output surface must receive the same provider-aware typed outcome."""

    path = tmp_path / "corrupt.parquet"
    path.write_bytes(b"PAR1not-a-valid-footerPAR0")
    request = build_source_request(
        alias="warehouse",
        locator=path.name,
        anchor=path.parent,
    )

    with CSVQLEngine() as engine:
        failure = prepare_source_requests(
            (request,),
            engine_session=engine,
            operation=engine.operation_context,
        )

    assert isinstance(failure, SourcePreparationFailure)
    diagnostic = failure.diagnostics[0]
    assert diagnostic.code.value == "source.parquet_invalid"
    assert diagnostic.stage.value == "resolution"
    assert diagnostic.safe_source_reference == "corrupt.parquet"
    assert diagnostic.required_action is not None
    assert diagnostic.required_action.kind == "correct_source"
    assert diagnostic.required_action.provider_keys == ("parquet",)
    assert str(tmp_path) not in diagnostic.message


def test_parquet_resolution_rejects_implicit_partitioning_modes(tmp_path: Path) -> None:
    """Automatic partition interpretation would make path spelling change schema."""

    path = tmp_path / "orders.parquet"
    _write_parquet(path, "SELECT 1::INTEGER AS id")

    with pytest.raises(SourceResolutionError) as error:
        _adapter().resolve(
            _selected_parquet(path, options=(("partitioning", "auto"),)),
            _operation(),
        )

    assert error.value.code == "source.partitioning_invalid"


def test_parquet_directory_resolution_freezes_exact_manifest_members(
    tmp_path: Path,
) -> None:
    """A directory must become an immutable ordered member list before binding."""

    root = tmp_path / "warehouse"
    _write_parquet(root / "z.parquet", "SELECT 2::INTEGER AS id")
    _write_parquet(root / "region=west" / "a.parq", "SELECT 1::INTEGER AS id")
    (root / "notes.txt").write_text("ignored", encoding="utf-8")

    resolved = _adapter().resolve(_selected_parquet(root), _operation())
    facts = _facts(resolved)

    assert resolved.locator_shape == "directory"
    assert resolved.selection_reason == "explicit_type"
    assert facts["member_count"] == 2
    assert facts["member_paths"] == ["region=west/a.parq", "z.parquet"]
    assert facts["excluded_regular_file_count"] == 1
    assert facts["excluded_suffix_summary"] == [[".txt", 1]]


def test_parquet_directory_identity_includes_the_manifest_root_state(
    tmp_path: Path,
) -> None:
    """Replacing a directory at the same path must create a new reproducibility identity."""

    root = tmp_path / "warehouse"
    original_member = root / "part.parquet"
    _write_parquet(original_member, "SELECT 1::INTEGER AS id")
    original_stat = original_member.stat()
    adapter = _adapter()
    first = adapter.resolve(_selected_parquet(root), _operation())

    moved_root = tmp_path / "warehouse-old"
    root.rename(moved_root)
    replacement_member = root / "part.parquet"
    replacement_member.parent.mkdir()
    replacement_member.write_bytes((moved_root / "part.parquet").read_bytes())
    os.utime(
        replacement_member,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    second = adapter.resolve(_selected_parquet(root), _operation())

    assert first.canonical_locator == second.canonical_locator
    assert _facts(first)["members"] == _facts(second)["members"]
    assert first.identity != second.identity


def test_parquet_adapter_rejects_a_directory_without_explicit_selection(
    tmp_path: Path,
) -> None:
    """The adapter must defend the no-untyped-directory invariant at its boundary."""

    root = tmp_path / "warehouse"
    _write_parquet(root / "part.parquet", "SELECT 1::INTEGER AS id")
    selected = _selected_parquet(root)
    invalid = SelectedSource(
        request=selected.request,
        provider_key=selected.provider_key,
        source_kind=selected.source_kind,
        descriptor=selected.descriptor,
        selection_reason="extension",
        extension_evidence=".parquet",
        options=selected.options,
    )

    with pytest.raises(SourceResolutionError) as error:
        _adapter().resolve(invalid, _operation())

    assert error.value.code == "source.parquet_invalid"


def test_parquet_file_binding_is_lazy_queryable_and_idempotently_released(
    tmp_path: Path,
) -> None:
    """A binding must expose rows while owning only its registered relation."""

    path = tmp_path / "orders.parquet"
    _write_parquet(
        path,
        "SELECT * FROM (VALUES (1, 'alpha'), (2, 'beta')) AS t(id, value)",
    )
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(path, alias="orders"), operation)
    engine = _EngineSession()
    try:
        binding = adapter.bind(resolved, engine, BindingContext(operation=operation))

        assert binding.state is BindingState.IDLE
        assert engine.connection.execute("SELECT * FROM orders ORDER BY id").fetchall() == [
            (1, "alpha"),
            (2, "beta"),
        ]
        binding.close(_operation())
        binding.close(_operation())
        assert binding.state is BindingState.CLOSED
        with pytest.raises(duckdb.Error):
            engine.connection.execute("SELECT * FROM orders")
        assert engine.connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        engine.close()


def test_parquet_binding_reads_empty_nested_nullable_and_multiple_row_group_files(
    tmp_path: Path,
) -> None:
    """Provider structure handling must cover Parquet shapes DuckDB already supports."""

    empty = tmp_path / "empty.parquet"
    nested = tmp_path / "nested.parquet"
    row_groups = tmp_path / "row-groups.parquet"
    _write_parquet(empty, "SELECT 1::INTEGER AS id WHERE false")
    _write_parquet(
        nested,
        """
        SELECT 1::INTEGER AS id, {'label': 'alpha'} AS metadata, [1, 2] AS items
        UNION ALL
        SELECT 2::INTEGER AS id, NULL AS metadata, NULL AS items
        """,
    )
    _write_parquet(
        row_groups,
        "SELECT range::INTEGER AS id FROM range(250000)",
        row_group_size=100_000,
    )
    adapter = _adapter()

    for path, expected_count in ((empty, 0), (nested, 2), (row_groups, 250_000)):
        resolved = adapter.resolve(_selected_parquet(path), _operation())
        engine = _EngineSession()
        try:
            binding = adapter.bind(
                resolved,
                engine,
                BindingContext(operation=_operation()),
            )
            assert engine.connection.execute("SELECT count(*) FROM warehouse").fetchone() == (
                expected_count,
            )
            if path == nested:
                assert engine.connection.execute(
                    "SELECT metadata, items FROM warehouse ORDER BY id"
                ).fetchall() == [({"label": "alpha"}, [1, 2]), (None, None)]
            binding.close(_operation())
        finally:
            engine.close()

    metadata = duckdb.sql(
        "SELECT num_row_groups FROM parquet_file_metadata(?)",
        params=[str(row_groups)],
    ).fetchone()
    assert metadata is not None
    assert metadata[0] > 1


def test_parquet_partition_interpretation_is_explicit(tmp_path: Path) -> None:
    """Hive-looking paths must add columns only when the request says hive."""

    root = tmp_path / "warehouse"
    _write_parquet(root / "region=west" / "part.parquet", "SELECT 1::INTEGER AS id")
    adapter = _adapter()

    for partitioning, expected_columns in (
        ("none", ["id"]),
        ("hive", ["id", "region"]),
    ):
        selected = _selected_parquet(
            root,
            alias=f"warehouse_{partitioning}",
            options=(("partitioning", partitioning),),
        )
        resolved = adapter.resolve(selected, _operation())
        engine = _EngineSession()
        try:
            binding = adapter.bind(
                resolved,
                engine,
                BindingContext(operation=_operation()),
            )
            columns = [
                row[0]
                for row in engine.connection.execute(
                    f"DESCRIBE SELECT * FROM {resolved.alias}"
                ).fetchall()
            ]
            assert columns == expected_columns
            binding.close(_operation())
        finally:
            engine.close()


def test_parquet_schema_union_requires_explicit_intent(tmp_path: Path) -> None:
    """Mismatched member schemas must fail unless union_by_name is requested."""

    root = tmp_path / "warehouse"
    _write_parquet(root / "a.parquet", "SELECT 1::INTEGER AS id")
    _write_parquet(root / "b.parquet", "SELECT 'beta'::VARCHAR AS name")
    adapter = _adapter()

    strict = adapter.resolve(_selected_parquet(root), _operation())
    strict_engine = _EngineSession()
    try:
        with pytest.raises(SourceBindingError) as error:
            adapter.bind(
                strict,
                strict_engine,
                BindingContext(operation=_operation()),
            )
        assert error.value.code == "source.parquet_schema_mismatch"
        assert strict_engine._registrations == {}
    finally:
        strict_engine.close()

    unioned = adapter.resolve(
        _selected_parquet(root, options=(("union_by_name", True),)),
        _operation(),
    )
    union_engine = _EngineSession()
    try:
        binding = adapter.bind(
            unioned,
            union_engine,
            BindingContext(operation=_operation()),
        )
        assert union_engine.connection.execute(
            "SELECT id, name FROM warehouse ORDER BY coalesce(id, 99)"
        ).fetchall() == [(1, None), (None, "beta")]
        binding.close(_operation())
    finally:
        union_engine.close()


def test_parquet_schema_mismatch_preserves_typed_failure_and_cleanup(
    tmp_path: Path,
) -> None:
    """Coordinator cleanup must not replace the provider's primary schema failure."""

    root = tmp_path / "warehouse"
    _write_parquet(root / "a.parquet", "SELECT 1::INTEGER AS id")
    _write_parquet(root / "b.parquet", "SELECT 'beta'::VARCHAR AS name")
    request = build_source_request(
        alias="warehouse",
        locator=root.name,
        anchor=root.parent,
        explicit_type="parquet",
    )

    with CSVQLEngine() as engine:
        failure = prepare_source_requests(
            (request,),
            engine_session=engine,
            operation=engine.operation_context,
        )

        assert isinstance(failure, SourcePreparationFailure)
        assert failure.diagnostics[0].code.value == "source.parquet_schema_mismatch"
        assert failure.diagnostics[0].stage.value == "binding"
        assert failure.cleanup_failures == ()
        assert engine.registered_aliases == ()


def test_parquet_binding_revalidates_observational_strong_and_exact_identity(
    tmp_path: Path,
) -> None:
    """Every requested strength must either return matching evidence or fail explicitly."""

    path = tmp_path / "orders.parquet"
    _write_parquet(path, "SELECT 1::INTEGER AS id")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(path), operation)
    engine = _EngineSession()
    try:
        binding = adapter.bind(resolved, engine, BindingContext(operation=operation))

        observational = binding.revalidate(
            IdentityRequirement(IdentityStrength.OBSERVATIONAL),
            operation,
        )
        strong = binding.revalidate(
            IdentityRequirement(IdentityStrength.STRONG),
            operation,
        )
        exact = binding.revalidate(
            IdentityRequirement(IdentityStrength.EXACT),
            operation,
        )

        assert observational.status is IdentityValidationStatus.CONFIRMED
        assert observational.confirmed_strength is IdentityStrength.OBSERVATIONAL
        assert strong.status is IdentityValidationStatus.CONFIRMED
        assert strong.confirmed_strength is IdentityStrength.STRONG
        assert len(strong.evidence_digest or "") == 64
        assert exact.status is IdentityValidationStatus.CONFIRMED
        assert exact.confirmed_strength is IdentityStrength.EXACT
        assert len(exact.evidence_digest or "") == 64
        binding.close(_operation())
    finally:
        engine.close()


def test_parquet_strong_identity_reports_unavailable_without_downgrading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing stable metadata support must not be relabeled observational success."""

    import csvql.parquet_adapter as parquet_adapter

    path = tmp_path / "orders.parquet"
    _write_parquet(path, "SELECT 1::INTEGER AS id")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(path), operation)
    engine = _EngineSession()
    try:
        binding = adapter.bind(resolved, engine, BindingContext(operation=operation))

        def unavailable(*_args: object, **_kwargs: object) -> str:
            raise parquet_adapter._IdentityStrengthUnavailable

        monkeypatch.setattr(parquet_adapter, "_strong_identity_digest", unavailable)
        outcome = binding.revalidate(
            IdentityRequirement(IdentityStrength.STRONG),
            operation,
        )

        assert outcome.status is IdentityValidationStatus.UNAVAILABLE
        assert outcome.confirmed_strength is None
        assert outcome.evidence_digest is None
        assert outcome.diagnostic is not None
        assert outcome.diagnostic.code.value == "source.identity_strength_unavailable"
        binding.close(_operation())
    finally:
        engine.close()


def test_parquet_strong_identity_disables_duckdb_extension_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata validation must preserve the platform's no-silent-install guarantee."""

    import csvql.parquet_adapter as parquet_adapter

    path = tmp_path / "orders.parquet"
    _write_parquet(path, "SELECT 1::INTEGER AS id")
    operation = _operation()
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(path), operation)
    engine = _EngineSession()
    real_connect = duckdb.connect
    observed_configs: list[object] = []

    def recording_connect(*args: object, **kwargs: object):
        observed_configs.append(kwargs.get("config"))
        return real_connect(*args, **kwargs)

    try:
        binding = adapter.bind(resolved, engine, BindingContext(operation=operation))
        monkeypatch.setattr(parquet_adapter.duckdb, "connect", recording_connect)

        outcome = binding.revalidate(
            IdentityRequirement(IdentityStrength.STRONG),
            operation,
        )

        assert outcome.status is IdentityValidationStatus.CONFIRMED
        assert observed_configs == [
            {
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
            }
        ]
        binding.close(_operation())
    finally:
        engine.close()


def test_parquet_exact_identity_checks_cancellation_between_bounded_chunks(
    tmp_path: Path,
) -> None:
    """Exact hashing must remain cancellable rather than monopolizing preparation."""

    class CancelAfterCheckpoints(OperationToken):
        def __init__(self, allowed: int) -> None:
            super().__init__()
            self._allowed = allowed
            self._checks = 0

        def raise_if_cancelled(self) -> None:
            self._checks += 1
            if self._checks > self._allowed:
                self.cancel()
            super().raise_if_cancelled()

    path = tmp_path / "orders.parquet"
    _write_parquet(path, "SELECT range::INTEGER AS id FROM range(500000)")
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(path), _operation())
    engine = _EngineSession()
    try:
        binding = adapter.bind(
            resolved,
            engine,
            BindingContext(operation=_operation()),
        )

        with pytest.raises(OperationCancelled):
            binding.revalidate(
                IdentityRequirement(IdentityStrength.EXACT),
                OperationContext(CancelAfterCheckpoints(3)),
            )
        binding.close(_operation())
    finally:
        engine.close()


@pytest.mark.parametrize("change", ("remove", "rename_case", "modify"))
def test_parquet_dataset_revalidation_detects_member_removal_rename_and_change(
    tmp_path: Path,
    change: str,
) -> None:
    """Every included-member observation must remain fixed until resubmission."""

    root = tmp_path / "warehouse"
    member = root / "part.parquet"
    _write_parquet(member, "SELECT 1::INTEGER AS id")
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(root), _operation())
    if change == "remove":
        member.unlink()
    elif change == "rename_case":
        member.rename(root / "PART.parquet")
    else:
        current = member.stat()
        os.utime(
            member,
            ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000),
        )
    engine = _EngineSession()
    try:
        with pytest.raises(SourceIdentityError) as error:
            adapter.bind(
                resolved,
                engine,
                BindingContext(operation=_operation()),
            )

        assert error.value.code == "source.dataset_changed"
        assert engine._registrations == {}
    finally:
        engine.close()


def test_parquet_semantic_options_are_part_of_reproducibility_identity(
    tmp_path: Path,
) -> None:
    """Changing partition or union semantics must produce a different identity."""

    path = tmp_path / "orders.parquet"
    _write_parquet(path, "SELECT 1::INTEGER AS id")
    adapter = _adapter()

    default = adapter.resolve(_selected_parquet(path), _operation())
    hive = adapter.resolve(
        _selected_parquet(path, options=(("partitioning", "hive"),)),
        _operation(),
    )
    unioned = adapter.resolve(
        _selected_parquet(path, options=(("union_by_name", True),)),
        _operation(),
    )

    assert len({default.identity.digest, hive.identity.digest, unioned.identity.digest}) == 3


def test_parquet_dataset_change_is_rejected_before_relation_construction(
    tmp_path: Path,
) -> None:
    """Binding must never silently swap a newly discovered member set into a snapshot."""

    root = tmp_path / "warehouse"
    _write_parquet(root / "a.parquet", "SELECT 1::INTEGER AS id")
    adapter = _adapter()
    resolved = adapter.resolve(_selected_parquet(root), _operation())
    _write_parquet(root / "b.parquet", "SELECT 2::INTEGER AS id")
    engine = _EngineSession()
    try:
        with pytest.raises(SourceIdentityError) as error:
            adapter.bind(
                resolved,
                engine,
                BindingContext(operation=_operation()),
            )

        assert error.value.code == "source.dataset_changed"
        assert engine._registrations == {}
    finally:
        engine.close()
