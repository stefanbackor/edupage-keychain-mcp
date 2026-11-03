# SPDX-License-Identifier: GPL-3.0-or-later
import base64
import json

from conftest import HOST, FakeEdu, event, reply, tools_for

FILE_PATH = '/elearning/ruqjzfpv'


def inbox():
    edu = FakeEdu()
    edu.events = [
        event(1, 'sprava', '9.Z · Trieda', 'Trip on Friday',
              {'receipt': '1', 'attachements': {FILE_PATH + '?f=1': 'trip.pdf',
                                                'https://example.com/x.pdf': 'outside.pdf',
                                                'http://cloud-1.edupage.org/y.pdf': 'plain-http.pdf'}}),
        event(2, 'sprava', '1.Y · Trieda', 'Party moved', {'receipt': '0'}),
        event(3, 'homework', '9.Z · Fyzika', 'not a message'),
    ]
    return tools_for(('demo-school', edu))


def test_listing_then_reading():
    tools = inbox()
    listing = tools.list_messages()
    assert [(m['id'], m['for_children'], m['files'], m['wants_receipt']) for m in listing['messages']] == [
        ('2', ['Ema'], 0, False), ('1', ['Šimon'], 1, True)]
    assert 'ruqjzfpv' not in json.dumps(listing)  # the model never sees file URLs
    letter = tools.get_message('1')
    assert letter['text'] == 'Trip on Friday' and letter['untrusted_content'] is True
    assert letter['files'] == [{'file': '1.1', 'name': 'trip.pdf'}]
    assert tools.get_message('3')['status'] == 'MESSAGE_NOT_LISTED'


def test_child_listing_does_not_forget_earlier_listings():
    tools = inbox()
    tools.list_messages()
    assert [m['id'] for m in tools.list_messages(child='Ema')['messages']] == ['2']
    assert tools.get_message('1')['status'] == 'READY'


def test_attachment_download_rules(web):
    tools = inbox()
    tools.list_messages()
    url = f'https://{HOST}{FILE_PATH}'
    assert tools.get_attachment('1', '1.2')['status'] == 'FILE_NOT_LISTED'
    web.routes[url] = lambda r: reply(r, 200, b'%PDF-1.7 demo')
    pdf = tools.get_attachment('1', '1.1')
    assert pdf['status'] == 'READY' and pdf['content_type'] == 'application/pdf' and pdf['name'] == 'trip.pdf'
    assert base64.b64decode(pdf['data_base64']) == b'%PDF-1.7 demo' and pdf['size'] == 13
    web.routes[url] = lambda r: reply(r, 200, b'<html>login</html>')
    assert tools.get_attachment('1', '1.1')['status'] == 'FILE_TYPE_NOT_ALLOWED'
    web.routes[url] = lambda r: reply(r, 302, headers={'Location': 'https://cloud-2.edupage.org/f.pdf'})
    web.routes['https://cloud-2.edupage.org/'] = lambda r: reply(r, 200, b'%PDF-1.4')
    assert tools.get_attachment('1', '1.1')['status'] == 'REDIRECT_NOT_ALLOWED'
    tools.download_hosts = frozenset({'cloud-2.edupage.org'})
    assert tools.get_attachment('1', '1.1')['status'] == 'READY'
    web.routes[url] = lambda r: reply(r, 200, b'%PDF' + b'0' * (3 * 1024 * 1024))
    assert tools.get_attachment('1', '1.1')['status'] == 'FILE_TOO_LARGE'
    assert all('example.com' not in call for call in web.calls)
