# Project Stewardship Audit

## 1. Metadata

| Field | Value |
| --- | --- |
| Status | Revised candidate; maintainer acceptance and repository adoption pending |
| Audit date | 2026-07-12 |
| Repository | `highlordleonas/csvql` |
| Evidence snapshot | Branch `main`, committed baseline `f238b6daff0adc048224743095a79def07d38056` (`v1.0.1`), plus the uncommitted working-tree diff listed below |
| Scope | Repository governance, product intent, architecture, workflow, packaging, tests, and local proof |
| Exclusions | Product implementation, dependencies, lockfile changes, remote mutation, Git mutation, publication, and release |

This is a historical audit record, not evergreen implementation truth. Code,
tests, current Git state, and adopted project documentation supersede any stale
observation here.

## 2. Executive Summary

### Direction verdict

The released product is coherent: LocalQL v1.0.1 is a local CSV query workflow
backed by DuckDB. The maintainer has approved a broader structured-data
direction and a DuckDB-native adapter architecture with bounded Arrow fallback.
Those decisions are recorded in a revised roadmap and design candidate, but the
files remain uncommitted and are not yet adopted repository authority.

The initial audit found nine material stewardship issues. This candidate makes
safe governance, documentation, packaging-policy, test, and local-gate
corrections. It does not implement TUI, result-streaming, connector, credential,
or release features.

### Most consequential conclusions

1. Current behavior and future direction must remain visibly separate.
2. Full Python result materialization is the central resource constraint before
   multi-source growth.
3. v2.0 is credible as a three-slice proving release, not as the whole target
   connector ecosystem.
4. LocalQL-managed connector operations must be read-only, while user SQL
   remains trusted; the hybrid data path is not a security control.
5. Current-tree proof is local macOS/Python 3.12 only. Remote matrix evidence
   applies to the committed baseline until a future adopted diff runs in CI.

### State vocabulary

- **Drafted:** text exists in the working tree.
- **Maintainer-approved direction:** the owner accepted the product intent.
- **Repository-adopted:** the artifact passed review and entered repository
  history.
- **Verified:** named evidence passed for the exact candidate.
- **Released:** an adopted, verified artifact was published through release
  controls.

No state implies the next one.

## 3. Scope, Coverage, And Limitations

### In scope

- repository instruction and authority layers;
- public product, contributor, architecture, security, and roadmap documents;
- source, tests, build metadata, workflows, and package-content controls;
- local Git history and current dirty-tree inventory;
- local quality, build, and archive inspection; and
- architecture change packets for changes too large to implement in this lane.

### Limitations

- No customer or usage research was performed.
- No remote system was accessed during this hostile-review revision.
- No cross-platform CI ran for the uncommitted candidate.
- No package was published and no connector exists to install-smoke.
- Manual cross-terminal TUI behavior was not exercised.
- The secondary automated review is advisory, not human, security, or release
  assurance.

### Evidence coverage

| Area | Coverage | Primary evidence |
| --- | --- | --- |
| Product intent | Exhaustive repository read | README, roadmap, contribution and support docs |
| Architecture | Targeted implementation trace | `docs/ARCHITECTURE.md`, engine, CLI, TUI result store |
| Quality | Full local gate for exact working tree | Make targets, Ruff, mypy, pytest |
| Packaging | Built wheel/sdist and archive inspection | `pyproject.toml`, package-audit script/tests |
| Delivery | Baseline-only remote evidence | CI and publish workflows at baseline HEAD |
| Runtime UX | Documentation and tests; no terminal matrix | TUI docs and tests |

## 4. Effective Authority Map

| Layer | Authority | Boundary |
| --- | --- | --- |
| Human | Maintainer instructions and explicit current-task approvals | Product intent and action authorization |
| Repository governance | Adopted root/nested instruction files | Workflow and contribution behavior |
| Released product | README, release notes, packaged behavior | v1.0.1 public contract |
| Current architecture | Architecture docs corroborated by code/tests | Implemented structure only |
| Future direction | Roadmap and v2 design after repository adoption | Proposal and milestone intent, not implementation authority |
| Implementation truth | `src/csvql/` and tests | Observed behavior |
| Delivery truth | Build metadata and workflows | Packaging and release mechanics |

The maintainer's 2026-07-12 conversational decisions are real product authority,
but uncommitted documents recording them remain candidate repository authority.
The roadmap now contains a dated durable maintainer disposition; normal Git
review remains the adoption mechanism.

## 5. Instruction Scope Matrix

| Scope | Applicable guidance | Revision outcome |
| --- | --- | --- |
| Repository root | Global instructions plus candidate `AGENTS.md` | Concise public project contract; sdist exclusion |
| `src/csvql/` | Root chain, architecture, tests | No implementation changes |
| `tests/` | Root chain and current contracts | Governance/package checks only |
| `docs/` | Root chain and current-vs-future labels | Roadmap/design remain proposals until adoption |
| `.github/` | Root chain and explicit release authority | Templates clarified; workflows unchanged |

## 6. Project Reality Model

| Question | Answer at evidence snapshot | Confidence |
| --- | --- | --- |
| What exists? | Local CSV CLI/API/TUI with DuckDB, catalogs, checks, and exports | High |
| What is released? | `localql` v1.0.1, command/import `csvql` | High |
| What is proposed? | v1.x foundations/local formats and v2 structured-source expansion | High |
| What is active? | An uncommitted v1.0.2 governance/reliability candidate | High |
| What is not implemented? | Source adapters, bounded results, non-CSV sources, remote connectors | High |
| What remains uncertain? | Detailed implementation plans, connector threat models, measured budgets | High |

## 7. Declared Versus Observed

| Topic | Declared | Observed | Disposition |
| --- | --- | --- | --- |
| v1 scope | Local CSV and trusted DuckDB SQL | Matches code/tests | Preserve |
| TUI large results | Previously implied memory-only behavior | Session store spills after an in-memory threshold | Documentation corrected |
| Result bounds | Future bounded/streaming goal | Engine uses complete `fetchall()` materialization | ACP-001 required |
| Local gate | Reproducible frozen validation | Sync and checks were coupled | Split `ci` and `ci-fresh` |
| v2 sources | Broad structured-data vision | No connector boundary exists | Three-slice proving release proposed |
| Remote safety | Read-only promise | No connector enforcement exists | Threat model and negative proof required |

## 8. Traceability Map

| Objective | Milestone | Evidence now | Missing proof |
| --- | --- | --- | --- |
| Stewardship/reliability | v1.0.2 candidate | Governance/docs/local gate revisions | Adoption, remote CI, remaining product-code work |
| Bounded result/source base | v1.1 | ACP-001/ACP-002 | Benchmarks, approved implementation plan |
| Local formats | v1.2 | Roadmap intent | Adapter implementation and installed artifacts |
| Point and Query | v2.0 | Proposed proving scope and design | All connector/security/package gates |
| Broader ecosystem | v2.x | Target list | Prioritization and connector-specific evidence |

## 9. Governance Maturity

| Dimension | Score (0-4) | Evidence | Gap |
| --- | --- | --- | --- |
| Product intent | 3 | Clear released contract and candidate roadmap | Candidate not adopted |
| Architecture | 3 | Current architecture plus bounded ACPs | No accepted source/result RFC |
| Traceability | 3 | Milestones, findings, acceptance gates | No issue tracker linkage |
| Test confidence | 3 | Full local gate and baseline CI matrix | Candidate lacks remote matrix |
| Release hygiene | 3 | Manual OIDC workflow and archive audit | No candidate publication proof |
| Agent usability | 3 | Concise candidate root instructions | Candidate not adopted |

## 10. Findings Ledger

### PSA-001: Public Agent Governance Was Removed With Internal Material

- **Severity:** Medium
- **Fact:** Baseline history removed large internal planning material and left no
  root project instruction file.
- **Inference:** A concise public contract can reduce rediscovery without
  restoring internal launch machinery.
- **Impact:** Contributors and agents can drift on tooling, scope, and authority.
- **Evidence:** Baseline tree/history; current repo commands and docs.
- **Counterevidence:** Existing public docs already cover end-user behavior.
- **Recommendation:** Adopt a root `AGENTS.md` under 100 lines and exclude it
  from source distributions.
- **Disposition:** Candidate correction drafted; adoption pending.

### PSA-002: Roadmap Had No Owned Post-1.0 Milestone

- **Severity:** High
- **Fact:** The baseline roadmap listed possible improvements without status,
  sequencing, acceptance criteria, or maintainer disposition.
- **Inference:** Broad feature requests could bypass reliability foundations.
- **Impact:** Scope and contribution authority were ambiguous.
- **Evidence:** Baseline roadmap and contribution templates.
- **Counterevidence:** The released v1 boundary itself was clear.
- **Recommendation:** Adopt status-bearing v1.x milestones and a narrow v2.0
  proving release, retaining the broader ecosystem as v2.x vision.
- **Disposition:** Candidate roadmap drafted; maintainer direction approved;
  repository adoption pending.

### PSA-003: TUI Storage Documentation Denied Automatic Disk Spill

- **Severity:** Medium
- **Fact:** The TUI result store spills large results to session-owned temporary
  files, while prior user documentation denied automatic temporary storage.
- **Impact:** Users could make incorrect privacy and disk assumptions.
- **Evidence:** `tui_result_store.py`, architecture and TUI docs.
- **Counterevidence:** Spill files are session-owned and cleaned normally.
- **Recommendation:** Describe threshold spill, lifecycle, and cleanup limits.
- **Disposition:** Documentation/tests corrected in candidate; abnormal-exit
  proof remains future work.

### PSA-004: Full Python Materialization Precedes Large-Result Spill

- **Severity:** High
- **Fact:** Query execution builds complete Python tuples with `fetchall()`
  before downstream TUI spill decisions.
- **Impact:** Large results can exhaust memory before bounded storage helps.
- **Evidence:** Engine/result/TUI call path.
- **Counterevidence:** Current CSV workflows and explicit export paths work for
  ordinary inputs.
- **Recommendation:** Benchmark and implement ACP-001 before connector growth.
- **Disposition:** Accepted architecture gap; no product code changed.

### PSA-005: Local Gate Conflated Environment Sync And Checks

- **Severity:** Medium
- **Fact:** The candidate initially made `make ci` always perform a frozen sync,
  which can mutate the environment or require downloads.
- **Impact:** Iteration and deterministic environment reproduction were
  conflated.
- **Evidence:** Makefile, CI workflow, observed fresh-cache behavior.
- **Counterevidence:** Sync-first is a strong reproducibility default.
- **Recommendation:** Keep explicit `sync`; make `ci` use `--no-sync`; add
  `ci-fresh` as sync plus full gate.
- **Disposition:** Candidate correction drafted and locally verified.

### PSA-006: Release Identity Is Repeated

- **Severity:** Medium
- **Fact:** Version expectations exist in package metadata, workflow input, and
  tests.
- **Impact:** A release bump can drift across surfaces.
- **Evidence:** `pyproject.toml`, publish workflow, release tests.
- **Counterevidence:** Manual dispatch and tests catch common mismatches.
- **Recommendation:** Design one validated release-identity source without
  weakening manual approval, OIDC isolation, or post-publish checks.
- **Disposition:** Deferred product/workflow change.

### PSA-007: Portable TUI Navigation Is Incomplete

- **Severity:** Medium
- **Fact:** Important panes rely on function keys that some terminals intercept.
- **Impact:** Results, History, or Help can be awkward or unreachable.
- **Evidence:** TUI bindings, docs, and existing automated tests.
- **Counterevidence:** Function keys work in supported terminal configurations.
- **Recommendation:** Add and manually verify portable alternatives.
- **Disposition:** Roadmapped; no TUI code changed.

### PSA-008: Current Source Contracts Are CSV-Shaped

- **Severity:** High
- **Fact:** CLI, engine, catalogs, and Python API accept CSV-oriented paths and
  aliases directly.
- **Impact:** Adding formats piecemeal would duplicate validation and errors.
- **Evidence:** Current interfaces and tests.
- **Counterevidence:** DuckDB already supplies multiple native readers.
- **Recommendation:** Introduce the adapter/capability boundary through CSV
  compatibility first; prove Parquet before remote connectors.
- **Disposition:** ACP-002 proposed; no implementation.

### PSA-009: Remote Read-Only Lacks An Enforcement Decision

- **Severity:** High
- **Fact:** Current SQL is trusted and unsandboxed; no remote connector layer
  exists. The proposed product promises read-only connector operations.
- **Impact:** A write-capable handle or extension could expose remote mutation
  to arbitrary trusted SQL.
- **Evidence:** Security docs and v2 proposal.
- **Counterevidence:** Provider read-only modes and least-privilege credentials
  can create defensible controls.
- **Recommendation:** Require connector-specific threat modeling, provider
  controls, handle isolation, negative mutation tests, and rejection where only
  docs or SQL filtering provide safety.
- **Disposition:** Candidate design boundary strengthened; implementation barred
  until separately approved and proven.

## 11. Corrections Applied In This Candidate

| Files | Correction | Why |
| --- | --- | --- |
| `AGENTS.md` | Concise project authority, boundaries, and validation contract | Restore usable governance without internal launch material |
| `docs/ROADMAP.md` | State model, dated maintainer disposition, phased v1.x, narrow v2.0 | Separate intent, adoption, verification, and release |
| `docs/v2-point-and-query-design.md` | Three proving slices and precise remote-read boundary | Make scope and safety claims credible |
| `Makefile`, contributor docs/templates | Split sync, current-environment CI, and fresh CI | Make mutation/reproducibility tradeoff explicit |
| `pyproject.toml`, package audit/tests | Exclude audit reports; retain public roadmap/design | Enforce explicit sdist policy |
| TUI/architecture docs and tests | Disclose result spill behavior | Align docs with implementation |
| This report | Condensed evidence/dispositions; named baseline snapshot | Avoid duplicative operational narrative |

## 12. Architecture Change Packets

### ACP-001: Bounded And Streaming Result Contract

| Field | Detail |
| --- | --- |
| Status | Proposed; no implementation authority |
| Architectural claim | Replace unconditional full Python materialization with a bounded/streaming result contract before source expansion |
| Evidence | Engine uses `fetchall()`; TUI spill occurs afterward |
| Counterevidence | Existing small-result API is simple and compatible |
| Objective/constraint | Bound memory while preserving v1 CLI, API, JSON, export, and cleanup contracts |
| Current architecture | DuckDB result becomes complete Python rows consumed by CLI/TUI/export/API |
| Failure mode | Memory exhaustion or long latency before spill/export |
| Consequence of no change | Connector growth multiplies transfer and memory risk |
| Trigger | Before v1.1 completion or any remote-source implementation |

#### Options

1. Keep materialization and document limits: lowest change, fails the product
   direction.
2. DuckDB record-batch/cursor result: best native path, requires compatibility
   adapters.
3. Arrow batches everywhere: uniform but adds overhead and dependency concerns
   for native sources.
4. **Recommended hybrid:** native cursor/record batches with bounded Arrow as an
   adapter fallback, exposed through one LocalQL result contract.

#### Delivery contract

- **Non-goals:** distributed execution, hidden cache, or unbounded background
  prefetch.
- **Affected systems:** engine, CLI renderers, TUI store, exports, Python API,
  JSON contracts, tests, and docs.
- **Compatibility/migration:** preserve current small-result materialization as
  an explicit compatibility method; version any JSON changes.
- **Data migration:** none; temporary-result lifecycle may change.
- **Security/privacy:** bounded temp permissions, deterministic deletion,
  redacted diagnostics, explicit spill disclosure.
- **Operations/observability:** expose truncation, rows when known, bytes,
  transferred/spilled state, cancellation, and cleanup failures.
- **Test strategy:** shared contract tests, memory benchmarks, cancellation,
  export streaming, TUI spill, failure cleanup, and installed-wheel proof.
- **Rollback:** retain the compatibility path and switch consumers incrementally.
- **Incremental plan:** result interface; CSV engine path; CLI/export; TUI;
  Python compatibility; remove unconditional materialization only after proof.
- **Risks/mitigations:** API churn via adapters; DuckDB behavior via pinned
  contract tests; temp leakage via lifecycle tests.
- **Open questions:** batch size, stable row-count semantics, Python streaming
  API, JSON truncation representation, and budgets.
- **Entry conditions:** benchmarks, compatibility decision, approved plan,
  measurable limits, and rollback tests.

### ACP-002: Structured Source Adapter And Point-And-Query Architecture

| Field | Detail |
| --- | --- |
| Status | Maintainer-approved direction; proposed architecture; adoption and implementation approval pending |
| Architectural claim | DuckDB remains the SQL engine; prefer native adapters and use bounded Arrow fallback behind one capability contract |
| Evidence | DuckDB fits current SQL model; HTTP/API sources need normalized pagination/batching |
| Counterevidence | Native extensions vary in maturity and can expose security/packaging complexity |
| Objective/constraint | One-shot structured-source querying with optional catalogs, explicit extras, no hidden install, and v1 compatibility |
| Current architecture | CSV-specific paths, aliases, catalog fields, and result materialization |
| Failure mode | Per-source branching, inconsistent errors, unsafe credential/network handling |
| Consequence of no change | “Point and query” becomes brittle integrations rather than a product contract |
| Trigger | After ACP-001 entry criteria and before non-CSV implementation |

#### Options

1. DuckDB-native only: small core, but cannot normalize every structured API.
2. Arrow-first only: uniform, but bypasses useful native readers.
3. Per-source query engines: broad reach, but violates one SQL-engine boundary.
4. **Recommended hybrid:** native primary, bounded Arrow fallback, DuckDB SQL
   always, with explicit capabilities.

#### Delivery contract

- **Non-goals:** arbitrary document search, NLP-to-SQL, distributed federation,
  write ETL, secret vault, silent installs, or universal v2.0 coverage.
- **Affected systems:** CLI, engine, catalogs, source/result contracts,
  credentials, network policy, packaging extras, errors, diagnostics, docs/tests.
- **Compatibility/migration:** v1 catalogs remain readable; migrations are
  previewable and reversible; CSV goes through the new boundary first.
- **Data migration:** optional catalog schema only; no user data movement.
- **Security/privacy:** LocalQL-managed connector operations are read-only;
  LocalQL is not a SQL sandbox; credentials are references and always redacted;
  URL sources require SSRF/redirect/private-network policy.
- **Operations/observability:** contacted systems, selected capabilities,
  pushdown, local transfer, limits, retries, cancellation, and cleanup.
- **Test strategy:** shared adapter suite; deterministic fixtures; PostgreSQL
  container; recorded bounded API; credential/redaction and negative mutation
  tests; cross-source joins; exact-artifact install smoke.
- **Rollback:** source boundary behind existing CSV behavior; adapters removable
  without catalog corruption; no automatic irreversible migration.
- **Incremental plan:** CSV boundary; Parquet; PostgreSQL; bounded HTTP JSON;
  v2.0 cross-source proof; then prioritized v2.x packs.
- **Risks/mitigations:** extension supply chain via allowlists/pinning; SSRF via
  target policy; writes via provider read-only/least privilege/handle isolation;
  dependency size via extras.
- **Open questions:** exact connector libraries/extensions, catalog schema,
  credential provider abstraction, HTTP pagination schema, transfer budgets.
- **Entry conditions:** ACP-001 decision; source/capability RFC; compatibility
  decision; connector threat models; packaging matrix; separate authorization.

## 13. Decision Queue

| ID | Decision | Owner | Evidence required |
| --- | --- | --- | --- |
| DQ-001 | Adopt or revise this governance/roadmap/design candidate | Maintainer | Another hostile review plus local diff/proof |
| DQ-002 | Select bounded result implementation | Maintainer | Benchmarks and compatibility matrix |
| DQ-003 | Approve `SourceSpec` and capabilities | Maintainer | RFC and CSV adapter contract |
| DQ-004 | Define result/transfer/temp budgets | Maintainer | Representative benchmarks |
| DQ-005 | Consolidate release identity | Maintainer | Workflow design preserving manual/OIDC gates |
| DQ-006 | Add portable TUI bindings | Maintainer | Cross-terminal QA plan |
| DQ-007 | Approve connector threat models | Maintainer/security reviewer | Provider modes, mutation/SSRF negative tests |

## 14. Roadmap Corrections

| Item | Baseline | Revised candidate |
| --- | --- | --- |
| Possible improvements | Unowned list | Status-bearing v1.x milestones |
| v1.0.2 | Absent | Audit candidate adoption pending; durable roadmap status `In Progress` |
| v1.1 | Absent | Bounded result/source foundation |
| v1.2 | Absent | Local structured formats |
| v2.0 | Broad connector vision | Parquet, PostgreSQL, bounded HTTP JSON proving slices |
| v2.x | Sparse follow-up list | Explicit broader target ecosystem |

## 15. Hostile-Review Dispositions

| # | Finding | Disposition | Evidence-based reasoning |
| --- | --- | --- | --- |
| 1 | Completion/approval status | Accept with modification | Conversational maintainer approval is valid product authority, but untracked files are not adopted repository authority. The audit and handoff carry transient adoption state; evergreen canonical documents use durable authority and delivery language. |
| 2 | Source-distribution hygiene | Accept with modification | Operational audit reports do not help installed users and are now excluded. The public roadmap/design remain in the sdist because they are linked product/contributor documentation. Tests and policy name the actual boundary. |
| 3 | v2.0 scope credibility | Accept with modification | The broad list is strategically useful as a target ecosystem, but simultaneous v2.0 support was not credible. v2.0 now proves Parquet, PostgreSQL, and bounded HTTP JSON end to end; breadth moves to v2.x. |
| 4 | Trusted SQL/read-only boundary | Accept with modification | The design already required provider read-only controls and rejected indefensible connectors. It now states the precise boundary, says the hybrid is not enforcement, and rejects docs/SQL filtering as controls. |
| 5 | Validation precision | Accept with modification | Prior current-tree proof was local macOS/Python 3.12 and baseline remote CI cannot prove this diff. `ci`, `sync`, and `ci-fresh` now have distinct mutation/reproducibility contracts. |
| 6 | Audit size/durable governance | Accept with modification | The stewardship method requires a self-contained evidence/findings/ACP record, so a tiny summary would lose required decision context. This revision removes command-by-command narrative and duplication, points durable intent to roadmap/design, names the baseline, and excludes audits from sdists. |
| 7 | Challenger independence | Accept | The prior label overstated assurance. It is now described as a secondary automated adversarial review with shared-workflow limitations; its earlier Go is superseded by this review. |

### Second bounded side review

| # | Finding | Disposition | Evidence-based reasoning |
| --- | --- | --- | --- |
| 1 | Transient state in canonical documents | Accept | Adoption-pending language would become false when committed. It remains in this historical audit and handoff, while the roadmap, design, and root instructions now use durable states. |
| 2 | v1.2/v2.x format duplication | Accept | v2.0 now carries the verified v1.x file-format baseline; JSON, NDJSON, and Excel are no longer double-booked in v2.x. Parquet explicitly proves adapter reuse. |
| 3 | Parallel `ci-fresh` ordering | Accept | `ci-fresh` now depends only on `sync` and invokes recursive `make ci` afterward, preventing sibling prerequisite execution under parallel Make. |
| 4 | No-sync environment wording | Accept | `make ci` is described as using the existing project environment without dependency reconciliation. Only a successful `ci-fresh` establishes the lock-reconciled state. |
| 5 | Ambiguous advertised-source gate | Accept | The release gate now applies to sources advertised as supported by v2.0, not the broader target ecosystem. |

### Third hostile review

Evidence snapshot: branch `main` at
`f238b6daff0adc048224743095a79def07d38056`, with 13 modified tracked files and
three untracked candidate files before this correction pass.

| # | Finding | Disposition | Evidence-based reasoning |
| --- | --- | --- | --- |
| 1 | Planning and implementation gates conflated | Accept with modification | Planning, plan approval, slice implementation, and release approval are now separate gates. Verified v1.1 is required before v2 source implementation; verified v1.2 is required for the Parquet proof and v2.0 release, not every v2 connector implementation. |
| 2 | Governance tests enforce prose layout | Accept with modification | Prose tests now inspect named Markdown sections, normalize whitespace, and assert semantic policy. Exact assertions remain for executable Make and package contracts where literal structure is the contract. |

Focused governance/package/documentation validation passed all 28 tests. Package
artifacts were not rebuilt because neither packaging behavior nor package-policy
enforcement changed. The earlier isolated TUI concurrency failure remains an
unresolved timing risk outside this correction lane.

## 16. Validation Record

The validation table distinguishes the fresh-sync run from the final exact-tree
gate:

| Check | Purpose | Candidate result |
| --- | --- | --- |
| `UV_CACHE_DIR=... make ci-fresh` | Prove sequential frozen sync and complete local gate | Sync, Ruff, and mypy passed; one untouched TUI timing test failed while 661 tests passed |
| Targeted TUI test, five consecutive runs | Check whether the full-gate failure reproduces | All five passed; no root cause was established, so no unrelated TUI change was made |
| `UV_CACHE_DIR=... make ci` | Repeat the complete no-sync gate | Passed Ruff, mypy, and all 662 tests on macOS/Python 3.12 |
| `uv build --sdist --wheel` | Package construction | Passed locally; one wheel and one sdist built |
| Package-content audit and member assertions | Prove audit/agent exclusion and public-design inclusion | Passed: audit and `AGENTS.md` absent; roadmap/design present in sdist |
| Focused governance/package/docs tests | Contract checks | All 27 passed |
| Diff, whitespace, YAML, link, and placeholder checks | Handoff hygiene | Recorded in final handoff after the last revision |

The committed baseline has remote cross-platform CI evidence, but that evidence
does not validate this uncommitted candidate. No publication, release, or
installed connector proof exists.

### Secondary automated adversarial review

An earlier secondary agent was given a read-only challenger role and returned a
Go after reviewing the prior candidate. It was separate in task execution, but
shared the surrounding workflow, repository context, tools, and model family.
It was not independent human review, a security assessment, or release
assurance. Because it missed the sdist-policy and v2-scope concerns identified
later, its Go is superseded and carries no approval weight for this revision.

## 17. Residual Risks And Recommended Next Phase

### Residual risks

- The candidate files are untracked or modified and not repository-adopted.
- Remote CI has not evaluated the candidate.
- Result budgets and implementation choices remain undecided.
- TUI portability and abnormal spill cleanup lack manual cross-terminal proof.
- Connector threat models, dependencies, and provider controls do not yet exist.
- The three v2.0 slices remain proposed and unimplemented.

### Recommended next phase

Submit this locally verified working-tree candidate to another hostile review.
Only after owner acceptance should repository adoption be considered. Product
implementation, dependencies, Git mutation, network access, publication, and
release remain outside this phase.

This revision is not approved. It is a revised candidate awaiting another
hostile review.
