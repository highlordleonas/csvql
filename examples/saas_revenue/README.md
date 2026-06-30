# SaaS Revenue Example

This example models a small local B2B SaaS revenue project with three CSVs:

- `customers.csv`
- `subscriptions.csv`
- `revenue_movements.csv`

It is the primary copy/paste example for CSVQL v0.8 planning. The goal is to
show that the existing CLI surface can inspect a project, validate it, run a
saved analysis, and export results for both automation and human review.

## Quickstart

```bash
cd examples/saas_revenue

uv run csvql inspect data/revenue_movements.csv --output json
uv run csvql profile revenue_movements --output json
uv run csvql check --output json
uv run csvql run queries/revenue_health.sql --output json
uv run csvql export queries/revenue_health.sql --format json --out output/revenue-health.json --force
uv run csvql export queries/revenue_health.sql --format markdown --out output/revenue-health.md --force
```

## What The Outputs Prove

- `inspect` shows the raw shape of a core project table
- `profile` shows row counts, duplicate counts, and column-level completeness
- `check` validates project health from `.csvql.yml`
- `run` returns the canonical revenue-health readout as JSON
- `export` writes the same analysis to machine-readable JSON and a Markdown sidecar

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

## Regenerate The Data

The committed CSVs are intentional and reproducible. To rewrite them exactly:

```bash
cd examples/saas_revenue
uv run python scripts/regenerate_data.py
```

The script rewrites only the files under `data/`.
