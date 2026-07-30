# FAQ

## Why do I install `localql` but run `csvql`?

`localql` is the installable distribution name. The command remains `csvql`, as
do the Python import package and the `.csvql.yml` project configuration.

## Should I install the terminal menu?

No. `python -m pip install localql` provides the full core CLI. Install
`localql[tui]` only when you want the optional `csvql menu` terminal workbench.
The core CLI and project catalogs work without it.

## Which Python versions and operating systems are supported?

LocalQL supports Python 3.11 through 3.14 on macOS, Linux, and Windows.

## Is SQL sandboxed?

No. LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL safe.

## Can SQL read local files?

DuckDB SQL can access local files according to DuckDB behavior and your local
environment. Only run SQL you trust.

## Why use LocalQL instead of DuckDB directly?

DuckDB executes SQL. LocalQL adds deterministic local-source selection, table
aliases, project catalogs, saved SQL files, readable terminal output, explicit
exports, data-quality checks, troubleshooting commands, and the optional
terminal menu.

## Which source formats does LocalQL support?

LocalQL supports local CSV, Parquet (including explicitly typed partitioned
datasets), JSON, NDJSON/JSON Lines, and Excel `.xlsx` sources. The Excel provider
requires DuckDB's optional `excel` extension to be provisioned before LocalQL
starts; LocalQL does not install it during a query.

Cloud sources, remote databases, object stores, and web dashboards are outside
this local-source release. See the [Roadmap](ROADMAP.md) for planned work.

## How does LocalQL choose a source type?

An explicit type always wins. Otherwise, one recognized extension selects its
provider. If a file is extensionless or a directory is supplied without a type,
LocalQL may inspect a bounded amount of local metadata to report possible
matches, but it intentionally does not select from those matches. The
diagnostic tells you which explicit choice is required.

## Where do terminal-menu result sources go?

When you explicitly save a complete preserved tabular result in the terminal
menu, LocalQL writes `.csvql/results/{alias}.csv` and adds that alias to the
current menu session. The alias becomes durable across sessions only when you
explicitly save sources to `.csvql.yml`.

A preview-only result cannot be saved as a source because LocalQL will not
present a partial result as complete. If session capacity was exhausted, delete
an older preserved result from History and rerun the query. If the result's
temporary storage was lost, rerun the query to create a new complete result.

## Where should I ask for help or report a problem?

Use [Support](../SUPPORT.md) for normal bugs, documentation problems, and
focused feature requests. Use [Security](../SECURITY.md) for sensitive
vulnerabilities; do not include sensitive details in a public issue.
