# CSVQL

CSVQL is a lightweight DuckDB-powered CLI for querying local CSV files like SQL tables.

```bash
csvql query \
  --table customers=examples/saas_revenue/data/customers.csv \
  --table subscriptions=examples/saas_revenue/data/subscriptions.csv \
  "SELECT
      c.segment,
      COUNT(*) AS active_subscriptions,
      SUM(s.current_mrr) AS current_mrr
   FROM customers c
   JOIN subscriptions s USING (customer_id)
   WHERE s.status = 'active'
   GROUP BY c.segment
   ORDER BY current_mrr DESC"
```

CSVQL does not implement a SQL engine. DuckDB executes SQL; CSVQL owns the local workflow around table aliases, readable output, validation, and project catalog configuration.

## Status

This repository has the core local workflow implemented for local CLI use:
query, inspect/sample, project catalogs, saved SQL, export, profile, configured
checks, doctor, benchmark and release-readiness proof scripts, JSON contract
documentation, the failure gallery, the polished example project, and the small
project-backed Python API. It also includes an optional Textual-powered terminal
menu for local interactive work. The release workflow and release-note material
now exist. The package version is prepared as `1.0.0` for the local v1 release
state.

This local release state is not a tag, PyPI upload, GitHub release, artifact
upload, or external publication.

Implemented now:

- `csvql query --table name=path "SELECT ..."`
- `.csvql.yml` project catalog discovery
- `csvql init`
- `csvql add`
- `csvql tables`
- catalog-backed `csvql query "SELECT ... FROM alias"`
- `csvql inspect data/orders.csv --output json`
- `csvql sample data/orders.csv --limit 10`
- `csvql run queries/file.sql`
- `csvql export queries/file.sql --format csv|json|markdown --out path`
- catalog-backed `csvql inspect alias`
- catalog-backed `csvql sample alias`
- `csvql profile data/orders.csv --output json`
- catalog-backed `csvql profile alias`
- configured data-quality checks in `.csvql.yml`
- `csvql check [table] --output json`
- `csvql doctor --output json`
- sampled failure output with `csvql check --show-failures`
- repeated `--table` mappings for joins
- single-file shortcut mode
- optional `csvql menu` terminal workbench through the `tui` extra
- TUI startup from a project catalog, one CSV path, or repeated `--table`
  mappings
- TUI source actions for inspect, sample, profile, add, remove, and explicit
  project catalog save
- TUI query history for the current session only
- TUI explicit result export and explicit derived result sources under
  `.csvql/results/{alias}.csv`
- table and JSON stdout output
- DuckDB in-memory execution
- focused tests, Ruff, mypy, and GitHub Actions scaffolding

Repo-local hardening now:

- benchmark harness with JSON artifact and Markdown summary
- release-readiness verification for version consistency, build smoke, and installed-wheel smoke
- local output under `output/`

Current local proof evidence is generated under ignored `output/` directories
when the release-readiness and benchmark workflows are rerun.

## Install For Development

```bash
uv sync --all-extras
```

Run the CLI from the repo:

```bash
uv run csvql --help
```

## Interactive Terminal Menu

CSVQL can also run an optional Textual-powered terminal menu:

```bash
uv run --all-extras csvql menu
uv run --all-extras csvql menu /path/to/orders.csv
uv run --all-extras csvql menu --table customers=customers.csv --table orders=orders.csv
```

Install the optional TUI dependency before using the menu from an installed
package:

```bash
pip install "csvql[tui]"
```

The menu is session-backed by default. Sources added inside the TUI live only
for the current session unless you explicitly save them to a `.csvql.yml`
project catalog. Exports are written only when you choose the export action.

The SQL editor is focused when the menu opens. Type SQL directly, then press
`Ctrl+Enter` or `F4` to run the whole editor. The action is labeled "Run
Editor" because selected-SQL and current-statement execution are not part of
this slice. `F4` is the reliable fallback if your terminal does not emit
`Ctrl+Enter`.

Use `F2` or `Ctrl+Down` for the SQL editor, `F5` for results, `F6` or
`Ctrl+Up` for sources, and `F8` for history. Printable keys type into SQL while
the editor is focused. Source actions use letters only when the source pane is
focused: `i` inspect, `s` sample, `p` profile, `a` add, `d` remove, and `w`
save sources. History actions use `Enter` to reopen a query and `r` to rerun a
query against the current session sources. `F1` opens help; `?` is a help
fallback only outside the SQL editor.

`Ctrl+N` or `F10` clears the editor for a new query while keeping history and
the last result view visible. Query history is in-memory session state only: it
is not written to disk, logged, or sent anywhere by CSVQL, and it clears when
the TUI exits.

`Ctrl+S` saves the last successful tabular query result as a derived source.
`Alt+S` is also bound for terminals that emit Alt key events, and `F11` is
available where it is not intercepted by the OS. macOS may intercept `F11` for
Show Desktop. CSVQL prompts for an alias, writes
`.csvql/results/{alias}.csv`, and adds that alias to the Sources pane with kind
`derived` so it can be queried or joined later in the same TUI session. The CSV
file remains on disk; the alias becomes durable across TUI sessions only if you
explicitly save sources to `.csvql.yml`. Derived result sources are explicit
CSV-backed artifacts, not hidden cache or automatic materialization. They use
the same trusted local DuckDB SQL posture as other CSVQL sources.

The SQL editor uses the same trusted local DuckDB execution posture as the rest
of CSVQL. Do not run untrusted SQL.

## Python API Example

CSVQL also exposes a project-backed Python API:

```python
from csvql import CSVQLSession

session = CSVQLSession.from_config("examples/saas_revenue")

tables = session.tables()
sample = session.sample("revenue_movements", limit=5)
profile = session.profile("revenue_movements")
result = session.run_file("queries/revenue_health.sql")
output_path = session.export(
    "queries/revenue_health.sql",
    "output/revenue-health.json",
    format="json",
    force=True,
)

for row in result.as_records():
    print(row)
```

The Python API is intentionally project-backed: table listing, trusted SQL,
saved SQL files, inspect, sample, profile, configured checks, and export. It
does not provide direct-path sessions, ad hoc table mappings, config mutation,
dataframe helpers, async execution, plugins, or a second execution engine.

## Query Examples

Query one CSV with the single-file shortcut. The table name is derived from the file stem, so `revenue_movements.csv` becomes `revenue_movements`.

```bash
uv run csvql query examples/saas_revenue/data/revenue_movements.csv \
  "SELECT movement_type, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_type
   ORDER BY movement_type"
```

Query multiple CSV files:

```bash
uv run csvql query \
  --table customers=examples/saas_revenue/data/customers.csv \
  --table subscriptions=examples/saas_revenue/data/subscriptions.csv \
  "SELECT
      c.customer_id,
      c.company_name,
      s.plan_name,
      s.current_mrr
   FROM customers c
   JOIN subscriptions s USING (customer_id)
   WHERE s.status = 'active'
   ORDER BY s.current_mrr DESC"
```

Return JSON for automation:

```bash
uv run csvql query \
  --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv \
  --output json \
  "SELECT movement_month, SUM(mrr_delta) AS net_mrr_change
   FROM revenue_movements
   GROUP BY movement_month
   ORDER BY movement_month"
```

## Project Catalog Examples

Initialize a local project catalog:

```bash
uv run csvql init
```

Register a table once:

```bash
uv run csvql add revenue_movements examples/saas_revenue/data/revenue_movements.csv
```

List registered tables as JSON:

```bash
uv run csvql tables --output json
```

Query a registered table by alias:

```bash
uv run csvql query "SELECT COUNT(*) AS movement_count FROM revenue_movements"
```

For one invocation, explicit `--table` mappings still work and override catalog aliases with the same name.

```bash
uv run csvql query \
  --table revenue_movements=examples/saas_revenue/data/revenue_movements.csv \
  "SELECT COUNT(*) AS movement_count FROM revenue_movements"
```

## Saved Workflow Examples

Run SQL from a file using catalog aliases:

```bash
cd examples/saas_revenue
uv run csvql run queries/revenue_health.sql --output json
```

Inspect a registered catalog alias and profile it:

```bash
cd examples/saas_revenue
uv run csvql inspect revenue_movements --output json
uv run csvql profile revenue_movements --output json
```

Export the main analysis:

```bash
cd examples/saas_revenue
uv run csvql export queries/revenue_health.sql \
  --format json \
  --out output/revenue-health.json \
  --force

uv run csvql export queries/revenue_health.sql \
  --format markdown \
  --out output/revenue-health.md \
  --force
```

See `examples/saas_revenue/README.md` for the full copy/paste walkthrough.

## Inspect And Sample Examples

Inspect the core revenue-movement table:

```bash
uv run csvql inspect examples/saas_revenue/data/revenue_movements.csv --output json
```

Calculate an exact row count when you explicitly want a full scan:

```bash
uv run csvql inspect examples/saas_revenue/data/revenue_movements.csv --exact --output json
```

Sample rows from the same table:

```bash
uv run csvql sample examples/saas_revenue/data/revenue_movements.csv --limit 5
```

## Profile Examples

Profile the revenue-movement CSV with a full scan:

```bash
uv run csvql profile examples/saas_revenue/data/revenue_movements.csv
```

Return JSON profile metrics:

```bash
uv run csvql profile examples/saas_revenue/data/revenue_movements.csv --output json
```

Profile a registered catalog alias:

```bash
cd examples/saas_revenue
uv run csvql profile revenue_movements --output json
```

`csvql profile` reports row and column counts, duplicate row count, per-column null counts and percentages, non-null counts, distinct counts excluding nulls, and DuckDB `min`/`max` values. String `min` and `max` use DuckDB lexicographic ordering.

## Data Quality Check Examples

Configure checks in `.csvql.yml`:

```yaml
version: 1
tables:
  customers:
    path: data/customers.csv
    checks:
      - name: customer_id_required
        type: not_null
        column: customer_id
      - name: customer_id_unique
        type: unique
        column: customer_id
  subscriptions:
    path: data/subscriptions.csv
    checks:
      - name: subscription_id_required
        type: not_null
        column: subscription_id
      - name: subscription_id_unique
        type: unique
        column: subscription_id
      - name: subscription_customer_exists
        type: foreign_key
        column: customer_id
        references:
          table: customers
          column: customer_id
  revenue_movements:
    path: data/revenue_movements.csv
    checks:
      - name: movement_id_required
        type: not_null
        column: movement_id
      - name: movement_id_unique
        type: unique
        column: movement_id
      - name: movement_type_known
        type: accepted_values
        column: movement_type
        values: [new, expansion, contraction, churn, reactivation]
```

Run all configured checks:

```bash
uv run csvql check
```

Run checks for one registered table and return JSON:

```bash
uv run csvql check revenue_movements --output json
```

Include capped failure samples:

```bash
uv run csvql check revenue_movements --output json --show-failures --failure-limit 5
```

`csvql check` exits `0` when checks pass or no checks are configured. It exits `11` when configured checks run successfully and find data-quality failures. Missing catalogs, missing files, invalid config, and DuckDB execution errors use the existing CLI error path.

## Project Health Examples

Run project doctor from a directory with a `.csvql.yml` project catalog:

```bash
uv run csvql doctor
```

Return doctor results as JSON for automation:

```bash
uv run csvql doctor --output json
```

`csvql doctor` exits `0` for `passed` and `warning` results. It exits `12` when the
project catalog exists but CSVQL finds concrete project-health failures such as invalid
config, missing configured CSV files, unreadable CSV inputs, or configured checks that
reference missing columns.

## Benchmark And Release Hardening

Generate local benchmark evidence:

- `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`

Verify build and install proof:

- `uv run python scripts/verify_release_readiness.py --work-dir output/release-readiness`

Release workflow and notes:

- [Changelog](CHANGELOG.md)
- [v1 release notes](docs/release-notes/v1.md)
- [Release readiness](docs/release-readiness.md)

Claims boundary:

- Local benchmark evidence only
- No large-file proof beyond the recorded datasets
- No production-readiness claim
- No sandbox-safety claim
- No publish, tag, or upload action without separate explicit approval

## Development Checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run --all-extras mypy src
uv run --all-extras pytest
```

Or run the combined local gate:

```bash
make ci
```

## Security Model

CSVQL is currently a local developer tool for trusted SQL. DuckDB executes the SQL, and CSVQL does not restrict DuckDB capabilities or filesystem access. Do not run untrusted SQL files or input.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarking](docs/benchmarking.md)
- [Changelog](CHANGELOG.md)
- [JSON contracts](docs/json-contracts.md)
- [Failure gallery](docs/failure-gallery.md)
- [Product direction](docs/PRODUCT_DIRECTION.md)
- [Release readiness](docs/release-readiness.md)
- [v1 release notes](docs/release-notes/v1.md)
- [Roadmap](docs/ROADMAP.md)
- [Codex capability review](docs/CODEX_CAPABILITY_REVIEW.md)
- [v1 Quality Spine design](docs/superpowers/specs/2026-06-26-csvql-v1-quality-spine-design.md)
