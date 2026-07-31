"""Data-only source request and diagnostic vectors shared by surface tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSurfaceVector:
    """One transport-independent source intent and expected detection outcome."""

    name: str
    locator_name: str
    fixture_kind: str
    explicit_type: str | None
    option_mappings: tuple[str, ...] = ()
    expected_variant: str = "selected"
    expected_provider: str | None = None
    expected_code: str | None = None
    expected_action: str | None = None


SEMANTIC_REQUEST_VECTORS = (
    SourceSurfaceVector(
        name="explicit_csv_over_json_extension",
        locator_name="orders.json",
        fixture_kind="csv",
        explicit_type="csv",
        expected_provider="csv",
    ),
    SourceSurfaceVector(
        name="explicit_parquet",
        locator_name="orders.parquet",
        fixture_kind="parquet",
        explicit_type="parquet",
        option_mappings=("union_by_name=true",),
        expected_provider="parquet",
    ),
    SourceSurfaceVector(
        name="explicit_json_with_typed_option",
        locator_name="records.json",
        fixture_kind="json",
        explicit_type="json",
        option_mappings=("sample_size=10",),
        expected_provider="json",
    ),
    SourceSurfaceVector(
        name="explicit_ndjson",
        locator_name="records.ndjson",
        fixture_kind="ndjson",
        explicit_type="ndjson",
        expected_provider="ndjson",
    ),
    SourceSurfaceVector(
        name="explicit_excel",
        locator_name="records.xlsx",
        fixture_kind="opaque",
        explicit_type="excel",
        option_mappings=("sheet=Orders", "header=true"),
        expected_provider="excel",
    ),
)


DETECTION_VECTORS = (
    SourceSurfaceVector(
        name="recognized_csv_extension",
        locator_name="orders.csv",
        fixture_kind="csv",
        explicit_type=None,
        expected_provider="csv",
    ),
    SourceSurfaceVector(
        name="recognized_parquet_extension",
        locator_name="orders.parq",
        fixture_kind="opaque",
        explicit_type=None,
        expected_provider="parquet",
    ),
    SourceSurfaceVector(
        name="recognized_json_extension",
        locator_name="records.json",
        fixture_kind="json",
        explicit_type=None,
        expected_provider="json",
    ),
    SourceSurfaceVector(
        name="recognized_ndjson_extension",
        locator_name="records.jsonl",
        fixture_kind="ndjson",
        explicit_type=None,
        expected_provider="ndjson",
    ),
    SourceSurfaceVector(
        name="recognized_excel_extension",
        locator_name="records.xlsx",
        fixture_kind="opaque",
        explicit_type=None,
        expected_provider="excel",
    ),
    SourceSurfaceVector(
        name="extensionless_overlapping_text",
        locator_name="records",
        fixture_kind="ndjson",
        explicit_type=None,
        expected_variant="ambiguous",
        expected_code="source.ambiguous",
        expected_action="specify_type",
    ),
    SourceSurfaceVector(
        name="untyped_directory",
        locator_name="warehouse",
        fixture_kind="directory",
        explicit_type=None,
        expected_variant="ambiguous",
        expected_code="source.ambiguous",
        expected_action="specify_type",
    ),
    SourceSurfaceVector(
        name="explicit_parquet_directory",
        locator_name="warehouse",
        fixture_kind="directory",
        explicit_type="parquet",
        expected_provider="parquet",
    ),
    SourceSurfaceVector(
        name="unsupported_xls",
        locator_name="legacy.xls",
        fixture_kind="opaque",
        explicit_type=None,
        expected_variant="unsupported",
        expected_code="source.unsupported_excel_binary",
        expected_action="convert_or_choose_type",
    ),
    SourceSurfaceVector(
        name="extensionless_excel",
        locator_name="workbook",
        fixture_kind="xlsx_container",
        explicit_type=None,
        expected_variant="ambiguous",
        expected_code="source.ambiguous",
        expected_action="specify_type",
    ),
    SourceSurfaceVector(
        name="unknown_option",
        locator_name="records.json",
        fixture_kind="json",
        explicit_type="json",
        option_mappings=("unknown_option=10",),
        expected_variant="invalid",
        expected_code="source.request_invalid",
        expected_action="correct_options",
    ),
    SourceSurfaceVector(
        name="option_type_error",
        locator_name="records.json",
        fixture_kind="json",
        explicit_type="json",
        option_mappings=("sample_size=ten",),
        expected_variant="invalid",
        expected_code="source.request_invalid",
        expected_action="correct_options",
    ),
)
