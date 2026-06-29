# Codex Capability Review

This review tiers the local Codex skills, plugins, and agent roles that are useful for CSVQL. The intent is to keep the project efficient by loading the right capability at the right time instead of turning every task into process overhead. `AGENTS.md` owns mandatory skill activation rules; this file is selection guidance, not scope authority.

## Reconciled Codex-Ops Verdict

This file reconciles three external research passes about making Codex effective on
CSVQL. The durable verdict is:

> Use Codex like a strict repo operator: one accountable implementer, bounded
> read-only reviewers, deterministic repo checks, and explicit scope rejection.

Do not import the proposed scaffolding wholesale. The reports were directionally
right about determinism, contracts, and adversarial review, but repeatedly
overbuilt the operating system before `v0.1` is stable.

Keep now:

| Recommendation | Current repo expression |
|---|---|
| Strict repo authority | `AGENTS.md` plus the active release lane |
| Product direction gate | `docs/PRODUCT_DIRECTION.md` implementation checklist |
| One implementer | Main agent owns architecture, edits, and final synthesis |
| Read-only review pressure | Use reviewer/subagent roles only for bounded scouting, test drafting, or final review |
| Deterministic proof | Use the existing `uv run ...` gates until a repo-native wrapper is justified |
| Contract discipline | State command, JSON, exit-code, docs, and test impact in implementation plans |

Defer until trigger:

| Surface | Add only when |
|---|---|
| Repo-local `.agents/skills` | The same CSVQL-specific workflow fails repeatedly despite `AGENTS.md` and this review |
| Project `.codex/agents` | Built-in reviewer roles are too generic for repeated contract/security reviews |
| Project `.codex/hooks` | A deterministic script exists, has been run manually, and the user approves the hook trust surface |
| `scripts/verify.sh` | `v0.1` gates settle and the wrapper only calls repo-native `uv run` commands |
| Codex GitHub Action | A remote and CI exist, and the user explicitly wants advisory PR review automation |
| Contract docs/golden framework | Query JSON contract decisions are made and the command surface needs stable machine compatibility |

Reject for the current lane:

- replacing the current `v0.1` query target with Inspect/Sample
- importing a full v1 roadmap into `AGENTS.md`
- adding `.csvql.yml`, export, check, benchmark, profile, safe-mode, or cache work before `v0.1` is stable
- creating broad hook, custom-agent, or skill systems before real repeated failures exist
- using regex doc guards as hard gates before they are tuned against real docs
- letting subagents regenerate golden files, define JSON schema shape, set exit-code policy, or change security posture

## Tier 0 - Active Defaults

Use these for most CSVQL implementation turns.

| Capability | Type | Why it matters |
|---|---|---|
| `python-codebase-standards` | skill | Governs `uv`, `pyproject.toml`, typed Python boundaries, tests, error handling, dependency discipline, and security-sensitive path/SQL handling. |
| `project-creator` | skill | Useful during kickoff for converting the pack into repo-local docs, roadmap, and project context. |
| `multi_agent_v1` `python-pro` | agent role | Best write-capable helper for bounded Python implementation slices once the main architecture is clear. |
| `multi_agent_v1` `reviewer` | agent role | Best final review role for correctness, regressions, security, and missing tests before larger handoffs. |
| `multi_agent_v1` `test-drafter` | agent role | Useful when expected behavior is already defined and a narrow test patch can be delegated. |
| Product direction gate | repo doc | Use `docs/PRODUCT_DIRECTION.md` before implementation planning to check the current lane, strengthened wedge, rejected scope, touched contracts, and verification target. |

## Tier 1 - Near-Term Specialists

Use these when a task specifically enters their domain.

| Capability | Type | Trigger |
|---|---|---|
| `testing-strategy` / `qa-test-planner` | skills | Expanding CLI integration tests, fixture strategy, and release confidence. |
| `code-review` | skill | Human-style review of a diff before commit or PR. |
| `security-best-practices` | skill | Any safe-mode, file/path boundary, SQL templating, or untrusted input work. |
| `data-quality` | skill | Designing the v0.5 check model and failure reporting. |
| `performance-engineering` | skill | Benchmark harness and large CSV behavior. |
| `readme` / `documentation` | skills | README polish, docs restructuring, and release documentation. |
| GitHub connector | plugin/tool | Creating issues, PRs, checking CI, or release workflow after a remote exists and you explicitly approve GitHub mutations. |

## Tier 2 - Useful Later

Keep available, but do not load by default.

| Capability | Type | Later use |
|---|---|---|
| `dataAnalyticsWidgets` | plugin/tool | Rendering benchmark reports or demo analytics artifacts after benchmark data exists. |
| Codex Security | plugin/skill/tool | Differential security scans once safe mode, path handling, or packaged releases become substantial. |
| OpenAI Developer Docs | plugin/tool | Only if project docs or automation start depending on OpenAI/Codex APIs. |
| `architecture-decision-records` | skill | Recording durable design choices such as safe mode, cache behavior, or parameter syntax. |
| `session-handoff` | skill | Creating a durable handoff packet before long pauses. |

## Tier 3 - Avoid Unless Scope Changes

These are installed or available, but they do not match CSVQL's current shape.

- AWS skills and AWS MCP tools
- PostgreSQL/database migration skills
- Spark/dbt/warehouse skills
- FastAPI, microservices, GraphQL, and web-app skills
- Hugging Face tools
- Google Drive/Sheets/Slides tools
- OpenAPI generation

## Recommended Operating Pattern

1. Keep the main agent responsible for architecture, synthesis, and final file integration.
2. Start implementation planning with the direction gate from `docs/PRODUCT_DIRECTION.md`: target lane, wedge strengthened, scope rejected, contracts touched, and verification target.
3. Use one accountable implementer for code changes; avoid parallel write-heavy work.
4. Use `python-codebase-standards` for every non-trivial Python/tooling change.
5. Delegate only bounded, independent tasks to subagents, such as scouting, test drafting, or read-only diff review.
6. Use GitHub tools only after the repo has a remote and the action is explicitly requested.
7. Do not load cloud, web-app, or database-platform skills unless the roadmap actually moves there.
8. Do not create new Codex authority surfaces unless the trigger conditions above are met.

## Subagent Guardrails

Use subagents for bounded scouting, test drafting, or final review. Keep product direction, JSON contract shape, exit-code policy, security posture, and roadmap sequencing in the main agent's synthesis. A subagent can surface evidence or draft a narrow patch, but it should not silently redefine the wedge, regenerate golden contracts, widen the release lane, or introduce new product surfaces.
