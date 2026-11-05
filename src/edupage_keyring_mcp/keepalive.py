# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep-alive: load `/user/` now and then so EduPage doesn't end an idle session.

EduPage signs a session out after about 110-180 minutes without requests. While
the server runs, this loads each open school's home page once per interval (every
DEFAULT_MINUTES unless `--keep-alive` says otherwise; 0 turns it off). It
never opens a session that isn't open yet, so it never reads the Credential Store
and never starts a sign-in.
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, Iterable

from .client import SchoolSession, fetch_userhome
from .errors import SESSION_FAILURES, EduPageError

# EduPage's idle timeout can be as short as about 110 minutes.
MIN_MINUTES, MAX_MINUTES = 5, 120
# On by default: an overnight run at this interval kept a session alive for 19 hours.
DEFAULT_MINUTES = 60


def keep_alive_minutes(value: str | None) -> int:
    """The `--keep-alive` value as whole minutes; DEFAULT_MINUTES when empty, 0 for off.

    Raises:
        EduPageError: INVALID_KEEP_ALIVE unless it is 0 or MIN_MINUTES..MAX_MINUTES.
    """
    text = (value or '').strip()
    if not text:
        return DEFAULT_MINUTES
    whole, _, fraction = text.partition('.')  # the .mcpb number field may arrive as "60.0"
    if not whole.isdigit() or fraction.strip('0'):
        raise EduPageError('INVALID_KEEP_ALIVE', minimum=MIN_MINUTES, maximum=MAX_MINUTES)
    minutes = int(whole)
    if minutes and not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise EduPageError('INVALID_KEEP_ALIVE', minimum=MIN_MINUTES, maximum=MAX_MINUTES)
    return minutes


class KeepAlive:
    """Pings every already connected school once per `minutes`."""

    def __init__(self, sessions: Iterable[SchoolSession], minutes: int, *,
                 wait: Callable[[float], bool] | None = None) -> None:
        self.sessions = list(sessions)
        self.seconds = minutes * 60
        self._stopped = threading.Event()
        self._wait = wait or self._stopped.wait  # returns True to stop

    def tick(self) -> None:
        for session in self.sessions:
            with session.lock:
                if session.edu is None:
                    continue
                try:
                    fetch_userhome(session.edu, session.school)
                except EduPageError as exc:
                    code = exc.code
                except Exception:
                    code = 'LOCAL_ERROR'
                else:
                    continue
                if code in SESSION_FAILURES:
                    session.reset()  # pinged again only after a tool call connects it
            _log(session.school, code)

    def run(self) -> None:
        while not self._wait(self.seconds):
            self.tick()

    def start(self) -> threading.Thread:
        """Run in a daemon thread, so it never keeps the process alive on its own."""
        thread = threading.Thread(target=self.run, name='edupage-keep-alive', daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stopped.set()


def _log(school: str, code: str) -> None:
    """One stderr line (the MCP client's server log): the school and the code, nothing else."""
    try:
        print(f'edupage-keyring-mcp: keep-alive {school} {code}', file=sys.stderr, flush=True)
    except Exception:
        pass
