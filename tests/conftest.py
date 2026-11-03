# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures. All data is invented; no test touches the network or the Keychain."""
from __future__ import annotations

import io
import json
from datetime import time
from types import SimpleNamespace

import pytest
import requests

from edupage_keyring_mcp.client import SchoolSession
from edupage_keyring_mcp.keychain import Cookie, SavedSession
from edupage_keyring_mcp.tools import FullTools

SCHOOL = 'demo-school'
HOST = 'demo-school.edupage.org'
LABEL = 'parent@example.invalid'
COOKIE = Cookie('PHPSESSID', 'synthetic-session', HOST)
SAVED = SavedSession(SCHOOL, 'Rodic100', LABEL, (COOKIE,))

ACCOUNT = {
    'userid': 'Rodic100',
    'parentStudentids': ['11', '12'],
    'dbi': {
        'students': {'11': {'firstname': 'Šimon', 'lastname': 'Vzorový', 'classid': '7'},
                     '12': {'firstname': 'Ema', 'lastname': 'Vzorová', 'classid': '8'}},
        'classes': {'7': {'name': '9.Z'}, '8': {'name': '1.Y'}},
        'teachers': {'55': {'firstname': 'Hana', 'lastname': 'Učiteľka'}},
        'parents': {}, 'subjects': {}, 'classrooms': {},
    },
    'zvonenia': [{'period': '1', 'starttime': '08:00', 'endtime': '08:45'}],
    'dp': {'year': 2026},
}


def reply(request, status=200, body=b'', headers=None):
    """A requests.Response built in memory."""
    import urllib3
    response = requests.Response()
    response.status_code = status
    response.raw = urllib3.HTTPResponse(body=io.BytesIO(body), headers=headers or {}, status=status,
                                        preload_content=False)
    response.headers.update(headers or {})
    response.url = request.url
    response.request = request
    return response


def account_page(userid='Rodic100', login=LABEL):
    switcher = (f'<a class="edubarProfileUserBtn edubarChangeEdurowBtn Rodic selected" '
                f'data-rowid="edupage;{SCHOOL};{login};rodic">Parent</a>')
    data = dict(ACCOUNT, userid=userid)
    return (switcher + '<script>userhome(' + json.dumps(data) + ');\n</script>'
            '<script>ASC.gsechash="00000000";</script>').encode()


@pytest.fixture
def web(monkeypatch):
    """Fake internet: routes by URL prefix, records every URL actually sent."""
    calls: list[str] = []
    routes: dict = {}

    def send(adapter, request, **kwargs):
        calls.append(request.url)
        for prefix in sorted(routes, key=len, reverse=True):
            if request.url.startswith(prefix):
                return routes[prefix](request)
        return reply(request, 404)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    return SimpleNamespace(calls=calls, routes=routes)


class FakeEdu:
    """Stands in for edupage_api.Edupage in tool tests."""

    def __init__(self):
        self.data = json.loads(json.dumps(ACCOUNT))
        self.session = requests.Session()
        self.session.cookies.set(COOKIE.name, COOKIE.value, domain=HOST)
        self.switched: list = []
        self.sent: list = []
        self.meals = None
        self.events: list = []
        self.error: Exception | None = None

    def get_user_id(self):
        return self.data['userid']

    def switch_to_child(self, child_id):
        self.switched.append(child_id)

    def get_my_timetable(self, day):
        if self.error:
            raise self.error
        lesson = SimpleNamespace(period=1, start_time=time(8), end_time=time(8, 45),
                                 subject=SimpleNamespace(name='Matematika', short='MAT'),
                                 teachers=[SimpleNamespace(name='Hana Učiteľka')], classrooms=[],
                                 classes=[], groups=[], curriculum='Zlomky', is_cancelled=False,
                                 is_event=False, online_lesson_link=None)
        return SimpleNamespace(lessons=[lesson])

    def get_next_ringing_time(self, moment):
        return SimpleNamespace(kind='LESSON', at=moment.replace(hour=8, minute=0))

    def get_notification_history(self, since):
        return self.events

    def get_meals(self, day):
        return self.meals

    def send_message(self, recipients, body):
        self.sent.append((recipients, body))
        return 999


def school_session(edu, school=SCHOOL):
    def load(name, label):
        if isinstance(edu, Exception):
            raise edu
        return SavedSession(name, edu.data['userid'], LABEL, (COOKIE,))

    return SchoolSession(school, '', load, opener=lambda saved: edu)


def tools_for(*pairs) -> FullTools:
    return FullTools([school_session(edu, school) for school, edu in pairs])


def event(event_id, kind, recipient, text='', data=None, when=None):
    from datetime import datetime
    from edupage_api.timeline import EventType
    return SimpleNamespace(event_id=event_id, event_type=EventType(kind),
                           timestamp=when or datetime(2026, 11, 2, 9, event_id % 60), event_time=None,
                           text=text, author='Hana Učiteľka', recipient=recipient,
                           additional_data=data or {}, is_done=False, is_removed=False)
