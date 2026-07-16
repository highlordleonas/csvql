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

DuckDB executes SQL. LocalQL adds a local CSV workflow around table aliases,
project catalogs, saved SQL files, readable terminal output, explicit exports,
data-quality checks, troubleshooting commands, and the optional terminal menu.

## Does LocalQL support Parquet, cloud sources, or web dashboards?

LocalQL v1 focuses on local CSV files, DuckDB SQL, project catalogs, exports,
and the optional terminal menu. See the [Roadmap](ROADMAP.md) for planned work.

## Where do terminal-menu result sources go?

When you explicitly save a successful tabular result in the terminal menu,
LocalQL writes `.csvql/results/{alias}.csv` and adds that alias to the current
menu session. The alias becomes durable across sessions only when you explicitly
save sources to `.csvql.yml`.

## Where should I ask for help or report a problem?

Use [Support](../SUPPORT.md) for normal bugs, documentation problems, and
focused feature requests. Use [Security](../SECURITY.md) for sensitive
vulnerabilities; do not include sensitive details in a public issue.
