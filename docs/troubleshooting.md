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
| `4` | A CSV file is missing. | Correct the path or update `.csvql.yml`. |
| `6` | A `--table name=path` mapping is invalid. | Use a non-empty path and valid table alias. |
| `7` | A CSV could not be inspected, sampled, or profiled. | Check that it is a readable CSV with a header row. |
| `8` | The project catalog cannot be found or validated. | Run `csvql init`, `csvql add`, or repair `.csvql.yml`. |
| `9` | A saved SQL file is missing, unreadable, or empty. | Create or correct the SQL file. |
| `10` | An export destination already exists. | Choose a new path or use `--force`. |
| `11` | A configured data-quality check failed. | Inspect the failed checks and repair the data or rule. |
| `12` | `csvql doctor` found a project-health problem. | Correct the catalog, sources, or check configuration. |

## CSV file not found

Typical causes are a moved file, a path relative to a different working
directory, or a stale path in `.csvql.yml`. Check the path, then retry with the
correct CSV:

```console
csvql query orders.csv "SELECT * FROM orders LIMIT 5"
csvql add orders data/orders.csv --replace
```

For project catalogs, LocalQL resolves table paths relative to the directory
that contains `.csvql.yml`.

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

Check that the table alias matches the CSV file stem or `--table` mapping, and
that the SQL column names match the CSV header. These commands help inspect a
source:

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

`F3` opens a native CSV picker on macOS. `Ctrl+O` opens the path prompt on every
platform. See the [Terminal menu guide](tui-guide.md) for all keybindings.

## SQL safety

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict filesystem access, or make untrusted SQL safe.

## Still need help?

Use [Support](../SUPPORT.md) for normal bugs and documentation questions. Use
[Security](../SECURITY.md) for sensitive vulnerabilities.
