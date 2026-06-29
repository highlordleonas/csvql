# CSVQL v0.3 Project Catalog Design

## Purpose

CSVQL v0.3 adds a small project catalog so users can register local CSV files once and query them repeatedly without repeating `--table name=path` mappings. The catalog keeps CSVQL local-first and deterministic: it stores user-controlled metadata in `.csvql.yml`, resolves paths relative to the project root, and still delegates SQL execution to DuckDB.

This slice strengthens the repeatable local analytics workflow. It does not expand CSVQL into a server, cache, database, safe sandbox, data-quality framework, or general project platform.

## Product Decision

The catalog must be immediately useful for the core query workflow.

Supported flow:

```bash
uv run csvql init
uv run csvql add orders examples/sales/data/orders.csv
uv run csvql query "SELECT * FROM orders LIMIT 5"
```

Without catalog-backed `query`, v0.3 would only create and list config while users still repeat `--table` mappings. That is not enough product value for this feature lane.

## Command Contract

### `csvql init [--force]`

Creates `.csvql.yml` in the current working directory.

Default output file:

```yaml
version: 1
tables: {}
```

Rules:

- Refuse to overwrite an existing `.csvql.yml`.
- `--force` explicitly rewrites `.csvql.yml` to an empty catalog.
- The command does not inspect CSV files or create hidden state.

### `csvql add <name> <path> [--replace]`

Adds or updates a table entry in the nearest project catalog.

Rules:

- Discover `.csvql.yml` by walking upward from the current directory.
- Validate `<name>` with the existing table alias rules.
- Validate `<path>` by resolving it from the invocation current working directory, matching existing CLI path behavior.
- Store paths inside the project as project-root-relative path strings.
- Store absolute paths as absolute path strings.
- Refuse duplicate table names unless `--replace` is passed.
- `--replace` updates only the named table entry.

Minimal catalog shape after adding `orders`:

```yaml
version: 1
tables:
  orders:
    path: examples/sales/data/orders.csv
```

### `csvql tables --output table|json`

Lists registered catalog tables.

Table output should show at least:

- `name`
- `path`
- `resolved_path`

JSON output must include:

```json
{
  "project_root": "/path/to/project",
  "config_path": "/path/to/project/.csvql.yml",
  "tables": [
    {
      "name": "orders",
      "path": "examples/sales/data/orders.csv",
      "resolved_path": "/path/to/project/examples/sales/data/orders.csv"
    }
  ]
}
```

### `csvql query`

Catalog-backed query behavior:

```bash
uv run csvql query "SELECT * FROM orders LIMIT 5"
```

Rules:

- If explicit `--table` mappings are provided, keep current query behavior and register those mappings.
- If no explicit `--table` mappings are provided and the invocation is inline SQL mode, discover `.csvql.yml` and register catalog tables.
- If catalog aliases and explicit mappings are both present, explicit `--table` mappings override catalog aliases for that invocation.
- Query output stays unchanged: table output by default, JSON output with `--output json`.
- User-authored SQL remains trusted local SQL.

Single-file shortcut behavior remains unchanged:

```bash
uv run csvql query data/orders.csv "SELECT * FROM orders"
```

That shortcut uses the file path argument and does not require a project catalog.

## Catalog Discovery And Path Resolution

Project discovery walks upward from the current working directory until it finds `.csvql.yml`.

Example:

```text
project/
  .csvql.yml
  data/orders.csv
  queries/
```

Running from `project/queries` should find `project/.csvql.yml`. Catalog table paths resolve relative to `project/`, not `project/queries`.

If discovery reaches the filesystem root without finding `.csvql.yml`, commands that require a catalog fail with a typed project-config error.

For `csvql add`, the user-provided path resolves from the invocation current working directory. If the resolved CSV file is inside the project root, CSVQL stores the path relative to the project root. If the resolved CSV file is outside the project root, CSVQL stores the absolute path so later catalog-backed queries can still resolve it unambiguously.

## Config Format And Dependency

CSVQL keeps the roadmap's `.csvql.yml` format and adds an intentional `PyYAML` dependency.

Rules:

- Use `yaml.safe_load` for reading.
- Use `yaml.safe_dump` for writing.
- Treat empty config files, non-mapping YAML, missing `version`, unsupported versions, missing `tables`, non-mapping `tables`, and invalid table entries as config errors.
- Version `1` is the only supported version in v0.3.
- Do not add reader options, type overrides, tags, descriptions, owners, or metadata fields in v0.3.

## Architecture

Add a focused project-config layer.

### `src/csvql/project_config.py`

Responsibilities:

- Define config constants such as `.csvql.yml` and supported version `1`.
- Define value objects such as `ProjectConfig`, `ProjectTable`, and `ProjectContext`.
- Discover the project root and config path.
- Load and validate YAML safely.
- Save deterministic YAML.
- Add and replace table entries.
- Convert project tables into existing `TableSource` values for the engine.

This module owns project config behavior. The CLI should call it instead of parsing YAML directly.

### `src/csvql/cli.py`

Responsibilities:

- Add `init`, `add`, and `tables` commands.
- Keep Typer command bodies thin.
- Update query request building so inline SQL can use catalog tables.
- Preserve current query behavior for explicit `--table` mappings and single-file shortcut mode.

### `src/csvql/output.py`

Responsibilities:

- Add deterministic JSON output for table listings.
- Add Rich table output for table listings.
- Keep existing query, inspect, and sample output contracts unchanged.

### `src/csvql/exceptions.py`

Add:

```python
class ProjectConfigError(CSVQLError):
    """Raised when project catalog discovery, parsing, or validation fails."""

    exit_code = 8
```

Exit code `8` keeps project-config failures distinct from missing files, table mapping errors, query execution failures, and CSV inspection failures.

### `pyproject.toml` And `uv.lock`

Add `PyYAML` intentionally as a runtime dependency. The lockfile update is part of the feature.

## Error Handling

All catalog failures should use `ProjectConfigError` unless an existing error type more precisely describes the failure.

Expected user-facing failures:

- `csvql query "SELECT * FROM orders"` with no catalog and no `--table`:
  - error: no project catalog found
  - suggestion: run `csvql init` and `csvql add`, or pass `--table name=path`
- invalid YAML:
  - error: failed to parse `.csvql.yml`
  - suggestion: fix YAML syntax
- unsupported version:
  - error: unsupported project config version
  - suggestion: use `version: 1`
- duplicate `add`:
  - error: table already exists
  - suggestion: use `--replace`
- `init` when `.csvql.yml` exists:
  - error: `.csvql.yml` already exists
  - suggestion: use `--force`
- invalid catalog table alias:
  - reuse existing alias validation behavior where practical
- missing catalog CSV path:
  - keep missing-file behavior but include enough context to identify the catalog entry

No error should expose stack traces during normal CLI use.

## Non-Goals

v0.3 does not include:

- registered-table support for `csvql inspect`
- registered-table support for `csvql sample`
- `csvql run`
- `csvql export`
- profiling
- data quality checks
- reader options
- type overrides
- safe mode
- sandboxing
- cache or materialization
- Python API
- cloud or remote data sources

## Testing Strategy

Use focused unit tests for config behavior and CLI integration tests for user workflows.

Unit tests:

- default config creation
- upward project discovery
- discovery failure
- safe YAML load and dump shape
- invalid YAML
- unsupported config version
- missing or invalid `tables`
- invalid table entries
- duplicate add without `--replace`
- replace behavior
- catalog path resolution relative to project root
- conversion to `TableSource`

CLI tests:

- `csvql init` creates `.csvql.yml`
- `csvql init` refuses overwrite
- `csvql init --force` rewrites the catalog
- `csvql add orders path.csv` writes a table entry
- `csvql add orders path.csv` rejects duplicate entries
- `csvql add orders path.csv --replace` updates the entry
- `csvql tables` renders table output
- `csvql tables --output json` renders deterministic JSON
- catalog-backed `csvql query "SELECT ... FROM orders"` succeeds
- explicit `--table` overrides catalog aliases
- catalog-backed query works from a subdirectory
- missing catalog produces a typed CLI error
- invalid config produces a typed CLI error

Verification commands:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

## Acceptance Criteria

- `csvql init` creates a valid empty catalog.
- `csvql add` registers CSV paths under validated aliases.
- `csvql tables` lists registered tables in table and JSON formats.
- `csvql query "SELECT ... FROM alias"` works with catalog aliases.
- explicit `--table` mappings override catalog aliases for the current command.
- project discovery works from subdirectories.
- config parse and validation failures are typed CLI errors.
- `PyYAML` is an intentional dependency using safe APIs.
- Existing `query`, `inspect`, and `sample` tests continue to pass.
- Docs describe the catalog workflow without sandbox, production, untrusted-SQL, or large-file performance claims.

## Execution Boundary

Implementation should happen on a fresh feature branch from `codex/inspect-sample-stabilization` at commit `89c7d6d`.

Do not implement this in the dirty `63fd` worktree. Do not mix this work with the separate doc/governance edits currently present there.
