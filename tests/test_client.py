# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from conftest import HOST, LABEL, SAVED, SCHOOL, FakeEdu, account_page, reply, school_session
from edupage_keychain_mcp.client import SchoolSession, open_edupage, reported_login
from edupage_keychain_mcp.errors import EduPageError
from edupage_keychain_mcp.keychain import Cookie, SavedSession
from edupage_keychain_mcp.net import SchoolHttp


def test_saved_session_opens_inside_school_http(web):
    web.routes[f'https://{HOST}/user/'] = lambda r: reply(r, 200, account_page())
    edu = open_edupage(SAVED)
    assert isinstance(edu.session, SchoolHttp) and edu.session.allowed_hosts == {HOST}
    assert edu.get_user_id() == 'Rodic100' and edu.gsec_hash == '00000000'
    assert edu.username == LABEL and edu.subdomain == SCHOOL


def test_expired_session_is_reported_not_followed(web):
    web.routes[f'https://{HOST}/user/'] = lambda r: reply(
        r, 302, headers={'Location': 'https://login1.edupage.org/?next=x'})
    with pytest.raises(EduPageError, match='^AUTH_REQUIRED$'):
        open_edupage(SAVED)
    assert not any('login1' in url for url in web.calls)
    web.routes[f'https://{HOST}/user/'] = lambda r: reply(r, 302, headers={'Location': '/login/'})
    web.routes[f'https://{HOST}/login/'] = lambda r: reply(r, 200, b'<form></form>')
    with pytest.raises(EduPageError, match='^AUTH_REQUIRED$'):
        open_edupage(SAVED)


def test_foreign_cookie_in_saved_session_is_refused():
    bad = SavedSession(SCHOOL, 'Rodic100', LABEL, (Cookie('x', 'y', 'example.com'),))
    with pytest.raises(EduPageError, match='^SESSION_CORRUPT$'):
        open_edupage(bad)


def test_login_name_is_read_from_the_account_switcher():
    assert reported_login(account_page(login='Real.Login@example.invalid').decode(), SCHOOL) == \
        'Real.Login@example.invalid'
    assert reported_login('<html></html>', SCHOOL) is None
    other = '<a class="edubarChangeEdurowBtn selected" data-rowid="edupage;other;x@y;rodic">'
    assert reported_login(other, SCHOOL) is None


def test_library_cannot_be_redirected_off_the_school_host(web):
    web.routes[f'https://{HOST}/user/'] = lambda r: reply(r, 200, account_page())
    web.routes[f'https://{HOST}/znamky/'] = lambda r: reply(r, 302, headers={'Location': 'https://example.com/'})
    edu = SchoolSession(SCHOOL, LABEL, lambda s, l: SAVED).connect()
    with pytest.raises(EduPageError, match='^HOST_NOT_ALLOWED$'):
        edu.get_grades()
    assert all(url.startswith(f'https://{HOST}/') for url in web.calls)


def test_child_switch_round_trip_against_the_real_library(web):
    state = {'who': 'Student11'}  # left in a child's view by an earlier crash

    def user(request):
        return reply(request, 200, account_page(state['who']))

    def change(request):
        assert 'rid=edupage%3Bdemo-school%3Bparent%40example.invalid' in request.url
        state['who'] = 'Rodic100'
        return reply(request, 200, b'')

    def switch(request):
        state['who'] = 'Student12'
        return reply(request, 200, b'OK')

    web.routes.update({f'https://{HOST}/user/': user, f'https://{HOST}/login/edupageChange': change,
                       f'https://{HOST}/login/switchchild': switch})
    session = SchoolSession(SCHOOL, LABEL, lambda s, l: SAVED)
    assert session.connect().get_user_id() == 'Rodic100'  # repaired on connect
    with session.as_child('12'):
        assert state['who'] == 'Student12'
    assert state['who'] == 'Rodic100' and session.edu is not None


def test_child_switch_always_returns_and_is_verified():
    edu = FakeEdu()
    session = school_session(edu)
    with session.as_child('11'):
        pass
    assert edu.switched == [11] and session.restores == [LABEL] and session.edu is edu

    def half_applied(child_id):
        raise TimeoutError()
    edu.switch_to_child = half_applied
    with pytest.raises(TimeoutError):
        with session.as_child('11'):
            pass
    assert session.restores == [LABEL, LABEL]

    stuck = school_session(FakeEdu(), reloader=lambda e, s: 'Student11')
    with stuck.as_child('11'):
        pass
    assert stuck.edu is None


def test_a_session_still_showing_a_child_is_refused_if_it_cannot_be_repaired():
    edu = FakeEdu()
    edu.data['userid'] = 'Student11'
    session = SchoolSession(SCHOOL, LABEL, lambda s, l: SAVED, opener=lambda saved: edu,
                            reloader=lambda e, s: e.data['userid'], restorer=lambda e, s, l: None)
    with pytest.raises(EduPageError, match='^ACCOUNT_MISMATCH$'):
        session.connect()


def test_children_and_matching():
    session = school_session(FakeEdu())
    kids = session.children()
    assert [(k['ref'], k['first_name'], k['class']) for k in kids] == [
        ('demo-school/11', 'Šimon', '9.Z'), ('demo-school/12', 'Ema', '1.Y')]
    for query in ['simon', 'ŠIMON', 'Šimon Vzorový', '11', 'demo-school/11']:
        assert session.resolve_child(query)['student_id'] == '11'
    assert session.resolve_child('nobody') is None
    assert session.resolve_child('') is None  # two children: must say which
