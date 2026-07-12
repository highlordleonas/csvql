# LocalQL v2 Point And Query Design

| Field | Value |
| --- | --- |
| Status | Maintainer-approved product direction; proposed architecture; implementation not approved |
| Audience | Maintainer, contributors, reviewers, and future connector authors |
| Decision authority | Project maintainer |
| Maintainer disposition | On 2026-07-12 the maintainer approved the product direction and DuckDB-native architecture with bounded Arrow fallback |
| Canonical relationship | Expands `docs/ROADMAP.md`; does not replace current `docs/ARCHITECTURE.md` or v1 contracts |
| Maintenance trigger | Revisit when a v1 source-foundation plan is approved, a connector changes scope, or implementation evidence disproves an assumption |

## Product Promise

Install LocalQL, point it at a structured source, and query it with SQL.

“Structured source” includes files, columnar formats, relational databases,
object stores, warehouses, and HTTP APIs that expose records with a stable or
describable shape. It does not include arbitrary free-text documents, vector
search, or natural-language query generation.

## Experience

One-shot querying is the primary path:

```bash
csvql query orders.parquet "SELECT status, count(*) FROM orders GROUP BY status"

csvql query postgres://analytics/orders \
  "SELECT customer_id, total FROM orders LIMIT 100"

csvql query https://api.example.com/orders \
  "SELECT * FROM orders WHERE status = 'open'"
```

Catalogs remain optional for repeatable or cross-source work. This S3 example
illustrates target v2.x behavior; S3 is not part of the proposed v2.0 proving
release:

```bash
csvql query \
  --source orders=postgres://analytics/orders \
  --source events=s3://analytics/events/*.parquet \
  "SELECT * FROM orders JOIN events USING (order_id)"
```

Automatic behavior is required only when detection is safe. Ambiguous APIs,
workbooks, and databases can require a table, sheet, record path, pagination
strategy, schema hint, or explicit source type.

## Architecture Direction

DuckDB remains the SQL engine. LocalQL owns source discovery, validation,
credential resolution, capability reporting, registration, bounded result
handling, errors, and workflow UX. It does not implement a federated query
planner or SQL dialect translator.

The architecture is a deliberately asymmetric hybrid:

1. Prefer a DuckDB-native reader or controlled extension.
2. Use bounded Arrow record batches when no reliable DuckDB-native path exists,
   especially for structured HTTP APIs.
3. Never convert through both paths without a concrete need.
4. Keep SQL execution in DuckDB for both paths.

This approach captures DuckDB's format and connector ecosystem while allowing
LocalQL to normalize pagination, schema, and streaming for sources DuckDB cannot
consume directly.

## Source Contract

A typed `SourceSpec` should represent:

- source type and locator;
- optional alias, table, sheet, record path, object pattern, or dataset;
- format, schema, and pagination hints;
- credential references; and
- validated connector-specific options.

Each `SourceAdapter` should expose:

- detection and validation;
- capability description;
- DuckDB relation registration or bounded Arrow batch production;
- schema inspection and bounded sampling;
- profile and data-quality support where meaningful;
- dependency, extension, credential, and network requirements;
- cancellation and deterministic cleanup; and
- source-specific diagnostic context without secrets.

Capability negotiation must make partial support explicit. A connector that can
query and sample but cannot profile or push down filters must report that truth
instead of emulating unsupported behavior silently.

## Result Contract

The current v1 engine builds complete Python tuples from `fetchall()`. That
contract must not become the v2 foundation.

The replacement must:

- support bounded previews and streaming export;
- avoid full Python materialization before TUI spill decisions;
- expose columns, progress, row counts when known, and truncation state;
- preserve deterministic cleanup and cancellation;
- support a compatibility materialization method for small Python API results;
  and
- make memory, temporary disk, and remote-transfer behavior observable.

No implementation option is approved yet. Viable choices include DuckDB record
batches, Arrow record batches, and cursor-backed iteration. The v1.1 planning
lane must benchmark alternatives before selecting one.

## Credential Model

Credential resolution is a hybrid that borrows convenience without making
LocalQL a secret-vault product.

Catalogs may store safe connection metadata and references, including:

- environment-variable names;
- cloud or database profile names;
- operating-system keychain entry names; and
- anonymous or provider-default credential selection.

Catalogs must reject literal passwords, tokens, access keys, and sensitive API
headers when saved.

Resolution order is deterministic:

1. session-only prompt or standard-input value;
2. named operating-system or provider profile;
3. named environment-variable reference; and
4. provider default chain.

`localql[keychain]` may integrate with macOS Keychain, Windows Credential
Manager, and Linux Secret Service through maintained libraries. LocalQL does not
design its own encryption format, recovery mechanism, or master-key lifecycle.

Diagnostics may state which credential source was selected but never its value.
Credentials, sensitive headers, and complete authenticated connection strings
must be redacted from output, exceptions, TUI history, logs, tests, screenshots,
and proof artifacts.

## Installation Model

- `localql` contains the core CLI, DuckDB engine, and common local formats.
- Source-specific extras such as `localql[postgres]` install explicit connector
  dependencies.
- `localql[keychain]` enables optional operating-system credential integration.
- `localql[all]` installs every supported first-party connector.
- Missing capabilities return an exact install command.
- LocalQL never silently installs Python packages, connectors, or DuckDB
  extensions.

## Initial Source Coverage

The proposed v2.0 release is a contract-proving release, not the complete
connector ecosystem:

| Slice | Proposed source | Contract it must prove |
| --- | --- | --- |
| Native local/columnar | Parquet | v1.2 source reuse, DuckDB-native registration, bounded results, installed-artifact behavior |
| Credentialed relational | PostgreSQL | explicit extra, credential references and redaction, provider read-only controls, cancellation |
| Network/Arrow fallback | Bounded structured HTTP JSON API | target policy, pagination and transfer limits, Arrow batches, timeouts, SSRF defenses |

v2.0 carries forward the verified v1.x local-format baseline. CSV remains a
required compatibility baseline, and Parquet is retained as a proving slice to
demonstrate reuse of the native adapter contract rather than introduce the
format again. Cross-source joins among CSV and the three proving slices are
required. API pagination may support offset/page, cursor, and link-header
strategies when configured or safely detected.

## Target v2.x Ecosystem

Candidate v2.x source packs include SQLite, DuckDB, MySQL, S3, Google Cloud
Storage, Azure Blob Storage, HTTPS file sources, Snowflake, BigQuery, Redshift,
and Databricks where stable integration exists.

SQL Server, Oracle, GraphQL, document databases, and less common systems belong
in prioritized v2.x source packs rather than blocking v2.0.

## Safety And Operations

- **LocalQL-managed connector operations are read-only; LocalQL is not a SQL
  sandbox. User SQL remains trusted.**
- The DuckDB-native/Arrow hybrid is a data-path choice, not a safety control.
- Every remote connector requires a connector-specific threat model before
  implementation. It must cover credential scope, native extension behavior,
  handle exposure to trusted SQL, redirects, and network targets as applicable.
- Read-only is an enforced connector property, not a documentation promise.
  Adapters must use provider read-only connection modes and least-privilege
  credentials where available, and must not expose a write-capable remote handle
  to user SQL. A connector without a defensible enforcement path is not eligible
  for the v2.0 set. SQL keyword filtering or documentation alone is not an
  enforcement path.
- Negative proof must show that connector credentials and DuckDB-native
  extensions do not expose unintended remote mutation paths to trusted SQL.
- Network access is explicit and visible.
- URL-based adapters require an approved network-target and SSRF policy before
  implementation, including scheme restrictions, redirect behavior, private
  network handling, and DNS-rebinding considerations.
- HTTP clients use bounded timeouts, pagination, response sizes, and retries.
- Retries apply only to safe, idempotent reads.
- Cancellation closes cursors, clients, streams, and temporary resources.
- Temporary materialization is disclosed; hidden persistent caching is
  prohibited.
- Cross-source queries expose which systems are contacted and which data is
  transferred locally.
- Connector errors distinguish dependency, authentication, authorization,
  timeout, source-shape, capability, query, and local-write failures.
- Sensitive values are redacted before they reach shared error or output layers.

## Error Contract

All adapters must classify these failures consistently:

1. Source cannot be found or reached.
2. Connector extra or extension is missing.
3. Authentication is missing, rejected, or expired.
4. Network request timed out or exhausted bounded retries.
5. Source type or schema cannot be detected safely.
6. Requested table, sheet, record path, object, or capability is absent.
7. Pagination, response-size, result-size, or transfer limit was reached.
8. DuckDB rejected the SQL or source registration.
9. Temporary or exported output could not be written.

Errors identify the affected source and a corrective action without exposing
credentials, private headers, or full authenticated locators.

## Connector Definition Of Done

Every source advertised as supported by a LocalQL release requires:

- one-shot point-and-query proof;
- optional catalog save and reload;
- schema inspection, bounded sampling, and diagnostics;
- explicit capability declarations;
- credential selection and redaction tests;
- negative tests proving remote mutation attempts are rejected or impossible;
- network-target and redirect tests for URL-based connectors;
- timeout, cancellation, cleanup, and failure-path tests;
- bounded-memory or streaming evidence;
- minimal working documentation;
- supported Python and operating-system evidence; and
- package-extra and missing-dependency tests.

Testing includes a shared adapter contract, deterministic local fixtures,
container integration tests for databases, recorded API fixtures, narrow
credential-gated live smoke tests, cross-source joins, performance evidence,
and installed-package verification.

## v2.0 Release Gates

v2.0 is not releasable until:

1. Every source advertised as supported by the v2.0 release passes the shared
   connector contract.
2. Catalog v1 migration and rollback are proven.
3. Credentials are absent from catalogs, output, errors, history, and artifacts.
4. Large results no longer require complete Python `fetchall()` materialization.
5. Network timeouts, retries, cancellation, and cleanup are deterministic.
6. Every remote connector proves read-only enforcement with least-privilege
   setup and negative mutation tests.
7. URL-based connectors pass the approved SSRF/network-target policy tests.
8. Cross-source joins pass reproducible integration tests.
9. Packaged extras match supported-source documentation.
10. Exact release artifacts pass installed-wheel and connector smoke tests.
11. Manual terminal and credential-flow QA is recorded.

## Compatibility And Migration

The v1 `.csvql.yml` format remains readable. A v2 migration must be explicit,
previewable, and reversible. Existing CSV aliases should map to the new source
model without requiring users to rewrite working projects immediately.

CLI, JSON, Python API, and exit-code changes require versioned contracts or
documented compatibility behavior. Proposed v2 functionality does not alter the
released v1 contract before implementation and acceptance.

## Non Goals

- Free-text document search or vector retrieval.
- Natural-language SQL generation.
- A distributed or federated query planner.
- Write-oriented ETL or remote mutation by default.
- A LocalQL-owned encrypted secret vault.
- Silent dependency or extension installation.
- Claiming universal source support without connector-specific evidence.

## Planning Authorization

This roadmap and design record product direction. They authorize neither
planning nor implementation by themselves.

Planning for v1.1 or a later slice may begin only after:

1. the v1.0.2 reliability lane is verified; and
2. the maintainer explicitly authorizes preparation of a plan for the named
   slice.

Planning authorization ends with a proposed plan. It does not authorize code,
dependency, lockfile, network, connector, or release changes.

## Plan Approval

A slice plan is eligible for approval only when it defines scope, acceptance
evidence, compatibility impact, tests, rollback, and phased delivery. The plan
must identify every prerequisite decision that applies to that slice, including:

- the benchmark-backed bounded result contract and `SourceSpec`/capability
  contract for the v1.1 foundation;
- catalog, JSON, CLI, Python API, and exit-code compatibility;
- connector dependencies and DuckDB extension policy;
- credential, remote read-only, network-target, and URL/SSRF threat models; and
- package extras and installed-artifact verification.

Each applicable architecture, compatibility, security, and package decision is
reviewed explicitly. Plan approval does not authorize implementation.

## Slice Implementation Authorization

Implementation of a named slice may begin only after:

1. its implementation plan is approved;
2. its applicable architecture, compatibility, security, and package decisions
   are accepted;
3. its prerequisite foundation is verified; and
4. the maintainer separately authorizes implementation of that named slice.

The prerequisite foundation is milestone-specific:

- v1.1 implementation requires verified v1.0.2 reliability work;
- v1.2 implementation requires the verified v1.1 source and bounded-result
  foundation; and
- any v2 source implementation requires the verified v1.1 foundation.

Verified v1.2 is not required before every v2 connector implementation. It is
required before the Parquet reuse proof can be accepted and before v2.0 release
approval.

## v2.0 Release Approval

v2.0 release approval requires:

1. the v1.2 local-format baseline, including Parquet, to be verified;
2. every source advertised as supported by v2.0 to satisfy the connector
   definition of done; and
3. every item in the v2.0 release gates to pass against the exact release
   artifacts.

Planning authorization, plan approval, implementation authorization,
verification, and release approval are separate decisions. No earlier decision
implies a later one.
