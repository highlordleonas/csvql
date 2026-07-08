# TUI SQL Assistance Design

## Status

Approved design pending implementation.

The conversation-level design and tracked revised spec were approved on
2026-07-08. Implementation must follow the Skill Activation Contract and the
approved implementation plan.

## Baseline Truth

Design-session repo truth:

- branch: `main`
- tracked status: clean and tracking `origin/main`
- `HEAD`: `0990fd3 test: wait for tui sample before export refusal`
- `origin`: `https://github.com/highlordleonas/csvql.git`
- no tag points at `HEAD`
- no repo-local `AGENTS.md` or `AGENTS.override.md` was found in the checked
  repo scope

This baseline is historical design-session context, not current proof. Each
implementation or proof-execution session must rerun live repo truth before
acting.

## Skill Activation Contract

Before writing the implementation plan, use `superpowers:writing-plans`.

Before editing tracked docs, use `documentation`.

Before editing `src/**/*.py`, `tests/**/*.py`, `.github/workflows/**`, Python
tooling, `uv` behavior, package metadata, TUI behavior, keybindings, or CI
commands, use `python-codebase-standards`.

Before changing behavior or guard tests, use `superpowers:test-driven-development`
unless the implementation plan explicitly embeds failing-test-first steps.

If Textual key handling, modal focus, generated SQL behavior, or CI behavior
contradicts assumptions, use `superpowers:systematic-debugging` before making
another fix.

Before accepting the implementation branch, use `code-review` or
`superpowers:requesting-code-review`.

Before claiming completion, use `superpowers:verification-before-completion`.

Remote actions are separately gated. This spec does not authorize pushing,
hosted CI execution, private GitHub log collection, tags, publishing, release
actions, version changes, or artifact uploads.

## Context

LocalQL is the installable distribution name. The runtime contract remains the
`csvql` CLI, `csvql` Python import package, `.csvql.yml` project config, and
`csvql menu` TUI command.

The current TUI already has a Source Intelligence cluster:

- `i` inspects the selected source
- `c` loads or shows source columns
- `l` inserts the selected source alias/table name
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
- Add a SQL-editor-only completion palette that helps insert source
  aliases/table names, loaded columns, SQL keywords, and snippets.
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
- No SQL parser, completion engine, or other new runtime/development dependency
  by default. Any dependency, lockfile, or package metadata change needs
  explicit implementation-plan justification and separate user approval.
- No dataframe-first API, plugin system, web app, or cloud connector.
- No sandbox-safety, safe-untrusted-SQL, production-readiness, or broad
  large-file claims.
- No tag, publish, GitHub release, release artifact upload, package version
  change, or `v1-stable` claim.

## Design

### Terminology

This spec uses two different alias concepts. Implementation docs, helper names,
and tests should keep them distinct.

- Source alias or source table name: the loaded TUI source name, such as
  `revenue_movements`. This is the name shown in the source table, stored on the
  `TUISource`, inserted by `l`, and used as the DuckDB table name in generated
  `FROM` clauses.
- Generated SQL range alias: a short SQL alias generated only for editable SQL
  text, such as `rm` in `FROM "revenue_movements" AS rm`. This is not a loaded
  TUI source name, is not persisted to `.csvql.yml`, and must be deterministic.
- Generated output alias: a SQL result-column alias generated for expressions,
  such as `sum_mrr_delta` or `non_null_customer_id`.

### Source Actions

`i` becomes a richer inspect action. It should show information that differs
from `c`, including source identity and source-level metadata where available:

- source alias/table name
- origin
- display path
- row-count status when inspection provides it
- column count
- dialect or sniffed CSV details when inspection provides them
- column/type rows

If `i` completes successfully, it must store the inspected column metadata in
session state for completion and template use. `c` remains the explicit
"show/load columns" path. Both `i` and `c` should converge on the same
session-local column metadata model.

`i` must not force an exact full row count by default. It may display row-count
status only when already available from the inspection result. Otherwise it
should display `not counted`, display `unknown`, or omit the exact row count.
This design does not broaden into large-file performance proof.

`c` remains the quick column action. It loads columns into session memory and
shows a compact column/type table. Column metadata is session-local and is not
written to `.csvql.yml`.

`l` keeps inserting the selected source alias/table name into the SQL editor.

`x` opens a starter-template picker for the selected source. It no longer
blindly inserts only `SELECT * FROM <source> LIMIT 10;`.

`x` must still offer metadata-free templates that require only the selected
source alias/table name, such as preview rows and row count. Column-dependent
templates are omitted or shown disabled until columns have been loaded by `c` or
`i`. Opening `x` must not inspect or auto-read the CSV as a side effect. Status
or help text should tell the user to press `c` or `i` for column-aware
templates.

### Starter Templates

Starter templates insert SQL into the editor. They do not execute SQL.

The v1 template picker is limited to these deterministic starter options.
Preview and row-count templates require only a selected source alias/table name.
Column-dependent templates require loaded column metadata:

- preview rows
- row count
- numeric summary for numeric columns
- group by a text-like category column
- date or month trend for date-trend-eligible columns
- missingness or null profile
- exact shared-column join skeleton when multiple loaded sources share a column
  name

Templates should not guess business meaning. A column named `mrr_delta` may
enable a numeric summary because it is numeric, but the app should not claim it
understands SaaS revenue.

V1 does not include column sub-selection inside the template picker. When a
template needs a column, it uses the first deterministic eligible column from
the loaded metadata order. Column sub-selection can be considered later, but it
is not part of this slice.

V1 type classification should be deterministic:

- numeric: DuckDB type contains `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT`,
  `DOUBLE`, `FLOAT`, `REAL`, `DECIMAL`, or `NUMERIC`
- date-trend eligible: DuckDB type contains `DATE` or `TIMESTAMP`
- time-only: DuckDB type contains `TIME` and does not contain `DATE` or
  `TIMESTAMP`; these columns remain available for generic completion but are
  excluded from date/month trend templates unless a separate time-of-day
  template is explicitly approved
- text-like: DuckDB type contains `VARCHAR`, `TEXT`, `STRING`, or an equivalent
  textual type already exposed by DuckDB inspection
- unknown types remain available in generic completion but are excluded from
  specialized templates

The implementation plan may refine these rules if repo truth shows an existing
type helper with a stronger local contract, but it must keep classification
deterministic.

### Template SQL Contracts

Generated SQL must reuse the existing DuckDB identifier rendering behavior,
such as `render_duckdb_identifier()` or `quote_identifier()`, so source aliases,
source table names, and column headers with spaces, punctuation, reserved words,
or mixed case remain valid.

Generated identifiers also have to be deterministic and valid:

- Source aliases/table names and column names must use existing DuckDB
  identifier rendering.
- Generated SQL range aliases must be safe unquoted DuckDB identifiers matching
  `[a-z_][a-z0-9_]*`, derived deterministically from the source alias/table
  name, and adjusted to avoid collisions with the exact v1 reserved-word set
  below.
- Generated output aliases must be safe unquoted DuckDB identifiers matching
  `[a-z_][a-z0-9_]*`, derived from sanitized stems rather than raw column text,
  and adjusted to avoid collisions with the exact v1 reserved-word set below.
- The exact v1 reserved-word avoidance set for generated unquoted identifiers is
  `all`, `and`, `as`, `by`, `case`, `cast`, `create`, `delete`, `from`,
  `group`, `insert`, `join`, `limit`, `not`, `null`, `or`, `order`, `select`,
  `table`, `update`, `where`, and `with`. If a generated identifier collides,
  prefix it with `t_` for range aliases or `col_` for output aliases before
  applying collision suffixes.
- Collision handling for generated SQL range aliases and generated output
  aliases must be deterministic.

The v1 templates have these minimum deterministic SQL shapes:

- Preview rows:

  ```sql
  SELECT *
  FROM "revenue_movements"
  LIMIT 10;
  ```

- Row count:

  ```sql
  SELECT COUNT(*) AS row_count
  FROM "revenue_movements";
  ```

- Numeric summary: use the first deterministic numeric column from the loaded
  metadata order. V1 summarizes one numeric column per generated query to keep
  output bounded.

  ```sql
  SELECT
    COUNT(*) AS rows,
    COUNT(rm."mrr_delta") AS non_null_mrr_delta,
    MIN(rm."mrr_delta") AS min_mrr_delta,
    AVG(rm."mrr_delta") AS avg_mrr_delta,
    MAX(rm."mrr_delta") AS max_mrr_delta,
    SUM(rm."mrr_delta") AS sum_mrr_delta
  FROM "revenue_movements" AS rm;
  ```

- Text/category grouping: use the first deterministic text-like column from the
  loaded metadata order. Include `COUNT(*) AS rows`, order by rows descending,
  and include a bounded limit.

  ```sql
  SELECT
    rm."movement_type",
    COUNT(*) AS rows
  FROM "revenue_movements" AS rm
  GROUP BY rm."movement_type"
  ORDER BY rows DESC
  LIMIT 20;
  ```

- Date/month trend: available only for `DATE` or `TIMESTAMP` columns. Use the
  first deterministic eligible column from the loaded metadata order.

  ```sql
  SELECT
    date_trunc('month', rm."movement_month") AS month,
    COUNT(*) AS rows
  FROM "revenue_movements" AS rm
  GROUP BY month
  ORDER BY month;
  ```

- Missingness/null profile: use the first deterministic loaded column. V1
  profiles one column per generated query to keep output bounded.

  ```sql
  SELECT
    COUNT(*) AS rows,
    COUNT(rm."customer_id") AS non_null_customer_id,
    COUNT(*) - COUNT(rm."customer_id") AS null_customer_id
  FROM "revenue_movements" AS rm;
  ```

- Exact shared-column join skeleton: use only exact shared column names between
  two loaded sources. Use deterministic generated SQL range aliases and rendered
  identifiers. Keep the generated SQL editable and non-executing until the user
  explicitly runs it.

  ```sql
  SELECT *
  FROM "revenue_movements" AS rm
  JOIN "customers" AS c
    ON rm."customer_id" = c."customer_id"
  LIMIT 50;
  ```

Generated templates use deterministic generated SQL range aliases and
range-alias-qualified columns where that improves clarity and robustness. The
example below is illustrative of shape and quoting:

```sql
SELECT
  rm."movement_type",
  COUNT(*) AS rows,
  SUM(rm."mrr_delta") AS total_mrr_delta
FROM "revenue_movements" AS rm
GROUP BY rm."movement_type"
ORDER BY total_mrr_delta DESC;
```

Generated SQL range alias generation should be stable and boring:

- `revenue_movements` should become `rm`
- `customers` should become `c`
- `subscriptions` should become `s`
- collisions should receive deterministic suffixes or otherwise stable
  disambiguation

Join templates should appear only when two loaded sources share an exact column
name. Join templates must use deterministic generated SQL range aliases and
range-alias-qualified columns.

### SQL Completion Palette

The completion palette is v1 autocomplete. It is explicit, not as-you-type.

It works only from the SQL editor in this slice. `Ctrl+Space` is the preferred
primary trigger. This spec does not name a fallback key. The implementation
plan must include a Textual key-behavior check and make a documented fallback
decision before docs claim one. If no reliable fallback is found, the
implementation must document `Ctrl+Space` as the only supported v1 trigger.

The palette should offer:

- loaded source aliases/table names
- loaded columns
- common SQL keywords
- a bounded v1 snippet set: `SELECT ... FROM ...`, `WHERE`, `GROUP BY`,
  `ORDER BY`, and `COUNT(*)`

Source alias/table name suggestions are available immediately from current TUI
sources. Generated SQL range aliases are produced only by template generation
and must be distinct from source aliases. Normal SQL-editor completion must
never insert generated SQL range aliases in v1. Column suggestions are
available only for sources whose columns have been loaded by `c` or `i`.
Opening the palette must not auto-read CSV files or start background metadata
loading.

Column completion must use a deterministic v1 insertion rule. It should not
parse arbitrary SQL to infer context.

- For SQL-editor completion, the helper source set is the current TUI source
  list, not an inferred parse of editor SQL.
- For source-pane template picking, the helper source set is the selected source
  plus any additional source required by the selected template.
- If exactly one source is present in the helper source set, SQL-editor
  completion should insert the bare column name, such as `mrr_delta`.
- If multiple sources are present in the helper source set, SQL-editor
  completion must insert rendered source-qualified columns, such as
  `"revenue_movements"."mrr_delta"`.
- Generated templates may use range-alias-qualified columns, such as
  `rm."mrr_delta"`, because the generated SQL also declares `rm`.
- Generated SQL range aliases must come from the deterministic SQL-assistance
  helper logic for generated templates only. V1 does not support alias-aware
  editor completion and does not infer generated aliases by parsing freeform
  editor SQL.

The palette may display source context even when inserting a bare column, for
example `mrr_delta  column  revenue_movements DOUBLE`.

### Completion Insertion Mechanics

Completion selection must insert at the current SQL editor cursor, not append to
the end of the editor.

- If there is an active selection, completion replaces the selected text.
- Otherwise completion replaces the current lexical token prefix immediately
  before the cursor.
- Token-prefix detection must be local and lexical, not an arbitrary SQL parse.
- The implementation plan should define and test the exact token-prefix
  character set before implementation. A reasonable default is the contiguous
  run of ASCII letters, digits, underscores, dots, and double quotes immediately
  before the cursor.
- If the typed qualifier is an exact source alias/table name, either raw or
  rendered, completion may use that source. For example,
  `"revenue_movements".` may complete to `"revenue_movements"."mrr_delta"`.
- If the typed qualifier is unknown, including an undeclared generated range
  alias such as `rm.`, v1 must not infer what it means and should show no column
  completions for that qualifier.
- Existing append helpers for `l` and the current starter query are not
  sufficient for completion behavior.

If repo inspection proves token-prefix replacement too risky for v1, the spec
must be revised to choose append-only behavior and must stop calling that
behavior autocomplete.

### Component Boundaries

The implementation should keep most SQL-assistance logic outside
`src/csvql/tui_app.py`.

Expected new focused module:

- `src/csvql/tui_sql_assist.py`

Responsibilities:

- classify loaded columns by source
- generate deterministic SQL range aliases
- generate deterministic output aliases
- build starter templates
- find exact shared-column join candidates
- build completion items
- decide completion insertion text and token-replacement spans

The helper module should expose typed helper interfaces instead of ad hoc
`dict[str, Any]` plumbing. The implementation should use typed dataclasses or
equivalent typed models for source metadata, source columns, deterministic
generated SQL range-alias maps, generated output aliases, template options,
completion items, generated SQL results, and completion replacement spans. Broad
untyped dictionaries are allowed only when the implementation plan names a
specific reason.

V1 should use existing Textual/TUI capabilities and small local helpers unless
repo truth proves that is not viable. This spec does not authorize new
dependencies, lockfile changes, or package metadata changes.

Existing TUI responsibilities:

- show picker or modal UI
- pass selected source, sources, loaded columns, and current editor text into
  SQL-assistance helpers
- pass cursor and selection state into completion insertion helpers
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
8. The TUI inserts generated template text, or applies completion text at the
   cursor by replacing the active selection or current lexical token prefix.
9. Nothing runs until the user explicitly runs SQL.

## Error Handling

If no source is selected, source-pane assistance actions should keep using the
existing "No source selected" error path.

If a template requires loaded columns and columns are not loaded, the picker
should either omit that template or show a clear disabled/unavailable state. It
must not auto-read the CSV as a side effect of opening the picker. Preview and
row-count templates should still be available because they require only the
selected source alias/table name.

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
- `x` still offers preview and row-count templates when columns are not loaded,
  without inspecting or loading the CSV.
- Selecting a starter template inserts SQL into the editor and does not execute
  it.
- Starter templates include preview, row count, numeric summary, text/category
  grouping, date/month trend for `DATE` or `TIMESTAMP` columns where
  applicable, missingness/null profile, and exact shared-column join skeleton
  where applicable.
- Starter templates follow the deterministic template SQL contracts in this
  spec.
- Starter templates use the first deterministic eligible column for
  column-dependent templates; v1 does not require column sub-selection inside
  the picker.
- Join templates are omitted when no exact shared column exists.
- Template SQL uses deterministic generated SQL range aliases and existing
  DuckDB identifier rendering where helpful.
- Generated SQL range aliases and generated output aliases are deterministic,
  valid DuckDB identifiers, and collision-safe.
- SQL editor completion opens with `Ctrl+Space`.
- The implementation records a documented fallback-key decision after verifying
  Textual key behavior. The decision may be "no fallback in v1" if no reliable
  fallback is found.
- Completion suggests source aliases/table names immediately.
- Completion keeps source aliases/table names distinct from generated SQL range
  aliases.
- Completion suggests columns only for loaded source metadata.
- Completion inserts bare column names only when the helper source set contains
  exactly one source.
- Generated templates may use range-alias-qualified columns because they also
  declare those generated SQL range aliases.
- Normal multi-source SQL-editor completion inserts rendered source-qualified
  columns, not generated SQL range aliases.
- SQL-editor completion never inserts generated SQL range aliases in v1.
- Completion inserts at the SQL editor cursor, replaces an active selection, and
  otherwise replaces the current lexical token prefix.
- Opening completion or the template picker does not read CSV files, run SQL, or
  mutate results.
- Docs and help text describe the new behavior without implying AI, hidden
  execution, or safety for untrusted SQL.

## Test Plan

Unit tests should cover `tui_sql_assist.py`:

- deterministic generated SQL range alias generation
- generated SQL range alias collision behavior
- generated SQL range alias reserved-word avoidance
- deterministic generated output alias generation
- generated output aliases from spaced or mixed-case columns are valid
- generated output aliases from reserved-word columns are valid
- generated output alias collision behavior is deterministic
- source alias/table name suggestions are distinct from generated SQL range
  aliases
- preview template generation
- row-count template generation
- numeric summary template generation
- text/category grouping template generation
- date trend template generation
- `TIME` columns do not enable date/month template generation
- missingness/null profile template generation
- exact-column join template generation
- no join template without exact shared columns
- deterministic numeric, date-trend-eligible, time-only, text-like, and unknown
  type classification
- completion items include source aliases/table names without loaded columns
- completion items include columns only after metadata is supplied
- single-source column insertion is bare
- multi-source SQL-editor completion uses rendered source-qualified columns
- generated templates use generated SQL range aliases and
  range-alias-qualified columns because the generated SQL declares them
- SQL-editor completion never inserts generated SQL range aliases
- generated SQL uses the existing DuckDB identifier rendering behavior for
  source names and column names
- completion replacement spans cover cursor insertion, active-selection
  replacement, and current lexical token-prefix replacement
- append-only completion behavior is tested only if the spec is explicitly
  revised to choose append-only behavior

TUI interaction tests should cover:

- `i` result differs visibly from `c`
- `i` can load columns for later completion
- `x` opens a picker and inserts selected SQL without running it
- `x` does not inspect or load columns automatically when metadata is missing
- `x` still offers preview and row-count templates when metadata is missing
- completion palette opens from the SQL editor
- completion palette is not active from unrelated panes
- selecting a source alias/table name inserts text
- selecting a loaded column inserts text
- selecting a completion inserts at the cursor
- selecting a completion replaces active selection
- selecting a completion replaces the current lexical token prefix
- token replacement after a source-qualified prefix such as
  `"revenue_movements".` produces a rendered source-qualified column
- token replacement after an unknown qualifier such as `rm.` does not infer a
  generated range alias and shows no column completions for that qualifier
- spies or monkeypatches prove that opening completion or a template picker does
  not call inspect, column loading, sample, profile, query execution, export,
  save, or result mutation paths
- generated SQL insertion changes only the editor text until the user explicitly
  runs SQL
- fallback key behavior is verified before docs claim it, or docs explicitly
  say no fallback is supported in v1

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
