# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys

import pytest

from conftest import COOKIE, HOST, LABEL, SAVED, SCHOOL
from edupage_keychain_mcp import keychain
from edupage_keychain_mcp.errors import EduPageError
from edupage_keychain_mcp.keychain import (Cookie, SavedSession, SessionStore, account_key,
                                           parse_cookie, session_cookies)


class MemoryKeyring:
    def __init__(self, broken=False):
        self.secrets, self.broken = {}, broken

    def set_password(self, service, account, secret):
        self.secrets[service, account] = secret

    def get_password(self, service, account):
        if self.broken:
            raise OSError('keychain locked')
        return self.secrets.get((service, account))

    def delete_password(self, service, account):
        self.secrets.pop((service, account))


def test_saved_session_round_trip():
    ring = MemoryKeyring()
    store = SessionStore(ring)
    store.save(LABEL, SAVED)
    [(service, account)] = ring.secrets
    assert service == 'edupage-keychain-mcp'
    assert account.startswith(SCHOOL + '/') and LABEL not in account
    assert store.load(SCHOOL, LABEL) == SAVED
    assert store.load(SCHOOL, LABEL.upper()) == SAVED  # label match ignores case
    assert store.delete(SCHOOL, LABEL) and not store.delete(SCHOOL, LABEL)


def test_load_failures():
    with pytest.raises(EduPageError, match='^NOT_SIGNED_IN$'):
        SessionStore(MemoryKeyring()).load(SCHOOL, LABEL)
    with pytest.raises(EduPageError, match='^KEYCHAIN_LOCKED$'):
        SessionStore(MemoryKeyring(broken=True)).load(SCHOOL, LABEL)
    ring = MemoryKeyring()
    for secret in ['not json', json.dumps({'format': 1}), json.dumps(
            {'format': 2, 'school': 'other', 'account': 'x', 'login': 'y', 'cookies': []}),
            json.dumps({'format': 2, 'school': SCHOOL, 'account': 'x', 'login': 'y', 'cookies': [['bad']]})]:
        ring.secrets['edupage-keychain-mcp', account_key(SCHOOL, LABEL)] = secret
        with pytest.raises(EduPageError, match='^SESSION_CORRUPT$'):
            SessionStore(ring).load(SCHOOL, LABEL)


@pytest.mark.parametrize('parts', [
    ('a b', 'v', HOST), ('n', 'x;y', HOST), ('n', 'v\n', HOST), ('n', 'v', HOST, 'rel'),
    ('n', 'v', HOST, '/', 'later'), ('n', 'v', HOST, '/', True), ('', 'v', HOST),
])
def test_malformed_cookie_parts(parts):
    with pytest.raises(EduPageError, match='^SESSION_CORRUPT$'):
        parse_cookie(*parts)


def test_session_cookies_scope_and_expiry():
    fresh, stale = COOKIE, Cookie('old', 'v', '.' + HOST, '/', 50)
    assert session_cookies(HOST, [fresh, stale], now=100) == [fresh]
    with pytest.raises(EduPageError, match='^SESSION_EXPIRED$'):
        session_cookies(HOST, [stale], now=100)
    with pytest.raises(EduPageError, match='^SESSION_CORRUPT$'):
        session_cookies(HOST, [fresh, Cookie('x', 'v', 'example.com')])
    assert session_cookies(HOST, [Cookie('lang', 'sk', '.edupage.org')]) != []


def test_only_the_macos_keychain_backend_is_accepted(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    with pytest.raises(EduPageError, match='^MACOS_REQUIRED$'):
        keychain.require_macos_keychain()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    for module, ok in [('keyrings.alt.file', False), ('keyring.backends.chainer', False),
                       ('keyring.backends.macOS.api', True)]:
        backend = type('Backend', (), {'__module__': module})()
        if ok:
            keychain.require_macos_keychain(backend)
        else:
            with pytest.raises(EduPageError, match='^MACOS_KEYCHAIN_REQUIRED$'):
                keychain.require_macos_keychain(backend)


def test_saved_session_is_immutable():
    with pytest.raises(Exception):
        SAVED.account = 'x'  # type: ignore[misc]
    assert isinstance(SAVED, SavedSession)


def test_cookies_with_the_same_name_are_kept_apart():
    pair = (Cookie('PHPSESSID', 'school', HOST), Cookie('PHPSESSID', 'portal', '.edupage.org'))
    ring = MemoryKeyring()
    SessionStore(ring).save(LABEL, SavedSession(SCHOOL, 'Rodic100', LABEL, pair))
    assert SessionStore(ring).load(SCHOOL, LABEL).cookies == pair
