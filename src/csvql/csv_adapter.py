"""Private CSV source resolution, binding, and supplemental metadata."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from csvql.exceptions import SourceError
from csvql.models import DialectInfo
from csvql.operation import OperationCancelled, OperationContext
from csvql.source import (
    SOURCE_CAPABILITY_OPERATIONS,
    ResolvedSource,
    SourceCapabilities,
    SourceCapabilityStatus,
    SourceFingerprint,
    SourceSpec,
)
from csvql.source_adapter import (
    AdapterInspectionMetadata,
    SourceAdapterDescriptor,
    SourceAdapterRegistry,
)
from csvql.sql_utils import quote_identifier

SNIFF_BYTES = 64 * 1024

CSV_CAPABILITIES = SourceCapabilities(
    statuses=tuple(
        SourceCapabilityStatus(operation=operation, state="available")
        for operation in SOURCE_CAPABILITY_OPERATIONS
    )
)


def _fingerprint(path: Path) -> SourceFingerprint:
    stat = path.stat()
    return SourceFingerprint(
        version=1,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    )


def _source_missing(spec: SourceSpec) -> SourceError:
    return SourceError(
        "source_missing",
        "CSV source is missing.",
        kind="csv",
        alias=spec.alias,
        suggestion="Restore the CSV source or update its configured locator.",
    )


def _source_changed(spec: SourceSpec) -> SourceError:
    return SourceError(
        "source_changed",
        "CSV source changed after submission.",
        kind="csv",
        alias=spec.alias,
        suggestion="Submit the operation again to capture the current CSV source.",
    )


def _current_fingerprint(resolved: ResolvedSource) -> SourceFingerprint:
    path = Path(resolved.canonical_locator)
    try:
        if not path.is_file():
            raise _source_missing(resolved.spec)
        return _fingerprint(path)
    except SourceError:
        raise
    except (OSError, ValueError) as exc:
        raise _source_missing(resolved.spec) from exc


def _revalidate(resolved: ResolvedSource) -> None:
    # This metadata comparison detects common changes; it is not a content hash and does not
    # claim byte identity when version, size, and UTC modification time remain unchanged.
    if resolved.fingerprint is None or _current_fingerprint(resolved) != resolved.fingerprint:
        raise _source_changed(resolved.spec)


@dataclass(slots=True)
class _CSVPreparedBinding:
    _connection: duckdb.DuckDBPyConnection
    _source: ResolvedSource
    _closed: bool = field(default=False, init=False)

    @property
    def alias(self) -> str:
        """Return the exact user-visible alias registered in DuckDB."""

        return self._source.spec.alias

    @property
    def source(self) -> ResolvedSource:
        """Return the immutable source snapshot used for this binding."""

        return self._source

    @property
    def capabilities(self) -> SourceCapabilities:
        """Return the effective capabilities of the bound CSV source."""

        return self._source.capabilities

    def close(self) -> None:
        """Drop only this adapter-owned view; the engine retains connection ownership."""

        if self._closed:
            return
        try:
            self._connection.execute(f"DROP VIEW IF EXISTS {quote_identifier(self.alias)}")
        except duckdb.Error as exc:
            raise SourceError(
                "source_bind_failed",
                "Failed to clean up a CSV source binding.",
                kind="csv",
                alias=self.alias,
                suggestion="Close the LocalQL operation and try again.",
            ) from exc
        self._closed = True


class CSVSourceAdapter:
    """Adapter for LocalQL-managed CSV sources."""

    @property
    def descriptor(self) -> SourceAdapterDescriptor:
        """Return the immutable CSV descriptor without optional dependency loading."""

        return CSV_ADAPTER_DESCRIPTOR

    def validate_options(self, spec: SourceSpec) -> None:
        """Reject every CSV option; v1.1 keeps DuckDB's established defaults."""

        if spec.kind != "csv":
            raise SourceError(
                "unknown_source_kind",
                "The CSV adapter received a different source kind.",
                kind=spec.kind,
                alias=spec.alias,
                suggestion="Select the adapter matching the source kind.",
            )
        if spec.options:
            raise SourceError(
                "unsupported_source_option",
                "CSV source options are not supported.",
                kind="csv",
                alias=spec.alias,
                suggestion="Remove all source options to preserve CSV auto-detection.",
            )

    def resolve(self, spec: SourceSpec, context: OperationContext) -> ResolvedSource:
        """Resolve against the captured anchor and snapshot file metadata."""

        context.checkpoint()
        self.validate_options(spec)
        try:
            candidate = Path(spec.locator).expanduser()
            if not candidate.is_absolute():
                candidate = spec.anchor / candidate
            canonical_path = candidate.resolve(strict=False)
            if not canonical_path.is_file():
                raise _source_missing(spec)
            fingerprint = _fingerprint(canonical_path)
        except SourceError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise _source_missing(spec) from exc
        context.checkpoint()
        return ResolvedSource(
            spec=spec,
            canonical_locator=str(canonical_path),
            fingerprint=fingerprint,
            capabilities=CSV_CAPABILITIES,
        )

    def bind(
        self,
        connection: duckdb.DuckDBPyConnection,
        source: ResolvedSource,
        context: OperationContext,
    ) -> _CSVPreparedBinding:
        """Revalidate and register one exact, non-replacing CSV view."""

        context.checkpoint()
        self.validate_options(source.spec)
        _revalidate(source)
        context.checkpoint()
        resolved = source
        try:
            relation = connection.read_csv(
                resolved.canonical_locator,
                auto_detect=True,
                header=True,
            )
            relation.create_view(resolved.spec.alias, replace=False)
        except (duckdb.Error, OSError) as exc:
            raise SourceError(
                "source_bind_failed",
                "Failed to bind CSV source.",
                kind="csv",
                alias=source.spec.alias,
                suggestion="Check that the source is a readable CSV with a header row.",
            ) from exc
        binding = _CSVPreparedBinding(connection, source)
        try:
            context.checkpoint()
        except OperationCancelled:
            try:
                binding.close()
            except SourceError:
                # Cancellation remains the primary failure; the engine owns final connection
                # cleanup when a view cannot be dropped with confidence.
                pass
            raise
        return binding

    def inspect_metadata(
        self,
        source: ResolvedSource,
        context: OperationContext,
    ) -> AdapterInspectionMetadata:
        """Read a bounded raw sample and return CSV-specific dialect metadata."""

        context.checkpoint()
        self.validate_options(source.spec)
        _revalidate(source)
        warnings: list[str] = []
        try:
            with Path(source.canonical_locator).open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as file:
                sample = file.read(SNIFF_BYTES)
        except OSError as exc:
            raise _source_missing(source.spec) from exc
        context.checkpoint()
        dialect = _detect_dialect(sample, warnings=warnings)
        return AdapterInspectionMetadata(dialect=dialect, warnings=tuple(warnings))


def _detect_dialect(sample: str, *, warnings: list[str]) -> DialectInfo:
    if not sample:
        warnings.append("CSV file is empty; dialect detection used default values.")
        return _default_dialect()

    try:
        sniffed = csv.Sniffer().sniff(sample)
    except csv.Error:
        warnings.append("Could not detect CSV dialect from the bounded sample.")
        return _default_dialect()

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


def _default_dialect() -> DialectInfo:
    return DialectInfo(
        delimiter=None,
        quote=None,
        escape=None,
        header=None,
        encoding="utf-8",
    )


def _create_csv_adapter() -> CSVSourceAdapter:
    return CSVSourceAdapter()


CSV_ADAPTER_DESCRIPTOR = SourceAdapterDescriptor(
    kind="csv",
    access_mode="read_only",
    capabilities=CSV_CAPABILITIES,
    dependency=None,
    extra=None,
    factory=_create_csv_adapter,
)

DEFAULT_SOURCE_ADAPTER_REGISTRY = SourceAdapterRegistry((CSV_ADAPTER_DESCRIPTOR,))
