# Contributing

This repo hosts the HySPRINT Analysis Apps (`apps/<AppName>/`), all reachable
from the [App Dashboard](apps/App_dashboard/). See `CLAUDE.md` for the
codebase conventions (layout, shared utils, lint rules). This file covers the
process for proposing and landing a change.

## 1. Open an issue first

Every change (bug fix, feature, improvement) starts as a GitHub issue on
[nomad-hzb/nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues),
using the *Bug report* or *Feature request* template. This is how we keep a
record of *why* something changed, not just what the diff says.

Small exceptions that don't need an issue: typo fixes, CI/tooling-only
changes, and repo-wide sweeps (lint config, dependency bumps) that don't
change app behavior.

## 2. Open a PR that references it

Use `Fixes #123` or `Closes #123` in the PR description so the issue closes
automatically on merge. Fill out the PR template checklist.

## 3. Bump the app's version if the change is user-visible

Each app has its own `version` in `apps/<AppName>/pyproject.toml`, following
[SemVer](https://semver.org/):

| Change type | Bump | Example |
|---|---|---|
| Bug fix, no behavior change | patch | `0.1.0` -> `0.1.1` |
| New feature, backward-compatible | minor | `0.1.0` -> `0.2.0` |
| Breaking change (removed feature, changed data/export format, etc.) | major | `0.1.0` -> `1.0.0` |

Bump the version in the same PR as the change, for that app only. Internal
refactors, test-only changes, and changes to `shared/hysprint_utils/` don't
require an app version bump (a `hysprint_utils` change is a separate,
cross-cutting decision — see `CLAUDE.md` rule 2).

## 4. Releases

"What's new" is surfaced via [GitHub Releases](https://github.com/nomad-hzb/nomad-pv-analysis-apps/releases),
linked from the top-right of the App Dashboard. When a meaningful batch of
merged, issue-linked PRs has landed, cut a release:

```
gh release create <tag> --generate-notes
```

`--generate-notes` builds the changelog from merged PR titles since the last
tag, so PR titles should be descriptive on their own (not just "fix bug").
There's no separate hand-maintained CHANGELOG file to keep in sync.
