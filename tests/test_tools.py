# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from conftest import FakeEdu, event, tools_for
from edupage_keychain_mcp.data import missing_teacher_names, recipient_matches, tolerant_grades
from edupage_keychain_mcp.errors import EduPageError


def test_child_tools_name_the_child_and_mark_content_untrusted():
    edu = FakeEdu()
    result = tools_for(('demo-school', edu)).get_timetable('ema', '2026-11-03')
    assert result['status'] == 'READY' and result['untrusted_content'] is True
    assert result['child'] == {'ref': 'demo-school/12', 'name': 'Ema Vzorová', 'class': '1.Y'}
    assert result['lessons'][0]['subject'] == 'Matematika'
    assert edu.switched == [12]


def test_which_child_must_be_clear():
    tools = tools_for(('demo-school', FakeEdu()))
    assert tools.get_timetable() == {'status': 'CHILD_REQUIRED', 'children': ['Šimon Vzorový', 'Ema Vzorová']}
    assert tools.get_timetable('Jozef')['status'] == 'UNKNOWN_CHILD'


def test_library_failures_never_leak_text():
    edu = FakeEdu()
    edu.error = KeyError('<html>secret page</html>')
    assert tools_for(('demo-school', edu)).get_timetable('Ema') == {
        'status': 'SCHEMA_CHANGED', 'error_type': 'KeyError'}
    expired = type('NotLoggedInException', (Exception,), {})
    edu.error = expired('token=abc')
    tools = tools_for(('demo-school', edu))
    assert tools.get_timetable('Ema') == {'status': 'AUTH_REQUIRED', 'error_type': 'NotLoggedInException'}
    assert tools.sessions['demo-school'].edu is None


def test_schools_are_independent():
    tools = tools_for(('demo-school', FakeEdu()), ('second-school', EduPageError('NOT_SIGNED_IN')))
    assert {s['school']: s['status'] for s in tools.list_schools()['schools']} == {
        'demo-school': 'READY', 'second-school': 'NOT_SIGNED_IN'}
    listing = tools.list_children()
    assert len(listing['children']) == 2
    assert listing['unavailable_schools'] == [{'school': 'second-school', 'status': 'NOT_SIGNED_IN'}]
    assert tools.get_timetable('Ema')['status'] == 'READY'
    assert tools.user_id('second-school') == {'status': 'NOT_SIGNED_IN'}
    assert tools.user_id('elsewhere')['status'] == 'UNKNOWN_SCHOOL'
    assert tools.list_children('elsewhere')['status'] == 'UNKNOWN_SCHOOL'
    crashed = tools_for(('demo-school', RuntimeError('private keyring detail')))
    assert crashed.get_timetable('Ema') == {'status': 'LOCAL_ERROR', 'error_type': 'RuntimeError'}


def test_timeline_tags_children_and_filters_siblings():
    edu = FakeEdu()
    edu.events = [event(1, 'homework', '9.Z · Fyzika', '', {'nazov': 'Workbook p. 10', 'date': '2026-11-05'}),
                  event(2, 'homework', '1.Y · Čítanie', 'Read p. 4'),
                  event(3, 'pipnutie', 'Ema Vzorová', 'Arrived 07:55'),
                  event(4, 'news', '*', 'School news'),
                  event(5, 'homework', '9.ZA · Chémia', 'Not our class')]
    tools = tools_for(('demo-school', edu))
    every = tools.timeline(None)
    assert {i['id']: i['for_children'] for i in every['items']} == {
        1: ['Šimon'], 2: ['Ema'], 3: ['Ema'], 4: [], 5: []}
    homework = tools.timeline({'homework'}, child='Šimon')
    assert [(i['id'], i['text']) for i in homework['items']] == [
        (5, 'Not our class'), (1, 'Workbook p. 10')]
    assert edu.switched == []  # filtering needs no account switch
    old = (date.today() - timedelta(days=91)).isoformat()
    assert tools.timeline(None, since=old)['status'] == 'DATE_OUT_OF_RANGE'


def test_recipient_matching_uses_whole_class_tokens():
    child = {'name': 'Ema Vzorová', 'class': '1.Y'}
    assert recipient_matches({'recipient': 'Rodičia 1.Y'}, child)
    assert recipient_matches({'recipient': 'ema vzorova'}, child)
    assert not recipient_matches({'recipient': '1.YZ · Fyzika'}, child)
    assert not recipient_matches({'recipient': '*'}, child)


def test_grades_survive_rows_the_library_rejects(monkeypatch):
    raw = {'vsetkyZnamky': [{'udalostid': '1', 'datum': '2026-11-02 10:00:00', 'data': '2 (diktát)'},
                            {'udalostid': '2', 'datum': '2026-11-01 10:00:00', 'data': '1'}, None],
           'vsetkyUdalosti': {'edupage': {'1': {'PredmetID': '9', 'UcitelID': '55', 'p_meno': 'Diktát',
                                                'p_typ_udalosti': '1', 'p_vaha': '20'}}}}
    userhome = {'dbi': {'subjects': {'9': {'name': 'Slovenčina'}},
                        'teachers': {'55': {'firstname': 'Hana', 'lastname': 'Učiteľka'}}}}
    rows, skipped = tolerant_grades(userhome, raw)
    assert skipped == 2 and rows[0]['subject'] == 'Slovenčina' and rows[0]['grade'] == 2.0
    assert rows[0]['comment'] == 'diktát' and rows[0]['teacher'] == 'Hana Učiteľka' and rows[0]['weight'] == 1.0

    import edupage_api.grades as library
    edu = FakeEdu()
    edu.get_grades = lambda: None.missing  # the library's own crash
    monkeypatch.setattr(library.Grades, '_Grades__get_grade_data', lambda self: raw, raising=False)
    result = tools_for(('demo-school', edu)).get_grades('Ema')
    assert result['status'] == 'READY' and result['parser'] == 'tolerant' and len(result['grades']) == 1


def test_missing_teachers_without_roster_lookup():
    page = ('<span class="print-font-resizable">Chýbajúci: Eva Malá, Jana  Veľká  (1 - 3), '
            'Ivan Horný + Mária Dolná</span>')
    assert missing_teacher_names(page) == ['Eva Malá', 'Jana Veľká', 'Ivan Horný', 'Mária Dolná']
    assert missing_teacher_names(None) == []


def test_send_message_checks_recipient_and_body():
    edu = FakeEdu()
    tools = tools_for(('demo-school', edu))
    for recipient, body, status in [('https://x', 'hi', 'INVALID_RECIPIENT'), ('Teacher56', 'hi', 'UNKNOWN_RECIPIENT'),
                                    ('Teacher55', ' ', 'INVALID_BODY'), ('Teacher55', 'x' * 5001, 'INVALID_BODY')]:
        assert tools.send_message(recipient, body)['status'] == status
    assert edu.sent == []
    assert tools.send_message('Teacher55', 'Dobrý deň')['timeline_id'] == 999
    assert edu.sent == [(['Teacher55'], 'Dobrý deň')]


def test_meal_tools():
    edu = FakeEdu()
    tools = tools_for(('demo-school', edu))
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert tools.get_meals('Ema', tomorrow)['status'] == 'MEALS_NOT_AVAILABLE'
    edu.get_meals = lambda day: None.canteen
    assert tools.get_meals('Ema', tomorrow)['status'] == 'MEALS_NOT_AVAILABLE'
    picked = []
    lunch = SimpleNamespace(chooseable_menus=['A', 'B'], menus=[], title='Obed', served_from=None,
                            served_to=None, ordered_meal=None, can_be_changed_until=None,
                            choose=lambda e, n: picked.append(n), sign_off=lambda e: picked.append('off'))
    edu.get_meals = lambda day: SimpleNamespace(snack=None, lunch=lunch, afternoon_snack=None)
    assert tools.choose_meal('Ema', tomorrow, 'dinner', 1)['status'] == 'INVALID_MEAL_TYPE'
    assert tools.choose_meal('Ema', '2020-01-01', 'lunch', 1)['status'] == 'DATE_OUT_OF_RANGE'
    assert tools.choose_meal('Ema', tomorrow, 'lunch', 3)['status'] == 'INVALID_MENU_NUMBER'
    assert tools.choose_meal('Ema', tomorrow, 'lunch', 2)['menu'] == 'B'
    assert tools.sign_off_meal('Ema', tomorrow, 'lunch')['ordered'] is False
    assert picked == [2, 'off']
    assert tools.rate_meal('Ema', date.today().isoformat(), 'snack', 3, 3)['status'] == 'INVALID_MEAL_TYPE'
    assert tools.rate_meal('Ema', date.today().isoformat(), 'lunch', 6, 1)['status'] == 'INVALID_RATING'


def test_bell_tools_guard_against_bad_data():
    edu = FakeEdu()
    tools = tools_for(('demo-school', edu))
    assert tools.get_next_ringing_time('2026-11-03T07:30:00Z')['status'] == 'READY'
    assert tools.get_next_ringing_time('1990-01-01T08:00')['status'] == 'DATE_OUT_OF_RANGE'
    edu.data['zvonenia'] = []
    assert tools.get_next_ringing_time()['status'] == 'DATA_NOT_AVAILABLE'
