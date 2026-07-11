# Security Policy

## Reporting A Vulnerability

Use GitHub private vulnerability reporting for sensitive security reports when
it is enabled for the public repository.
If private vulnerability reporting is not enabled yet, open a public issue
asking for private contact without including sensitive details.

Do not report sensitive vulnerabilities in public issues. Public issues are
fine for normal bugs, documentation problems, and non-sensitive behavior
questions.

## Supported Versions

The latest published 1.x release and the current `main` branch are reviewed for
security reports unless the release notes say otherwise.

## Security Boundary

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not sandbox DuckDB,
restrict DuckDB filesystem access, or make untrusted SQL safe.

Security reports are useful when they concern LocalQL package behavior,
dependency vulnerabilities, accidental disclosure, misleading security claims,
or behavior that contradicts documented local-only expectations.
