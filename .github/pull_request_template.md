## Summary

## Scope Check

- [ ] This change stays within LocalQL's local CSV, DuckDB, CLI/TUI, explicit export, project catalog, docs, or test scope.
- [ ] This change does not add web app, cloud connector, NLP execution, hidden cache, sandbox-safe SQL, or production-readiness claims.
- [ ] Public examples use installed `csvql ...` commands unless the section is specifically for source-checkout development.

## Verification

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run --all-extras mypy src`
- [ ] `uv run --all-extras pytest`

## Notes
