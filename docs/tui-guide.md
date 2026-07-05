# Terminal Menu Guide

`csvql menu` is an optional Textual-powered terminal workbench for the same
local CSV sources and trusted SQL used by the CLI. It is useful when you want to
iterate in a terminal without repeatedly retyping source mappings.

## Launch

From an installed package, install the optional extra first:

```bash
pip install "localql[tui]"
csvql menu
```

Then open a CSV or repeated table mappings:

```bash
csvql menu examples/saas_revenue/data/revenue_movements.csv
csvql menu --table customers=customers.csv --table orders=orders.csv
```

From a source checkout, use the repo-local environment:

```bash
uv sync --all-extras
uv run --all-extras csvql menu
```

You can also add sources after launch with `F3`. On macOS it opens a local CSV
picker; elsewhere it opens a CSV path prompt. Pasting `.csv` paths into the SQL
editor also turns those paths into session sources immediately.

![Terminal screenshot of the LocalQL TUI workbench with project sources loaded and a query result visible](assets/localql-tui-workbench.svg)

## Panes

The menu opens with the SQL editor focused.

- SQL editor: write selected SQL, the current statement, or the full buffer
- Sources: inspect, sample, profile, add, remove, and save source mappings
- Results: view the latest or recalled tabular result
- History: recall results, reopen queries, or rerun queries from the current session
- Help: view available keybindings inside the app

## Core Keys

| Key | Action |
| --- | --- |
| `F4` | Run selected SQL or the current statement |
| `F12` | Run all semicolon-delimited editor statements as separate History rows |
| `F2` or `Ctrl+Down` | Focus SQL editor |
| `F3` | Choose CSV file(s) on macOS or open a CSV path prompt elsewhere |
| `F5` | Focus results |
| `F6` or `Ctrl+Up` | Focus sources |
| `F8` | Focus history |
| `F9` | Quit |
| `?` | Help |
| `F1` | Also opens Help |
| `Ctrl+N` or `F10` | Clear editor for a new query |

## Source Actions

When the Sources pane is focused:

| Key | Action |
| --- | --- |
| `i` | Inspect selected source |
| `s` | Sample selected source |
| `p` | Profile selected source |
| `a` | Add source |
| paste `.csv` paths | Add CSV path text as session sources |
| `d` | Remove source from the session |
| `w` | Save current sources to `.csvql.yml` |
| `c` | Load or show source columns |
| `l` | Insert selected source alias into SQL |
| `x` | Insert `SELECT *` starter query |

The Add source prompt accepts either `name=path` or one or more pasted `.csv`
paths. Direct path paste derives aliases from file names, and duplicate aliases
receive numeric suffixes such as `orders_2`. Added sources are session-local
until you save sources to `.csvql.yml`.

Column metadata is session-local and is not written to `.csvql.yml`.

## History

History is in-memory session state. It is not written to disk, logged, or sent
anywhere by CSVQL.

When the History pane is focused:

- `Enter` reopens a query in the editor
- `r` reruns a query against the current session sources

History clears when the TUI exits.

## Save A Result As A Source

After a successful tabular query, press `Ctrl+S` to save the result as a derived
CSV source. `Alt+S` is also available where terminals emit Alt key events, and
`F11` is available where the OS does not intercept it. macOS may reserve `F11`
for Show Desktop.

CSVQL prompts for an alias, writes `.csvql/results/{alias}.csv`, and adds the
alias to the current Sources pane with kind `derived`.

The CSV file remains on disk. The alias becomes durable across TUI sessions only
if you explicitly save sources to `.csvql.yml`.

## Boundaries

- The TUI uses the same trusted local DuckDB SQL posture as the CLI.
- Derived result sources are explicit CSV files, not hidden cache or automatic
  materialization.
- The TUI is optional; the CLI remains the complete core workflow.
