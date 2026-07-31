"""Dependency-free XLSX workbook metadata contract tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import csvql.excel_workbook as workbook_module
from csvql.excel_workbook import (
    ExcelWorkbookError,
    inspect_excel_workbook,
    normalize_excel_range,
)
from csvql.operation import OperationContext, OperationToken

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _operation() -> OperationContext:
    return OperationContext(OperationToken())


def _write_workbook(
    path: Path,
    *,
    sheets: tuple[tuple[str, str | None], ...] = (("Orders", "A1:B3"),),
    workbook_prefix: str = "",
    worksheet_prefix: str = "",
    relationship_target: str = "worksheets/sheet1.xml",
    relationship_mode: str | None = None,
    relationship_types: tuple[str, ...] | None = None,
    extras: tuple[tuple[str, bytes], ...] = (),
    compression: int = zipfile.ZIP_STORED,
) -> None:
    sheet_elements = "".join(
        (f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
        for index, (name, _dimension) in enumerate(sheets, start=1)
    )
    workbook_xml = (
        f'<workbook xmlns="{_SPREADSHEET_NS}" xmlns:r="{_DOCUMENT_REL_NS}">'
        f"{workbook_prefix}<sheets>{sheet_elements}</sheets></workbook>"
    ).encode()
    relationship_elements = []
    worksheet_entries: list[tuple[str, bytes]] = []
    for index, (_name, dimension) in enumerate(sheets, start=1):
        target = relationship_target if index == 1 else f"worksheets/sheet{index}.xml"
        mode = "" if relationship_mode is None else f' TargetMode="{relationship_mode}"'
        relationship_type = (
            f"{_DOCUMENT_REL_NS}/worksheet"
            if relationship_types is None
            else relationship_types[index - 1]
        )
        relationship_elements.append(
            f'<Relationship Id="rId{index}" Type="{relationship_type}" Target="{target}"{mode}/>'
        )
        dimension_element = "" if dimension is None else f'<dimension ref="{dimension}"/>'
        worksheet_entries.append(
            (
                f"xl/worksheets/sheet{index}.xml",
                (
                    f'<worksheet xmlns="{_SPREADSHEET_NS}">'
                    f"{worksheet_prefix}{dimension_element}<sheetData/></worksheet>"
                ).encode(),
            )
        )
    relationships_xml = (
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">{"".join(relationship_elements)}</Relationships>'
    ).encode()
    content_types_xml = (
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    )
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
        for name, content in worksheet_entries:
            archive.writestr(name, content)
        for name, content in extras:
            archive.writestr(name, content)


def test_resolves_default_sheet_and_dimension_in_declared_order(tmp_path: Path) -> None:
    path = tmp_path / "orders.xlsx"
    _write_workbook(
        path,
        sheets=(
            ("First", "A1:C4"),
            ("Second", "D5:E6"),
        ),
    )

    selection = inspect_excel_workbook(
        path,
        requested_sheet=None,
        requested_range=None,
        operation=_operation(),
    )

    assert selection.selected_sheet.name == "First"
    assert selection.selected_sheet.index == 0
    assert selection.selected_sheet.worksheet_part == "xl/worksheets/sheet1.xml"
    assert selection.resolved_range == "A1:C4"
    assert selection.sheet_source == "workbook_order"
    assert selection.range_source == "worksheet_dimension"
    assert selection.sheet_count == 2
    assert selection.metadata_bytes_read > 0


def test_exact_unicode_sheet_and_quoted_range_are_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "quoted.xlsx"
    sheet_name = "O'Brien Δ"
    _write_workbook(path, sheets=((sheet_name, "A1:B2"),))

    selection = inspect_excel_workbook(
        path,
        requested_sheet=sheet_name,
        requested_range="'O''Brien Δ'!$B$2:$D$5",
        operation=_operation(),
    )

    assert selection.selected_sheet.name == sheet_name
    assert selection.resolved_range == "B2:D5"
    assert selection.sheet_source == "explicit_option"
    assert selection.range_source == "explicit_option"


def test_missing_dimension_requires_range_but_explicit_range_avoids_guessing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "no-dimension.xlsx"
    _write_workbook(path, sheets=(("Orders", None),))

    with pytest.raises(ExcelWorkbookError) as captured:
        inspect_excel_workbook(
            path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert captured.value.code == "source.excel_range_required"
    selection = inspect_excel_workbook(
        path,
        requested_sheet=None,
        requested_range="A1:B10",
        operation=_operation(),
    )
    assert selection.resolved_range == "A1:B10"


def test_dimension_search_never_expands_past_the_metadata_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "late-dimension.xlsx"
    _write_workbook(
        path,
        worksheet_prefix=" " * workbook_module.MAX_METADATA_ENTRY_BYTES,
    )

    with pytest.raises(ExcelWorkbookError) as captured:
        inspect_excel_workbook(
            path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert captured.value.code == "source.excel_range_required"
    selection = inspect_excel_workbook(
        path,
        requested_sheet=None,
        requested_range="A1:B3",
        operation=_operation(),
    )
    assert selection.resolved_range == "A1:B3"


@pytest.mark.parametrize(
    "range_value",
    (
        "Orders!A1:B2",
        "'Other'!A1:B2",
        "A:A",
        "1:10",
        "A1:B2,C1:D2",
        "=A1:B2",
        "B2:A1",
        "XFE1:XFE2",
        " A1:B2",
        "A1:B2 ",
        f"A{'9' * 10_000}:B2",
    ),
)
def test_invalid_ranges_fail_without_correction(range_value: str) -> None:
    with pytest.raises(ExcelWorkbookError) as captured:
        normalize_excel_range(range_value, selected_sheet="Orders")

    assert captured.value.code == "source.excel_range_invalid"


def test_range_cell_bound_is_enforced() -> None:
    with pytest.raises(ExcelWorkbookError) as captured:
        normalize_excel_range(
            "A1:XFD1048576",
            selected_sheet="Orders",
        )

    assert captured.value.code == "source.excel_metadata_limit"


def test_sheet_matching_is_exact_and_casefold_collisions_are_ambiguous(
    tmp_path: Path,
) -> None:
    exact_path = tmp_path / "exact.xlsx"
    _write_workbook(exact_path, sheets=(("Orders", "A1"),))

    with pytest.raises(ExcelWorkbookError) as missing:
        inspect_excel_workbook(
            exact_path,
            requested_sheet="orders",
            requested_range=None,
            operation=_operation(),
        )

    assert missing.value.code == "source.excel_sheet_missing"

    ambiguous_path = tmp_path / "ambiguous.xlsx"
    _write_workbook(
        ambiguous_path,
        sheets=(("Orders", "A1"), ("orders", "A1")),
    )
    with pytest.raises(ExcelWorkbookError) as ambiguous:
        inspect_excel_workbook(
            ambiguous_path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert ambiguous.value.code == "source.excel_sheet_ambiguous"

    normalized_path = tmp_path / "normalized-ambiguous.xlsx"
    _write_workbook(
        normalized_path,
        sheets=(("Café", "A1"), ("Cafe\u0301", "A1")),
    )
    with pytest.raises(ExcelWorkbookError) as normalized:
        inspect_excel_workbook(
            normalized_path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )
    assert normalized.value.code == "source.excel_sheet_ambiguous"


def test_only_the_selected_sheet_relationship_must_be_a_worksheet(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mixed-sheet-types.xlsx"
    _write_workbook(
        path,
        sheets=(("Orders", "A1:B2"), ("Chart", "A1")),
        relationship_types=(
            f"{_DOCUMENT_REL_NS}/worksheet",
            f"{_DOCUMENT_REL_NS}/chartsheet",
        ),
    )

    selected = inspect_excel_workbook(
        path,
        requested_sheet=None,
        requested_range=None,
        operation=_operation(),
    )
    assert selected.selected_sheet.name == "Orders"

    with pytest.raises(ExcelWorkbookError) as chart:
        inspect_excel_workbook(
            path,
            requested_sheet="Chart",
            requested_range="A1",
            operation=_operation(),
        )
    assert chart.value.code == "source.excel_invalid"


def test_custom_namespace_elements_cannot_spoof_workbook_sheets(
    tmp_path: Path,
) -> None:
    path = tmp_path / "namespace-spoof.xlsx"
    _write_workbook(
        path,
        workbook_prefix=('<evil:sheet xmlns:evil="urn:localql:test" name="Spoofed" r:id="rId1"/>'),
    )

    selection = inspect_excel_workbook(
        path,
        requested_sheet=None,
        requested_range=None,
        operation=_operation(),
    )

    assert selection.selected_sheet.name == "Orders"


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    (
        ("traversal", "source.excel_invalid"),
        ("leading_junk", "source.excel_invalid"),
        ("canonical_duplicate", "source.excel_invalid"),
        ("dtd", "source.excel_invalid"),
        ("external_relationship", "source.excel_invalid"),
        ("parent_relationship", "source.excel_invalid"),
    ),
)
def test_hostile_package_metadata_is_rejected(
    tmp_path: Path,
    mutator: str,
    expected_code: str,
) -> None:
    path = tmp_path / f"{mutator}.xlsx"
    extras: tuple[tuple[str, bytes], ...] = ()
    prefix = ""
    relationship_target = "worksheets/sheet1.xml"
    relationship_mode = None
    if mutator == "traversal":
        extras = (("../outside.xml", b"<outside/>"),)
    elif mutator == "canonical_duplicate":
        extras = (("xl/./workbook.xml", b"<workbook/>"),)
    elif mutator == "dtd":
        prefix = '<!DOCTYPE workbook [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    elif mutator == "external_relationship":
        relationship_mode = "External"
    elif mutator == "parent_relationship":
        relationship_target = "../worksheets/sheet1.xml"
    _write_workbook(
        path,
        workbook_prefix=prefix,
        relationship_target=relationship_target,
        relationship_mode=relationship_mode,
        extras=extras,
    )
    if mutator == "leading_junk":
        path.write_bytes(b"junk" + path.read_bytes())

    with pytest.raises(ExcelWorkbookError) as captured:
        inspect_excel_workbook(
            path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert captured.value.code == expected_code


def test_declared_metadata_limits_are_enforced_before_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert workbook_module.MAX_ZIP_ENTRIES == 4_096
    assert workbook_module.MAX_METADATA_ENTRY_BYTES == 1024 * 1024
    assert workbook_module.MAX_METADATA_TOTAL_BYTES == 4 * 1024 * 1024
    assert workbook_module.MAX_METADATA_COMPRESSION_RATIO == 100
    assert workbook_module.MAX_WORKSHEETS == 1_024
    assert workbook_module.MAX_RANGE_CELLS == 10_000_000

    path = tmp_path / "bounded.xlsx"
    _write_workbook(path)
    monkeypatch.setattr(workbook_module, "MAX_ZIP_ENTRIES", 3)

    with pytest.raises(ExcelWorkbookError) as captured:
        inspect_excel_workbook(
            path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert captured.value.code == "source.excel_metadata_limit"


def test_excessive_declared_metadata_compression_ratio_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "compressed.xlsx"
    _write_workbook(
        path,
        workbook_prefix=" " * 100_000,
        compression=zipfile.ZIP_DEFLATED,
    )

    with pytest.raises(ExcelWorkbookError) as captured:
        inspect_excel_workbook(
            path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert captured.value.code == "source.excel_metadata_limit"


def test_worksheet_prefix_compression_ratio_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "compressed-worksheet.xlsx"
    _write_workbook(
        path,
        worksheet_prefix=" " * 100_000,
        compression=zipfile.ZIP_DEFLATED,
    )

    with pytest.raises(ExcelWorkbookError) as captured:
        inspect_excel_workbook(
            path,
            requested_sheet=None,
            requested_range=None,
            operation=_operation(),
        )

    assert captured.value.code == "source.excel_metadata_limit"
