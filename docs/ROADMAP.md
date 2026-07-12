# Roadmap

Status: Maintainer-approved product direction; milestone delivery states below.

LocalQL is moving from a dependable local CSV workflow toward a structured-data
query tool with a simple promise: install LocalQL, point it at a structured
source, and query it with SQL.

The released v1.0.1 contract remains CSV-first. Future milestones do not change
current behavior until their implementation and acceptance evidence exist.

## Current Release

LocalQL v1.0.1 provides:

- local CSV queries and joins through DuckDB SQL;
- `.csvql.yml` project catalogs and saved SQL;
- inspect, sample, profile, doctor, and configured data-quality checks;
- JSON and human-readable output plus explicit exports;
- a small project-backed Python API; and
- an optional terminal workbench.

The repository is in post-1.0 maintenance and product-foundation work. v1.0.2
is the active stewardship and reliability milestone; its product-code items
remain unstarted.

## Maintainer Disposition

On 2026-07-12, the maintainer approved the structured-data product direction,
the phased v1.x path, and the DuckDB-native adapter architecture with a bounded
Arrow fallback. That approval establishes product intent. It does not make this
roadmap an implementation plan, approve implementation, or prove any milestone
complete. Architecture, implementation, verification, and release remain
separate decisions.

## v1.0.2 — Stewardship And Reliability

Status: In Progress

Objectives:

- align the local quality gate with CI's frozen lockfile behavior;
- disclose and verify TUI temporary result-spill behavior;
- add portable TUI navigation where terminals intercept function keys;
- establish a bounded large-result policy;
- reduce duplicated release-version configuration; and
- keep concise public repository governance without restoring removed internal
  launch artifacts.

Acceptance criteria:

1. The frozen local gate and exact-HEAD cross-platform CI pass.
2. TUI spill lifecycle, permissions, cleanup, and abnormal-exit behavior have
   tests and public documentation.
3. Results, History, and Help have verified portable navigation paths.
4. Release identity has one validated source without weakening manual release
   approval, OIDC isolation, or post-publish verification.
5. No CLI, Python, catalog, JSON, or export compatibility regression exists.

## v1.1 — Bounded Results And Source Foundations

Status: Planned

Objectives:

- introduce internal `SourceSpec`, `SourceAdapter`, and capability contracts;
- implement the existing CSV behavior through that boundary first;
- replace complete Python `fetchall()` materialization with an explicit bounded
  or streaming result contract;
- define consistent result-size behavior for CLI, TUI, exports, and Python API;
  and
- add diagnostics for detected source type, supported operations, and required
  optional dependencies.

Acceptance criteria:

1. Existing v1 CSV commands, catalogs, JSON output, Python API, and exit codes
   remain compatible or have an approved migration note.
2. Large-result tests record peak memory and prove deterministic cleanup.
3. CSV adapter contract tests become the reusable baseline for later formats.
4. No connector installs packages or DuckDB extensions silently.

## v1.2 — Local Structured Formats

Status: Planned

Objectives:

- add Parquet, including partitioned datasets where support is reliable;
- add JSON and NDJSON with explicit record-path or schema hints for ambiguity;
- add Excel with sheet selection and documented type conversion;
- auto-detect formats with an explicit override;
- support one-shot queries and cross-format joins; and
- persist optional source metadata without breaking v1 catalogs.

Network databases, structured HTTP APIs, cloud object stores, warehouses, and
credential handling remain out of v1.x.

Acceptance criteria:

1. Each format passes the shared adapter contract.
2. Inspect, sample, profile, doctor, query, and errors are source-aware.
3. Cross-format joins pass reproducible tests.
4. Supported Python and operating-system targets pass from installed artifacts.
5. Performance claims cite candidate-specific benchmark evidence.

## v2.0 — Point And Query

Status: Product direction approved; proving-release scope proposed; Not Started

Product promise:

> Install LocalQL, point it at a structured source, and query it with SQL.

The maintainer-approved v2 direction includes:

- one-shot source detection with optional catalog persistence;
- files, databases, object stores, warehouses, and structured HTTP APIs;
- a DuckDB-native adapter path with bounded Arrow batches as the fallback;
- lightweight core installation, source-specific extras, and `localql[all]`;
- environment and provider-profile credentials, plus optional operating-system
  keychain integration;
- read-only LocalQL-managed remote connector operations;
- cross-source joins; and
- consistent capabilities, diagnostics, errors, cancellation, and cleanup.

The proposed v2.0 proving release is deliberately narrow. It must demonstrate
three distinct vertical slices end to end:

- Parquet as the native local/columnar slice built on the v1.2 foundation;
- PostgreSQL as the credentialed relational slice; and
- a bounded, read-only structured HTTP JSON API as the network and Arrow
  fallback slice.

CSV compatibility remains required, but it is not counted as a new v2 slice.
v2.0 carries forward the verified v1.x local-format baseline. Parquet remains a
proving slice to demonstrate reuse of the native adapter contract, not to
introduce it a second time.
Each proving slice must cover one-shot querying, optional catalog persistence,
capabilities, diagnostics, bounded results, cleanup, packaging, installed-
artifact proof, and the applicable security gates. Cross-source joins among
the proving slices are part of the release gate.

See [Point And Query Design](v2-point-and-query-design.md) for the maintainer-
approved product boundaries and the proposed architecture, credential model,
and delivery gates.

## v2.x Evolution

The target ecosystem remains broader than the proving release. Candidate v2.x
lanes, subject to separate approval and connector-specific evidence, include:

- SQLite, DuckDB, MySQL, S3, Google Cloud Storage, Azure Blob Storage, HTTPS
  file sources, Snowflake, BigQuery, Redshift, Databricks, SQL Server, Oracle,
  GraphQL, document databases, and additional warehouses;
- a stable third-party connector SDK after first-party adapters prove the
  contract; and
- connector-specific pushdown and cost diagnostics.

## Product Boundaries

The current and planned product remains SQL-centered and structured-data
oriented. The roadmap does not authorize:

- free-text document search or a vector database product;
- natural-language SQL generation;
- a distributed or federated SQL planner;
- write-oriented ETL or remote mutation by default;
- silent dependency, extension, or connector installation;
- embedded secrets in tracked catalogs; or
- unsupported claims that every source works on day one.

The phrase “query anything” describes an extensible structured-source direction.
Public release documentation must always list the exact connectors actually
implemented and verified.
