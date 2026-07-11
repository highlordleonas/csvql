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

Launch with one CSV, or repeat `--table` to load several named CSVs:

```bash
csvql menu examples/saas_revenue/data/revenue_movements.csv
csvql menu --table customers=customers.csv --table orders=orders.csv
```

From a source checkout, use the repo-local environment:

```bash
uv sync --all-extras
uv run --all-extras csvql menu
```

You can add sources after launch with `F3`. On macOS it opens a CSV picker;
`Ctrl+O` opens the path prompt on every platform. You can also paste a standalone
`.csv` path into the SQL editor to add it as a source. CSV paths inside SQL
strings, comments, or expressions remain ordinary SQL text.

![Terminal screenshot of the LocalQL TUI workbench with project sources loaded and a query result visible](assets/localql-tui-workbench.svg)

## Panes

The menu opens with the SQL editor focused.

- SQL editor: write selected SQL, the current statement, or the full buffer
- Sources: inspect, sample, profile, add, remove, and save source mappings
- Results: view the latest or recalled tabular result; `[` and `]` move between
  buffer results when Results is focused
- History: recall results, reopen queries, or rerun queries from the current session
- Help: view available keybindings inside the app

## Core Keys

| Key | Action |
| --- | --- |
| `F4` or `Ctrl+R` | Run selected SQL or the current statement |
| `F7` | Export active result |
| `F12` or `Ctrl+B` | Run the buffer as separate History rows |
| `F2` or `Ctrl+Down` | Focus SQL editor |
| `F3` or `Ctrl+O` | Choose CSV file(s) or prompt for paths |
| `F5` | Focus results |
| `F6` or `Ctrl+Up` | Focus sources |
| `F8` | Focus history |
| `F9` or `q` | Quit outside text entry |
| `F1` | Help |
| `Ctrl+N` or `F10` | Clear editor for a new query |

`F4` or `Ctrl+R` runs the selected or current statement in a fresh DuckDB
session. `F12` or `Ctrl+B` runs the editor's semicolon-delimited statements in
one shared session, so earlier temporary tables can feed later statements in
that buffer.

The History run column labels entries as `current` for F4/Ctrl+R runs,
`buffer` for F12/Ctrl+B runs, and `rerun` for History reruns.

The full workbench needs at least 100 columns by 30 rows. A 120x36 terminal is
recommended.

## Source Actions

When the Sources pane is focused:

| Key | Action |
| --- | --- |
| `i` | Inspect selected source and load columns |
| `s` | Sample selected source |
| `p` | Profile selected source |
| `a` | Add source |
| paste `.csv` paths | Add CSV path text as session sources |
| `d` | Remove selected source from the session after confirmation |
| `w` | Save current sources to `.csvql.yml` |
| `c` | Load or show source columns |
| `l` | Insert selected source alias into SQL |
| `x` | Open starter SQL templates |

The Add source prompt accepts either `name=path` or one or more pasted `.csv`
paths. Direct path paste derives aliases from file names, and duplicate aliases
receive numeric suffixes such as `orders_2`. Added sources are session-local
until you save sources to `.csvql.yml`.

Saving sources to `.csvql.yml` may persist local filesystem paths. Project-relative
paths are portable; external absolute paths and symlink-resolved paths outside the
start directory are allowed for local workflows but can reveal machine-specific
locations if you share the catalog.

Column details stay in the current session and are not written to `.csvql.yml`.
`x` always offers preview rows and row count, and column-aware templates appear
after `c` or `i` loads metadata. In the SQL editor, `Tab` is the primary
SQL-editor completion key. When completion items are available, it opens
the completion list; otherwise it inserts four spaces and keeps focus in
the SQL editor. `Ctrl+Space` remains available where the terminal delivers it.
Generated SQL is editable and does not execute automatically. Pane focus stays
on `F2`, `F5`, `F6`, and `F8`.

## History

History is in-memory session state. It is not written to disk, logged, or sent
anywhere by CSVQL.

When the History pane is focused:

- `Enter` reopens a query in the editor
- `r` reruns a query against the current session sources

History clears when the TUI exits.

## Export Active Result

Press `F7` to export the active tabular result shown in Results. CSVQL prompts
for a file path. The file suffix chooses the format: `.csv`, `.json`, `.md`,
`.markdown`, or `.txt`. If the path has no suffix, CSVQL writes `.csv` by
default.

Relative export paths are resolved from the directory where you launched
`csvql menu`.

## Save A Result As A Source

After a successful tabular query, press `Ctrl+S` to save the active tabular
result as a derived CSV source. `Alt+S` is also available where terminals emit Alt key
events, and `F11` is available where the OS does not intercept it. macOS may
reserve `F11` for Show Desktop.

CSVQL prompts for an alias, writes `.csvql/results/{alias}.csv`, and adds the
alias to the current Sources pane with kind `derived`.

The CSV file remains on disk. The alias becomes durable across TUI sessions only
if you explicitly save sources to `.csvql.yml`.

## Important Behavior

- The terminal menu follows the same SQL safety rules as the CLI: run only SQL
  you trust.
- Saving a result as a source creates a normal CSV file. LocalQL does not create
  a hidden result cache.
- The terminal menu is optional; all core commands are also available from the
  CLI.
