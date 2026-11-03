# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration: school list, optional account label, and the no-plaintext-secrets rule."""
from __future__ import annotations

import os
from collections.abc import Mapping

from .errors import EduPageError
from .net import school_name

# The only EDUPAGE_* setting allowed in plain text: an optional account label
# (the EduPage login name), used only to keep two accounts at one school apart.
NON_SECRET_SETTINGS = frozenset({'EDUPAGE_USERNAME'})


def refuse_plaintext_secrets(environ: Mapping[str, str] | None = None) -> None:
    """Stop if any EDUPAGE_* setting other than the login label is set.

    An allowlist rather than a list of suspicious names: a password stored as
    EDUPAGE_PWD or EDUPAGE_SID is refused just like EDUPAGE_PASSWORD.
    """
    environ = os.environ if environ is None else environ
    for key, value in environ.items():
        upper = key.upper()
        if upper.startswith('EDUPAGE_') and value and upper not in NON_SECRET_SETTINGS:
            raise EduPageError('PLAINTEXT_SECRET_REFUSED', setting=upper)


def login_name(explicit: str | None = None, environ: Mapping[str, str] | None = None) -> str:
    """The account label, or '' for the usual one account per school."""
    environ = os.environ if environ is None else environ
    name = (explicit or environ.get('EDUPAGE_USERNAME') or '').strip()
    if len(name) > 320 or any(ch in name for ch in '\r\n\0'):
        raise EduPageError('INVALID_USERNAME')
    return name


def parse_schools(values: list[str], default_username: str | None = None,
                  environ: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """Turn `--school name` / `--school name=login` into (school, login) pairs."""
    if not values:
        raise EduPageError('SCHOOL_REQUIRED')
    result: list[tuple[str, str]] = []
    for value in values:
        if '://' in value:
            school, username = value, ''  # a pasted address carries no login
        else:
            school, _, username = value.partition('=')
        school = school_name(school)
        if any(school == s for s, _ in result):
            raise EduPageError('DUPLICATE_SCHOOL')
        result.append((school, login_name(username or default_username, environ)))
    return result
