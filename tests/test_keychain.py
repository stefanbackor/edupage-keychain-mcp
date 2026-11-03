# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

from conftest import COOKIE, HOST, LABEL, SAVED, SCHOOL
from edupage_keyring_mcp import keychain
from edupage_keyring_mcp.errors import EduPageError
from edupage_keyring_mcp.keychain import (Cookie, SavedSession, SessionStore, account_key,
                                           parse_cookie, session_cookies)


class MemoryKeyring:
    def __init__(self, broken=False):
        self.secrets, self.broken = {}, broken

    def set_password(self, service, account, secret):
        if self.broken:
            raise OSError('store locked')
        self.secrets[service, account] = secret

    def get_password(self, service, account):
        if self.broken:
            raise OSError('store locked')
        return self.secrets.get((service, account))

    def delete_password(self, service, account):
        self.secrets.pop((service, account))


def test_saved_session_round_trip():
    ring = MemoryKeyring()
    store = SessionStore(ring)
    store.save(LABEL, SAVED)
    [(service, account)] = ring.secrets
    assert service == 'edupage-keyring-mcp'
    assert account.startswith(SCHOOL + '/') and LABEL not in account
    assert store.load(SCHOOL, LABEL) == SAVED
    assert store.load(SCHOOL, LABEL.upper()) == SAVED  # label match ignores case
    assert store.delete(SCHOOL, LABEL) and not store.delete(SCHOOL, LABEL)


def test_one_account_per_school_needs_no_label():
    ring = MemoryKeyring()
    store = SessionStore(ring)
    store.save('', SAVED)
    assert list(ring.secrets) == [('edupage-keyring-mcp', SCHOOL)]
    assert store.load(SCHOOL, '') == SAVED
    with pytest.raises(EduPageError, match='^NOT_SIGNED_IN$'):
        store.load(SCHOOL, LABEL)  # a labelled entry is a different account
    store.save(LABEL, SAVED)
    assert store.load(SCHOOL, LABEL) == SAVED and len(ring.secrets) == 2


def test_a_failed_write_is_reported(capsys):
    with pytest.raises(EduPageError, match='^CREDENTIAL_STORE_WRITE_FAILED$'):
        SessionStore(MemoryKeyring(broken=True)).save(LABEL, SAVED)
    log = capsys.readouterr().err
    assert 'CREDENTIAL_STORE_WRITE_FAILED from OSError' in log and 'store locked' not in log


def test_load_failures(capsys):
    with pytest.raises(EduPageError, match='^NOT_SIGNED_IN$'):
        SessionStore(MemoryKeyring()).load(SCHOOL, LABEL)
    with pytest.raises(EduPageError, match='^CREDENTIAL_STORE_LOCKED$'):
        SessionStore(MemoryKeyring(broken=True)).load(SCHOOL, LABEL)
    log = capsys.readouterr().err
    assert 'CREDENTIAL_STORE_LOCKED from OSError' in log and 'in get_password' in log
    assert 'store locked' not in log
    ring = MemoryKeyring()
    for secret in ['not json', json.dumps({'format': 1}), json.dumps(
            {'format': 2, 'school': 'other', 'account': 'x', 'login': 'y', 'cookies': []}),
            json.dumps({'format': 2, 'school': SCHOOL, 'account': 'x', 'login': 'y', 'cookies': [['bad']]})]:
        ring.secrets['edupage-keyring-mcp', account_key(SCHOOL, LABEL)] = secret
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


def backend_from(module):
    return type('Backend', (), {'__module__': module})()


@pytest.mark.parametrize('platform, module', [
    ('darwin', 'keyring.backends.macOS'), ('win32', 'keyring.backends.Windows'),
])
def test_the_os_credential_store_is_accepted(platform, module):
    backend = backend_from(module)
    store = keychain.open_credential_store(platform, backend)
    assert isinstance(store, SessionStore) and store.backend is backend


@pytest.mark.parametrize('platform, module', [
    ('darwin', 'keyring.backends.Windows'), ('win32', 'keyring.backends.macOS'),
    ('darwin', 'keyrings.alt.file'), ('win32', 'keyrings.alt.Windows'),
    ('darwin', 'keyring.backends.chainer'), ('win32', 'keyring.backends.fail'),
    ('darwin', 'keyring.backends.null'), ('darwin', 'keyring_pass'),
    ('darwin', 'keyring.backends.macOSfake'), ('linux', 'keyring.backends.SecretService'),
    ('linux', 'keyring.backends.macOS'),
])
def test_other_platforms_and_backends_are_refused(platform, module):
    with pytest.raises(EduPageError, match='^CREDENTIAL_STORE_REQUIRED$'):
        keychain.open_credential_store(platform, backend_from(module))


def test_windows_saved_sessions_stay_on_this_machine():
    backend = backend_from('keyring.backends.Windows')
    keychain.open_credential_store('win32', backend)
    assert backend.persist == 'local machine'


def test_macos_backend_has_no_persistence_setting():
    backend = backend_from('keyring.backends.macOS')
    keychain.open_credential_store('darwin', backend)
    assert not hasattr(backend, 'persist')


def test_saved_session_is_immutable():
    with pytest.raises(Exception):
        SAVED.account = 'x'  # type: ignore[misc]
    assert isinstance(SAVED, SavedSession)


def test_cookies_with_the_same_name_are_kept_apart():
    pair = (Cookie('PHPSESSID', 'school', HOST), Cookie('PHPSESSID', 'portal', '.edupage.org'))
    ring = MemoryKeyring()
    SessionStore(ring).save(LABEL, SavedSession(SCHOOL, 'Rodic100', LABEL, pair))
    assert SessionStore(ring).load(SCHOOL, LABEL).cookies == pair


def test_a_secret_over_2_kb_is_refused_when_saving():
    ring = MemoryKeyring()
    big = SavedSession(SCHOOL, 'Rodic100', LABEL, (Cookie('PHPSESSID', 'x' * 2048, HOST),))
    with pytest.raises(EduPageError, match='^SESSION_CORRUPT$'):
        SessionStore(ring).save(LABEL, big)
    assert ring.secrets == {}


def test_an_older_saved_session_with_several_cookies_still_loads():
    names = ['PHPSESSID', 'edusrs', 'egdid', 'hsid', 'erfp']
    secret = json.dumps({'format': 2, 'school': SCHOOL, 'account': 'Rodic100', 'login': LABEL,
                         'saved': 1, 'cookies': [[n, 'v' * 150, '.' + HOST, '/', -1] for n in names]})
    ring = MemoryKeyring()
    ring.secrets['edupage-keyring-mcp', account_key(SCHOOL, LABEL)] = secret
    assert [c.name for c in SessionStore(ring).load(SCHOOL, LABEL).cookies] == names
