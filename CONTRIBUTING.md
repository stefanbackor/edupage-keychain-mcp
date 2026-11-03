# Contributing

Setup and conventions for working on edupage-keyring-mcp. To install and use
it, see the [README](README.md).

## Setup

```sh
git clone https://github.com/stefanbackor/edupage-keyring-mcp
cd edupage-keyring-mcp
uv sync --locked
uv run pytest
```

Tests use synthetic data only and never touch the network or the Keychain.

## Running your checkout in a client

Point the client at the checkout with `uv run` instead of `uvx`. For Claude
Desktop:

```json
{
  "mcpServers": {
    "edupage": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/path/to/edupage-keyring-mcp",
               "edupage-keyring-mcp", "--school", "myschool"]
    }
  }
}
```

Use `which uv` for `command`, and quit and reopen the client (⌘Q) after code
changes. The checkout runs its own Python, so macOS asks once more whether it
may use the Keychain; choose **Always Allow**.

To try the sign-in flow, run `uv run edupage-keyring-mcp logout myschool` and
ask Claude something about school.

## Dependencies

`edupage-api` is pinned exactly: it wraps EduPage's undocumented endpoints and
this server replaces its HTTP session, so every upgrade is a reviewed change.
Upgrading it means changing its pin in `pyproject.toml`, running `uv lock`, and
reviewing the diff.

The other dependencies take compatible updates within their major version.
`uv lock --upgrade` refreshes them in `uv.lock`, which CI installs with
`--locked`.

## Releases

Releases are cut by the maintainer through an agent, with the `/release` skill
in [`.claude/skills/release/`](.claude/skills/release/SKILL.md). Release notes
live only in [GitHub Releases](https://github.com/stefanbackor/edupage-keyring-mcp/releases);
publishing one runs `.github/workflows/release.yml`, which publishes to PyPI
and the MCP Registry.
