# Benchmarking

LocalQL includes a repo-local benchmark harness for the existing `csvql` CLI
surface.

## Scope

The benchmark matrix covers:

- `query data/orders.csv --output json`
- `run queries/revenue_by_month.sql --output json`
- `inspect orders --output json`
- `inspect orders --exact --output json`
- `profile orders --output json`
- `check orders --output json`

## Run It

Run `uv run python scripts/benchmark_csvql.py --output-root output/benchmarks`.

The run writes:

- `output/benchmarks/<run-id>/benchmark.json`
- `output/benchmarks/<run-id>/benchmark-summary.md`

## Claims Boundary

- Local benchmark evidence only
- No large-file proof beyond the recorded datasets
- No production-readiness claim
