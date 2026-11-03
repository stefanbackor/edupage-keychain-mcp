# SPDX-License-Identifier: GPL-3.0-or-later
"""edupage-api clients opened from saved Keychain sessions, one per school."""
from __future__ import annotations

import html
import re
import threading
import unicodedata
from contextlib import contextmanager
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

import requests

from .errors import EduPageError
from .keychain import SavedSession, session_cookies
from .net import SchoolHttp, school_host

ACCOUNT_ROW = re.compile(r'data-rowid="edupage;([^";]+);([^";]+);[^"]*"')


def fetch_userhome(edu: Any, school: str) -> str:
    """Load `/user/` into `edu.data`; return the page so callers can read more from it.

    Raises:
        EduPageError: AUTH_REQUIRED when EduPage no longer accepts the session,
            SCHEMA_CHANGED when the page is not what edupage-api expects.
    """
    from edupage_api.login_session import LoginSession

    try:
        response = edu.session.get(f'https://{school_host(school)}/user/')
    except EduPageError as exc:
        # An expired session is redirected to EduPage's central login host.
        raise EduPageError('AUTH_REQUIRED' if exc.code == 'HOST_NOT_ALLOWED' else exc.code) from None
    except requests.RequestException:
        raise EduPageError('TEMPORARY_ERROR') from None
    page = response.content.decode('utf-8', errors='replace')
    if response.status_code in (401, 403) or urlsplit(response.url).path.startswith('/login') \
            or 'userhome(' not in page:
        raise EduPageError('AUTH_REQUIRED')
    if response.status_code != 200:
        raise EduPageError('TEMPORARY_ERROR')
    try:
        LoginSession(edu).parse_login_data(page)
    except Exception:
        raise EduPageError('SCHEMA_CHANGED') from None
    if not isinstance(edu.data, dict) or not edu.data.get('userid'):
        raise EduPageError('SCHEMA_CHANGED')
    edu.subdomain = school
    return page


def reported_login(page: str, school: str) -> str | None:
    """The login name EduPage itself shows for this school in its account switcher."""
    for tag in re.findall(r'<a [^>]*edubarChangeEdurowBtn[^>]*>', page or ''):
        match = ACCOUNT_ROW.search(tag)
        if match and match.group(1) == school and 'selected' in tag:
            return html.unescape(match.group(2))
    return None


def open_edupage(saved: SavedSession) -> Any:
    """An `edupage_api.Edupage` logged in with saved cookies, confined to the school host."""
    from edupage_api import Edupage

    host = school_host(saved.school)
    edu = Edupage()
    edu.session.close()
    edu.session = SchoolHttp({host})
    for cookie in session_cookies(host, list(saved.cookies)):
        edu.session.cookies.set(cookie.name, cookie.value, domain=cookie.domain,
                                path=cookie.path, secure=True)
    fetch_userhome(edu, saved.school)
    # edupage-api builds its switch-back request from this; it must be the real login.
    edu.username = saved.login
    return edu


def current_account(edu: Any, school: str) -> str:
    fetch_userhome(edu, school)
    return str(edu.data['userid'])


def return_to_parent(edu: Any, school: str, login: str) -> None:
    """Ask EduPage to put the session back on the parent account.

    Done directly because edupage-api's own `switch_to_parent` refuses to run
    when its cached data already reports the child.
    """
    response = edu.session.get(f'https://{school_host(school)}/login/edupageChange',
                               params={'rid': f'edupage;{school};{login}'})
    if 'EdupageLoginFailed' in response.url:
        raise EduPageError('ACCOUNT_MISMATCH')
    edu._selected_child_id = None


def fold(text: str) -> str:
    """Case- and accent-insensitive form: 'Šimon' and 'simon' fold alike."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


_fold = fold  # used by sibling modules


class SchoolSession:
    """A lazily opened edupage-api client for one school, guarded by one lock."""

    def __init__(self, school: str, label: str,
                 loader: Callable[[str, str], SavedSession],
                 opener: Callable[[SavedSession], Any] = open_edupage,
                 reloader: Callable[[Any, str], str] = current_account,
                 restorer: Callable[[Any, str, str], None] = return_to_parent,
                 lock: Any = None) -> None:
        self.school = school
        self.label = label
        self.host = school_host(school)
        self._loader, self._opener = loader, opener
        self._reloader, self._restorer = reloader, restorer
        self.lock = lock if lock is not None else threading.RLock()
        self.edu: Any = None
        self.saved: SavedSession | None = None

    @property
    def expected_userid(self) -> str | None:
        return self.saved.account if self.saved else None

    def connect(self) -> Any:
        if self.edu is not None:
            return self.edu
        saved = self._loader(self.school, self.label)
        edu = self._opener(saved)
        seen = str(edu.data.get('userid'))
        if seen != saved.account and saved.account.startswith('Rodic'):
            # Left in a child's view by an earlier failure: put it back, then re-check.
            try:
                self._restorer(edu, self.school, saved.login)
                seen = self._reloader(edu, self.school)
            except Exception:
                raise EduPageError('ACCOUNT_MISMATCH') from None
        if seen != saved.account:
            raise EduPageError('ACCOUNT_MISMATCH')
        self.saved, self.edu = saved, edu
        return edu

    def reset(self) -> None:
        if self.edu is not None:
            try:
                self.edu.session.close()
            except Exception:
                pass
        self.edu = None

    @property
    def role(self) -> str:
        account = str(self.connect().data.get('userid', ''))
        return ('parent' if account.startswith('Rodic') else
                'student' if account.startswith('Student') else 'teacher')

    def children(self) -> list[dict]:
        """A parent's children, or the student themself."""
        data = self.connect().data
        db = data.get('dbi') if isinstance(data.get('dbi'), dict) else {}
        pupils = db.get('students') if isinstance(db.get('students'), dict) else {}
        classes = db.get('classes') if isinstance(db.get('classes'), dict) else {}
        role = self.role
        if role == 'parent':
            ids = [str(i) for i in data.get('parentStudentids') or [] if isinstance(i, (str, int))]
        elif role == 'student':
            ids = [str(data['userid'])[len('Student'):]]
        else:
            ids = []
        found = []
        for position, pupil_id in enumerate(ids, 1):
            pupil = pupils.get(pupil_id) if isinstance(pupils.get(pupil_id), dict) else {}
            given = str(pupil.get('firstname') or '').strip() or f'Child {position}'
            full = ' '.join(filter(None, [str(pupil.get('firstname') or '').strip(),
                                          str(pupil.get('lastname') or '').strip()])) or given
            group = classes.get(str(pupil.get('classid'))) if pupil.get('classid') else None
            found.append({'ref': f'{self.school}/{pupil_id}', 'student_id': pupil_id,
                          'name': full, 'first_name': given,
                          'class': group.get('name') if isinstance(group, dict) else None,
                          'school': self.school})
        return found

    def resolve_child(self, child: str) -> dict | None:
        """Find one child by ref, student ID, full name or first name."""
        options = self.children()
        if not child:
            return options[0] if len(options) == 1 else None
        wanted = fold(str(child))
        exact = [o for o in options if wanted in (o['ref'].casefold(), o['student_id'].casefold())]
        if exact:
            return exact[0]
        for field in ('name', 'first_name'):
            hits = [o for o in options if fold(o[field]) == wanted]
            if len(hits) == 1:
                return hits[0]
        return None

    @contextmanager
    def as_child(self, child_id: str | None) -> Iterator[Any]:
        """Switch a parent session to one child for the block, then back, verified."""
        edu = self.connect()
        if child_id is None or self.role != 'parent':
            yield edu
            return
        try:
            edu.switch_to_child(int(child_id))  # may be applied server-side even if it raises
            yield edu
        finally:
            try:
                self._restorer(edu, self.school, self.saved.login)
                if self._reloader(edu, self.school) != self.expected_userid:
                    raise EduPageError('ACCOUNT_MISMATCH')
            except Exception:
                self.reset()  # connect() will repair or refuse it next time
