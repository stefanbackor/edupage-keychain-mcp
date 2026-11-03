# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP access for edupage-api, limited to an explicit set of EduPage hosts.

`edupage-api` creates its own URLs on an ordinary `requests.Session`. We hand
it a `SchoolHttp` instead. Every outgoing request, and every redirect that
`requests` follows, is matched against a fixed set of allowed origins, and no
response body may grow past a byte budget.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from .errors import EduPageError

CONNECT_TIMEOUT, READ_TIMEOUT = 8, 30
BODY_BUDGET = 8 * 1024 * 1024
SUBDOMAIN = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
RESERVED_SUBDOMAINS = frozenset({'www', 'login1', 'portal', 'help', 'cloud'})


def school_host(school: str) -> str:
    """`zsabc` → `zsabc.edupage.org`, refusing anything that is not a plain subdomain."""
    if (not isinstance(school, str) or len(school) > 63 or not SUBDOMAIN.match(school)
            or school in RESERVED_SUBDOMAINS):
        raise EduPageError('INVALID_SCHOOL')
    return f'{school}.edupage.org'


def is_edupage_host(host: str) -> bool:
    labels = (host or '').split('.')
    return (len(labels) >= 3 and labels[-2:] == ['edupage', 'org']
            and all(SUBDOMAIN.match(label) for label in labels[:-2]))


class _BudgetAdapter(HTTPAdapter):
    """Transport that refuses bodies over a byte budget.

    `requests` calls the transport separately for each redirect hop and only
    afterwards inspects the body, so the budget also covers 3xx responses.
    """

    def __init__(self, budget: int) -> None:
        super().__init__(max_retries=0)
        self.budget = budget

    def send(self, request, stream=False, **kwargs):  # noqa: D401 - requests API
        response = super().send(request, stream=True, **kwargs)
        try:
            body = response.raw.read(self.budget + 1, decode_content=True) or b''
            if len(body) > self.budget or response.raw.read(1, decode_content=True):
                raise EduPageError('RESPONSE_LIMIT')
        finally:
            response.close()
        response._content = body
        response._content_consumed = True
        return response


class SchoolHttp(requests.Session):
    """A session that only speaks HTTPS to the given EduPage hosts."""

    def __init__(self, hosts: set[str], *, budget: int = BODY_BUDGET) -> None:
        super().__init__()
        if not hosts or not all(is_edupage_host(h) for h in hosts):
            raise EduPageError('HOST_NOT_ALLOWED')
        # Exact network locations: a port or user:password@ never equals a bare host.
        self.origins = frozenset(hosts)
        self.trust_env = False  # ignore proxy variables, .netrc and CA bundle overrides
        self.max_redirects = 5
        self.adapters.clear()
        self.mount('https://', _BudgetAdapter(budget))

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return self.origins

    def permits(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.scheme == 'https' and parts.netloc in self.origins

    def send(self, request, **kwargs):  # noqa: D401 - requests API
        if not self.permits(request.url):
            raise EduPageError('HOST_NOT_ALLOWED')
        if not kwargs.get('timeout'):
            kwargs['timeout'] = (CONNECT_TIMEOUT, READ_TIMEOUT)
        return super().send(request, **kwargs)
