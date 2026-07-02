# CSVQL V1 Manual QA Matrix

Status: manual proof checklist for local v1 candidate evaluation.

This matrix is local evidence only. It does not publish, tag, upload, or claim
`v1-stable`.

Run from the repository root unless a step explicitly changes directories.

## Setup

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql --version
```

Expected: prints `1.0.0`.

## Checklist

- [ ] CLI single-file query

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    examples/saas_revenue/data/revenue_movements.csv \
    "SELECT COUNT(*) AS movement_count FROM revenue_movements"
  ```

  Expected: table output contains `movement_count`.

- [ ] CLI project catalog query

  ```bash
  cd examples/saas_revenue
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    "SELECT COUNT(*) AS customer_count FROM customers"
  ```

  Expected: table output contains `customer_count`.

- [ ] CLI export and reuse as CSV source

  ```bash
  cd examples/saas_revenue
  mkdir -p .csvql/results
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out .csvql/results/revenue_health.csv \
    --force
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    --table revenue_health_result=.csvql/results/revenue_health.csv \
    "SELECT COUNT(*) AS result_rows FROM revenue_health_result"
  ```

  Expected: export succeeds and the follow-up query returns `result_rows`.

- [ ] TUI launch

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras csvql menu \
    examples/saas_revenue/data/revenue_movements.csv
  ```

  Expected: Workbench opens with a loaded source alias.

- [ ] TUI repeated query

  In the TUI, run:

  ```sql
  SELECT COUNT(*) AS movement_count FROM revenue_movements;
  ```

  Then clear the editor and run:

  ```sql
  SELECT movement_type, COUNT(*) AS rows
  FROM revenue_movements
  GROUP BY movement_type;
  ```

  Expected: both runs complete, history records both attempts, and the editor
  remains usable.

- [ ] TUI derived save and query

  In the TUI, save the last tabular result with `Ctrl+S`, use alias
  `movement_counts`, then run:

  ```sql
  SELECT * FROM movement_counts;
  ```

  Expected: `.csvql/results/movement_counts.csv` is written under the current
  local root, Sources shows `movement_counts` with kind `derived`, and the query
  returns rows from the saved result.

- [ ] Bad SQL

  Run:

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query \
    --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv \
    "SELECT missing_column FROM revenue_movements"
  ```

  Expected: exit code `1`, an error beginning `DuckDB query failed`, and a
  suggestion to check table names, column names, and SQL syntax.

- [ ] No-result SQL

  In the TUI, run:

  ```sql
  CREATE TABLE scratch AS SELECT 1 AS value;
  ```

  Expected: prior results are cleared and the TUI reports that the statement
  completed with no tabular result to display.

- [ ] Export overwrite refusal and force

  ```bash
  cd examples/saas_revenue
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out output/revenue-health.csv
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out output/revenue-health.csv
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql export queries/revenue_health.sql \
    --format csv \
    --out output/revenue-health.csv \
    --force
  ```

  Expected: first export succeeds, second export exits `10` with overwrite
  guidance, third export succeeds.

- [ ] Missing file behavior

  ```bash
  env UV_CACHE_DIR=/private/tmp/uv-cache uv run csvql query missing.csv "SELECT 1"
  ```

  Expected: exit code `4` and a message that the CSV file was not found.

- [ ] Quit path

  In the TUI, press `F9`.

  Expected: the app exits cleanly without a traceback.

- [ ] Mac keybinding path

  On macOS, use `Ctrl+S` for Save Result As Source. Confirm `F11` is not the
  only documented save path because macOS may intercept it for Show Desktop.

## Result Recording

Record the final manual result in release notes or handoff text with:

- date
- commit SHA
- terminal app
- passed checklist items
- failed checklist items and blockers
