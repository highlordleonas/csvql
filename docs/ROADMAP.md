# Roadmap

LocalQL is focused on a dependable local CSV workflow: use DuckDB SQL, keep
repeatable work in a small project catalog, and make outputs easy to inspect or
export.

## Current capabilities

- Query one CSV or join named CSV tables.
- Save project catalogs in `.csvql.yml`.
- Run saved SQL and export results.
- Inspect, sample, profile, and validate local sources.
- Use JSON output for automation-oriented commands.
- Work interactively through the optional terminal menu.

## Next areas of exploration

Future work is driven by real local-analytics workflows rather than a fixed
feature promise. Possible areas include:

- additional export formats where they solve a demonstrated workflow;
- optional, user-controlled result materialization;
- broader local file formats after CSV workflows remain simple and reliable;
- carefully scoped improvements to the small Python API.

## Deliberate boundaries

LocalQL is not a hosted analytics platform, cloud connector suite, web
dashboard, notebook replacement, natural-language SQL tool, or plugin system.
It runs trusted local DuckDB SQL; a safety mode for untrusted SQL would require
a separate product and security design.
