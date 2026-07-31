# LocalQL v1.2.0 Benchmarks

This page publishes one reproducible performance snapshot for LocalQL 1.2.0.
It is evidence for the multi-format export workflow on the recorded environment,
not a universal speed claim or a comparison with another product.

## What was measured

The benchmark crosses all five local source providers with the three structured
export formats added in v1.2.0:

- sources: CSV, JSON, NDJSON, Parquet, and Excel `.xlsx`
- outputs: NDJSON, Parquet, and Excel `.xlsx`
- workload: 100,000 synthetic rows with `id`, `category`, `amount`, and `active`
- repetitions: one warmup followed by three measured runs per route
- reported time: the median of the three measured runs

Each timing is an end-to-end `csvql export` invocation. It includes process
startup, deterministic source resolution, query execution, export writing, and
atomic publication of the completed file. Validation runs after the timer and
checks the row count plus deterministic ID sum, minimum, and maximum.

## Reference environment

| Item | Recorded value |
| --- | --- |
| LocalQL | `1.2.0` |
| Reference code | [`5c9f793552e6b39df62c5e4671c82376e31025a4`](https://github.com/highlordleonas/csvql/commit/5c9f793552e6b39df62c5e4671c82376e31025a4) |
| Generated | `2026-07-31T12:13:48.455158Z` |
| Python | `3.12.11` |
| DuckDB | `1.5.4` |
| DuckDB Excel extension | `f4c72b5` |
| Platform | `macOS 26.5.2`, ARM64 |
| Rows per route | `100,000` |
| Warmup / measured runs | `1 / 3` |

The run did not record the exact CPU model, storage model, power state, or
background workload. Treat those as uncontrolled variables when interpreting
or attempting to reproduce the numbers.

## Results

| Source | Output | Input bytes | Output bytes | Median ms | Rows/s |
| --- | --- | ---: | ---: | ---: | ---: |
| CSV | NDJSON | 2,727,917 | 7,327,890 | 648.976 | 154,088.9 |
| CSV | Parquet | 2,727,917 | 805,594 | 299.864 | 333,484.9 |
| CSV | Excel | 2,727,917 | 1,883,439 | 476.487 | 209,869.1 |
| JSON | NDJSON | 6,417,892 | 7,327,890 | 625.427 | 159,890.7 |
| JSON | Parquet | 6,417,892 | 805,594 | 278.840 | 358,628.1 |
| JSON | Excel | 6,417,892 | 1,883,439 | 454.780 | 219,886.6 |
| NDJSON | NDJSON | 6,417,890 | 7,327,890 | 618.473 | 161,688.5 |
| NDJSON | Parquet | 6,417,890 | 805,594 | 269.798 | 370,647.4 |
| NDJSON | Excel | 6,417,890 | 1,883,439 | 447.171 | 223,628.0 |
| Parquet | NDJSON | 805,594 | 7,327,890 | 532.037 | 187,956.9 |
| Parquet | Parquet | 805,594 | 805,594 | 184.951 | 540,683.5 |
| Parquet | Excel | 805,594 | 1,883,439 | 364.215 | 274,563.2 |
| Excel | NDJSON | 1,883,439 | 7,327,890 | 815.096 | 122,685.0 |
| Excel | Parquet | 1,883,439 | 805,594 | 469.332 | 213,068.9 |
| Excel | Excel | 1,883,439 | 1,883,439 | 659.463 | 151,638.5 |

All 15 routes passed post-timing validation for 100,000 output rows, an ID sum
of `4,999,950,000`, a minimum ID of `0`, and a maximum ID of `99,999`.

## How to interpret the matrix

- These are local end-to-end CLI measurements, not isolated parser or writer
  microbenchmarks.
- A row includes both its source-decoding and output-encoding costs. Do not read
  the table as a source-format ranking independent of the selected output.
- Input and output encodings have different byte sizes and type-preservation
  behavior, so throughput alone does not choose the right format.
- Three measured runs are sufficient for a release regression signal, not for a
  statistically robust hardware benchmark.
- The Excel routes require DuckDB's `excel` extension to have been provisioned
  explicitly before the run; LocalQL does not install it automatically.
- Use these values as a baseline only when the machine, runtime versions,
  dataset, warmups, and measured-run count are comparable.

For format-selection guidance, see
[Save and reuse results](cli-reference.md#save-and-reuse-results). For the exact
source-checkout command and evidence location, see
[Benchmark structured exports](development.md#benchmark-structured-exports).
The benchmark implementation is
[`scripts/benchmark_multiformat_exports.py`](../scripts/benchmark_multiformat_exports.py).
