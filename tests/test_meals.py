# SPDX-License-Identifier: GPL-3.0-or-later
import json
from datetime import date, timedelta

import pytest

from conftest import HOST, SCHOOL, FakeEdu, reply, tools_for
from edupage_keyring_mcp import meals
from edupage_keyring_mcp.errors import EduPageError

TOMORROW = date.today() + timedelta(days=1)


def lunch(**changes):
    """A lunch shaped like EduPage's 2026 canteen page, with invented dishes."""
    row = {'nazov': 'Polievka', 'alergenyStr': '1, 7', 'hmotnostiStr': '200/250'}
    meal = {
        'vydaj_od': '11:00', 'vydaj_do': '14:00', 'isCooking': True,
        'choosableMenus': {'1': True, '2': True}, 'zmen_do': '2099-01-01 08:00',
        'menus': {'1': {'nazovMenu': 'Menu A', 'rows': [row]},
                  '2': {'nazovMenu': 'Menu B', 'rows': [{'nazov': 'Šalát', 'hmotnostiStr': '150'}]}},
        'evidencia': {'stav': 'A', 'obj': 'A'},
    }
    meal.update(changes)
    return meal


def menu_page(meal=None, snack=None, day=TOMORROW):
    slots = {'2': meal or lunch()}
    if snack is not None:
        slots['1'] = snack
    data = {SCHOOL: {'novyListok': {day.isoformat(): slots, 'addInfo': {'strRow': {'stravnikid': 77}}}}}
    # EduPage now ends the block with ",\n", which edupage-api 0.13.3 cannot split.
    return ('<script>var w = x.strava_listok({\n    edupageData: ' + json.dumps(data)
            + ',\n    uzivatel: uzivatel,\n});</script>').encode()


@pytest.fixture
def serve(web):
    """Serve one canteen page; return the tools and the child-switch log."""
    def install(page=None, status=200):
        web.routes[f'https://{HOST}/menu/'] = lambda r: reply(r, status, page or menu_page())
        edu = FakeEdu()
        return tools_for((SCHOOL, edu)), edu
    return install


def test_reads_the_current_page_format(serve, web):
    tools, edu = serve()
    result = tools.get_meals('Ema', TOMORROW.isoformat())
    assert result['status'] == 'READY' and result['untrusted_content'] is True
    assert result['meals']['snack'] is None and result['meals']['afternoon_snack'] is None
    assert result['meals']['lunch'] == {
        'served_from': '11:00', 'served_to': '14:00',
        'menus': [{'menu': 'A', 'name': 'Menu A',
                   'dishes': [{'name': 'Polievka', 'allergens': '1, 7', 'weight': '200/250'}]},
                  {'menu': 'B', 'name': 'Menu B',
                   'dishes': [{'name': 'Šalát', 'allergens': None, 'weight': '150'}]}],
        'ordered_menu': 'A', 'cancelled': False, 'served': False,
        'choosable_menus': ['A', 'B'], 'can_be_changed_until': '2099-01-01 08:00'}
    assert edu.switched == [12]
    assert all(call.startswith(f'https://{HOST}/') for call in web.calls)  # GET only, school host only


@pytest.mark.parametrize('order, ordered, cancelled, served', [
    ({'stav': None, 'obj': None}, None, False, False),
    ({'stav': 'X', 'obj': 'B'}, None, True, False),
    ({'stav': 'V', 'obj': 'B'}, 'B', False, True),
])
def test_order_states(serve, order, ordered, cancelled, served):
    tools, _ = serve(menu_page(lunch(evidencia=order), snack={'isCooking': False}))
    result = tools.get_meals('Ema', TOMORROW.isoformat())['meals']
    assert result['snack'] is None
    assert (result['lunch']['ordered_menu'], result['lunch']['cancelled'], result['lunch']['served']) == (
        ordered, cancelled, served)


def test_pages_without_canteen_data():
    for page in ['<html></html>', 'edupageData: {"other": {}},\n', 'edupageData: [],\n']:
        with pytest.raises(EduPageError, match='MEALS_NOT_AVAILABLE'):
            meals.day_listings(page, SCHOOL)
    with pytest.raises(EduPageError, match='SCHEMA_CHANGED'):
        meals.day_listings('edupageData: {broken', SCHOOL)


def test_fetch_failures_map_to_statuses(serve):
    assert serve(b'<html></html>')[0].get_meals('Ema', TOMORROW.isoformat())['status'] == 'MEALS_NOT_AVAILABLE'
    assert serve(status=500)[0].get_meals('Ema', TOMORROW.isoformat())['status'] == 'TEMPORARY_ERROR'
    assert serve(status=403)[0].get_meals('Ema', TOMORROW.isoformat())['status'] == 'AUTH_REQUIRED'
    assert serve()[0].get_meals('Ema', '2020-01-01')['status'] == 'DATE_OUT_OF_RANGE'


def test_meal_actions_say_the_library_is_broken(serve, web):
    tools, edu = serve()
    def broken(day):
        raise AttributeError("'list' object has no attribute 'get'")  # edupage-api 0.13.3 on this page
    edu.get_meals = broken
    day = TOMORROW.isoformat()
    results = [tools.choose_meal('Ema', day, 'lunch', 1), tools.sign_off_meal('Ema', day, 'lunch')]
    tools, edu = serve(menu_page(day=date.today()))
    edu.get_meals = broken
    results.append(tools.rate_meal('Ema', date.today().isoformat(), 'lunch', 4, 4))
    for result in results:
        assert result['status'] == 'MEAL_ACTIONS_UNAVAILABLE'
        assert 'Nothing was sent' in result['reason'] and 'EduPage itself' in result['next_step']
    assert all('/menu/' in call for call in web.calls)  # only page reads, never a POST


def test_meal_actions_without_a_canteen(serve):
    tools, edu = serve(b'<html></html>')
    edu.get_meals = lambda day: None
    assert tools.choose_meal('Ema', TOMORROW.isoformat(), 'lunch', 1)['status'] == 'MEALS_NOT_AVAILABLE'
