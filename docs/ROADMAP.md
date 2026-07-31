# Roadmap

LocalQL grows from a dependable local CSV workflow toward a broader way to
query structured sources without hiding capability, safety, or compatibility
boundaries.

## Authority

This roadmap is the canonical public source for future product direction.
Shipped behavior is defined by the code, tests, user documentation, changelog,
and release notes for a release.
A roadmap status does not make a feature available.

Roadmap direction still requires concrete planning and validation before
implementation.

## Product promise

Install LocalQL, point it at a structured source, and query it with SQL.

This promise guides future work. It does not imply that every structured source
or connector described below is available today.

## Status vocabulary

- **Shipped** — available in a published release and documented as supported.
- **Active** — work currently being implemented or validated.
- **Planned** — adopted direction that still requires implementation and
  release evidence.
- **Candidate** — a useful option that needs a deliberate product decision
  before it becomes planned work.
- **Deferred** — adopted or considered direction intentionally postponed.
- **Superseded** — direction replaced by a newer public decision.

## Current foundation

LocalQL v1.2.0 is the shipped local structured-format foundation. It can:

- query and join CSV, Parquet, JSON, NDJSON, and Excel sources with DuckDB SQL;
- open explicitly typed partitioned Parquet directories without recursive
  dataset guessing;
- select a provider deterministically from explicit intent or a recognized
  extension, while reporting bounded evidence and requiring a choice when a
  source remains ambiguous;
- use the same normalized source definitions and provider options across the
  CLI, LocalQL Workbench, project catalogs, and Python API;
- write version 2 `.csvql.yml` source definitions while keeping version 1
  catalogs readable;
- inspect, sample, profile, and validate supported local sources;
- run saved SQL and export complete results as CSV, the LocalQL JSON envelope,
  record-oriented NDJSON, typed Parquet, Excel, Markdown, or text;
- bound interactive `csvql query` and `csvql run` table previews to 1,000 rows
  while keeping query/run JSON output, Python API results, and exports complete;
- produce JSON output for automation-oriented commands; and
- provide the optional LocalQL Workbench with preserved complete results under
  one 1 GiB session capacity and no automatic eviction.

See the [changelog](../CHANGELOG.md) for release history. Future priorities
remain evidence-led and require concrete planning and validation before
implementation.

## Milestone spine

The milestones below preserve dependency order. Their statuses describe
direction, not current availability.

### v1.1 — Bounded Results and Source Foundations

Status: `Shipped`

Depends on the shipped v1 foundation.

Shipped in LocalQL 1.1.1.

- Introduced private `SourceSpec`, `SourceAdapter`, and explicit capability
  contracts, routing CSV through the adapter boundary first.
- Added bounded or streaming result behavior for the interactive CLI, terminal
  menu, and exports.
- Bounded interactive CLI table output and terminal menu previews. Exports remain
  complete, the Python API remains complete, and query/run JSON output remains
  complete in v1.1.
- Preserved complete terminal-menu results under one 1 GiB session capacity
  with no automatic eviction, while reporting preview-only results truthfully
  when capacity is exhausted.
- Reported source type, capabilities, and missing optional dependencies clearly.
- Proved compatibility, bounded memory behavior, cancellation, and cleanup.

### v1.2 — Local Structured Formats

Status: `Shipped`

Depends on v1.1.

Shipped in LocalQL 1.2.0.

- Added Parquet files and explicitly typed partitioned datasets.
- Added JSON and NDJSON with bounded inference, explicit schemas, and fixed
  record paths.
- Added Excel with explicit dependency provisioning, sheet and range selection,
  and documented type conversion.
- Centralized deterministic source detection: explicit type first, recognized
  extension second, and bounded evidence without heuristic selection for
  ambiguous files or directories.
- Added provider-option and diagnostic parity across the CLI, LocalQL
  Workbench, project catalog, and Python API.
- Added cross-format joins and shared inspect, sample, and profile operations.
- Added NDJSON, Parquet, and Excel result exports across the CLI, Python API,
  and Workbench, with an end-to-end multi-format benchmark matrix.
- Added normalized version 2 source definitions while preserving readable
  version 1 catalogs.
- Kept provider registration internal rather than introducing a public plugin
  SDK before first-party providers prove the extension boundary.

Network databases, APIs, object stores, warehouses, and credential handling
remain outside v1.x.

### Point-and-Query product direction

Status: `Planned`

This is planned product direction for extending the v1.2 registered-provider
foundation beyond local files. The remote and database behavior below is not
shipped behavior.

- Extend explicit source registration to databases, object stores, warehouses,
  and structured HTTP APIs without changing deterministic selection rules.
- Prefer DuckDB-native adapters where available and use a bounded Arrow
  fallback where needed.
- Keep source-specific dependencies in explicit optional extras, with a
  convenience extra for users who deliberately want the full supported set.
- Store credential references rather than literal secrets, support optional
  operating-system keychain integration, and redact sensitive values at
  user-visible boundaries.
- Enforce read-only behavior for LocalQL-managed remote connectors.
- Support cross-source joins with consistent diagnostics, errors, bounds,
  cancellation, and cleanup.

### Exact v2.0 proving release

Status: `Candidate`

Depends on v1.1 and v1.2.

The candidate proving release would validate three deliberately different
slices:

- Parquet as a local structured source;
- PostgreSQL as a database source; and
- a bounded, read-only HTTP JSON API source.

Promotion to `Planned` requires a deliberate public roadmap status change after
the prerequisite foundations have evidence.

### v2.x evolution

Status: `Candidate`

Potential later connectors include SQLite, DuckDB, MySQL, S3, GCS, Azure Blob,
HTTPS files, Snowflake, BigQuery, Redshift, Databricks, SQL Server, Oracle,
GraphQL, document databases, and other warehouses.

A third-party connector SDK remains candidate work until first-party connectors
prove the contract. Pushdown and cost diagnostics are also candidates. These
items are candidates, not shipped support, and do not imply universal coverage.

## Unscheduled candidates

These ideas remain useful but are not scheduled milestones:

- explicit, user-controlled result materialization or caching;
- additional export formats;
- a richer Python API after real usage feedback;
- safe mode after a separate security design; and
- further editor improvements such as line numbers, syntax highlighting,
  formatting, and persisted history.

## Product boundaries and non-goals

LocalQL v1.2.0 does not ship remote or cloud connectors or a public plugin
ecosystem. It provides an internal registered-provider boundary for its five
local source types. Future connector support remains planned or candidate work,
and a third-party SDK remains conditional on additional first-party contract
proof. LocalQL is not a hosted analytics platform and does not claim universal
connector support.

The roadmap does not pursue:

- natural-language SQL generation;
- free-text or vector retrieval as a core product direction;
- a distributed query planner;
- write-oriented ETL or default mutation of remote sources;
- a LocalQL-managed secret vault;
- silent dependency installation; or
- universal connector support without explicit, tested capability boundaries.

## Point-and-Query safeguards

These product constraints apply to future source and connector work:

- Existing v1 catalogs remain readable. Any migration must be explicit,
  previewable, and reversible.
- Connector packages, optional dependencies, and DuckDB extensions are never
  installed silently. Missing capabilities must have explicit guidance.
- Saved catalogs contain credential references, never literal secrets such as
  passwords, tokens, access keys, or sensitive headers. Sensitive values and
  authenticated locators must be redacted from output, errors, logs, history,
  screenshots, tests, and validation artifacts.
- Remote read-only behavior is an enforced connector property, backed by
  provider controls and least-privilege credentials where available. A
  documentation promise or SQL keyword filter is not enough.
- Every remote connector requires a connector-specific threat model. URL-based
  connectors also require a network-target and SSRF policy covering schemes,
  redirects, private-network handling, and DNS rebinding.
- Network operations require bounded timeouts, response and transfer limits,
  safe retries, cancellation, and deterministic cleanup.
- A connector is supported only after shared capability tests, negative
  mutation tests where applicable, bounded-result and cleanup evidence,
  package-extra verification, user documentation, and installed-artifact proof.
- Public release documentation names
  the exact implemented and verified connectors. Extensibility does not justify
  a universal-support claim.

## Change discipline

Adopted direction must not disappear silently. When a roadmap change removes,
narrows, or redirects it, mark the affected item `Deferred` or `Superseded`,
name the replacement direction when one exists, and state
the public product reason for the change.

Keep shipped behavior in release history instead of rewriting it as future
work. This document records product decisions in public, maintainer-facing
language.
