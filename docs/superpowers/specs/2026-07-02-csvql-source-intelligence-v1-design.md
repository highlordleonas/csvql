# CSVQL Source Intelligence V1 Design

## Status

Approved design for the next CSVQL TUI polish lane.

Current repo state at design time:

- Branch: `main`
- Baseline HEAD: `49bc46e`
- Tracked tree: clean
- Untracked generated state: `.superpowers/`

## Goal

Make the optional TUI Sources pane help users write SQL faster by exposing
selected-source columns and inserting simple source/column snippets into the
SQL editor.

## North Star

CSVQL remains a local-first CSV + DuckDB CLI with an optional Textual terminal
workbench. Source Intelligence v1 improves authoring ergonomics without adding
new storage, background indexing, hidden cache, dataframe runtime, parquet
support, safe mode, sandbox claims, plugin scope, or project catalog schema
changes.

## Follow-On Lane Order

Track these lanes in order so they do not live only in chat:

1. Source Intelligence v1.
2. Editor Quality v2.
3. Release Candidate Proof Packet.

Editor Quality v2 should wait until Source Intelligence v1 lands. The Release
Candidate Proof Packet should wait until no higher-priority TUI polish remains
or Richard explicitly chooses to stop polishing and prove a candidate.

## Scope

Implement Source Intelligence v1 only inside the optional TUI.

Included:

- Session-local selected-source column metadata.
- Explicit user action to load/show columns for the selected source.
- Explicit user actions to insert source-aware SQL snippets into the editor.
- Help and README updates for the new TUI keymap.
- Focused tests for state, workflow, app behavior, and docs/help text.

Excluded:

- CLI command changes.
- Python API changes.
- Project catalog schema changes.
- Automatic startup inspection of all sources.
- Durable column metadata.
- Background source indexing.
- Query autocomplete.
- Syntax highlighting.
- SQL formatting.
- Selected SQL or current-statement execution.
- Error-recovery suggestions from failed SQL.
- pandas, Polars, parquet, notebooks, dashboards, web UI, AI, or plugins.

## User Experience

The user flow is explicit and source-focused:

1. User focuses the Sources pane.
2. User selects a source alias.
3. User presses a key to load/show that source's columns.
4. The TUI displays columns and DuckDB types in the existing output area.
5. User presses a key to insert source-aware SQL text into the existing editor.
6. Focus returns to the SQL editor after insertion.

The first version should not add a separate column picker. Without a picker,
column insertion uses the first inspected column as the deterministic default.
That keeps the feature small and predictable while still making simple queries
faster to start.

## Keymap

New keybindings are active only when the Sources pane is focused:

- `c`: load/show columns for the selected source.
- `l`: insert selected source alias into the SQL editor.
- `.`: insert `alias.first_column` into the SQL editor.
- `x`: insert a starter select into the SQL editor:

  ```sql
  SELECT alias.first_column
  FROM alias;
  ```

Existing source actions remain:

- `i`: inspect selected source.
- `s`: sample selected source.
- `p`: profile selected source.
- `a`: add source.
- `d`: remove source.
- `w`: save sources to project catalog.

Printable keys must remain safe while the SQL editor is focused. Source
intelligence actions should be disabled while focus is in the editor, matching
the existing source-action focus rules.

## Architecture

Keep the existing TUI layering:

- `src/csvql/tui_state.py` owns in-memory TUI state.
- `src/csvql/tui_workflows.py` adapts existing CSVQL inspection/query services
  for the TUI.
- `src/csvql/tui_app.py` owns Textual keybindings, focus, editor insertion, and
  visible messages.
- `src/csvql/tui_help.py` owns in-app help text.

Add a small state model:

```python
@dataclass(frozen=True, slots=True)
class TUISourceColumn:
    name: str
    duckdb_type: str
```

Add session-local column metadata to `TUISessionState`, keyed by validated
source alias. The cache is:

- loaded only when the user requests source columns or an insertion action needs
  columns;
- cleared for a source when that source is removed;
- not persisted to `.csvql.yml`;
- not written to disk;
- discarded when the TUI exits.

Add workflow helper:

```python
def inspect_source_columns(source: TUISource) -> tuple[TUISourceColumn, ...]:
    """Return column names and DuckDB types for a TUI source."""
```

The helper should call existing `inspect_source(source)` and convert its column
objects into `TUISourceColumn` instances. DuckDB execution and CSV inspection
remain in existing engine/workflow layers. `cli.py` remains untouched.

## Editor Insertion

The implementation should prefer a small helper in `tui_app.py` for inserting
text into the existing `TextArea`.

Required v1 behavior:

- Insertions append to the editor with sensible spacing if cursor insertion is
  not straightforward through Textual's stable API.
- If the editor is empty, inserted text becomes the editor content directly.
- If the editor has content and does not end with whitespace, append a newline
  before the inserted text.
- After insertion, focus returns to the SQL editor.

Cursor-exact insertion can be evaluated during implementation only if Textual's
current `TextArea` API makes it simple and testable. It is not required for v1.

## Error Handling

Use existing TUI error display style through `CSVQLError`.

Required failures:

- No selected source:
  - message: `No source selected.`
- Selected source has no columns:
  - message: `Source '<alias>' has no columns to insert.`
- Inspect failure:
  - surface the existing inspection `CSVQLError` message and suggestion.
- Insertion action needs columns and none are cached:
  - inspect the selected source first;
  - cache columns if inspection succeeds;
  - insert after successful inspection;
  - show no partial insertion if inspection fails.

## Display

Column display should reuse the existing output text area instead of adding a
new pane in v1.

Format:

```text
orders columns
  order_id VARCHAR
  customer_id VARCHAR
  total DOUBLE
```

The status line should report:

```text
orders: 3 columns loaded.
```

This keeps the UI dense and avoids adding layout churn before there is evidence
that a dedicated column pane is needed.

## Tests

Add focused tests before implementation.

State tests in `tests/test_tui_state.py`:

- `TUISourceColumn` stores name and DuckDB type.
- `TUISessionState` can store and retrieve columns by alias.
- removing a source clears cached columns for that alias.
- selecting/getting aliases remains case-insensitive where existing behavior is
  case-insensitive.

Workflow tests in `tests/test_tui_workflows.py`:

- `inspect_source_columns` returns column names and DuckDB types for a CSV.
- wrapper keeps source display path as the alias through existing inspect
  behavior.

App tests in `tests/test_tui_app.py`:

- `c` loads and shows selected-source columns when Sources is focused.
- `c` is disabled while the SQL editor is focused.
- `l` inserts selected source alias and focuses the editor.
- `.` inspects when needed and inserts `alias.first_column`.
- `x` inspects when needed and inserts starter select.
- source insertion does not mutate the editor when inspect fails.
- source insertion reports a clear error when no source is selected.

Docs/help tests:

- help text documents `c`, `l`, `.`, and `x`.
- README TUI keymap text mentions source intelligence actions.

## Documentation

Update README's TUI section and `src/csvql/tui_help.py` to describe the new
source intelligence actions.

Documentation must keep the current posture:

- Source metadata is session-local.
- No hidden persistence.
- No automatic indexing.
- SQL remains trusted local DuckDB SQL.
- No sandbox, production-readiness, or large-file performance claims.

## Verification

Minimum implementation gates:

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest tests/test_tui_state.py tests/test_tui_workflows.py tests/test_tui_app.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras mypy src
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --all-extras pytest
```

Manual proof target:

- Launch `csvql menu` against an example CSV.
- Focus Sources.
- Load columns with `c`.
- Insert alias with `l`.
- Insert qualified first column with `.`.
- Insert starter select with `x`.
- Run the starter query with `F4`.

## Risks And Mitigations

- **Terminal key conflicts:** `.` and letters are ordinary keys. Mitigation:
  keep actions active only when Sources is focused so SQL typing stays safe.
- **Large CSV inspection cost:** column loading uses explicit inspect action,
  not automatic full-project scanning.
- **No column picker yet:** v1 uses first column for qualified/starter snippets.
  A real picker can be part of Source Intelligence v2 if this proves useful.
- **TextArea cursor API uncertainty:** v1 requires append-with-spacing behavior,
  not cursor-exact insertion.
- **User confusion around persistence:** docs and help must say column metadata
  is session-local and source paths persist only through explicit Save sources.

## Acceptance Criteria

Source Intelligence v1 is complete when:

- selected-source columns can be loaded and displayed in the TUI;
- alias, qualified first column, and starter select snippets can be inserted
  from the Sources pane;
- source-intelligence keys do not fire while typing in the SQL editor;
- column metadata is session-local only;
- docs and help describe the new actions;
- focused and full gates pass;
- no unsupported scope or safety claims are introduced.
