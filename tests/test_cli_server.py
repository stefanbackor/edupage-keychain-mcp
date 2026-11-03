# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import pathlib
import sys

import pytest

from conftest import FakeEdu, tools_for
from edupage_keyring_mcp import __version__, cli, config
from edupage_keyring_mcp.errors import EduPageError
from edupage_keyring_mcp.server import create_server

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRITE_TOOLS = {'send_message', 'choose_meal', 'sign_off_meal', 'rate_meal'}
LOCAL_TOOLS = {'sign_in'}  # acts on this computer only: opens a browser window
FORBIDDEN_PARAMETERS = {'password', 'passwd', 'cookie', 'cookies', 'session', 'session_id', 'token',
                        'url', 'link', 'headers', 'username', 'login'}


@pytest.mark.parametrize('name', ['EDUPAGE_PASSWORD', 'EDUPAGE_PWD', 'EDUPAGE_PHPSESSID', 'edupage_sid'])
def test_plaintext_settings_are_refused(name):
    with pytest.raises(EduPageError, match='^PLAINTEXT_SECRET_REFUSED$'):
        config.refuse_plaintext_secrets({name: 'x'})
    config.refuse_plaintext_secrets({'EDUPAGE_USERNAME': 'a', 'EDUPAGE_NOTHING': '', 'PATH': '/bin'})


def test_school_arguments():
    env = {'EDUPAGE_USERNAME': 'p@example.invalid'}
    assert config.parse_schools(['a', 'b=q@example.invalid'], environ=env) == [
        ('a', 'p@example.invalid'), ('b', 'q@example.invalid')]
    for values, code in [(['a', 'a'], 'DUPLICATE_SCHOOL'), ([], 'SCHOOL_REQUIRED'), (['x.com'], 'INVALID_SCHOOL')]:
        with pytest.raises(EduPageError, match=f'^{code}$'):
            config.parse_schools(values, environ=env)
    with pytest.raises(EduPageError, match='^USERNAME_MISSING$'):
        config.parse_schools(['a'], environ={})


def test_cli_stops_early_without_a_safe_environment(monkeypatch, capsys):
    monkeypatch.setenv('EDUPAGE_PASSWORD', 'x')
    assert cli.main(['status', '--school', 'a']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'PLAINTEXT_SECRET_REFUSED'
    monkeypatch.delenv('EDUPAGE_PASSWORD')
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert cli.main(['--school', 'a']) == 1  # bare options run the server
    assert capsys.readouterr().err.strip() == 'MACOS_REQUIRED'


def test_probe_output_has_no_school_content():
    rows = cli.run_probe(tools_for(('demo-school', FakeEdu())))
    dumped = json.dumps(rows, ensure_ascii=False)
    for private in ('Matematika', 'Šimon', 'Ema', 'Hana', 'Vzor'):
        assert private not in dumped
    assert all(set(row) <= {'tool', 'status', 'count', 'error_type', 'school', 'child'} for row in rows)


def test_every_tool_is_safe_to_expose():
    server = create_server(tools_for(('demo-school', FakeEdu())))
    listed = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert len(listed) == 36
    assert not [n for n in listed if 'login' in n or 'request' in n or 'session' in n]
    for name, tool in listed.items():
        assert not FORBIDDEN_PARAMETERS & set(tool.input_schema.get('properties', {})), name
        assert tool.output_schema, name
        writes = name in WRITE_TOOLS
        assert bool(tool.annotations.destructive_hint) is writes, name
        assert bool(tool.annotations.read_only_hint) is not (writes or name in LOCAL_TOOLS), name
    assert set(listed['sign_in'].input_schema['properties']) == {'school'}


def test_tools_answer_over_mcp():
    server = create_server(tools_for(('demo-school', FakeEdu())))
    children = asyncio.run(server.call_tool('list_children', {})).structured_content
    assert children['status'] == 'READY' and len(children['children']) == 2
    stranger = asyncio.run(server.call_tool('school_year', {'school': 'elsewhere'})).structured_content
    assert stranger['status'] == 'UNKNOWN_SCHOOL'


def test_release_metadata_agrees():
    tomllib = pytest.importorskip('tomllib')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    manifest = json.loads((ROOT / 'server.json').read_text())
    assert project['version'] == __version__ == manifest['version'] == manifest['packages'][0]['version']
    assert manifest['packages'][0]['identifier'] == project['name']
    assert f"mcp-name: {manifest['name']}" in (ROOT / 'README.md').read_text()
    assert len(manifest['description']) <= 100


def test_every_source_file_carries_the_license_tag():
    for path in [*ROOT.glob('src/**/*.py'), *ROOT.glob('tests/*.py')]:
        assert path.read_text().startswith('# SPDX-License-Identifier: GPL-3.0-or-later'), path
