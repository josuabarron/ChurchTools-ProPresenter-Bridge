import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Client, BridgeError, note_on, resolve_position, notes
from server import Server


class Semantics(unittest.TestCase):
    def setUp(self):
        self.items = [dict(title='Begrüßung'), dict(title='Song', duration=0, song={}),
                      dict(title='Predigt', duration=1200)]

    def test_midi_filters(self):
        self.assertEqual(note_on(0x643C90), 60)
        for packed in [0x003C90, 0x643C80, 0x643C91, 0x643CB0, 0x64FF90]:
            self.assertIsNone(note_on(packed))
        self.assertEqual(note_on(0x643C91, 2), 60)

    def test_advance_and_boundaries(self):
        self.assertEqual(resolve_position('vor', 0, self.items), 1)
        self.assertEqual(resolve_position('vor', 1, self.items), 3)
        self.assertEqual(resolve_position('vor', 3, self.items), 4)
        self.assertEqual(resolve_position('vor', 4, self.items), 4)
        self.assertEqual(resolve_position('zurück', 0, self.items), 0)
        self.assertEqual(resolve_position('zurück', 3, self.items), 2)
        self.assertEqual(resolve_position('vor', 0, []), 1)

    def test_direct_titles(self):
        self.assertEqual(resolve_position('  BEGRUSSUNG ', 0, self.items), 1)
        self.assertEqual(resolve_position('2', 0, self.items), 2)
        self.assertEqual(resolve_position('0', 2, self.items), 0)
        for value in ['missing', '-1', '5']:
            with self.assertRaises(BridgeError):
                resolve_position(value, 0, self.items)
        self.assertEqual(notes(dict(note=' ', comments=' hello ')), 'hello')


class Protocol(unittest.TestCase):
    def setUp(self):
        self.config = dict(api='https://example.invalid/api', user='42', days=14, filter='', locked=True)
        self.client = Client(self.config, 'SECRET')
        self.agenda = dict(id=7, items=[dict(type='header', title='Header'), dict(title='Hello')])

    def test_execute_legacy_payload(self):
        calls = []
        def request(path, form=None):
            calls.append((path, form))
            if path.endswith('/agenda'):
                return dict(data=self.agenda)
            return dict(data=dict(pos_id='0'), status='success')
        self.client.request = request
        self.client.execute(99, 'Hello')
        self.assertEqual(calls[-1][1], dict(func='saveAgendaLivePosition', event_id=99, pos_id=1, addseconds=0))
        self.assertEqual(calls[-2][1]['agenda_id'], 7)

    def test_empty_and_stale_snapshot(self):
        self.client.agendas[1] = dict(id=7, items=[])
        self.client.position = lambda *args: 0
        self.assertEqual(self.client.snapshot(1), dict(current='', next='', notes=''))
        cached = self.client.cache[1][1]
        self.client.cache[1] = (0, cached)
        def fail(*args):
            raise BridgeError('offline')
        self.client.position = fail
        self.assertEqual(self.client.snapshot(1), cached)

    def test_snapshot_requests_coalesce(self):
        self.client.agendas[1] = self.agenda
        calls = []
        def position(*args):
            calls.append(1)
            time.sleep(0.02)
            return 1
        self.client.position = position
        threads = [threading.Thread(target=self.client.snapshot, args=(1,)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(calls), 1)

    def test_backoff_and_error_redaction(self):
        error = urllib.error.HTTPError('https://example.invalid/SECRET', 429, 'SECRET', {'Retry-After': '120'}, None)
        with patch.object(self.client.opener, 'open', side_effect=error) as opened:
            for _ in range(2):
                with self.assertRaises(BridgeError) as caught:
                    self.client.request('/whoami')
                self.assertNotIn('SECRET', str(caught.exception))
            self.assertEqual(opened.call_count, 1)
        self.assertGreater(self.client.backoff_until, time.monotonic() + 110)

    def test_api_authorization_and_legacy_form_encoding(self):
        import io
        requests = []
        def open_request(request, timeout):
            requests.append(request)
            return io.BytesIO(b'{"status":"success","data":"csrf"}')
        with patch.object(self.client.opener, 'open', side_effect=open_request):
            self.client.request('', dict(func='saveAgendaLivePosition', event_id=1, pos_id=2, addseconds=0))
        self.assertEqual(requests[0].full_url, 'https://example.invalid/api/csrftoken')
        self.assertEqual(requests[1].full_url, 'https://example.invalid/index.php?q=churchservice/ajax')
        self.assertEqual(requests[1].get_header('Authorization'), 'Login SECRET')
        self.assertEqual(requests[1].get_header('Csrf-token'), 'csrf')
        self.assertIn(b'pos_id=2', requests[1].data)

    def test_event_selection_filters_and_day(self):
        events = [dict(id=1, name='Canceled', isCanceled=True, startDate='2026-09-13T10:00:00Z'),
                  dict(id=2, name='Open', startDate='2026-09-13T11:00:00Z'),
                  dict(id=3, name='Locked', startDate='2026-09-14T10:00:00Z'),
                  dict(id=4, name='Second', startDate='2026-09-14T11:00:00Z'),
                  dict(id=5, name='Later', startDate='2026-09-15T10:00:00Z')]
        self.client.request = lambda *args: dict(data=events)
        self.client.agenda = lambda event_id: dict(isLocked=event_id != 2)
        self.assertEqual([e['id'] for e in self.client.events()], [3, 4])


class Http(unittest.TestCase):
    def test_loopback_routes_and_no_cache(self):
        class FakeClient:
            def snapshot(self, event):
                return dict(current='<script>not HTML</script>', next='Next', notes='hello')
            def live_url(self, event):
                return 'https://example.invalid/?login_token=SECRET'
        server = Server(0, lambda: (FakeClient(), 1, 72))
        try:
            self.assertEqual(server.http.server_address[0], '127.0.0.1')
            base = 'http://127.0.0.1:' + str(server.http.server_address[1])
            with urllib.request.urlopen(base + '/live/data.json') as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(json.load(response)['notesFontSize'], 72)
            with urllib.request.urlopen(base + '/live/strip') as response:
                html = response.read().decode()
                self.assertIn('textContent', html)
                self.assertNotIn('SECRET', html)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + '/missing')
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.close()


@unittest.skipUnless(os.name == 'nt', 'Windows native API required')
class WindowsNative(unittest.TestCase):
    def test_dpapi_roundtrip(self):
        from native import protect
        secret = 'test-token-ä'.encode()
        encrypted = protect(secret)
        self.assertNotIn(secret, encrypted)
        self.assertEqual(protect(encrypted, decrypt=True), secret)

    def test_midi_enumeration(self):
        from native import Midi
        midi = Midi()
        self.assertIsInstance(midi.devices(), list)
        midi.close()


if __name__ == '__main__':
    unittest.main()
