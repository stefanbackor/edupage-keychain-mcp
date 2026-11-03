# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain-data views of edupage-api objects, and argument validation."""
from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any

from .client import _fold
from .errors import EduPageError

MAX_TIMELINE_DAYS = 90
MAX_LIST_ITEMS = 1000
MAX_TEXT = 4000


# ---------------------------------------------------------------------------
# Serialization: library objects never reach the model as-is.
# ---------------------------------------------------------------------------
def plain(value: Any, depth: int = 0) -> Any:
    """Convert library dataclasses and values to JSON-safe data."""
    if depth > 6:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, Enum):
        return plain(value.value, depth + 1)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k)[:100]: plain(v, depth + 1) for k, v in list(value.items())[:200]}
    if isinstance(value, (list, tuple, set)):
        return [plain(v, depth + 1) for v in list(value)[:MAX_LIST_ITEMS]]
    if is_dataclass(value):
        out = {f.name: plain(getattr(value, f.name, None), depth + 1)
               for f in fields(value) if not f.name.startswith('_')}
        for key, item in vars(value).items():  # e.g. EduStudent.class_id set in __init__
            if not key.startswith('_') and key not in out:
                out[key] = plain(item, depth + 1)
        return out
    return None


def _name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:200]
    return getattr(value, 'name', None)


def lesson_data(lesson: Any) -> dict:
    subject = getattr(lesson, 'subject', None)
    return {
        'period': lesson.period,
        'start': lesson.start_time.isoformat(timespec='minutes') if lesson.start_time else None,
        'end': lesson.end_time.isoformat(timespec='minutes') if lesson.end_time else None,
        'subject': getattr(subject, 'name', None),
        'subject_short': getattr(subject, 'short', None),
        'teachers': [_name(t) for t in lesson.teachers or []],
        'classrooms': [_name(c) for c in lesson.classrooms or []],
        'classes': [_name(c) for c in lesson.classes or []],
        'groups': list(lesson.groups or []),
        'topic': plain(lesson.curriculum),
        'cancelled': bool(lesson.is_cancelled),
        'event': bool(lesson.is_event),
        'online_lesson_link': plain(lesson.online_lesson_link),
    }


def event_data(event: Any) -> dict:
    details = event.additional_data if isinstance(event.additional_data, dict) else {}
    text = event.text or details.get('nazov') or ''
    scalar = {k: plain(v) for k, v in details.items()
              if isinstance(v, (str, int, float, bool)) and k not in ('messageContent',)}
    return {
        'id': event.event_id,
        'type': plain(event.event_type) if event.event_type is not None else None,
        'timestamp': plain(event.timestamp),
        'event_time': plain(event.event_time),
        'text': plain(text),
        'author': _name(event.author),
        'recipient': _name(event.recipient),
        'done': bool(event.is_done),
        'removed': bool(event.is_removed),
        'details': dict(list(scalar.items())[:40]),
    }


def recipient_matches(row: dict, child: dict) -> bool:
    """True if a timeline item is addressed to this child by name or class.

    EduPage recipients look like 'Ema Nováková', '7.X · Matematika',
    'Rodičia 7.X' or '*'. Class names must match as a whole token, so '7.X'
    does not match '7.XY'.
    """
    recipient = _fold(row.get('recipient') or '')
    if not recipient or recipient == '*':
        return False
    name = _fold(child.get('name') or '')
    if name and not name.startswith('child ') and name in recipient:
        return True
    klass = _fold(child.get('class') or '')
    if klass:
        return re.search(r'(^|[\s·(,])' + re.escape(klass) + r'($|[\s·),])', recipient) is not None
    return False


def grade_data(grade: Any) -> dict:
    return {
        'date': plain(grade.date), 'subject': grade.subject_name, 'title': plain(grade.title),
        'grade': plain(grade.grade_n), 'comment': plain(grade.comment),
        'max_points': grade.max_points, 'percent': grade.percent, 'weight': grade.importance,
        'verbal': bool(grade.verbal), 'class_average': grade.class_grade_avg,
        'teacher': _name(grade.teacher),
    }


def missing_teacher_names(page: Any) -> list[str]:
    """Teacher names from the substitution page header, as edupage-api reads them."""
    if not isinstance(page, str) or '<span class="print-font-resizable">' not in page:
        return []
    header = page.split('<span class="print-font-resizable">', 1)[1].split('</span>', 1)[0]
    _, _, listed = header.partition(': ')
    names = []
    for part in listed.split(', '):
        for name in part.strip().split('  (')[0].split(' + '):
            name = re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', name)).strip()
            if name and name not in names:
                names.append(name[:200])
    return names


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tolerant_grades(userhome: dict, data: Any) -> tuple[list[dict], int]:
    """Read EduPage's grade viewer JSON one row at a time, skipping broken rows.

    Mirrors edupage-api's `Grades.get_grades` field mapping.
    """
    if not isinstance(data, dict):
        raise EduPageError('SCHEMA_CHANGED')
    dbi = userhome.get('dbi') if isinstance(userhome.get('dbi'), dict) else {}
    subjects = dbi.get('subjects') if isinstance(dbi.get('subjects'), dict) else {}
    teachers = dbi.get('teachers') if isinstance(dbi.get('teachers'), dict) else {}
    events = data.get('vsetkyUdalosti')
    events = events.get('edupage') if isinstance(events, dict) else None
    events = events if isinstance(events, dict) else {}
    rows, skipped = [], 0
    for grade in data.get('vsetkyZnamky') or []:
        try:
            details = events.get(str(grade.get('udalostid'))) or {}
            subject_id = details.get('PredmetID') or grade.get('predmetid')
            if subject_id in (None, '', 'vsetky'):
                skipped += 1
                continue
            subject = subjects.get(str(subject_id)) or {}
            teacher = teachers.get(str(details.get('UcitelID') or grade.get('ucitelid') or '')) or {}
            value, _, rest = str(grade.get('data') or '').partition(' (')
            kind, weight = str(details.get('p_typ_udalosti')), _number(details.get('p_vaha'))
            max_points = (weight if kind == '2' else _number(details.get('p_vaha_body')) if kind == '3' else None)
            numeric = _number(value)
            rows.append({
                'date': grade.get('datum'), 'subject': subject.get('name'),
                'title': plain(details.get('p_meno')),
                'grade': numeric if numeric is not None else plain(value),
                'comment': plain(rest.rsplit(')', 1)[0]) if rest else None,
                'max_points': max_points,
                'percent': round(numeric / max_points * 100, 2) if numeric is not None and max_points else None,
                'weight': weight / 20 if weight is not None and kind != '2' else None,
                'verbal': numeric is None, 'class_average': _number(details.get('priemer')),
                'teacher': ' '.join(filter(None, [teacher.get('firstname'), teacher.get('lastname')])) or None,
            })
        except (AttributeError, KeyError, TypeError, ValueError):
            skipped += 1
    return rows, skipped


def meal_data(meal: Any) -> dict | None:
    if meal is None:
        return None
    menus = []
    for menu in meal.menus or []:
        rating = menu.rating
        menus.append({
            'number': plain(menu.number), 'name': plain(menu.name),
            'allergens': plain(menu.allergens), 'weight': plain(menu.weight),
            'rated': rating is not None,
        })
    return {
        'title': plain(meal.title), 'served_from': plain(getattr(meal.served_from, 'time', lambda: None)()),
        'served_to': plain(getattr(meal.served_to, 'time', lambda: None)()),
        'ordered_menu': plain(meal.ordered_meal), 'choosable_menus': plain(meal.chooseable_menus),
        'can_be_changed_until': plain(meal.can_be_changed_until), 'menus': menus,
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def parse_day(value: str, *, back: int = 400, ahead: int = 400) -> date:
    if not value:
        return date.today()
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise EduPageError('INVALID_DATE') from None
    if not -back <= (day - date.today()).days <= ahead:
        raise EduPageError('DATE_OUT_OF_RANGE')
    return day


def parse_since(value: str) -> date:
    if not value:
        return date.today() - timedelta(days=30)
    day = parse_day(value, back=MAX_TIMELINE_DAYS, ahead=0)
    return day


