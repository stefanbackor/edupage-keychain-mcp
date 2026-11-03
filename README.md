# EduPage Keyring MCP

<!-- mcp-name: io.github.stefanbackor/edupage-keyring-mcp -->

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP
client) read your [EduPage](https://www.edupage.org) school account: timetables,
grades, homework, tests, absences, messages, menus and more, for every child
and school you have, **without ever storing your password**.

You sign in once per school in Chrome, on EduPage's own page, two-factor
included. Only the resulting session cookies are kept, in the **macOS
Keychain**. Built on [`edupage-api`](https://github.com/EdupageAPI/edupage-api).

> Unofficial. Not affiliated with EduPage or aSc Applied Software Consultants.
> EduPage's web endpoints are undocumented and can change without notice.
> macOS only.

## What you can ask

- "What does each kid have tomorrow, and what's due this week?"
- "Any tests coming up for Šimon? Which topics?"
- "How are Ema's grades in Slovak this term?"
- "Did Peter get to school on time today?"
- "Summarize what the school sent in the last two weeks and flag anything I must act on."
- "Which of today's lessons are substituted for 5.C?"
- "Tell the class teacher that Ema will be absent on Friday." (Claude Desktop asks before sending)

## Why this one

| | edupage-keyring-mcp | Typical EduPage MCP servers |
| --- | --- | --- |
| Password | Never stored; typed only into EduPage in Chrome | `EDUPAGE_PASSWORD` in a config file |
| Two-factor login | Yes, on EduPage's own page | Often unsupported or tool-driven |
| Several children | Matched by name; every timeline item says which child it is for | Varies |
| Several schools | Yes, one Keychain session each | Varies |
| Network | Confined to your school's host; every redirect checked; responses capped | Library defaults |
| Writes | 4 actions, marked destructive so clients ask first; inputs checked | Often none, or a raw-request tool |
| Errors | Fixed status codes; never server pages | Raw exception text |
| Dependencies | Exact pins plus a hashed `uv.lock` | Ranges |

## Install

Requirements: macOS, Google Chrome, and [uv](https://docs.astral.sh/uv/).

```sh
export EDUPAGE_USERNAME='you@example.com'      # your EduPage login name (not secret)
uvx edupage-keyring-mcp login myschool        # myschool = the part before .edupage.org
```

Chrome opens on your school's login page. Sign in there, including any
two-factor prompt. When EduPage shows your account, the window closes and the
session is saved to the Keychain. If macOS asks whether Python may use the
Keychain, choose **Always Allow**.

Check it:

```sh
uvx edupage-keyring-mcp status --school myschool
```

A session lasts until EduPage expires it. Tools then return `AUTH_REQUIRED`
(or `SESSION_EXPIRED`); run `login` again. `EDUPAGE_USERNAME` only labels the
Keychain entry; the login name EduPage itself reports is stored at sign-in.

## Connect Claude Desktop

Open **Settings → Local MCP servers → Edit Config** (older versions:
**Settings → Developer → Edit Config**) and add:

```json
{
  "mcpServers": {
    "edupage": {
      "command": "/Users/YOU/.local/bin/uvx",
      "args": ["edupage-keyring-mcp", "--school", "myschool"],
      "env": { "EDUPAGE_USERNAME": "you@example.com" }
    }
  }
}
```

Use the output of `which uvx` as `command`. Quit Claude Desktop (⌘Q) and reopen it.

- **Several schools:** repeat `--school`: `"--school", "first", "--school", "second"`.
  The first is the default. A school without a saved session reports
  `AUTH_REQUIRED` and does not affect the others.
- **Different login at one school:** `"--school", "second=other@example.com"`.
- **Attachments on EduPage file servers:** if `get_attachment` reports
  `REDIRECT_NOT_ALLOWED`, allow that exact host with
  `"--download-host", "cloud-4.edupage.org"`. Only `*.edupage.org` hosts are accepted.

Other MCP clients: run `edupage-keyring-mcp --school myschool` as a stdio server.

## Features

34 tools. Each takes an optional `school`. Child tools take `child`: a first
name (accents optional, so `simon` finds Šimon), full name, student ID, or the
`ref` from `list_children`.

### Account and children

| Tool | Returns |
| --- | --- |
| `auth_status` | Whether the saved session works |
| `list_schools` | Schools, session status, role (parent, student, teacher), number of children |
| `list_children` | Your children: name, class, student ID, `ref` |
| `user_id`, `school_year` | Account ID and role; current school year |

### Timetables

| Tool | Returns |
| --- | --- |
| `get_timetable` | A child's lessons for a date, with substitutions applied: times, subject, teacher, room, group, topic, cancelled flag |
| `get_week_timetable` | Monday to Friday for a child |
| `get_timetable_for` | Timetable of any teacher, class, classroom or student |
| `get_periods`, `get_next_ringing_time` | Bell schedule; next lesson or break |
| `get_timetable_changes` | School-wide substitutions and cancellations for a date |
| `get_missing_teachers` | Teachers absent on a date |

### Grades and the timeline

| Tool | Returns |
| --- | --- |
| `get_grades` | Subject, title, grade, comment, weight, points and percent, class average, teacher; current or a past term |
| `get_homework` | Homework with full text, subject, author and due date |
| `get_assignments` | Homework, tests and exams |
| `get_upcoming_events` | Tests announced as events (topic and date), trips, meetings, holidays |
| `get_absences` | Absences, excuses, arrival and departure scans |
| `get_news` | School news |
| `get_notifications` | Any timeline item, optionally by EduPage type (`znamka`, `homework`, ...) |

Timeline tools look back up to 90 days (default 30). Every item has
`for_children`: which of your children it is addressed to, by name or class.
With `child` set, items addressed to a sibling are left out.

### Messages

| Tool | Returns |
| --- | --- |
| `list_messages` | Messages with sender, recipient, `for_children`, snippet, number of files |
| `get_message` | Full text and the files attached; no read receipt is sent |
| `get_attachment` | A PDF, PNG, JPEG or GIF attached to a message, up to 3 MB, base64 |

### People and school data

`get_students`, `get_all_students`, `find_student`, `get_teachers` (IDs for
`send_message`), `get_classes`, `get_classrooms`, `get_subjects`.

### Meals

`get_meals`: a child's menu, allergens and current order, or
`MEALS_NOT_AVAILABLE` when the school has no canteen module.

### Actions

| Tool | Does | Checks |
| --- | --- | --- |
| `send_message` | Sends an EduPage message as you | Recipient must be a real teacher, student or parent ID; 1 to 5,000 characters |
| `choose_meal` | Orders menu A to H for a child | Meal type, date within 30 days, menu must be choosable |
| `sign_off_meal` | Cancels a child's meal | Meal type, date |
| `rate_meal` | Rates a served lunch 1 to 5 | Lunch only, last 14 days |

These are marked `destructiveHint`; clients such as Claude Desktop ask before each call.

## Security model

- **No password anywhere.** It is typed only into EduPage's page in a throwaway
  Chrome window. The Keychain item holds EduPage session cookies, the account ID
  and the login name EduPage reports.
  The server refuses to start if any `EDUPAGE_*` environment variable other
  than `EDUPAGE_USERNAME` is set.
- **Keychain only.** On anything but the macOS Keychain backend the server
  refuses to run, so sessions never land in a plaintext keyring file.
- **Confined network.** `edupage-api` gets a replacement session that allows
  HTTPS to your configured school host only, checks every redirect hop, caps
  every response at 8 MB (attachments at 3 MB) and ignores proxy and `.netrc`
  settings. Cookies loaded from the Keychain are validated for that host first.
- **Narrow inputs.** No tool accepts a URL, cookie, session ID, header or
  password. Dates are ISO and window-limited. `school` only picks a configured
  school. Attachments are fetched by file id; the model never sees their URLs.
- **Child switching is verified.** For parent accounts, child-scoped calls
  switch to the child and back under a per-school lock, then re-check that the
  session is the parent again; otherwise it is dropped and recovered before reuse.
- **Quiet errors.** Failures return fixed codes (and at most an exception class
  name), never server pages or messages.
- **Untrusted content.** All school text is labelled `untrusted_content`.
- **Pinned dependencies.** Exact versions in `pyproject.toml`, hashes in `uv.lock`.

Reading can still be visible to EduPage, like opening a page in the browser.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Commands

```text
edupage-keyring-mcp [serve] --school NAME[=LOGIN] [--school ...] [--download-host HOST]
edupage-keyring-mcp login NAME [--username LOGIN] [--timeout SECONDS]
edupage-keyring-mcp logout NAME [--username LOGIN]
edupage-keyring-mcp status --school NAME [...]
edupage-keyring-mcp probe --school NAME [...]   # every read tool once; statuses and counts only
```

`logout` removes the local session only; EduPage itself is not logged out.

## Development

```sh
git clone https://github.com/stefanbackor/edupage-keyring-mcp
cd edupage-keyring-mcp
uv sync --locked
uv run pytest
```

Tests use synthetic data only and never touch the network or the Keychain.
Upgrading a dependency means changing its pin in `pyproject.toml`, running
`uv lock`, and reviewing the diff.

## Credits

Built on [edupage-api](https://github.com/EdupageAPI/edupage-api) (GPL-3.0).
Tool coverage follows [Arnost55/edupage-mcp-full](https://github.com/Arnost55/edupage-mcp-full).

## License

[GPL-3.0-or-later](LICENSE). Copyright © 2026 Stefan Backor.
