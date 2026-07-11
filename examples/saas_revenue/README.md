# SaaS Revenue Example

This example models a small local B2B SaaS revenue project with three CSVs:

- `customers.csv`
- `subscriptions.csv`
- `revenue_movements.csv`

The example shows how to inspect a project, run its configured checks, execute a
saved analysis, and export results for scripts or for people to read.

## Quickstart

```bash
cd examples/saas_revenue

csvql inspect data/revenue_movements.csv --output json
csvql profile revenue_movements --output json
csvql check --output json
csvql run queries/revenue_health.sql --output json
mkdir -p output
csvql export queries/revenue_health.sql --format json --out output/revenue-health.json --force
csvql export queries/revenue_health.sql --format markdown --out output/revenue-health.md --force
```

What to expect:

- `inspect` prints the detected columns, dialect, file metadata, and row-count
  mode.
- `profile` prints row/column counts, null counts, duplicate count, and simple
  per-column summaries.
- `check` exits `0` when the configured project checks pass.
- `run` returns four monthly revenue-health rows.
- `export` writes JSON and Markdown files under `output/`.

![Terminal screenshot of the SaaS project query and configured checks](../../docs/assets/localql-terminal-project.svg)

## What The Commands Show

- `inspect` shows the raw shape of a core project table
- `profile` shows row counts, duplicate counts, and column-level completeness
- `check` runs the data-quality rules in `.csvql.yml`
- `run` returns the main revenue-health analysis as JSON
- `export` writes the same analysis as JSON and Markdown

## Main Analysis

`queries/revenue_health.sql` returns one row per month with:

- starting MRR
- new MRR
- expansion MRR
- contraction MRR
- churn MRR
- reactivation MRR
- ending MRR
- ending ARR
- net revenue retention percentage

The result is meant to be small enough to inspect in a terminal and structured
enough to export into another local workflow.

## Regenerate The Data

The committed CSVs are intentional and reproducible. To rewrite them exactly:

```bash
cd examples/saas_revenue
uv run python scripts/regenerate_data.py
```

The script rewrites only the files under `data/`.
