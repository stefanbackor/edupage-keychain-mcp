# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved EduPage sessions in the macOS login keychain.

A saved session is the set of EduPage cookies from one browser sign-in, plus
the account it belongs to. There is no password field anywhere: the person
types their password into EduPage in Chrome, never into this program.

Keychain item: service `edupage-keychain-mcp`, account `<school>/<sha1 of label>`,
secret = JSON {"format": 2, "account": ..., "login": ..., "cookies": [[name, value, domain, path, expires], ...]}.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

from .errors import EduPageError

SERVICE = 'edupage-keychain-mcp'
FORMAT = 2
SECRET_LIMIT = 64 * 1024
COOKIE_LIMIT = 64
TOKEN_CHARS = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                        "!#$%&'*+-.^_`|~")


def require_macos_keychain(backend: Any = None) -> None:
    """Only the native macOS Keychain backend is acceptable (no plaintext keyrings)."""
    if sys.platform != 'darwin':
        raise EduPageError('MACOS_REQUIRED')
    if backend is None:
        import keyring
        backend = keyring.get_keyring()
    if not type(backend).__module__.startswith('keyring.backends.macOS'):
        raise EduPageError('MACOS_KEYCHAIN_REQUIRED')


def account_key(school: str, label: str) -> str:
    return school + '/' + hashlib.sha1(label.casefold().encode(), usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class Cookie:
    name: str
    value: str
    domain: str
    path: str = '/'
    expires: float = -1  # seconds since epoch; -1 = session cookie

    def belongs_to(self, host: str) -> bool:
        return self.domain.lstrip('.') in (host, 'edupage.org')

    def expired(self, now: float) -> bool:
        return 0 < self.expires <= now


def parse_cookie(name: Any, value: Any, domain: Any, path: Any = '/', expires: Any = -1) -> Cookie:
    """Build a Cookie from untrusted parts, or raise SESSION_CORRUPT."""
    ok = (isinstance(name, str) and 0 < len(name) <= 128 and set(name) <= TOKEN_CHARS
          and isinstance(value, str) and len(value) <= 4096 and value.isprintable() and ';' not in value
          and isinstance(domain, str) and isinstance(path, str) and path[:1] == '/' and len(path) <= 256
          and type(expires) in (int, float))
    if not ok:
        raise EduPageError('SESSION_CORRUPT')
    return Cookie(name, value, domain, path, float(expires))


def session_cookies(host: str, cookies: list[Cookie], now: float | None = None) -> list[Cookie]:
    """The live cookies for `host`; foreign cookies are an error, expired ones are dropped."""
    if not cookies or len(cookies) > COOKIE_LIMIT:
        raise EduPageError('SESSION_CORRUPT')
    if not all(c.belongs_to(host) for c in cookies):
        raise EduPageError('SESSION_CORRUPT')
    moment = time.time() if now is None else now
    live = [c for c in cookies if not c.expired(moment)]
    if not live:
        raise EduPageError('SESSION_EXPIRED')
    return live


@dataclass(frozen=True)
class SavedSession:
    school: str
    account: str  # EduPage user ID, e.g. Rodic123
    login: str    # the EduPage login name exactly as EduPage reports it
    cookies: tuple[Cookie, ...]


class SessionStore:
    """Keychain persistence; `backend` is anything with keyring's three functions."""

    def __init__(self, backend: Any = None) -> None:
        if backend is None:
            import keyring as backend
        self.backend = backend

    def save(self, label: str, session: SavedSession) -> None:
        secret = json.dumps({
            'format': FORMAT, 'school': session.school, 'account': session.account,
            'login': session.login, 'saved': int(time.time()),
            'cookies': [[c.name, c.value, c.domain, c.path, c.expires] for c in session.cookies],
        }, separators=(',', ':'))
        if len(secret) > SECRET_LIMIT:
            raise EduPageError('SESSION_CORRUPT')
        try:
            self.backend.set_password(SERVICE, account_key(session.school, label), secret)
        except Exception:
            raise EduPageError('KEYCHAIN_WRITE_FAILED') from None

    def load(self, school: str, label: str) -> SavedSession:
        try:
            secret = self.backend.get_password(SERVICE, account_key(school, label))
        except Exception:
            raise EduPageError('KEYCHAIN_LOCKED') from None
        if secret is None:
            raise EduPageError('NOT_SIGNED_IN')
        try:
            data = json.loads(secret) if len(secret) <= SECRET_LIMIT else None
            if not (isinstance(data, dict) and data.get('format') == FORMAT
                    and data.get('school') == school and isinstance(data.get('cookies'), list)):
                raise ValueError
            cookies = tuple(parse_cookie(*spec) for spec in data['cookies'])
            return SavedSession(school, str(data['account']), str(data['login']), cookies)
        except EduPageError:
            raise
        except Exception:
            raise EduPageError('SESSION_CORRUPT') from None

    def delete(self, school: str, label: str) -> bool:
        try:
            self.backend.delete_password(SERVICE, account_key(school, label))
        except Exception:
            return False
        return True
