# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from conftest import HOST, reply
from edupage_keychain_mcp.errors import EduPageError
from edupage_keychain_mcp.net import SchoolHttp, is_edupage_host, school_host


@pytest.mark.parametrize('school', ['demo', 'zs-demo', 'a1'])
def test_school_names_become_edupage_hosts(school):
    assert school_host(school) == f'{school}.edupage.org'


@pytest.mark.parametrize('school', ['', 'Demo', 'evil.com', '-x', 'x-', 'a/b', 'login1', 'portal', 'a' * 64])
def test_bad_school_names_are_refused(school):
    with pytest.raises(EduPageError, match='^INVALID_SCHOOL$'):
        school_host(school)


def test_edupage_host_check():
    assert is_edupage_host('cloud-4.edupage.org')
    for host in ['edupage.org', 'edupage.org.evil.com', 'x.edupage.org.', 'x.edupage.com', '']:
        assert not is_edupage_host(host)
    with pytest.raises(EduPageError, match='^HOST_NOT_ALLOWED$'):
        SchoolHttp({'example.com'})


@pytest.mark.parametrize('url', [
    'https://example.com/', f'http://{HOST}/user/', f'https://{HOST}:8443/', f'https://u:p@{HOST}/',
    'https://other.edupage.org/', f'https://{HOST}.example.com/',
])
def test_only_allowed_origins_are_contacted(web, url):
    with pytest.raises(EduPageError, match='^HOST_NOT_ALLOWED$'):
        SchoolHttp({HOST}).get(url)
    assert web.calls == []


def test_redirects_are_checked_hop_by_hop(web):
    web.routes[f'https://{HOST}/a'] = lambda r: reply(r, 302, headers={'Location': '/b'})
    web.routes[f'https://{HOST}/b'] = lambda r: reply(r, 302, headers={'Location': 'https://example.com/'})
    with pytest.raises(EduPageError, match='^HOST_NOT_ALLOWED$'):
        SchoolHttp({HOST}).get(f'https://{HOST}/a')
    assert web.calls == [f'https://{HOST}/a', f'https://{HOST}/b']


def test_body_budget_covers_final_and_redirect_responses(web):
    web.routes[f'https://{HOST}/big'] = lambda r: reply(r, 200, b'x' * 5000)
    web.routes[f'https://{HOST}/hop'] = lambda r: reply(r, 301, b'y' * 5000, {'Location': '/small'})
    web.routes[f'https://{HOST}/small'] = lambda r: reply(r, 200, b'ok')
    for path in ('/big', '/hop'):
        with pytest.raises(EduPageError, match='^RESPONSE_LIMIT$'):
            SchoolHttp({HOST}, budget=1000).get(f'https://{HOST}{path}')
    assert SchoolHttp({HOST}, budget=5000).get(f'https://{HOST}/big').content == b'x' * 5000
    assert SchoolHttp({HOST}).get(f'https://{HOST}/hop').content == b'ok'


def test_environment_is_ignored(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.invalid:9')
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', '/nonexistent')
    assert SchoolHttp({HOST}).trust_env is False
