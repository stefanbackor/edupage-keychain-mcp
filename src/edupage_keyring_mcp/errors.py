# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed status codes. Only these, never server text, cross the tool boundary."""
from __future__ import annotations

from typing import Any


class EduPageError(Exception):
    """A failure identified by a fixed, public status code."""

    def __init__(self, code: str, **extra: Any) -> None:
        super().__init__(code)
        self.code = code
        self.extra = extra
