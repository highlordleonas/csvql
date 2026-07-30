# Troubleshooting

Start with the error shown in your terminal, then use the matching section
below for common causes and fixes.

## `csvql` command not found

Confirm that LocalQL is installed in the Python environment you selected:

```console
python -m pip show localql
python -m pip install localql
csvql --version
```

If the package is installed but the command is still unavailable, activate the
same Python environment or add its scripts directory to `PATH`. On Windows,
open a new terminal after changing `PATH`.

## Common exit codes

| Exit code | What it usually means | What to try |
| --- | --- | --- |
| `1` | A query or another runtime command failed. | Read the error, then check SQL or the command-specific requirement. |
| `4` | A configured local source is missing. | Correct the path or update `.csvql.yml`. |
| `6` | A source or legacy `--table name=path` mapping is invalid. | Use a non-empty path, valid alias, and matching source type. |
| `7` | A source could not be inspected, sampled, or profiled. | Check that the locator, type, options, and dependency are valid. |
| `8` | The project catalog cannot be found or validated. | Run `csvql init`, `csvql add`, or repair `.csvql.yml`. |
| `9` | A saved SQL file is missing, unreadable, or empty. | Create or correct the SQL file. |
| `10` | An export destination already exists. | Choose a new path or use `--force`. |
| `11` | A configured data-quality check failed. | Inspect the failed checks and repair the data or rule. |
| `12` | `csvql doctor` found a project-health problem. | Correct the catalog, sources, or check configuration. |

## Local source not found

Typical causes are a moved file, a path relative to a different working
directory, or a stale locator in `.csvql.yml`. Check the path, then retry with
the correct source:

```console
csvql query orders.csv "SELECT * FROM orders LIMIT 5"
csvql add orders data/orders.csv --replace
```

For project catalogs, LocalQL resolves table paths relative to the directory
that contains `.csvql.yml`.

## Source type is ambiguous

LocalQL does not choose a provider heuristically. An extensionless file or
untyped directory may produce a diagnostic with candidate evidence and the
required action `specify_type`. Retry with an explicit type:

```console
csvql inspect data/order_facts --type parquet
csvql query data/order_facts "SELECT COUNT(*) FROM order_facts" --type parquet
```

Directories are never recursively scanned to guess their dataset type.
Partitioned Parquet directories require explicit `--type parquet` intent.

## Optional source dependency is missing

Provider activation is lazy. A missing optional dependency is reported only
after its provider is selected, and LocalQL does not install it automatically.
For Excel `.xlsx`, provision DuckDB's `excel` extension in the environment
before running the command, then retry. The JSON extension must likewise be
available for JSON and NDJSON sources.

The diagnostic includes the dependency key, lifecycle stage, and required next
action without exposing raw exception details.

## No `.csvql.yml` project catalog found

Catalog-backed commands need a project catalog or explicit `--table` mappings.
Create a catalog in your project directory:

```console
csvql init
csvql add revenue_movements data/revenue_movements.csv
csvql tables
```

Or provide a table for one command:

```console
csvql query --table revenue_movements=data/revenue_movements.csv "SELECT COUNT(*) FROM revenue_movements"
```

## DuckDB query failed

Check that the table alias matches the source file stem, `--source` mapping, or
legacy CSV `--table` mapping, and that SQL column names match the source schema.
These commands help inspect a source:

```console
csvql inspect revenue_movements --output json
csvql sample revenue_movements --limit 5
```

## Export output already exists

LocalQL does not overwrite an export unless you choose `--force`:

```console
csvql export queries/revenue_health.sql --format csv --out output/revenue-health.csv
```

Use `--force` only when replacing that file is intended.

## Terminal menu dependency is not installed

Install the optional extra, then open the menu again:

```console
python -m pip install "localql[tui]"
csvql menu
```

## Terminal-menu keys do not work

Use `F4` or `Ctrl+R` to run the current SQL. On macOS, `F11` may be intercepted
by Show Desktop; use `Ctrl+S` to save a result as a derived source.

`F3` opens a native source picker on macOS. When native selection is unavailable,
`F3` or `Ctrl+O` opens the portable path prompt. Press `a` in Sources for the
full alias, type, and option flow. See the
[Terminal menu guide](tui-guide.md) for all keybindings.

## Terminal-menu session capacity was exhausted

If the menu says preservation stopped because the TUI session capacity was
exhausted, the retained preview remains viewable, but full export and save are
unavailable for that result. LocalQL does not automatically evict an earlier
complete result or write a partial export.

Focus History with `F8`, highlight an older preserved result, press `Delete`,
and confirm the deletion. Then rerun the preview-only query so LocalQL can try
to preserve it as a new complete result.

If you need a large result only as a file, `csvql export` streams the complete
result without using the terminal menu's result-storage capacity.

## The full result is no longer available because its temporary storage was lost

The menu may still show the retained preview and query History, but the
preserved complete result is gone. Full export and save remain unavailable for
that result. Highlight the query in History and press `r`, or reopen it with
`Enter` and run it again, to create a new complete result.

## SQL safety

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict filesystem access, or make untrusted SQL safe.

## Still need help?

Use [Support](../SUPPORT.md) for normal bugs and documentation questions. Use
[Security](../SECURITY.md) for sensitive vulnerabilities.
