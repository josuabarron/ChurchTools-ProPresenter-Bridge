"""Tests für die Härtung des lokalen HTTP-Servers.

Der Server lauscht nur auf 127.0.0.1. Das ist Netzwerkisolation, aber KEINE
Zugriffskontrolle: jeder lokale Prozess und jede Webseite im selben Browser
erreicht den Port. Diese Tests halten fest, was der Server deshalb ablehnt.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault('LOCALAPPDATA', os.path.join(tempfile.gettempdir(), 'ctp-tests'))

import core  # noqa: E402
import server  # noqa: E402


class KeinUmleiten(urllib.request.HTTPRedirectHandler):
    """Der 302 soll geprüft werden, nicht verfolgt."""

    def redirect_request(self, *args, **kwargs):
        return None


class Basis(unittest.TestCase):
    def setUp(self):
        self.config = dict(api='https://example.invalid/api', user='42')
        self.client = core.Client(self.config, 'TEST-TOKEN')
        srv = server.Server(0, lambda: (self.client, 1, 64))
        self.addCleanup(srv.close)
        self.server = srv
        self.port = srv.http.server_address[1]

    def hole(self, pfad, kopf=None, methode='GET'):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{pfad}', method=methode)
        for name, wert in (kopf or {}).items():
            req.add_header(name, wert)
        opener = urllib.request.build_opener(KeinUmleiten())
        try:
            with opener.open(req, timeout=5) as antwort:
                return antwort.status, antwort.read().decode('utf-8', 'replace'), dict(antwort.headers)
        except urllib.error.HTTPError as fehler:
            return fehler.code, fehler.read().decode('utf-8', 'replace'), dict(fehler.headers)


class HostPruefung(Basis):
    def test_fremder_host_wird_abgelehnt(self):
        """Ohne diese Prüfung liest eine fremde Seite per DNS-Rebinding mit."""
        for pfad in ('/live/strip', '/live/data.json', '/help'):
            status, _, _ = self.hole(pfad, {'Host': 'boese.example.com'})
            self.assertEqual(status, 403, pfad)

    def test_eigener_host_kommt_durch(self):
        self.assertEqual(self.hole('/live/strip')[0], 200)
        self.assertEqual(self.hole('/live/strip', {'Host': 'localhost'})[0], 200)

    def test_host_mit_port_ist_erlaubt(self):
        self.assertEqual(self.hole('/live/strip', {'Host': f'127.0.0.1:{self.port}'})[0], 200)


class HerkunftPruefung(Basis):
    def test_fremde_herkunft_wird_abgelehnt(self):
        status, _, _ = self.hole('/live/data.json', {'Origin': 'https://boese.example.com'})
        self.assertEqual(status, 403)

    def test_null_herkunft_wird_abgelehnt(self):
        """Sandbox- und Datei-Herkunft senden Origin: null."""
        self.assertEqual(self.hole('/live/data.json', {'Origin': 'null'})[0], 403)

    def test_eigene_herkunft_kommt_durch(self):
        status, _, _ = self.hole('/live/data.json', {'Origin': f'http://127.0.0.1:{self.port}'})
        self.assertNotEqual(status, 403)

    def test_fehlende_herkunft_kommt_durch(self):
        """ProPresenter-Browser-Source und curl senden keinen Origin."""
        self.assertNotEqual(self.hole('/live/strip')[0], 403)


class SecFetchSite(Basis):
    def test_seitenuebergreifend_wird_abgelehnt(self):
        self.assertEqual(self.hole('/live/data.json', {'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_eigene_werte_kommen_durch(self):
        for wert in ('none', 'same-origin', 'same-site'):
            self.assertNotEqual(self.hole('/live/data.json', {'Sec-Fetch-Site': wert})[0], 403)


class Methoden(Basis):
    def test_nur_get(self):
        for methode in ('POST', 'PUT', 'DELETE', 'OPTIONS'):
            self.assertEqual(self.hole('/live/strip', methode=methode)[0], 405, methode)


class Sicherheitskoepfe(Basis):
    def test_alle_antworten_tragen_die_schutzkoepfe(self):
        for pfad in ('/live/strip', '/live/data.json', '/help', '/gibtsnicht'):
            _, _, kopf = self.hole(pfad)
            self.assertEqual(kopf.get('X-Frame-Options'), 'DENY', pfad)
            self.assertEqual(kopf.get('X-Content-Type-Options'), 'nosniff', pfad)
            self.assertEqual(kopf.get('Referrer-Policy'), 'no-referrer', pfad)
            self.assertEqual(kopf.get('Cache-Control'), 'no-store', pfad)


class Hilfe(Basis):
    def test_hilfe_wird_ausgeliefert(self):
        status, body, _ = self.hole('/help')
        self.assertEqual(status, 200)
        self.assertIn('ChurchTools', body)

    def test_hilfe_liegt_beim_start_bereit(self):
        """Der Inhalt steht beim Start bereit, nicht erst je Anfrage."""
        self.assertTrue(self.server.help_text)
        self.assertEqual(self.server.help_text, self.hole('/help')[1])

    def test_fehlende_hilfe_bricht_die_antwort_nicht(self):
        """Fehlt help.html, muss trotzdem geantwortet werden."""
        srv = server.Server(0, lambda: (None, None, 64))
        self.addCleanup(srv.close)
        self.assertTrue(srv.help_text)


class UnbekannterPfad(Basis):
    def test_unbekannter_pfad_ist_404(self):
        self.assertEqual(self.hole('/gibtsnicht')[0], 404)


class UmleitungMitToken(Basis):
    def test_live_leitet_mit_token_um(self):
        """/live ist für ProPresenter gedacht: der Token gehört in die Umlenkung.

        Absichtlich so. Die Prüfungen oben verhindern, dass eine fremde Seite
        die Umlenkung auslesen kann. Ein lokaler Prozess als derselbe Benutzer
        könnte den Token ohnehin aus token.dpapi lesen.
        """
        status, _, kopf = self.hole('/live')
        self.assertEqual(status, 302)
        ziel = kopf.get('Location', '')
        self.assertIn('churchservice%2Fliveview', ziel)
        self.assertIn('event_id=1', ziel)

    def test_ohne_event_ist_live_503(self):
        srv = server.Server(0, lambda: (self.client, None, 64))
        self.addCleanup(srv.close)
        req = urllib.request.Request(f'http://127.0.0.1:{srv.http.server_address[1]}/live')
        try:
            urllib.request.build_opener(KeinUmleiten()).open(req, timeout=5)
            self.fail('503 erwartet')
        except urllib.error.HTTPError as fehler:
            self.assertEqual(fehler.code, 503)


class Cachelogik(unittest.TestCase):
    """Der Cache darf die Ansichten nicht ausbremsen."""

    def setUp(self):
        self.config = dict(api='https://example.invalid/api', user='42')
        self.client = core.Client(self.config, 'T')
        self.client.agendas[1] = dict(id=1, isLocked=True, items=[
            dict(type='song', title='Eins'), dict(type='song', title='Zwei')])

    def test_acht_parallele_abrufe_loesen_einen_netzaufruf_aus(self):
        import time
        aufrufe = []

        def position(*args):
            aufrufe.append(1)
            time.sleep(0.02)
            return 1

        self.client.position = position
        threads = [threading.Thread(target=self.client.snapshot, args=(1,))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(aufrufe), 1)

    def test_cache_treffer_ohne_globale_sperre(self):
        """Ein MIDI-Klick hält die globale Sperre – der Cache muss trotzdem liefern."""
        self.client.cache[1] = (__import__('time').monotonic(), dict(current='Sofort'))
        self.client.lock.acquire()
        try:
            ergebnis = []
            t = threading.Thread(target=lambda: ergebnis.append(self.client.snapshot(1)))
            t.start()
            t.join(timeout=2)
            self.assertFalse(t.is_alive(), 'Snapshot wartete auf die globale Sperre')
            self.assertEqual(ergebnis[0], dict(current='Sofort'))
        finally:
            self.client.lock.release()

    def test_fehler_pause_verhindert_nachfragen(self):
        from unittest.mock import patch
        from core import BridgeError
        self.client.cache[1] = (__import__('time').monotonic(), dict(current='Alt'))
        with patch.object(self.client, 'position', side_effect=BridgeError('weg')) as p:
            self.client.snapshot(1)                  # erster Fehler: merkt vor
            vorher = p.call_count
            for _ in range(5):
                self.client.snapshot(1)              # jetzt ohne Nachfragen
            self.assertEqual(p.call_count, vorher)

    def test_nach_erfolg_ist_die_pause_weg(self):
        self.client.recent_failures[1] = 0
        self.client.position = lambda *a: 1
        self.assertEqual(self.client.snapshot(1), dict(current='Eins', next='Zwei', notes=''))
        self.assertNotIn(1, self.client.recent_failures)


class BerichtSchreiben(unittest.TestCase):
    """Berichte kommen vom Installer – der Pfad wird nicht blind geschrieben."""

    def test_bericht_wird_geschrieben(self):
        import app
        ziel = Path(tempfile.mkdtemp()) / 'bericht.txt'
        self.assertTrue(app.write_report(str(ziel), ['Zeile eins', 'Zeile zwei']))
        self.assertEqual(ziel.read_text(encoding='utf-8'), 'Zeile eins\nZeile zwei')

    def test_ohne_pfad_kein_fehler(self):
        import app
        self.assertFalse(app.write_report(None, ['Zeile']))

    def test_schreibfehler_wird_gemeldet(self):
        import app
        self.assertFalse(app.write_report(str(Path(tempfile.mkdtemp())), ['Zeile']))

    def test_verknuepfung_wird_nicht_verfolgt(self):
        """Ein Reparse-Point wäre der Weg, den erhöhten Schritt umzulenken."""
        import app
        echt = Path(tempfile.mkdtemp()) / 'echt.txt'
        echt.write_text('unberührt', encoding='utf-8')
        link = Path(tempfile.mkdtemp()) / 'link.txt'
        try:
            link.symlink_to(echt)
        except (OSError, NotImplementedError):
            self.skipTest('Verknüpfungen sind hier nicht erlaubt')
        self.assertFalse(app.write_report(str(link), ['Inhalt']))
        self.assertEqual(echt.read_text(encoding='utf-8'), 'unberührt')


if __name__ == '__main__':
    unittest.main()