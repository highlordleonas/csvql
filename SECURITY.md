# Security Policy

## Reporting A Vulnerability

Use GitHub private vulnerability reporting for sensitive security reports when
it is enabled for the public repository.

Do not report sensitive vulnerabilities in public issues. Public issues are
fine for normal bugs, documentation problems, and non-sensitive behavior
questions.

## Supported Versions

Before the first public release, only the current `main` branch is reviewed for
security reports. After the first public release, the current published release
line is the supported line unless release notes say otherwise.

## Security Boundary

LocalQL treats user-authored SQL as trusted local DuckDB SQL. It does not
sandbox DuckDB, restrict DuckDB filesystem access, or make untrusted SQL safe.

Security reports are useful when they concern LocalQL package behavior,
dependency vulnerabilities, accidental disclosure, misleading security claims,
or behavior that contradicts documented local-only expectations.
