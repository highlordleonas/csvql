"""Typed benchmark artifacts and Markdown rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkMetadata:
    """Static metadata recorded for one benchmark artifact."""

    schema_version: int
    csvql_version: str
    duckdb_version: str
    python_version: str
    platform: str
    generated_at: str
    warmup_runs: int
    measured_runs: int

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly benchmark metadata payload."""

        return {
            "schema_version": self.schema_version,
            "csvql_version": self.csvql_version,
            "duckdb_version": self.duckdb_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "generated_at": self.generated_at,
            "warmup_runs": self.warmup_runs,
            "measured_runs": self.measured_runs,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkDatasetRecord:
    """Dataset facts captured for one benchmark tier."""

    dataset_id: str
    project_path: str
    seed: int | None
    customer_rows: int
    order_rows: int
    file_sizes: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly dataset record."""

        return {
            "dataset_id": self.dataset_id,
            "project_path": self.project_path,
            "seed": self.seed,
            "customer_rows": self.customer_rows,
            "order_rows": self.order_rows,
            "file_sizes": dict(sorted(self.file_sizes.items())),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    """Measured timings and validation facts for one benchmark case."""

    case_id: str
    dataset_id: str
    label: str
    command: tuple[str, ...]
    measured_timings_ms: tuple[float, ...]
    median_ms: float
    min_ms: float
    max_ms: float
    validation: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly benchmark case result."""

        return {
            "case_id": self.case_id,
            "dataset_id": self.dataset_id,
            "label": self.label,
            "command": list(self.command),
            "measured_timings_ms": list(self.measured_timings_ms),
            "median_ms": self.median_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "validation": self.validation,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkArtifact:
    """Complete JSON-serializable benchmark artifact."""

    metadata: BenchmarkMetadata
    datasets: tuple[BenchmarkDatasetRecord, ...]
    cases: tuple[BenchmarkCaseResult, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return the artifact payload as plain JSON-friendly objects."""

        return {
            "metadata": self.metadata.as_dict(),
            "datasets": [dataset.as_dict() for dataset in self.datasets],
            "cases": [case.as_dict() for case in self.cases],
            "notes": list(self.notes),
        }

    def write_json(self, path: Path) -> None:
        """Persist the artifact as deterministic JSON."""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), default=str, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def load_benchmark_artifact(path: Path) -> BenchmarkArtifact:
    """Load a benchmark artifact JSON file into typed result objects."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkArtifact(
        metadata=BenchmarkMetadata(
            schema_version=int(payload["metadata"]["schema_version"]),
            csvql_version=str(payload["metadata"]["csvql_version"]),
            duckdb_version=str(payload["metadata"]["duckdb_version"]),
            python_version=str(payload["metadata"]["python_version"]),
            platform=str(payload["metadata"]["platform"]),
            generated_at=str(payload["metadata"]["generated_at"]),
            warmup_runs=int(payload["metadata"]["warmup_runs"]),
            measured_runs=int(payload["metadata"]["measured_runs"]),
        ),
        datasets=tuple(
            BenchmarkDatasetRecord(
                dataset_id=str(dataset["dataset_id"]),
                project_path=str(dataset["project_path"]),
                seed=None if dataset["seed"] is None else int(dataset["seed"]),
                customer_rows=int(dataset["customer_rows"]),
                order_rows=int(dataset["order_rows"]),
                file_sizes={
                    str(relative_path): int(size_bytes)
                    for relative_path, size_bytes in dataset["file_sizes"].items()
                },
            )
            for dataset in payload["datasets"]
        ),
        cases=tuple(
            BenchmarkCaseResult(
                case_id=str(case["case_id"]),
                dataset_id=str(case["dataset_id"]),
                label=str(case["label"]),
                command=tuple(str(part) for part in case["command"]),
                measured_timings_ms=tuple(float(value) for value in case["measured_timings_ms"]),
                median_ms=float(case["median_ms"]),
                min_ms=float(case["min_ms"]),
                max_ms=float(case["max_ms"]),
                validation=dict(case["validation"]),
            )
            for case in payload["cases"]
        ),
        notes=tuple(str(note) for note in payload["notes"]),
    )


def render_benchmark_summary(artifact: BenchmarkArtifact) -> str:
    """Render a Markdown summary from a typed benchmark artifact."""

    lines = [
        "# CSVQL Benchmark Summary",
        "",
        f"- CSVQL: `{artifact.metadata.csvql_version}`",
        f"- DuckDB: `{artifact.metadata.duckdb_version}`",
        f"- Python: `{artifact.metadata.python_version}`",
        f"- Platform: `{artifact.metadata.platform}`",
        f"- Generated: `{artifact.metadata.generated_at}`",
        f"- Warmup runs: `{artifact.metadata.warmup_runs}`",
        f"- Measured runs: `{artifact.metadata.measured_runs}`",
        "",
        "## Dataset Tiers",
        "",
        "| Dataset | Customers | Orders | Seed |",
        "| --- | ---: | ---: | ---: |",
    ]
    for dataset in artifact.datasets:
        lines.append(
            "| "
            f"{dataset.dataset_id} | "
            f"{dataset.customer_rows} | "
            f"{dataset.order_rows} | "
            f"{'' if dataset.seed is None else dataset.seed} |"
        )

    lines.extend(
        [
            "",
            "## Benchmark Cases",
            "",
            "| Dataset | Case | Median (ms) | Min (ms) | Max (ms) |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for case in artifact.cases:
        lines.append(
            "| "
            f"{case.dataset_id} | "
            f"{case.label} | "
            f"{case.median_ms:.3f} | "
            f"{case.min_ms:.3f} | "
            f"{case.max_ms:.3f} |"
        )

    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in artifact.notes)
    lines.append("")
    return "\n".join(lines)
