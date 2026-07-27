from __future__ import annotations

import importlib
import io
import zipfile
from pathlib import Path

import pytest

from csvql.operation import OperationCancelled, OperationContext, OperationToken


def _identifiers_module():
    return importlib.import_module("csvql.source_identifiers")


def test_parquet_identifier_reads_only_leading_and_trailing_magic(tmp_path: Path) -> None:
    module = _identifiers_module()
    path = tmp_path / "warehouse"
    path.write_bytes(b"PAR1payloadPAR1")
    budget = module.AggregateIdentificationBudget()

    evidence = module.ParquetSourceIdentifier().identify(
        path,
        budget.for_identifier("parquet"),
    )

    assert evidence.status is module.IdentificationStatus.RECOGNIZED
    assert evidence.evidence_kind == "parquet_magic"
    assert evidence.bytes_read == 8
    assert budget.bytes_read == 8


def test_parquet_identifier_rejects_a_single_magic_value_as_too_short(
    tmp_path: Path,
) -> None:
    module = _identifiers_module()
    path = tmp_path / "short"
    path.write_bytes(b"PAR1")

    evidence = module.ParquetSourceIdentifier().identify(
        path,
        module.AggregateIdentificationBudget().for_identifier("parquet"),
    )

    assert evidence.status is module.IdentificationStatus.NOT_RECOGNIZED
    assert evidence.stable_detail == "file_too_short"


def test_xlsx_identifier_uses_bounded_central_directory_metadata(tmp_path: Path) -> None:
    module = _identifiers_module()
    path = tmp_path / "workbook"
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr("[Content_Types].xml", "<Types/>")
        workbook.writestr("xl/workbook.xml", "<workbook/>")
        workbook.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    budget = module.AggregateIdentificationBudget()

    evidence = module.ExcelSourceIdentifier().identify(
        path,
        budget.for_identifier("excel"),
    )

    assert evidence.status is module.IdentificationStatus.RECOGNIZED
    assert evidence.evidence_kind == "xlsx_container"
    assert evidence.container_entries == 3
    assert 0 < evidence.bytes_read <= 1024 * 1024
    assert budget.container_entries == 3


@pytest.mark.parametrize(
    ("provider_key", "content", "expected_kind"),
    [
        ("json", b'[{"id": 1}, {"id": 2}]', "json_document"),
        ("ndjson", b'{"id": 1}\n{"id": 2}\n', "ndjson_records"),
        ("csv", b"id,value\n1,alpha\n2,beta\n", "csv_record_shape"),
    ],
)
def test_text_identifiers_return_evidence_without_selecting(
    tmp_path: Path,
    provider_key: str,
    content: bytes,
    expected_kind: str,
) -> None:
    module = _identifiers_module()
    path = tmp_path / "source"
    path.write_bytes(content)
    identifier = module.build_builtin_identifier_table().identifier(provider_key)

    evidence = identifier.identify(
        path,
        module.AggregateIdentificationBudget().for_identifier(provider_key),
    )

    assert evidence.provider_key == provider_key
    assert evidence.status is module.IdentificationStatus.RECOGNIZED
    assert evidence.evidence_kind == expected_kind
    assert not hasattr(evidence, "selected_provider")


def test_identifier_budget_is_aggregate_and_cannot_be_reset_per_provider(
    tmp_path: Path,
) -> None:
    module = _identifiers_module()
    path = tmp_path / "source"
    path.write_bytes(b"0123456789")
    limits = module.IdentificationLimits(
        per_identifier_bytes=6,
        aggregate_bytes=8,
        container_entries=4,
    )
    budget = module.AggregateIdentificationBudget(limits)

    with budget.for_identifier("first").open(path) as reader:
        assert reader.read(5) == b"01234"
    with budget.for_identifier("second").open(path) as reader:
        assert reader.read(3) == b"012"
        with pytest.raises(module.IdentificationBudgetExceeded):
            reader.read(1)
    with budget.for_identifier("first").open(path) as reader:
        with pytest.raises(module.IdentificationBudgetExceeded):
            reader.read(2)

    assert budget.bytes_read == 8
    assert budget.bytes_read_for("first") == 5
    assert budget.bytes_read_for("second") == 3


@pytest.mark.parametrize("failure_point", ["success", "read_failure", "budget"])
def test_budgeted_reader_closes_handle_on_every_exit(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    module = _identifiers_module()

    class TrackingBytesIO(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            if failure_point == "read_failure":
                raise OSError("private read detail")
            return super().read(size)

    handle = TrackingBytesIO(b"0123456789")
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: handle)
    limits = module.IdentificationLimits(
        per_identifier_bytes=4,
        aggregate_bytes=4,
        container_entries=1,
    )
    budget = module.AggregateIdentificationBudget(limits)

    if failure_point == "success":
        with budget.for_identifier("test").open(Path("ignored")) as reader:
            assert reader.read(4) == b"0123"
    elif failure_point == "read_failure":
        with pytest.raises(OSError):
            with budget.for_identifier("test").open(Path("ignored")) as reader:
                reader.read(1)
    else:
        with pytest.raises(module.IdentificationBudgetExceeded):
            with budget.for_identifier("test").open(Path("ignored")) as reader:
                reader.read(5)

    assert handle.closed


def test_identifiers_reject_directories_without_enumerating_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _identifiers_module()

    def unexpected_iteration(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Identifiers must not enumerate directories.")

    monkeypatch.setattr(Path, "iterdir", unexpected_iteration)
    evidence = module.CSVSourceIdentifier().identify(
        tmp_path,
        module.AggregateIdentificationBudget().for_identifier("csv"),
    )

    assert evidence.status is module.IdentificationStatus.INVALID_LOCATOR
    assert evidence.bytes_read == 0


def test_cancellation_propagates_instead_of_becoming_format_evidence(
    tmp_path: Path,
) -> None:
    module = _identifiers_module()
    path = tmp_path / "source"
    path.write_bytes(b"PAR1payloadPAR1")
    token = OperationToken()
    token.cancel()
    budget = module.AggregateIdentificationBudget(operation=OperationContext(token=token))

    with pytest.raises(OperationCancelled):
        module.ParquetSourceIdentifier().identify(
            path,
            budget.for_identifier("parquet"),
        )


def test_builtin_identifier_table_is_immutable_and_canonically_ordered() -> None:
    module = _identifiers_module()
    table = module.build_builtin_identifier_table()

    assert table.provider_keys == ("csv", "excel", "json", "ndjson", "parquet")
    with pytest.raises(TypeError):
        table.identifiers["future"] = module.CSVSourceIdentifier()


def test_identifier_table_rejects_missing_behavior_as_composition_failure() -> None:
    module = _identifiers_module()
    from csvql.exceptions import ConfigurationFailure

    class InvalidIdentifier:
        provider_key = "future"
        identifier_key = "future.magic"

    with pytest.raises(ConfigurationFailure) as captured:
        module.IdentifierTable((InvalidIdentifier(),))

    assert tuple(finding.code for finding in captured.value.findings) == (
        "invalid_identifier_contract",
    )
