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
  F3 / Ctrl+O         Choose CSV file(s) or prompt for paths
  a                   Add source
  paste .csv path     Add CSV path text as a session source
  d                   Remove selected source after confirmation
  w                   Save sources to project catalog

History pane
  highlight           Recall selected query result
  Enter               Reopen selected query
  r                   Rerun selected query with current session sources

Results
  [ / ]               Previous/next buffer result when Results is focused

General
  F1                  Help
  F7                  Export active result (.csv, .json, .md, .markdown, .txt)
  F9 / q              Quit outside text entry
  Esc                 Close help or modal

Derived sources
  Ctrl+S              Save active result to .csvql/results/{alias}.csv
  Alt+S / F11         Alternate save-result shortcuts
  w in Sources        Persist source paths to .csvql.yml
"""
