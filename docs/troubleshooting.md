# Troubleshooting

This guide is organized by symptom. For exact exit codes, message shapes, and
test-backed contracts, see the [Failure gallery](failure-gallery.md).

## `CSV file not found`

Typical causes:

- the command is running from a different directory than expected
- the path in `.csvql.yml` is stale
- the CSV was moved or deleted

Try:

```bash
pwd
csvql query missing.csv "SELECT 1"
csvql add orders data/orders.csv --replace
```

For project catalogs, CSVQL resolves table paths relative to the project root
that contains `.csvql.yml`.

## `No .csvql.yml project catalog found`

This happens when you run catalog-backed commands without a project catalog and
without explicit `--table` mappings.

Start a catalog:

```bash
csvql init
csvql add revenue_movements data/revenue_movements.csv
csvql tables
```

Or bypass the catalog for one command:

```bash
csvql query \
  --table revenue_movements=data/revenue_movements.csv \
  "SELECT COUNT(*) FROM revenue_movements"
```

## `Invalid table mapping`

Explicit mappings must use `name=path`:

```bash
csvql query --table orders=data/orders.csv "SELECT COUNT(*) FROM orders"
```

Table aliases must be valid SQL identifiers: use letters, numbers, and
underscores, and start with a letter or underscore.

## `DuckDB query failed`

This usually means DuckDB could not bind a table, column, or SQL expression.

Check:

- the table alias matches your CSV file stem or `--table` mapping
- column names match the CSV header
- the SQL runs against the registered table names, not file names

Useful inspection commands:

```bash
csvql tables
csvql inspect revenue_movements --output json
csvql sample revenue_movements --limit 5
```

## Export Output Already Exists

CSVQL refuses to overwrite export files unless you ask for it:

```bash
csvql export queries/revenue_health.sql \
  --format csv \
  --out output/revenue-health.csv
```

If the existing file should be replaced:

```bash
csvql export queries/revenue_health.sql \
  --format csv \
  --out output/revenue-health.csv \
  --force
```

## `CSVQL TUI dependency is not installed`

Install the optional TUI dependency:

```bash
pip install "localql[tui]"
```

From a source checkout:

```bash
uv sync --all-extras
uv run --all-extras csvql menu
```

## TUI Keybindings Do Not Work In My Terminal

Use `F4` as the reliable run fallback when `Ctrl+Enter` is not emitted by your
terminal. On macOS, `F11` may be intercepted by Show Desktop; use `Ctrl+S` to
save a result as a derived source.

Core fallbacks:

- `F4`: run SQL
- `F6`: sources
- `F5`: results
- `F8`: history
- `F9`: quit
- `F1`: help

## Data-Quality Checks Fail

`csvql check` exits `11` when configured checks run and find data-quality
failures. Use failure samples to inspect the bad rows:

```bash
csvql check revenue_movements \
  --output json \
  --show-failures \
  --failure-limit 5
```

Fix either the CSV data or the check definition in `.csvql.yml`.

## Project Health Fails

Run doctor from the project root:

```bash
csvql doctor --output json
```

Doctor checks whether the project catalog loads, configured CSV paths exist,
CSV files are readable, and configured checks reference valid tables and
columns.

## SQL Safety

CSVQL treats user-authored SQL as trusted local DuckDB SQL. It does not sandbox
DuckDB, restrict filesystem access, or make untrusted SQL safe.
