"""Help text for the CSVQL Workbench TUI."""

WORKBENCH_HELP = """CSVQL Workbench Lite

Run SQL
  F4 / Ctrl+R         Run selected SQL, otherwise current statement
  F12 / Ctrl+B        Run Buffer
  Ctrl+N / F10        Clear editor for a new query
  Tab                 Complete SQL if available, otherwise indent
  Ctrl+Space          Alternate SQL completion where terminal supports it

Focus
  F2 / Ctrl+Down      SQL editor
  F5                  Results
  F6 / Ctrl+Up        Sources
  F8                  History

Source pane
  i                   Inspect selected source and load columns
  s                   Sample selected source
  p                   Profile selected source
  c                   Load/show selected source columns
  l                   Insert selected source alias
  x                   Open starter SQL templates
  F3 / Ctrl+O         Choose local source file(s) or prompt for a path
  a                   Add structured source intent
  paste .csv path     Add CSV immediately
  paste other path    Open type, option, detection, and confirmation flow
  d                   Remove selected source after confirmation
  w                   Save sources to project catalog

Detection
  Explicit type wins; otherwise a recognized extension selects its provider.
  Extensionless files and directories require an explicit type when ambiguous.
  LocalQL displays bounded evidence and never guesses between candidates.

History pane
  highlight           Recall selected query result
  Enter               Reopen selected query
  r                   Rerun selected query with current session sources
  Delete              Delete selected preserved result after confirmation

Results
  [ / ]               Previous/next buffer result when Results is focused
  A bounded preview appears while the same execution preserves the full result.
  Preservation reports rows, logical bytes, elapsed time, and remaining capacity.
  Complete results enable full-result actions; Preview-only results name why those actions are
  unavailable and LocalQL does not rerun SQL.
  Queued exports run before the next queued query starts.
  Delete removes only the confirmed preserved result.

General
  F1                  Help
  F7                  Export active result (.csv, .json, .md, .markdown, .txt)
  F9 / q              Quit outside text entry
  Esc                 Cancel active execution or preservation; otherwise close help or modal

Derived sources
  Ctrl+S              Save active result to .csvql/results/{alias}.csv
  Alt+S / F11         Alternate save-result shortcuts
  w in Sources        Persist source paths to .csvql.yml
"""
