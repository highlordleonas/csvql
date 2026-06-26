# CSVQL Project Instructions

## Scope

CSVQL is a Python CLI and package for querying local CSV files through DuckDB. DuckDB owns SQL execution; this repo owns CLI workflow, table aliasing, output formatting, tests, docs, and later project configuration.

## Current Implementation Target

The active implementation target is v0.1:

- `csvql query --table name=path "SELECT ..."`
- single-file shortcut: `csvql query data/orders.csv "SELECT ..."`
- DuckDB in-memory execution
- Rich table output and JSON output
- typed internal boundaries and clear CLI errors
- focused unit and CLI integration tests

Do not implement project config, profiling, data quality checks, exports, shell, doctor, persistent cache, safe mode, or Python API until the v0.1 surface is stable.

## Tooling

- Use `uv` for dependency management and command execution.
- Keep dependencies in `pyproject.toml`; keep `uv.lock` intentional once generated.
- Do not install global packages.
- Prefer `uv run` for local checks.

Expected local gates:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

## Architecture Rules

- Keep `cli.py` as a thin Typer boundary.
- Keep DuckDB connection and query execution in `engine.py`.
- Keep parsing and validation of table mappings outside the CLI command body.
- Validate generated table aliases before passing them to DuckDB.
- Resolve CSV paths before execution and fail loudly for missing files.
- Treat user-authored SQL as trusted local SQL unless safe mode is explicitly implemented and tested.
- Do not claim safe sandbox behavior.

## Source Pack

`csvql_project_pack/` and `csvql_project_pack.zip` are input artifacts, not runtime source. Copy useful content into normal repo files before relying on it.
