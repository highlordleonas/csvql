# TUI SQL Assistance Design

## Status

Draft written spec pending user review.

The conversation-level design was approved on 2026-07-08. This written spec
must not move to implementation planning until the user reviews and approves the
tracked revision.

## Baseline Truth

Design-session repo truth:

- branch: `main`
- tracked status: clean and tracking `origin/main`
- `HEAD`: `0990fd3 test: wait for tui sample before export refusal`
- `origin`: `https://github.com/highlordleonas/csvql.git`
- no tag points at `HEAD`
- no repo-local `AGENTS.md` or `AGENTS.override.md` was found in the checked
  repo scope

## Skill Activation Contract

Before writing the implementation plan, use `superpowers:writing-plans`.

Before editing tracked docs, use `documentation`.

Before editing `src/**/*.py`, `tests/**/*.py`, Python tooling, `uv` behavior,
package metadata, or TUI behavior, use `python-codebase-standards`.

Before changing behavior or guard tests, use `superpowers:test-driven-development`
unless the implementation plan explicitly embeds failing-test-first steps.

If TUI key handling or Textual behavior contradicts assumptions, use
`superpowers:systematic-debugging` before making another fix.

Before claiming completion, use `superpowers:verification-before-completion`.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, `csvql` Python import package, `.csvql.yml` project config, and
`csvql menu` TUI command.

The current TUI already has a Source Intelligence cluster:

- `i` inspects the selected source
- `c` loads or shows source columns
- `l` inserts the selected source alias
- `x` inserts a `SELECT *` starter query

Manual use showed that `i` and `c` currently produce nearly identical visible
output: both show a column/type table. The hidden distinction is that `c`
stores columns in session state. That distinction is too weak for a user-facing
shortcut.

The current `x` starter query is also too shallow for real analytical work. It
inserts a preview query, but it does not help users get to row counts, grouped
summaries, numeric summaries, date trends, or conservative joins.

The product direction remains local-first and deterministic. This feature
should help users write DuckDB SQL faster from known local CSV metadata. It must
not become natural-language execution, hidden analytics, or automatic query
execution.

## Goals

- Make `i` visibly useful as source inspection rather than a duplicate of `c`.
- Keep `c` as explicit, session-local column loading and quick column display.
- Replace the single `x` starter insert with a starter-template picker.
- Add a SQL-editor-only completion palette that helps insert aliases, loaded
  columns, SQL keywords, and snippets.
- Generate useful, deterministic, editable DuckDB SQL templates from selected
  source metadata.
- Support conservative join starters only when loaded sources share an exact
  column name.
- Keep all generated SQL user-reviewable and non-executing until the user runs
  it explicitly.
- Preserve the current release and safety boundaries.

## Non-Goals

- No full as-you-type IntelliSense in this slice.
- No NLP, natural-language query generation, or AI insight generation.
- No hidden execution.
- No automatic background file scans while the user types.
- No fuzzy join inference such as `customer_id` to `id`.
- No dataframe-first API, plugin system, web app, or cloud connector.
- No sandbox-safety, safe-untrusted-SQL, production-readiness, or broad
  large-file claims.
- No tag, publish, GitHub release, release artifact upload, package version
  change, or `v1-stable` claim.

## Design

### Source Actions

`i` becomes a richer inspect action. It should show information that differs
from `c`, including source identity and source-level metadata where available:

- alias
- origin
- display path
- row-count status when inspection provides it
- column count
- dialect or sniffed CSV details when inspection provides them
- column/type rows

`i` may also store the inspected column metadata in session state, because the
user has explicitly requested source metadata. This makes `i` useful before
opening the SQL completion palette.

`c` remains the quick column action. It loads columns into session memory and
shows a compact column/type table. Column metadata is session-local and is not
written to `.csvql.yml`.

`l` keeps inserting the selected source alias into the SQL editor.

`x` opens a starter-template picker for the selected source. It no longer
blindly inserts only `SELECT * FROM alias LIMIT 10;`.

### Starter Templates

Starter templates insert SQL into the editor. They do not execute SQL.

The template picker should include deterministic options when enough metadata is
loaded:

- preview rows
- row count
- group by a text-like column
- numeric summary for numeric columns
- date or month trend for date-like columns
- exact shared-column join starter when a conservative join candidate exists

Templates should not guess business meaning. A column named `mrr_delta` may
enable a numeric summary because it is numeric, but the app should not claim it
understands SaaS revenue.

Generated templates use deterministic table aliases and alias-qualified columns
where that improves clarity and robustness. Example shape:

```sql
SELECT
  rm.movement_type,
  COUNT(*) AS rows,
  SUM(rm.mrr_delta) AS total_mrr_delta
FROM revenue_movements AS rm
GROUP BY rm.movement_type
ORDER BY total_mrr_delta DESC;
```

Alias generation should be stable and boring:

- `revenue_movements` should become `rm`
- `customers` should become `c`
- `subscriptions` should become `s`
- collisions should receive deterministic suffixes or otherwise stable
  disambiguation

Join templates should appear only when two loaded sources share an exact column
name. Join templates must use deterministic aliases and qualified columns.

### SQL Completion Palette

The completion palette is v1 autocomplete. It is explicit, not as-you-type.

It works only from the SQL editor in this slice. `Ctrl+Space` is the preferred
primary trigger. The implementation plan must verify a fallback key that Textual
and the supported terminal test harness handle cleanly before documenting that
fallback as user-facing behavior.

The palette should offer:

- loaded table aliases
- loaded columns
- common SQL keywords
- useful SQL snippets

Alias suggestions are available immediately from current TUI sources. Column
suggestions are available only for sources whose columns have been loaded by `c`
or `i`. Opening the palette must not auto-read CSV files or start background
metadata loading.

Column completion should optimize for quick typing while avoiding sloppy
multi-source output:

- in a single-source helper context, inserting a column should insert the bare
  column name, such as `mrr_delta`
- when a template or multi-source helper context has an active alias map,
  generated SQL should use alias-qualified names, such as `rm.mrr_delta`

The palette may display source context even when inserting a bare column, for
example `mrr_delta  column  revenue_movements DOUBLE`.

### Component Boundaries

The implementation should keep most SQL-assistance logic outside
`src/csvql/tui_app.py`.

Expected new focused module:

- `src/csvql/tui_sql_assist.py`

Responsibilities:

- classify loaded columns by source
- generate deterministic table aliases
- build starter templates
- find exact shared-column join candidates
- build completion items
- decide completion insertion text

Existing TUI responsibilities:

- show picker or modal UI
- pass selected source, sources, loaded columns, and current editor text into
  SQL-assistance helpers
- insert selected text into the `TextArea`
- update status messages
- preserve explicit user-triggered execution only

Data flow:

1. User presses `c` or `i`.
2. The TUI loads source metadata and stores loaded columns in `TUISessionState`.
3. User presses `x` or opens completion from the SQL editor.
4. The TUI calls SQL-assistance helpers with sources, loaded columns, selected
   source, and current editor context.
5. Helpers return deterministic items or templates.
6. The TUI displays a picker.
7. User selects an item.
8. The TUI inserts text into the editor.
9. Nothing runs until the user explicitly runs SQL.

## Error Handling

If no source is selected, source-pane assistance actions should keep using the
existing "No source selected" error path.

If a template requires loaded columns and columns are not loaded, the picker
should either omit that template or show a clear disabled/unavailable state. It
must not auto-read the CSV as a side effect of opening the picker.

If no completion items are available, the palette should close or show a clear
status message without changing editor text.

If the fallback completion key is not reliable in Textual tests, the
implementation plan must choose a different fallback or document `Ctrl+Space`
as the only supported trigger for the first slice.

## Acceptance Criteria

- `i` is visibly distinct from `c` and includes source-level inspection
  metadata, not only the same column/type grid.
- `c` still loads columns into session state and displays the quick column/type
  table.
- `x` opens a starter-template picker.
- Selecting a starter template inserts SQL into the editor and does not execute
  it.
- Starter templates include preview, row count, text grouping, numeric summary,
  date trend where applicable, and exact shared-column join where applicable.
- Join templates are omitted when no exact shared column exists.
- Template SQL uses deterministic aliases where helpful.
- SQL editor completion opens with `Ctrl+Space` and a verified fallback key, or
  the fallback is explicitly deferred if Textual does not support it cleanly.
- Completion suggests aliases immediately.
- Completion suggests columns only for loaded source metadata.
- Completion inserts bare column names in single-source helper contexts.
- Completion or templates use alias-qualified columns for multi-source/template
  contexts.
- Opening completion does not read CSV files, run SQL, or mutate results.
- Docs and help text describe the new behavior without implying AI, hidden
  execution, or safety for untrusted SQL.

## Test Plan

Unit tests should cover `tui_sql_assist.py`:

- deterministic alias generation
- alias collision behavior
- preview template generation
- row-count template generation
- text grouping template generation
- numeric summary template generation
- date trend template generation
- exact-column join template generation
- no join template without exact shared columns
- completion items include aliases without loaded columns
- completion items include columns only after metadata is supplied
- single-source column insertion is bare
- multi-source/template generation uses aliases and qualified columns

TUI interaction tests should cover:

- `i` result differs visibly from `c`
- `i` can load columns for later completion
- `x` opens a picker and inserts selected SQL without running it
- completion palette opens from the SQL editor
- completion palette is not active from unrelated panes
- selecting an alias inserts text
- selecting a loaded column inserts text
- opening completion does not call inspect/sample/profile/query code
- fallback key behavior is verified before docs claim it

Verification for the implementation lane should include targeted unit tests,
targeted TUI tests, Ruff format check, Ruff lint, mypy over `src`, and full
pytest before any completion claim.

## Proof Boundaries

This design proves only deterministic local SQL assistance behavior after
implementation and verification.

It does not prove natural-language understanding, business insight generation,
automatic analytics correctness, production readiness, sandbox isolation, or
safe execution of untrusted SQL.

Generated SQL remains trusted local DuckDB SQL that the user can inspect and
choose to run.
