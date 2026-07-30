# Architecture

LocalQL is a local query application built around DuckDB and pluggable source
providers. It is not a custom database, orchestration system, public plugin
SDK, or SQL sandbox.

## Core flow

Every application surface translates user intent into the same immutable
`SourceRequest`. That request is the universal input boundary; later layers use
progressively narrower values instead of carrying raw CLI, Python, catalog, or
TUI inputs through the system.

```text
CLI / Python API / TUI / catalog
  -> SourceRequest
  -> SourceDetectionService
  -> DetectionResult
  -> SelectedSource
  -> AdapterFactory
  -> SourceAdapter
  -> ResolvedSource
  -> RelationalBinding
  -> DuckDB query engine
  -> ResultStream
  -> JSON / table preview / Python result / export / TUI result store
```

`DetectionResult` is a tagged outcome. Only `SelectedSource` may enter the
factory; ambiguous, unsupported, unknown, and invalid outcomes carry
deterministic evidence and a required next action.

`SourceCoordinator` sequences detection, lazy provider activation, resolution,
binding, and cleanup. It enforces transitions and failure cleanup but contains
no format-specific rules, option normalization, SQL execution, presentation,
or dependency-container behavior.

## Deterministic source selection

Selection follows one order:

1. An explicit source type wins.
2. One recognized extension selects its descriptor.
3. Otherwise, bounded identifiers may report possible matches, but LocalQL
   never selects from that evidence.

Identifiers are local, read-only, bounded, deterministic, and non-recursive.
An untyped directory is always ambiguous. Partitioned Parquet directories
therefore require explicit intent. Diagnostics explain the evidence, why
automatic selection stopped, and the required next action.

## Descriptor, identifier, and adapter boundaries

`DescriptorRegistry` contains immutable, import-free provider metadata:
provider and source keys, recognized extensions, locator shapes, option
metadata, dependency requirements, identifier registration, and an opaque
factory key. Detection sees descriptors and identifiers, never adapter classes
or constructors.

`AdapterFactory` independently maps factory keys to lazy constructors. Startup
composition validation proves that descriptor, identifier, and factory
registrations agree. Optional provider modules and dependencies are activated
only after deterministic selection.

Built-in providers currently expose:

- CSV
- Parquet files and explicitly typed partitioned datasets
- JSON documents
- NDJSON/JSON Lines records
- Excel `.xlsx` workbooks when DuckDB's optional `excel` extension is available

This is an internal extension boundary, not a public plugin framework. Adding a
built-in provider is registration work; it does not change the detection
pipeline.

## Capabilities and relational responsibilities

Descriptors declare metadata needed before activation. Adapters implement
behavioral source protocols for resolution and relational binding. Resolved
sources contain reproducibility facts and normalized semantic options without
owning open resources. Relational bindings own the session-scoped relation and
its cleanup.

Providers expose relational data. Filtering, projection, joins, sorting,
aggregation, and result export remain engine or result-pipeline
responsibilities. Provider-specific code does not reimplement relational
operations.

## Lifecycle and failure handling

Resolution captures source identity before a relation is registered. Binding
revalidates the source and registers one alias in one engine session. Bindings
are released in reverse ownership order on success, failure, or cancellation.
Cleanup failures are typed, and an uncertain engine session becomes tainted
rather than being silently reused.

The current provider boundary is synchronous. Textual runs synchronous source
work in workers; no adapter-specific async protocol is exposed. A future async
transport would require an explicit application boundary rather than mixed
sync/async adapter methods.

## Project catalogs

Project discovery finds the nearest `.csvql.yml`.

- Version 1 is a strict CSV compatibility schema. It preserves its original
  shape and is never silently migrated.
- Version 2 stores normalized user intent: source type, locator, explicit
  options, and table-level checks.

Catalogs do not persist detected candidates, inferred defaults, resolved
paths, dependency state, adapter objects, bindings, or runtime schemas.
Private TUI result-spool artifacts cannot be registered. Project-relative
locators remain portable; external locators remain explicit local intent.

## Application surfaces

`cli.py`
: Parses legacy CSV and provider-neutral source syntax, delegates workflows,
  renders shared diagnostics, and maps application outcomes to process exits.

`api.py`, `models.py`
: Expose `CSVQLSession`, the retained explicit-CSV `TableSource`, and the
  provider-neutral immutable `SourceDefinition`. They do not expose registry,
  adapter, factory, or binding objects.

`tui_state.py`, `tui_workflows.py`, `tui_query_runner.py`, `tui_app.py`
: Store source intent and presentation state, construct the shared request,
  run synchronous workflows in Textual workers, and render shared diagnostics.
  The TUI never keeps an adapter or open binding in session state.

`checks.py`, `doctor.py`
: Prepare catalog sources through the shared coordinator. Checks operate over
  relational bindings, including cross-format foreign keys. Doctor reports
  composition and selected-provider readiness without installing dependencies.

## Result pipeline

`CSVQLEngine` owns one in-memory DuckDB connection, source preparation,
trusted SQL execution, cancellation, and error conversion. `ResultStream` is a
single-consumer stream over one DuckDB cursor.

Interactive CLI output retains a `BoundedQueryResult` preview. JSON and Python
query results remain complete, while complete streaming export writes to an
atomically replaced destination.

The optional `TUIQueryRunner` executes each statement once. It displays a
bounded preview while `TUIResultStore` preserves the complete result in private
session storage under one 1 GiB aggregate capacity with no automatic eviction.
Capacity exhaustion produces a truthful preview-only result; LocalQL does not
evict prior results or rerun SQL. Explicitly saving a result creates a normal
project-local CSV source, never a hidden cache entry.

## Primary modules

- `source.py`: progressive source values, identities, diagnostics, and canonical
  request serialization
- `source_registry.py`: immutable descriptor metadata and composition findings
- `source_identifiers.py`: bounded identification evidence
- `source_detection.py`: deterministic selection and typed detection outcomes
- `adapter_factory.py`: lazy adapter construction and dependency activation
- `source_coordinator.py`, `source_runtime.py`: workflow sequencing and release
- `source_adapter.py`: behavioral adapter, engine-session, and binding protocols
- `csv_adapter.py`, `parquet_adapter.py`, `json_adapter.py`, `excel_adapter.py`:
  built-in provider behavior
- `project_config.py`: strict v1 and normalized v2 catalog models
- `query_workflow.py`, `source_operations.py`, `checks.py`, `doctor.py`:
  application workflows over prepared sources
- `engine.py`, `result_stream.py`, `bounded_result.py`, `streaming_export.py`:
  relational execution and result handling
- `output.py`, `tui_*`: human, automation, and terminal presentation

## Platform invariants

- User-authored SQL is trusted local DuckDB SQL and is not sandboxed.
- Detection never imports or constructs adapters.
- Bounded identification never becomes heuristic selection.
- Directories are never recursively scanned to infer a provider.
- Optional dependencies are never installed during application startup or a
  query.
- Each provider registration has exactly one descriptor, identifier where
  declared, and factory mapping.
- Later lifecycle layers receive narrower domain values.
- Adapters expose relations; the engine owns relational operations.
- Runtime resources have one explicit owner and deterministic cleanup.
- Human and automation surfaces preserve the same diagnostic code, evidence,
  and required-action semantics.
