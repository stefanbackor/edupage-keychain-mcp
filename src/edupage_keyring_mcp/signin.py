# SPDX-License-Identifier: GPL-3.0-or-later
"""`edupage-keyring-mcp login`: sign in with Chrome, keep only the session.

The person signs in on the school's EduPage site in an off-the-record Chrome
window (Playwright with the installed Google Chrome). Their password and
two-factor code go to EduPage only. When the browser reaches the signed-in
account page we take EduPage's session cookie (`PHPSESSID`, the only one it
needs) from that window, prove it works through `SchoolHttp`, and store it. The window's cookies and
storage live in memory and are discarded when Chrome closes.

`BrowserSignIn` lets the running MCP server start that same `login` command in
a child process when a session is missing or expired, so the person can sign
in without a terminal. The child's output is read for its status code only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from typing import Any, Callable
from urllib.parse import urlsplit

from .client import fetch_userhome, open_edupage, reported_login
from .errors import EduPageError
from .keychain import Cookie, SavedSession, SessionStore, parse_cookie, session_cookies
from .net import school_host

ACCOUNT_PAGES = ('/user', '/timeline', '/dashboard')
SESSION_COOKIE = 'PHPSESSID'


def _signed_in(host: str) -> Callable[[str], bool]:
    def check(url: str) -> bool:
        parts = urlsplit(url)
        return parts.hostname == host and parts.path.rstrip('/').startswith(ACCOUNT_PAGES)
    return check


def capture_cookies(school: str, wait_seconds: int = 600,
                    playwright: Callable[[], Any] | None = None) -> list[Cookie]:
    """Show EduPage in Chrome and return the school's session cookie once the person is signed in.

    Raises SCHEMA_CHANGED when the window holds no `PHPSESSID` for the school host.
    """
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
        if c.get('name') != SESSION_COOKIE or str(c.get('domain', '')).lstrip('.') != host:
            continue  # EduPage needs nothing else; tracking and device cookies stay behind
        try:
            mine.append(parse_cookie(c.get('name'), c.get('value'), c.get('domain'),
                                     c.get('path', '/'), c.get('expires', -1)))
        except EduPageError:
            continue
    if not mine:
        raise EduPageError('SCHEMA_CHANGED')  # EduPage no longer issues its session cookie
    return session_cookies(host, mine)


def sign_in(school: str, label: str = '', store: SessionStore | None = None,
            wait_seconds: int = 600, playwright: Callable[[], Any] | None = None) -> dict:
    """Capture a browser session, check it against EduPage, then save it."""
    cookies = tuple(capture_cookies(school, wait_seconds, playwright))
    trial = SavedSession(school, account='', login=label, cookies=cookies)
    edu = open_edupage(trial)
    try:
        page = fetch_userhome(edu, school)
        account = str(edu.data['userid'])
        login = reported_login(page, school) or label
    finally:
        edu.session.close()
    (store or SessionStore()).save(label, SavedSession(school, account, login, cookies))
    role = ('parent' if account.startswith('Rodic') else
            'student' if account.startswith('Student') else 'teacher')
    return {'status': 'SAVED', 'school': school, 'role': role}

STATUS_CODE = re.compile(r'^[A-Z][A-Z_]{1,40}$')


def spawn_login(school: str, label: str) -> Any:
    """Start `edupage-keyring-mcp login SCHOOL` with the server's own Python.

    stdout is piped, never inherited: the server's stdout is the MCP channel.
    """
    return subprocess.Popen(
        [sys.executable, '-m', 'edupage_keyring_mcp', 'login', school],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=_login_env(label), close_fds=True)


def _login_env(label: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop('EDUPAGE_USERNAME', None)
    if label:
        env['EDUPAGE_USERNAME'] = label
    return env


def login_outcome(output: bytes | str | None, returncode: int | None) -> str:
    """The status code from the last line `login` printed; nothing else is kept."""
    text = output.decode('utf-8', errors='replace') if isinstance(output, bytes) else (output or '')
    lines = [line for line in text.splitlines() if line.strip()]
    try:
        status = json.loads(lines[-1]).get('status') if lines else None
    except (ValueError, AttributeError):
        status = None
    if not isinstance(status, str) or not STATUS_CODE.match(status):
        return 'SIGNIN_FAILED'
    if status == 'SAVED' and returncode != 0:
        return 'SIGNIN_FAILED'
    return status


class BrowserSignIn:
    """Runs `login` in a child process, at most one per school at a time."""

    def __init__(self, spawn: Callable[[str, str], Any] = spawn_login) -> None:
        self._spawn = spawn
        self._lock = threading.Condition()
        self._running: dict[str, Any] = {}
        self._outcome: dict[str, str] = {}

    def running(self, school: str) -> bool:
        with self._lock:
            return school in self._running

    def outcome(self, school: str) -> str | None:
        """The last finished sign-in's status for a school, if any."""
        with self._lock:
            return self._outcome.get(school)

    def wait(self, school: str, seconds: float) -> bool:
        """Block until the school's sign-in has finished; False if still open after `seconds`."""
        with self._lock:
            return self._lock.wait_for(lambda: school not in self._running, timeout=seconds)

    def start(self, school: str, label: str, on_exit: Callable[[], None]) -> str:
        """Open the sign-in window; `on_exit` runs once the child has finished."""
        with self._lock:
            if school in self._running:
                return 'SIGNIN_IN_PROGRESS'
            try:
                child = self._spawn(school, label)
            except Exception:
                return 'SIGNIN_START_FAILED'
            self._running[school] = child
            self._outcome.pop(school, None)
        watcher = threading.Thread(target=self._watch, args=(school, child, on_exit),
                                   name=f'signin-{school}', daemon=True)
        watcher.start()
        return 'SIGNIN_STARTED'

    def _watch(self, school: str, child: Any, on_exit: Callable[[], None]) -> None:
        try:
            output, _ = child.communicate()
            status = login_outcome(output, child.returncode)
        except Exception:
            status = 'SIGNIN_FAILED'
        try:
            on_exit()
        finally:
            with self._lock:
                self._running.pop(school, None)
                self._outcome[school] = status
                self._lock.notify_all()
