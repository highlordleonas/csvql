# FAQ

## Why do I install `localql` but run `csvql`?

`localql` is the installable distribution name. The command remains `csvql`
because the tool is still the CSV query workflow users type in the terminal.
The Python import package also remains `csvql`, and project config remains
`.csvql.yml`.

## Should I use pip or uv tool?

Use `python -m pip` when LocalQL belongs in an existing Python environment. Use
`uv tool` when you want LocalQL as an isolated command-line application. `uv`
must already be installed before you use `uv tool`.

Both modes install the `csvql` command. Keep using the same mode for upgrades,
optional extras, and uninstalling so you manage the environment your shell
actually runs.

## How do I upgrade or uninstall LocalQL?

For a `pip` environment:

```console
python -m pip install --upgrade localql
python -m pip uninstall localql
```

For an isolated uv tool:

```console
uv tool upgrade localql
uv tool uninstall localql
```

An existing uv tool keeps the extras selected when it was installed. To change
between core and TUI mode, uninstall LocalQL and reinstall it with the desired
package expression.

## Which Python versions are supported?

LocalQL supports Python 3.11 through 3.14: Python 3.11, 3.12, 3.13, and 3.14.

## Why is the terminal workbench optional?

Core LocalQL intentionally omits Textual so the command-line workflow does not
require the terminal UI dependency. Install the `tui` extra when you want to run
`csvql menu`:

```console
python -m pip install "localql[tui]"
uv tool install "localql[tui]"
```

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

Not in v1. LocalQL v1 focuses on local CSV files, DuckDB SQL, project
catalogs, exports, and the optional terminal menu. Future source directions in
the roadmap are product direction, not current connector support.

## Where do TUI result sources go?

When you explicitly save a successful tabular result in the TUI, LocalQL writes
`.csvql/results/{alias}.csv` and adds that alias to the current TUI session.
The file remains on disk. The alias becomes durable across sessions only if you
explicitly save sources to `.csvql.yml`.

## What is stable in v1?

The documented CLI commands, project catalogs, saved SQL, exports, JSON and
table output, and optional terminal menu are part of LocalQL v1. See the
[CLI reference](cli-reference.md) for command details.
