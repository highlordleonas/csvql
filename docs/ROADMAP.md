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

LocalQL v1.0.5 is the shipped CSV-first foundation. It can:

- query one CSV or join named CSV tables with DuckDB SQL;
- save repeatable work in `.csvql.yml` project catalogs;
- run saved SQL and export results;
- inspect, sample, profile, and validate local sources;
- produce JSON output for automation-oriented commands; and
- provide an optional interactive terminal menu.

See the [changelog](../CHANGELOG.md) for release history. Future priorities
remain evidence-led and require concrete planning and validation before
implementation.

## Milestone spine

The milestones below preserve dependency order. Their statuses describe
direction, not current availability.

### v1.1 — Bounded Results and Source Foundations

Status: `Planned`

Depends on the shipped v1 foundation.

- Introduce `SourceSpec`, `SourceAdapter`, and explicit capability contracts.
- Route CSV through the adapter boundary first.
- Replace unbounded full-result materialization with bounded or streaming
  result behavior.
- Make result-size behavior consistent across the CLI, terminal menu, exports,
  and Python API.
- Report source type, capabilities, and missing optional dependencies clearly.
- Prove compatibility, bounded memory behavior, cancellation, and cleanup.

### v1.2 — Local Structured Formats

Status: `Planned`

Depends on v1.1.

- Add Parquet, including partitioned datasets.
- Add JSON and NDJSON with explicit record-path and schema hints.
- Add Excel with sheet selection and documented type conversion.
- Provide safe source detection with explicit overrides.
- Support cross-format joins.
- Keep optional catalog metadata compatible with readable v1 catalogs.

Network databases, APIs, object stores, warehouses, and credential handling
remain outside v1.x.

### Point-and-Query product direction

Status: `Planned`

This is planned product direction, not shipped behavior.

- Support one-shot source detection and optional reusable catalog entries.
- Cover files, databases, object stores, warehouses, and structured HTTP APIs
  through explicit source capabilities.
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

LocalQL v1.0.5 does not ship remote or cloud connectors or a plugin ecosystem.
Future connector support remains planned or candidate work, and a third-party
SDK remains conditional on first-party contract proof. LocalQL is not a hosted
analytics platform and does not claim universal connector support.

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
