# Codex Capability Review

This review tiers the local Codex skills, plugins, and agent roles that are useful for CSVQL. The intent is to keep the project efficient by loading the right capability at the right time instead of turning every task into process overhead. `AGENTS.md` owns mandatory skill activation rules; this file is selection guidance, not scope authority.

## Tier 0 - Active Defaults

Use these for most CSVQL implementation turns.

| Capability | Type | Why it matters |
|---|---|---|
| `python-codebase-standards` | skill | Governs `uv`, `pyproject.toml`, typed Python boundaries, tests, error handling, dependency discipline, and security-sensitive path/SQL handling. |
| `project-creator` | skill | Useful during kickoff for converting the pack into repo-local docs, roadmap, and project context. |
| `multi_agent_v1` `python-pro` | agent role | Best write-capable helper for bounded Python implementation slices once the main architecture is clear. |
| `multi_agent_v1` `reviewer` | agent role | Best final review role for correctness, regressions, security, and missing tests before larger handoffs. |
| `multi_agent_v1` `test-drafter` | agent role | Useful when expected behavior is already defined and a narrow test patch can be delegated. |

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
2. Use `python-codebase-standards` for every non-trivial Python/tooling change.
3. Delegate only bounded, independent tasks to subagents, such as test drafting, diff review, or a narrow implementation module.
4. Use GitHub tools only after the repo has a remote and the action is explicitly requested.
5. Do not load cloud, web-app, or database-platform skills unless the roadmap actually moves there.
