---
name: release
description: Cut a release of edupage-keyring-mcp — notes, version bump, GitHub Release, PyPI and MCP Registry.
disable-model-invocation: true
---

# Release

A release is one published GitHub Release. Publishing it fires
`.github/workflows/release.yml`, which builds, publishes to PyPI and the MCP
Registry, and attaches the built files. Its notes are the project's only
changelog, so they are written for users: what they will notice after
restarting their client.

Every step below runs only after the previous one meets its criterion.

## 1. Baseline

Fetch, then confirm: the working tree is clean, local `main` equals
`origin/main`, and the latest CI run on `main` passed
(`gh run list --workflow CI --branch main --limit 1`). Find the previous
release tag with `gh release list --limit 1` (fall back to `git describe
--tags --abbrev=0`).

Done when: all three hold and you know `vPREV`. If one fails, report it and stop.

## 2. Draft the notes

Read every commit in `vPREV..origin/main` (`git log --format='%h %s%n%b'`) and
the merged PRs behind them (`gh pr list --state merged --base main --search
"merged:>=<vPREV date>"`). Read the diff where a message is vague.

Write `release-notes.md` outside the repo (e.g. in `$TMPDIR`):

- Sections, only those with entries, in this order: `### Added`,
  `### Changed`, `### Fixed`, `### Security`.
- One line per user-visible change, naming tools, options and status codes in
  backticks: "`sign_in` opens EduPage's sign-in page in Chrome when the session
  has expired." A change needing user action (new option, changed config,
  removed tool) says what to do.
- A `### Dependencies` line when `edupage-api`'s pin changed, with old → new.
- Last line: `**Full diff:** https://github.com/stefanbackor/edupage-keyring-mcp/compare/vPREV...vNEXT`

Done when: every commit in the range is either reflected in a line or set
aside as internal (tests, CI, refactors, docs for maintainers), and you can
list which.

## 3. Choose the version

Semantic versioning from the notes: a removed or renamed tool, parameter or
option → major (minor while below 1.0); anything in Added → minor; otherwise
patch.

## 4. Approval

Show the user: `vPREV → vNEXT` with the reason, the full notes, and the commits
set aside as internal. Wait for an explicit go. Edits to notes or version loop
back here. This approval covers steps 5 to 7: merging the bump, publishing the
release, and everything the workflow then sends to PyPI and the MCP Registry.

## 5. Bump

On a branch `release/vNEXT` from `origin/main`: set the version in every file
the "Check versions match the tag" step of `release.yml` reads, run `uv lock`,
then `uv run pytest -q`. Commit as `Release vNEXT`, push, open a PR whose body
is the notes, and merge it once its CI passes (squash). Record the merge commit
SHA on `main`.

Done when: `main` at that SHA carries `vNEXT` in every version field and its
CI passed.

## 6. Publish

```sh
gh release create vNEXT --target <merge SHA> --title vNEXT --notes-file release-notes.md
```

This creates the tag and fires the Release workflow.

## 7. Verify

Follow the workflow run for `vNEXT` (`gh run list --workflow Release --limit 1`,
then `gh run view <id>`) until it finishes. Then check:

- `curl -fsS https://pypi.org/pypi/edupage-keyring-mcp/vNEXT/json` succeeds.
- `gh release view vNEXT` lists the wheel and sdist.
- `uvx edupage-keyring-mcp@latest --version` prints `vNEXT`'s number
  (`uv cache clean edupage-keyring-mcp` first if it shows the old one).

Done when: all three pass. Report the release URL.

## When the workflow fails

- **Before the `pypi` job succeeded:** nothing is public except the release.
  Delete it and its tag (`gh release delete vNEXT --cleanup-tag --yes`), fix on
  a new PR, and resume at step 5 with the same version.
- **After PyPI accepted it:** that version number is spent; PyPI never takes it
  again. A failed `mcp-registry` or `release-files` job is re-run with
  `gh run rerun <id> --failed`. Anything wrong in the package itself ships as
  the next patch, starting at step 2.
