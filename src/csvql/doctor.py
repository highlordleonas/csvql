"""Project-health result objects for `csvql doctor`."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DoctorScope = Literal["project", "table", "check"]
DoctorStatus = Literal["passed", "warning", "failed"]


@dataclass(frozen=True, slots=True)
class DoctorProbeResult:
    """One project-health finding emitted by `csvql doctor`."""

    name: str
    scope: DoctorScope
    status: DoctorStatus
    message: str
    table: str | None = None
    check: str | None = None
    path: Path | None = None
    resolved_path: Path | None = None
    column: str | None = None
    reference_table: str | None = None
    reference_column: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "scope": self.scope,
            "status": self.status,
            "message": self.message,
        }
        if self.table is not None:
            payload["table"] = self.table
        if self.check is not None:
            payload["check"] = self.check
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.resolved_path is not None:
            payload["resolved_path"] = str(self.resolved_path)
        if self.column is not None:
            payload["column"] = self.column
        if self.reference_table is not None:
            payload["reference_table"] = self.reference_table
        if self.reference_column is not None:
            payload["reference_column"] = self.reference_column
        return payload


@dataclass(frozen=True, slots=True)
class DoctorRunResult:
    """Aggregate result for a `csvql doctor` invocation."""

    project_root: Path | None
    config_path: Path | None
    probes: tuple[DoctorProbeResult, ...]

    @property
    def status(self) -> DoctorStatus:
        if any(probe.status == "failed" for probe in self.probes):
            return "failed"
        if any(probe.status == "warning" for probe in self.probes):
            return "warning"
        return "passed"

    @property
    def probe_count(self) -> int:
        return len(self.probes)

    @property
    def passed_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "passed")

    @property
    def warning_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "warning")

    @property
    def failed_count(self) -> int:
        return sum(1 for probe in self.probes if probe.status == "failed")

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "probe_count": self.probe_count,
            "passed_count": self.passed_count,
            "warning_count": self.warning_count,
            "failed_count": self.failed_count,
            "project": {
                "config_path": str(self.config_path) if self.config_path is not None else None,
                "project_root": str(self.project_root) if self.project_root is not None else None,
            },
            "probes": [probe.as_dict() for probe in self.probes],
        }
