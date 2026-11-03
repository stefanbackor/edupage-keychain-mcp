# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from conftest import HOST, LABEL, SCHOOL, FakeEdu, account_page, reply
from edupage_keychain_mcp import signin
from edupage_keychain_mcp.errors import EduPageError
from edupage_keychain_mcp.keychain import Cookie, SessionStore
from test_keychain import MemoryKeyring


class Chrome:
    """Just enough of Playwright's sync API for the sign-in flow."""

    def __init__(self, final_url, jar, fail=None):
        self.final_url, self.jar, self.fail = final_url, jar, fail
        self.visited, self.closed = [], False

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    chromium = property(lambda self: self)

    def launch(self, channel, headless):
        assert (channel, headless) == ('chrome', False)
        return self

    def new_context(self):
        return self

    def new_page(self):
        return self

    def goto(self, url, wait_until):
        self.visited.append(url)

    def wait_for_url(self, predicate, timeout):
        if self.fail:
            raise self.fail
        assert not predicate(f'https://{HOST}/login/twofactor')
        assert not predicate('https://example.com/user/')
        assert predicate(self.final_url)

    def cookies(self):
        return self.jar

    def close(self):
        self.closed = True


def test_cookies_are_taken_only_after_sign_in_and_only_for_edupage():
    jar = [{'name': 'PHPSESSID', 'value': 'abc', 'domain': HOST, 'path': '/', 'expires': -1, 'httpOnly': True},
           {'name': 'lang', 'value': 'sk', 'domain': '.edupage.org', 'path': '/', 'expires': -1},
           {'name': '_ga', 'value': '1', 'domain': '.google.com', 'path': '/', 'expires': -1},
           {'name': 'odd', 'value': 'bell\x07', 'domain': HOST, 'path': '/', 'expires': -1}]
    chrome = Chrome(f'https://{HOST}/user/', jar)
    cookies = signin.capture_cookies(SCHOOL, 60, chrome)
    assert [c.name for c in cookies] == ['PHPSESSID', 'lang']
    assert chrome.visited == [f'https://{HOST}/'] and chrome.closed


@pytest.mark.parametrize('failure, code', [(type('TimeoutError', (Exception,), {})(), 'SIGNIN_TIMEOUT'),
                                           (RuntimeError('Target closed'), 'SIGNIN_ABORTED')])
def test_browser_problems_become_codes(failure, code):
    chrome = Chrome('', [], fail=failure)
    with pytest.raises(EduPageError, match=f'^{code}$'):
        signin.capture_cookies(SCHOOL, 60, chrome)
    assert chrome.closed


def test_sign_in_stores_the_login_edupage_reports(web, monkeypatch):
    monkeypatch.setattr(signin, 'capture_cookies', lambda school, wait: [Cookie('PHPSESSID', 'abc', HOST)])
    web.routes[f'https://{HOST}/user/'] = lambda r: reply(r, 200, account_page(login='parent.real@example.invalid'))
    ring = MemoryKeyring()
    result = signin.sign_in(SCHOOL, LABEL, SessionStore(ring))
    assert result['status'] == 'SAVED' and result['role'] == 'parent' and 'note' in result
    saved = SessionStore(ring).load(SCHOOL, LABEL)
    assert saved.account == 'Rodic100' and saved.login == 'parent.real@example.invalid'
