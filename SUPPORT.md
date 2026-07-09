# Support

LocalQL is a solo-maintained open-source project.

Use GitHub issues for reproducible bugs, documentation problems, and focused
feature requests. Include the command you ran, a small CSV example when
possible, your Python version, your operating system, and the full error output.

There is no support SLA. The maintainer may close issues that are outside the
project scope or that cannot be reproduced with local files.

For sensitive vulnerability reports, use the path in [Security](SECURITY.md)
instead of a public issue.

## Post-Release Response

Issues are triaged by reproducibility, user impact, and whether the report fits
the local CSV workflow scope. Reproducible regressions in documented v1 behavior
are candidates for patch releases.

Patch releases use normal semantic versioning: small compatible fixes should use
the next patch version, while new feature scope waits for a later minor or
roadmap decision.

Published tags are immutable. If a release artifact is wrong after publication,
fix it with a new tag and release instead of moving an existing tag.

A PyPI release may be yanked when the artifact is broken, unsafe, accidentally
published, or materially misrepresents the supported Python/runtime contract. A
yank is a damage-control action; the preferred repair path is a follow-up patch
release with clear notes.
