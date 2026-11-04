# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed status codes. Only these, never server text, cross the tool boundary."""
from __future__ import annotations

import errno as errno_names
import sys
import traceback
from typing import Any

# The Saved Session itself no longer works; retrying will not help.
SESSION_FAILURES = frozenset({'AUTH_REQUIRED', 'ACCOUNT_MISMATCH', 'SESSION_EXPIRED'})


class EduPageError(Exception):
    """A failure identified by a fixed, public status code."""

    def __init__(self, code: str, **extra: Any) -> None:
        super().__init__(code)
        self.code = code
        self.extra = extra


def log_unexpected(exc: BaseException, code: str) -> None:
    """Write where an unexpected exception came from to stderr (the MCP client's server log).

    Only the class, the stack frames and, for OSError, the errno are written: the
    exception's message may hold EduPage page text, so it never leaves the process.
    """
    lines = [f'edupage-keyring-mcp: {code} from {type(exc).__name__}']
    if isinstance(exc, OSError) and exc.errno is not None:
        name = errno_names.errorcode.get(exc.errno, '?')
        lines[0] += f' (errno {exc.errno} {name})'
    lines += [f'  {frame.filename}:{frame.lineno} in {frame.name}'
              for frame in traceback.extract_tb(exc.__traceback__)]
    try:
        print('\n'.join(lines), file=sys.stderr, flush=True)
    except Exception:
        pass
