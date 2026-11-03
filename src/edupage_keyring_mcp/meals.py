# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only access to the canteen page (`/menu/`).

edupage-api 0.13.3 can no longer read this page: the JSON block now ends in
`,\\n` instead of `,\\r\\n`, the boarder ID moved under `addInfo.strRow`, and
menus are listed under `menus` rather than labelled rows. This module reads
the page the way EduPage's own `strava_listok.js` does. It never orders,
cancels or rates meals. Switch back to `Edupage.get_meals` once a released
edupage-api reads the current page.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from .client import get_page
from .errors import EduPageError
from .net import school_host

MEAL_SLOTS = {'snack': '1', 'lunch': '2', 'afternoon_snack': '3'}  # EduPage's jedlo_dna
LETTERS = 'ABCDEFGH'
DATA_MARKER = 'edupageData:'
CANCELLED, SERVED = 'X', 'V'  # order states besides a menu letter


@dataclass
class Meal:
    """One meal slot of one day, as the canteen page lists it."""
    listing: dict

    @property
    def order_record(self) -> dict:
        return dict_or(self.listing.get('evidencia'))

    @property
    def state(self) -> Any:
        return self.order_record.get('stav')

    @property
    def ordered_menu(self) -> str | None:
        """The menu letter on order, or the one served; None when nothing is ordered."""
        menu = self.order_record.get('obj') if self.state == SERVED else self.state
        return menu if is_letter(menu) else None

    def menus(self) -> list[dict]:
        found = dict_or(self.listing.get('menus'))
        out = []
        for key in sorted(found, key=menu_number):
            menu, letter = dict_or(found[key]), letter_for(key)
            if letter:
                out.append({'menu': letter, 'name': clean_text(menu.get('nazovMenu')) or f'Menu {letter}',
                            'dishes': [dish_view(r) for r in menu.get('rows') or [] if isinstance(r, dict)]})
        return out

    def view(self) -> dict:
        choosable = dict_or(self.listing.get('choosableMenus'))
        return {
            'served_from': clean_text(self.listing.get('vydaj_od')) or None,
            'served_to': clean_text(self.listing.get('vydaj_do')) or None,
            'menus': self.menus(),
            'ordered_menu': self.ordered_menu,
            'cancelled': self.state == CANCELLED,
            'served': self.state == SERVED,
            'choosable_menus': sorted(filter(None, (letter_for(k) for k, on in choosable.items() if on))),
            'can_be_changed_until': clean_text(self.listing.get('zmen_do')) or None,
        }


def clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ''


def is_letter(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 1 and value in LETTERS


def menu_number(key: Any) -> int:
    try:
        return int(key)
    except (TypeError, ValueError):
        return 0


def dict_or(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def letter_for(key: Any) -> str:
    number = menu_number(key)
    return LETTERS[number - 1] if 1 <= number <= len(LETTERS) else ''


def dish_view(row: dict) -> dict:
    return {'name': clean_text(row.get('nazov')), 'allergens': clean_text(row.get('alergenyStr')) or None,
            'weight': clean_text(row.get('hmotnostiStr')) or None}


def day_listings(page: str, school: str) -> dict:
    """The per-day listing from a canteen page.

    Raises:
        EduPageError: MEALS_NOT_AVAILABLE when the page has no canteen data for
            this school, SCHEMA_CHANGED when the data is not readable.
    """
    at = page.find(DATA_MARKER)
    if at < 0:
        raise EduPageError('MEALS_NOT_AVAILABLE')
    try:
        data, _ = json.JSONDecoder().raw_decode(page[at + len(DATA_MARKER):].lstrip())
    except ValueError:
        raise EduPageError('SCHEMA_CHANGED') from None
    listings = dict_or(dict_or(dict_or(data).get(school)).get('novyListok'))
    if not listings:
        raise EduPageError('MEALS_NOT_AVAILABLE')
    return listings


def load_day(edu: Any, school: str, day: date) -> dict[str, Meal | None]:
    """Every meal slot for one day; a slot the canteen does not cook is None."""
    page = get_page(edu, f'https://{school_host(school)}/menu/?date={day:%Y%m%d}')
    slots = dict_or(day_listings(page, school).get(day.isoformat()))
    meals: dict[str, Meal | None] = {}
    for name, slot in MEAL_SLOTS.items():
        listing = slots.get(slot)
        cooked = isinstance(listing, dict) and listing.get('isCooking') is not False
        meals[name] = Meal(listing) if cooked else None
    return meals
