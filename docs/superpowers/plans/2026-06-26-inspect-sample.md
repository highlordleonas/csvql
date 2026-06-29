# Inspect And Sample Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Inspect-First vertical: source model, `csvql inspect`, `csvql sample`, Rich table output, JSON output, fixtures, docs, and tests.

**Architecture:** Keep `cli.py` as a thin Typer boundary. Add `source.py` for resolved CSV source metadata and `inspection.py` for DuckDB-backed schema/sample work. Keep DuckDB execution details out of the CLI, reuse existing output patterns, and keep JSON contracts deterministic.

**Tech Stack:** Python 3.11+, Typer, DuckDB, Rich, pytest, Ruff, mypy, `uv`.

---

## Scope Boundaries

Implement this batch:

- `csvql inspect <path>`
- `csvql inspect <path> --exact`
- `csvql sample <path>`
- `csvql sample <path> --limit N`
- `--output table|json` for both commands
- source metadata and versioned fingerprint object
- unit tests, CLI tests, JSON contract tests, docs updates

Do not implement in this batch:

- project catalog
- saved SQL
- export files
- profile
- check
- cache/materialization
- safe mode
- Markdown output
- Python API

## File Structure

- Create `src/csvql/source.py`: local CSV path resolution, `CSVSource`, `SourceFingerprint`, and source summary conversion.
- Modify `src/csvql/table_mapping.py`: import path resolution from `source.py` so existing query behavior keeps one path-validation implementation.
- Modify `src/csvql/models.py`: add typed result models for `inspect` and `sample`.
- Modify `src/csvql/exceptions.py`: add a typed inspection error for CSV parsing and dialect failures.
- Create `src/csvql/inspection.py`: inspect schema/dialect/row-count status and sample bounded rows through DuckDB.
- Modify `src/csvql/output.py`: render inspect/sample results as deterministic JSON or Rich table text.
- Modify `src/csvql/cli.py`: add `inspect` and `sample` commands.
- Create `tests/test_source.py`: source metadata and missing-file behavior.
- Create `tests/test_inspection.py`: inspect/sample service behavior and JSON payload contracts.
- Create `tests/test_cli_inspect_sample.py`: CLI behavior, output, and exit codes.
- Modify `tests/test_table_mapping.py`: keep existing table mapping behavior covered after path-resolution move.
- Modify `README.md`: add inspect/sample examples and security wording remains aligned.
- Modify `docs/ARCHITECTURE.md`: describe new source/inspection boundaries.

## Task 1: Source Model And Shared Path Resolution

**Files:**
- Create: `src/csvql/source.py`
- Modify: `src/csvql/table_mapping.py`
- Create: `tests/test_source.py`
- Test: `tests/test_table_mapping.py`

- [ ] **Step 1: Write failing source tests**

Create `tests/test_source.py` with:

```python
from pathlib import Path

import pytest

from csvql.exceptions import FileMissingError
from csvql.source import source_from_path


def test_source_from_path_records_file_metadata(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,total_amount\nORD-1,12.34\n", encoding="utf-8")

    source = source_from_path(str(csv_path))

    assert source.path == csv_path
    assert source.display_path == str(csv_path)
    assert source.fingerprint.version == 1
    assert source.fingerprint.size_bytes == csv_path.stat().st_size
    assert source.fingerprint.modified_at
    assert source.to_json_summary()["fingerprint"]["version"] == 1


def test_source_from_path_resolves_relative_paths(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,email\nCUST-1,a@example.com\n", encoding="utf-8")

    source = source_from_path("customers.csv", base_dir=tmp_path)

    assert source.path == csv_path
    assert source.display_path == "customers.csv"


def test_source_from_path_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileMissingError):
        source_from_path("missing.csv", base_dir=tmp_path)
```

- [ ] **Step 2: Run source tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_source.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'csvql.source'`.

- [ ] **Step 3: Create `source.py`**

Create `src/csvql/source.py` with:

```python
"""Local CSV source resolution and metadata."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from csvql.exceptions import FileMissingError


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Versioned file metadata used to identify a local CSV source."""

    version: int
    size_bytes: int
    modified_at: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly fingerprint payload."""

        return {
            "version": self.version,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True, slots=True)
class CSVSource:
    """Resolved local CSV file plus display and fingerprint metadata."""

    path: Path
    display_path: str
    fingerprint: SourceFingerprint

    def to_json_summary(self) -> dict[str, object]:
        """Return the stable JSON source summary used by inspect and sample."""

        return {
            "display_path": self.display_path,
            "resolved_path": str(self.path),
            "size_bytes": self.fingerprint.size_bytes,
            "modified_at": self.fingerprint.modified_at,
            "fingerprint": self.fingerprint.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class RegisteredTable:
    """A validated table alias bound to a resolved CSV source."""

    name: str
    source: CSVSource


def resolve_csv_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    """Resolve and validate a local CSV path."""

    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    resolved_path = candidate.resolve(strict=False)
    if not resolved_path.is_file():
        raise FileMissingError(
            f"CSV file not found: {path_value}",
            suggestion="Check the path or run from the directory that contains the CSV file.",
        )
    return resolved_path


def source_from_path(path_value: str, *, base_dir: Path | None = None) -> CSVSource:
    """Build a resolved CSV source from a CLI path value."""

    resolved_path = resolve_csv_path(path_value, base_dir=base_dir)
    stat = resolved_path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    fingerprint = SourceFingerprint(
        version=1,
        size_bytes=stat.st_size,
        modified_at=modified_at,
    )
    return CSVSource(
        path=resolved_path,
        display_path=path_value,
        fingerprint=fingerprint,
    )
```

- [ ] **Step 4: Reuse source path resolution from table mappings**

Modify `src/csvql/table_mapping.py` so the imports start with:

```python
"""Parsing and validation for CLI table mappings."""

import re
from pathlib import Path

from csvql.exceptions import TableMappingError
from csvql.models import TableSource
from csvql.source import resolve_csv_path
```

Remove the existing `resolve_csv_path` function from `src/csvql/table_mapping.py`. Keep `parse_table_mapping`, `derive_alias_from_path`, and `source_from_single_csv` unchanged except that they now call the imported `resolve_csv_path`.

- [ ] **Step 5: Run source and table mapping tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_source.py tests/test_table_mapping.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/csvql/source.py src/csvql/table_mapping.py tests/test_source.py
git commit -m "feat: add CSV source metadata model"
```

## Task 2: Inspect And Sample Result Models

**Files:**
- Modify: `src/csvql/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing model contract tests**

Create `tests/test_models.py` with:

```python
from csvql.models import (
    ColumnInfo,
    DialectInfo,
    InspectResult,
    RowCountInfo,
    SampleResult,
)


def test_row_count_not_counted_contract() -> None:
    row_count = RowCountInfo.not_counted()

    assert row_count.as_dict() == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }


def test_row_count_exact_contract() -> None:
    row_count = RowCountInfo.exact_count(3)

    assert row_count.as_dict() == {
        "mode": "exact",
        "value": 3,
        "exact": True,
    }


def test_inspect_result_payload_contract() -> None:
    result = InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.not_counted(),
        warnings=("dialect warning",),
    )

    assert result.as_dict() == {
        "source": {"display_path": "orders.csv"},
        "dialect": {
            "delimiter": ",",
            "quote": '"',
            "escape": None,
            "header": True,
            "encoding": "utf-8",
        },
        "columns": [{"name": "order_id", "duckdb_type": "VARCHAR"}],
        "row_count": {"mode": "not_counted", "value": None, "exact": False},
        "warnings": ["dialect warning"],
    }


def test_sample_result_payload_contract() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=2,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    assert result.as_dict() == {
        "source": {"display_path": "orders.csv"},
        "limit": 2,
        "columns": ["order_id", "status"],
        "rows": [{"order_id": "ORD-1", "status": "paid"}],
        "warnings": [],
    }
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_models.py -q
```

Expected: FAIL because the inspect/sample model classes do not exist.

- [ ] **Step 3: Add inspect/sample models**

Append these classes to `src/csvql/models.py` after `QueryResult`:

```python
from typing import Literal


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """Column metadata inferred from DuckDB."""

    name: str
    duckdb_type: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-friendly column payload."""

        return {
            "name": self.name,
            "duckdb_type": self.duckdb_type,
        }


@dataclass(frozen=True, slots=True)
class DialectInfo:
    """Best-effort CSV dialect metadata from a bounded file sample."""

    delimiter: str | None
    quote: str | None
    escape: str | None
    header: bool | None
    encoding: str | None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly dialect payload."""

        return {
            "delimiter": self.delimiter,
            "quote": self.quote,
            "escape": self.escape,
            "header": self.header,
            "encoding": self.encoding,
        }


@dataclass(frozen=True, slots=True)
class RowCountInfo:
    """Row count status for inspection output."""

    mode: Literal["not_counted", "exact"]
    value: int | None
    exact: bool

    @classmethod
    def not_counted(cls) -> "RowCountInfo":
        """Return the default row count status."""

        return cls(mode="not_counted", value=None, exact=False)

    @classmethod
    def exact_count(cls, value: int) -> "RowCountInfo":
        """Return an exact row count status."""

        return cls(mode="exact", value=value, exact=True)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly row count payload."""

        return {
            "mode": self.mode,
            "value": self.value,
            "exact": self.exact,
        }


@dataclass(frozen=True, slots=True)
class InspectResult:
    """Structured result for `csvql inspect`."""

    source: dict[str, object]
    dialect: DialectInfo
    columns: tuple[ColumnInfo, ...]
    row_count: RowCountInfo
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return the stable JSON inspect payload."""

        return {
            "source": self.source,
            "dialect": self.dialect.as_dict(),
            "columns": [column.as_dict() for column in self.columns],
            "row_count": self.row_count.as_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class SampleResult:
    """Structured result for `csvql sample`."""

    source: dict[str, object]
    limit: int
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    warnings: tuple[str, ...]

    def as_records(self) -> list[dict[str, object]]:
        """Return rows as JSON-friendly dictionaries keyed by column name."""

        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def as_dict(self) -> dict[str, object]:
        """Return the stable JSON sample payload."""

        return {
            "source": self.source,
            "limit": self.limit,
            "columns": list(self.columns),
            "rows": self.as_records(),
            "warnings": list(self.warnings),
        }
```

Also move `from typing import Literal` to the top import group so `models.py` imports are:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
```

- [ ] **Step 4: Run model tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Run mypy for model typing**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/csvql/models.py tests/test_models.py
git commit -m "feat: add inspect and sample result models"
```

## Task 3: DuckDB-Backed Inspect Service

**Files:**
- Modify: `src/csvql/exceptions.py`
- Create: `src/csvql/inspection.py`
- Create: `tests/test_inspection.py`

- [ ] **Step 1: Write failing inspect service tests**

Create `tests/test_inspection.py` with:

```python
from pathlib import Path

from csvql.inspection import inspect_csv_source
from csvql.source import source_from_path


def test_inspect_csv_source_returns_columns_without_counting_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,total_amount\nORD-1,12.34\nORD-2,99.00\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = inspect_csv_source(source)

    payload = result.as_dict()
    assert payload["source"]["display_path"] == str(csv_path)
    assert payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert payload["columns"] == [
        {"name": "order_id", "duckdb_type": "VARCHAR"},
        {"name": "total_amount", "duckdb_type": "DOUBLE"},
    ]
    assert payload["warnings"] == []


def test_inspect_csv_source_exact_counts_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,total_amount\nORD-1,12.34\nORD-2,99.00\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = inspect_csv_source(source, exact=True)

    assert result.row_count.as_dict() == {
        "mode": "exact",
        "value": 2,
        "exact": True,
    }


def test_inspect_csv_source_reports_detected_dialect(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.tsv"
    csv_path.write_text(
        "order_id\tstatus\nORD-1\tpaid\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = inspect_csv_source(source)

    assert result.dialect.delimiter == "\t"
    assert result.dialect.header is True
    assert result.dialect.encoding == "utf-8"
```

- [ ] **Step 2: Run inspect service tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_inspection.py -q
```

Expected: FAIL because `csvql.inspection` does not exist.

- [ ] **Step 3: Add inspection exception**

Append this class to `src/csvql/exceptions.py`:

```python
class CSVInspectionError(CSVQLError):
    """Raised when CSV inspection or sampling fails."""

    exit_code = 7
```

- [ ] **Step 4: Create `inspection.py` with inspect support**

Create `src/csvql/inspection.py` with:

```python
"""CSV inspection and sampling services."""

import csv
from pathlib import Path

import duckdb

from csvql.exceptions import CSVInspectionError
from csvql.models import ColumnInfo, DialectInfo, InspectResult, RowCountInfo
from csvql.source import CSVSource

SNIFF_BYTES = 64 * 1024


def inspect_csv_source(source: CSVSource, *, exact: bool = False) -> InspectResult:
    """Inspect a CSV source and return schema, dialect, and row-count status."""

    warnings: list[str] = []
    dialect = _detect_dialect(source.path, warnings=warnings)

    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        relation = connection.read_csv(
            str(source.path),
            auto_detect=True,
            header=True,
        )
        columns = tuple(
            ColumnInfo(name=str(name), duckdb_type=str(duckdb_type))
            for name, duckdb_type in zip(relation.columns, relation.types, strict=True)
        )
        row_count = RowCountInfo.not_counted()
        if exact:
            count_row = relation.aggregate("count(*)").fetchone()
            row_count = RowCountInfo.exact_count(int(count_row[0]))
    except duckdb.Error as exc:
        raise CSVInspectionError(
            f"Failed to inspect CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    return InspectResult(
        source=source.to_json_summary(),
        dialect=dialect,
        columns=columns,
        row_count=row_count,
        warnings=tuple(warnings),
    )


def _detect_dialect(path: Path, *, warnings: list[str]) -> DialectInfo:
    sample = path.read_text(encoding="utf-8", errors="replace")[:SNIFF_BYTES]
    if not sample:
        warnings.append("CSV file is empty; dialect detection used default values.")
        return DialectInfo(
            delimiter=None,
            quote=None,
            escape=None,
            header=None,
            encoding="utf-8",
        )

    try:
        sniffed = csv.Sniffer().sniff(sample)
    except csv.Error:
        warnings.append("Could not detect CSV dialect from the bounded sample.")
        return DialectInfo(
            delimiter=None,
            quote=None,
            escape=None,
            header=None,
            encoding="utf-8",
        )

    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = None
        warnings.append("Could not determine whether the CSV has a header row.")

    return DialectInfo(
        delimiter=sniffed.delimiter,
        quote=sniffed.quotechar,
        escape=sniffed.escapechar,
        header=has_header,
        encoding="utf-8",
    )
```

- [ ] **Step 5: Run inspect tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_inspection.py -q
```

Expected: PASS.

- [ ] **Step 6: Run type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/csvql/exceptions.py src/csvql/inspection.py tests/test_inspection.py
git commit -m "feat: inspect CSV source metadata"
```

## Task 4: Sample Service

**Files:**
- Modify: `src/csvql/inspection.py`
- Modify: `tests/test_inspection.py`

- [ ] **Step 1: Add failing sample service tests**

Append to `tests/test_inspection.py`:

```python
from csvql.inspection import sample_csv_source


def test_sample_csv_source_returns_bounded_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\nORD-3,paid\n",
        encoding="utf-8",
    )
    source = source_from_path(str(csv_path))

    result = sample_csv_source(source, limit=2)

    assert result.as_dict()["limit"] == 2
    assert result.columns == ("order_id", "status")
    assert result.rows == (("ORD-1", "paid"), ("ORD-2", "pending"))
    assert result.warnings == ()


def test_sample_csv_source_rejects_non_positive_limit(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")
    source = source_from_path(str(csv_path))

    try:
        sample_csv_source(source, limit=0)
    except ValueError as exc:
        assert str(exc) == "Sample limit must be greater than zero."
    else:
        raise AssertionError("sample_csv_source accepted a non-positive limit")
```

- [ ] **Step 2: Run sample tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_inspection.py::test_sample_csv_source_returns_bounded_rows tests/test_inspection.py::test_sample_csv_source_rejects_non_positive_limit -q
```

Expected: FAIL because `sample_csv_source` does not exist.

- [ ] **Step 3: Add sample support to `inspection.py` imports**

Update the model import in `src/csvql/inspection.py` to:

```python
from csvql.models import ColumnInfo, DialectInfo, InspectResult, RowCountInfo, SampleResult
```

- [ ] **Step 4: Add `sample_csv_source`**

Append to `src/csvql/inspection.py`:

```python
def sample_csv_source(source: CSVSource, *, limit: int = 10) -> SampleResult:
    """Return a bounded row sample from a CSV source."""

    if limit <= 0:
        raise ValueError("Sample limit must be greater than zero.")

    warnings: list[str] = []
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(database=":memory:")
        relation = connection.read_csv(
            str(source.path),
            auto_detect=True,
            header=True,
        )
        sample_relation = relation.limit(limit)
        rows = tuple(tuple(row) for row in sample_relation.fetchall())
        columns = tuple(str(column) for column in relation.columns)
    except duckdb.Error as exc:
        raise CSVInspectionError(
            f"Failed to sample CSV file: {source.display_path}",
            suggestion="Check that the file is a readable CSV with a header row.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    return SampleResult(
        source=source.to_json_summary(),
        limit=limit,
        columns=columns,
        rows=rows,
        warnings=tuple(warnings),
    )
```

- [ ] **Step 5: Run inspection tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_inspection.py -q
```

Expected: PASS.

- [ ] **Step 6: Run mypy**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/csvql/inspection.py tests/test_inspection.py
git commit -m "feat: sample CSV source rows"
```

## Task 5: Inspect And Sample Renderers

**Files:**
- Modify: `src/csvql/output.py`
- Create: `tests/test_output.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/test_output.py` with:

```python
import json

from csvql.models import ColumnInfo, DialectInfo, InspectResult, RowCountInfo, SampleResult
from csvql.output import (
    format_inspect_result_json,
    format_inspect_result_table,
    format_sample_result_json,
    format_sample_result_table,
)


def _inspect_result() -> InspectResult:
    return InspectResult(
        source={"display_path": "orders.csv"},
        dialect=DialectInfo(
            delimiter=",",
            quote='"',
            escape=None,
            header=True,
            encoding="utf-8",
        ),
        columns=(ColumnInfo(name="order_id", duckdb_type="VARCHAR"),),
        row_count=RowCountInfo.not_counted(),
        warnings=(),
    )


def test_format_inspect_result_json_is_deterministic() -> None:
    payload = json.loads(format_inspect_result_json(_inspect_result()))

    assert payload["columns"] == [{"duckdb_type": "VARCHAR", "name": "order_id"}]
    assert payload["row_count"]["mode"] == "not_counted"


def test_format_inspect_result_table_contains_core_fields() -> None:
    output = format_inspect_result_table(_inspect_result())

    assert "orders.csv" in output
    assert "order_id" in output
    assert "not_counted" in output


def test_format_sample_result_json_is_deterministic() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=1,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    payload = json.loads(format_sample_result_json(result))

    assert payload["limit"] == 1
    assert payload["rows"] == [{"order_id": "ORD-1", "status": "paid"}]


def test_format_sample_result_table_contains_rows() -> None:
    result = SampleResult(
        source={"display_path": "orders.csv"},
        limit=1,
        columns=("order_id", "status"),
        rows=(("ORD-1", "paid"),),
        warnings=(),
    )

    output = format_sample_result_table(result)

    assert "ORD-1" in output
    assert "paid" in output
```

- [ ] **Step 2: Run renderer tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_output.py -q
```

Expected: FAIL because the renderer functions do not exist.

- [ ] **Step 3: Add renderer imports**

Modify `src/csvql/output.py` imports to include:

```python
from csvql.models import InspectResult, QueryResult, SampleResult
```

- [ ] **Step 4: Add inspect/sample JSON renderers**

Append to `src/csvql/output.py`:

```python
def format_inspect_result_json(result: InspectResult) -> str:
    """Format an inspect result as deterministic JSON."""

    return json.dumps(result.as_dict(), default=str, indent=2, sort_keys=True)


def format_sample_result_json(result: SampleResult) -> str:
    """Format a sample result as deterministic JSON."""

    return json.dumps(result.as_dict(), default=str, indent=2, sort_keys=True)
```

- [ ] **Step 5: Add inspect/sample table renderers**

Append to `src/csvql/output.py`:

```python
def format_inspect_result_table(result: InspectResult) -> str:
    """Format an inspect result as Rich table text."""

    console = Console(color_system=None, force_terminal=False, record=True, width=120)
    source = result.source
    console.print(f"Source: {source.get('display_path', '')}")
    console.print(f"Rows: {result.row_count.mode}")

    table = Table(show_header=True)
    table.add_column("column")
    table.add_column("type")
    for column in result.columns:
        table.add_row(column.name, column.duckdb_type)
    console.print(table)

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print(f"- {warning}")
    return console.export_text(clear=True)


def format_sample_result_table(result: SampleResult) -> str:
    """Format a sample result as Rich table text."""

    console = Console(color_system=None, force_terminal=False, record=True, width=120)
    table = Table(show_header=True)
    for column in result.columns:
        table.add_column(column)
    for row in result.rows:
        table.add_row(*(_format_cell(value) for value in row))
    console.print(table)
    console.print(f"{len(result.rows)} row(s) sampled with limit {result.limit}")

    if result.warnings:
        console.print("Warnings:")
        for warning in result.warnings:
            console.print(f"- {warning}")
    return console.export_text(clear=True)
```

- [ ] **Step 6: Run renderer tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_output.py -q
```

Expected: PASS.

- [ ] **Step 7: Run query CLI tests to catch output regressions**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_query.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/csvql/output.py tests/test_output.py
git commit -m "feat: render inspect and sample output"
```

## Task 6: CLI Commands

**Files:**
- Modify: `src/csvql/cli.py`
- Create: `tests/test_cli_inspect_sample.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_inspect_sample.py` with:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from csvql.cli import app

runner = CliRunner()


def test_inspect_outputs_json_without_counting_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(csv_path), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == {
        "mode": "not_counted",
        "value": None,
        "exact": False,
    }
    assert payload["columns"][0]["name"] == "order_id"


def test_inspect_exact_outputs_exact_row_count(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(csv_path), "--exact", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == {
        "mode": "exact",
        "value": 2,
        "exact": True,
    }


def test_sample_outputs_json_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,status\nORD-1,paid\nORD-2,pending\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["sample", str(csv_path), "--limit", "1", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["limit"] == 1
    assert payload["rows"] == [{"order_id": "ORD-1", "status": "paid"}]


def test_sample_outputs_table_by_default(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,status\nORD-1,paid\n", encoding="utf-8")

    result = runner.invoke(app, ["sample", str(csv_path)])

    assert result.exit_code == 0, result.output
    assert "ORD-1" in result.output
    assert "paid" in result.output


def test_inspect_missing_file_uses_existing_file_error() -> None:
    result = runner.invoke(app, ["inspect", "missing.csv"])

    assert result.exit_code == 4
    assert "CSV file not found" in result.output
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_inspect_sample.py -q
```

Expected: FAIL because the `inspect` and `sample` commands do not exist.

- [ ] **Step 3: Add CLI imports**

Modify `src/csvql/cli.py` imports to include:

```python
from csvql.inspection import inspect_csv_source, sample_csv_source
from csvql.output import (
    OutputFormat,
    format_inspect_result_json,
    format_inspect_result_table,
    format_json_result,
    format_sample_result_json,
    format_sample_result_table,
    format_table_result,
)
from csvql.source import source_from_path
```

- [ ] **Step 4: Add `inspect` command**

Add this command above `query` in `src/csvql/cli.py`:

```python
@app.command()
def inspect(
    csv_path: Annotated[
        str,
        typer.Argument(help="CSV file to inspect."),
    ],
    exact: Annotated[
        bool,
        typer.Option(
            "--exact",
            help="Run a full scan to calculate an exact row count.",
        ),
    ] = False,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Inspection output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Inspect a local CSV file without running user-authored SQL."""

    try:
        source = source_from_path(csv_path)
        result = inspect_csv_source(source, exact=exact)
        if output is OutputFormat.json:
            typer.echo(format_inspect_result_json(result))
        else:
            typer.echo(format_inspect_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)
```

- [ ] **Step 5: Add `sample` command**

Add this command above `query` in `src/csvql/cli.py`:

```python
@app.command()
def sample(
    csv_path: Annotated[
        str,
        typer.Argument(help="CSV file to sample."),
    ],
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            help="Maximum number of rows to sample.",
        ),
    ] = 10,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="Sample output format.",
        ),
    ] = OutputFormat.table,
) -> None:
    """Sample rows from a local CSV file without running user-authored SQL."""

    try:
        source = source_from_path(csv_path)
        result = sample_csv_source(source, limit=limit)
        if output is OutputFormat.json:
            typer.echo(format_sample_result_json(result))
        else:
            typer.echo(format_sample_result_table(result), nl=False)
    except CSVQLError as exc:
        _exit_with_error(exc)
```

- [ ] **Step 6: Run CLI inspect/sample tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_inspect_sample.py -q
```

Expected: PASS.

- [ ] **Step 7: Run existing query CLI tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_cli_query.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

```bash
git add src/csvql/cli.py tests/test_cli_inspect_sample.py
git commit -m "feat: add inspect and sample CLI commands"
```

## Task 7: Docs And Architecture Update

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update README planned status**

In `README.md`, under `Implemented now`, add:

```markdown
- `csvql inspect data/orders.csv --output json`
- `csvql sample data/orders.csv --limit 10`
```

Under `Planned later`, remove `inspect` and `sample` from the planned command list so it reads:

```markdown
- `.csvql.yml` project config
- `run` and `export`
- profiling and data quality checks
- benchmarks and release workflow
```

- [ ] **Step 2: Add README inspect example**

Add this section after `Query Examples`:

````markdown
## Inspect And Sample Examples

Inspect a CSV without running user-authored SQL:

```bash
uv run csvql inspect examples/sales/data/orders.csv --output json
```

Calculate an exact row count when you explicitly want a full scan:

```bash
uv run csvql inspect examples/sales/data/orders.csv --exact --output json
```

Sample rows from a CSV:

```bash
uv run csvql sample examples/sales/data/orders.csv --limit 5
```
````

- [ ] **Step 3: Update architecture boundaries**

In `docs/ARCHITECTURE.md`, add these boundaries after `table_mapping.py`:

```markdown
`source.py`
: Resolve local CSV paths and capture file metadata used by inspect, sample, and later catalog workflows.

`inspection.py`
: Use DuckDB and bounded file reads to infer columns, dialect metadata, row-count status, and sample rows.
```

Under `Current Design Choices`, add:

```markdown
- `inspect` does not run an exact row count by default; `--exact` is the explicit full-scan mode.
- `sample` reads a bounded row count and shares source resolution with `inspect` and `query`.
```

- [ ] **Step 4: Update roadmap status**

In `docs/ROADMAP.md`, keep `v0.2.0 - Inspect And Sample` but mark it as implemented with this text:

```markdown
## v0.2.0 - Inspect And Sample

Implemented:

- source model for resolved local CSV files
- `csvql inspect <path>`
- bounded/default row-count status; exact row count only with `--exact`
- `csvql sample <path>`
- table and JSON output for `inspect` and `sample`
- messy CSV fixtures and error-path tests
- README and architecture updates
```

- [ ] **Step 5: Run docs scans**

Run:

```bash
rg -n "schema <table>|preview <table>|safe mode is implemented|sandbox" README.md docs/ARCHITECTURE.md docs/ROADMAP.md docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md
```

Expected: no `schema <table>` or `preview <table>` command commitments. Any `sandbox` matches must be no-sandbox disclaimers.

- [ ] **Step 6: Commit Task 7**

```bash
git add README.md docs/ARCHITECTURE.md docs/ROADMAP.md
git commit -m "docs: document inspect and sample workflow"
```

## Task 8: Full Verification Gate

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run formatting check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
```

Expected: PASS.

- [ ] **Step 2: Run lint**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run type check**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy src
```

Expected: PASS.

- [ ] **Step 4: Run tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest
```

Expected: PASS.

- [ ] **Step 5: Run final diff hygiene checks**

Run:

```bash
git diff --check
rg -n "TB[D]|TO[D]O|placeholde[r]|FIXM[E]|XX[X]" src tests README.md docs
rg -n "[ \t]+$" src tests README.md docs
```

Expected:

- `git diff --check`: PASS with no output.
- red-flag scan: no matches.
- trailing whitespace scan: no matches.

- [ ] **Step 6: Review final command surface**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql --help
UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql inspect examples/sales/data/orders.csv --output json
UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql inspect examples/sales/data/orders.csv --exact --output json
UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql sample examples/sales/data/orders.csv --limit 2 --output json
```

Expected:

- `--help` lists `inspect`, `sample`, and `query`.
- default inspect JSON has `row_count.mode` equal to `"not_counted"` and `row_count.value` equal to `null`.
- exact inspect JSON has `row_count.mode` equal to `"exact"` and an integer row count.
- sample JSON includes `source`, `limit`, `columns`, `rows`, and `warnings`.

- [ ] **Step 7: Commit final verification notes if docs changed during verification**

If Task 8 changes any docs or tests, commit them with:

```bash
git add README.md docs tests src
git commit -m "chore: polish inspect and sample verification"
```

If Task 8 changes no files, do not create an empty commit.

## Self-Review Against Spec

Spec coverage:

- Source model: Task 1.
- `inspect`: Tasks 2, 3, 5, 6, 7.
- `sample`: Tasks 2, 4, 5, 6, 7.
- Rich table output: Task 5.
- JSON output and contracts: Tasks 2, 3, 4, 5, 6.
- default no-count inspect behavior: Tasks 3 and 6.
- `--exact`: Tasks 3 and 6.
- source fingerprint object: Task 1.
- no Markdown output: Task 7 keeps Markdown out of inspect/sample docs.
- no safe mode or sandbox claims: Task 7 verifies docs language.
- tests and fixtures: Tasks 1 through 6 use focused temp-file fixtures.
- verification gate: Task 8.

Remaining implementation-plan decisions:

- Default sample limit is set to `10`.
- Human inspect table columns are `column` and `type`, with source and row-count status above the table.
- Human sample table displays CSV columns and a sampled-row footer.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-inspect-sample.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
