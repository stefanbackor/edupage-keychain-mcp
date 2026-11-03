# SPDX-License-Identifier: GPL-3.0-or-later
"""`edupage-keyring-mcp login`: sign in with Chrome, keep only the session.

The person signs in on the school's EduPage site in an off-the-record Chrome
window (Playwright with the installed Google Chrome). Their password and
two-factor code go to EduPage only. When the browser reaches the signed-in
account page we take EduPage's cookies from that window, prove they work
through `SchoolHttp`, and store them in the Keychain. The window's cookies and
storage live in memory and are discarded when Chrome closes.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlsplit

from .client import fetch_userhome, open_edupage, reported_login
from .errors import EduPageError
from .keychain import Cookie, SavedSession, SessionStore, parse_cookie, session_cookies
from .net import school_host

ACCOUNT_PAGES = ('/user', '/timeline', '/dashboard')


def _signed_in(host: str) -> Callable[[str], bool]:
    def check(url: str) -> bool:
        parts = urlsplit(url)
        return parts.hostname == host and parts.path.rstrip('/').startswith(ACCOUNT_PAGES)
    return check


def capture_cookies(school: str, wait_seconds: int = 600,
                    playwright: Callable[[], Any] | None = None) -> list[Cookie]:
    """Show EduPage in Chrome and return its cookies once the person is signed in."""
    host = school_host(school)
    if playwright is None:
        try:
            from playwright.sync_api import sync_playwright as playwright
        except ImportError:
            raise EduPageError('PLAYWRIGHT_MISSING') from None
    with playwright() as driver:
        try:
            chrome = driver.chromium.launch(channel='chrome', headless=False)
        except Exception:
            raise EduPageError('CHROME_NOT_FOUND') from None
        try:
            window = chrome.new_context()  # off the record: nothing kept after close
            tab = window.new_page()
            try:
                tab.goto(f'https://{host}/', wait_until='domcontentloaded')
                tab.wait_for_url(_signed_in(host), timeout=wait_seconds * 1000)
            except Exception as exc:
                raise EduPageError('SIGNIN_TIMEOUT' if type(exc).__name__ == 'TimeoutError'
                                   else 'SIGNIN_ABORTED') from None
            jar = window.cookies()
        finally:
            try:
                chrome.close()
            except Exception:
                pass
    mine = []
    for c in jar:
        if str(c.get('domain', '')).lstrip('.') not in (host, 'edupage.org'):
            continue
        try:
            mine.append(parse_cookie(c.get('name'), c.get('value'), c.get('domain'),
                                     c.get('path', '/'), c.get('expires', -1)))
        except EduPageError:
            continue  # an odd tracking cookie must not spoil the sign-in
    return session_cookies(host, mine)


def sign_in(school: str, label: str, store: SessionStore | None = None,
            wait_seconds: int = 600) -> dict:
    """Capture a browser session, check it against EduPage, then save it."""
    cookies = tuple(capture_cookies(school, wait_seconds))
    trial = SavedSession(school, account='', login=label, cookies=cookies)
    edu = open_edupage(trial)
    try:
        page = fetch_userhome(edu, school)
        account = str(edu.data['userid'])
        reported = reported_login(page, school)
        login = reported or label
    finally:
        edu.session.close()
    (store or SessionStore()).save(label, SavedSession(school, account, login, cookies))
    role = ('parent' if account.startswith('Rodic') else
            'student' if account.startswith('Student') else 'teacher')
    result = {'status': 'SAVED', 'school': school, 'role': role}
    if reported is None and role == 'parent':
        result['note'] = ('EduPage did not show the login name; switching between children '
                          'assumes it is exactly the one given.')
    elif login.casefold() != label.casefold():
        result['note'] = 'EduPage reports a different login name than the one given; using EduPage\'s.'
    return result
