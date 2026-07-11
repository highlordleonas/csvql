# FAQ

## Why do I install `localql` but run `csvql`?

`localql` is the installable distribution name. The command remains `csvql`
because the tool is still the CSV query workflow users type in the terminal.
The Python import package also remains `csvql`, and project config remains
`.csvql.yml`.

## Is SQL sandboxed?

No. LocalQL treats user-authored SQL as trusted local DuckDB SQL. LocalQL does
not sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL
safe.

## Can SQL read local files?

DuckDB SQL can access local files according to DuckDB behavior and your local
environment. Only run SQL you trust.

## Why use this instead of DuckDB directly?

DuckDB owns SQL execution. LocalQL adds a local workflow around CSV table
aliases, project catalogs, saved SQL files, readable terminal output, explicit
exports, data-quality checks, troubleshooting commands, and the optional TUI.

## Does LocalQL support Parquet, cloud sources, NLP, or web dashboards?

Not in v1.0.0. The v1 scope is local CSV files, DuckDB SQL, CLI workflow,
project catalogs, explicit exports, and the optional terminal menu.

## Where do TUI result sources go?

When you explicitly save a successful tabular result in the TUI, LocalQL writes
`.csvql/results/{alias}.csv` and adds that alias to the current TUI session.
The file remains on disk. The alias becomes durable across sessions only if you
explicitly save sources to `.csvql.yml`.

## What is stable in v1.0.0?

The documented CLI commands, project catalog workflow, saved SQL execution,
explicit exports, JSON/table output contracts, and optional terminal menu are
part of v1.0.0. See the [CLI reference](cli-reference.md) for command details.
