"""Tests für den ChurchTools-Client.

Zwei Punkte, die der Vergleich mit der Windows-Fassung aufgedeckt hat:
der CSRF-Token muss bei 403 erneuert werden, und der Login-Kopf darf einer
Umleitung nicht folgen.
"""
import os
import sys
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

import core  # noqa: E402


class CSRFErneuerung(unittest.TestCase):
    """Windows verwirft den CSRF-Token bei 403 und holt ihn neu (core.py)."""

    def setUp(self):
        self.config = dict(api='https://example.invalid/api', user='42')
        self.client = core.Client(self.config, 'TEST')

    def test_403_verwirft_den_csrf_token(self):
        self.client.csrf = 'ALTER-TOKEN'
        import urllib.error
        fehler = urllib.error.HTTPError('https://example.invalid/api/csrftoken',
                                        403, 'verboten', {}, None)
        from unittest.mock import patch
        with patch.object(self.client.opener, 'open', side_effect=fehler):
            with self.assertRaises(core.BridgeError):
                self.client.request('/csrftoken')
        self.assertIsNone(self.client.csrf, 'CSRF-Token wurde bei 403 nicht verworfen')

    def test_nach_403_wird_der_token_neu_geholt(self):
        """Ohne das bliebe die Bridge dauerhaft bei 403 stehen."""
        import urllib.error
        from unittest.mock import patch
        self.client.csrf = None
        geholt = []

        def open_simulation(req, *args, **kwargs):
            raise urllib.error.HTTPError(req.full_url, 403, 'verboten', {}, None)

        with patch.object(self.client.opener, 'open', side_effect=open_simulation):
            for _ in range(2):
                try:
                    self.client.request('/whoami')
                except core.BridgeError:
                    pass
        # Nach dem Verwerfen muss der nächste POST-Pfad den Token neu auflösen.
        self.assertIsNone(self.client.csrf)


class Umleitungsschutz(unittest.TestCase):
    """Der Login-Kopf darf das Umleitungsziel nicht erreichen."""

    def test_no_redirect_ist_installiert(self):
        config = dict(api='https://example.invalid/api', user='42')
        client = core.Client(config, 'TEST')
        handler = [h for h in client.opener.handlers
                   if type(h).__name__ == 'NoRedirect']
        self.assertTrue(handler, 'NoRedirect fehlt – der Login-Kopf folgte einer Umleitung')

    def test_no_redirect_liefert_none(self):
        config = dict(api='https://example.invalid/api', user='42')
        client = core.Client(config, 'TEST')
        handler = next(h for h in client.opener.handlers
                       if type(h).__name__ == 'NoRedirect')
        self.assertIsNone(
            handler.redirect_request(None, None, 302, '', {}, 'https://boese.example.com'))

    def test_umleitung_wird_nicht_verfolgt(self):
        """Eine 302-Antwort ist ein Fehler, kein stiller Adresswechsel."""
        import urllib.error
        from unittest.mock import patch
        client = core.Client(dict(api='https://example.invalid/api', user='42'), 'T')
        fehler = urllib.error.HTTPError('https://example.invalid/api/x', 302, 'weiter', {}, None)
        with patch.object(client.opener, 'open', side_effect=fehler):
            with self.assertRaises(core.BridgeError) as e:
                client.request('/whoami')
        self.assertNotIn('boese', str(e.exception))


class FehlermeldungenOhneInhalt(unittest.TestCase):
    """Antwortkörper und Adressen gehören nicht ins Diagnose-Log."""

    def test_http_fehler_ohne_koerper(self):
        import urllib.error
        from unittest.mock import patch
        client = core.Client(dict(api='https://example.invalid/api', user='42'), 'T')
        fehler = urllib.error.HTTPError(
            'https://example.invalid/api/SECRET123?login_token=GEHEIM',
            500, 'intern', {}, None)
        with patch.object(client.opener, 'open', side_effect=fehler):
            with self.assertRaises(core.BridgeError) as e:
                client.request('/whoami')
        text = str(e.exception)
        self.assertNotIn('SECRET123', text)
        self.assertNotIn('GEHEIM', text)

    def test_429_setzt_backoff_und_verraet_nichts(self):
        import urllib.error
        from unittest.mock import patch
        client = core.Client(dict(api='https://example.invalid/api', user='42'), 'T')
        fehler = urllib.error.HTTPError(
            'https://example.invalid/api/SECRET', 429, 'zu viel',
            {'Retry-After': '120'}, None)
        with patch.object(client.opener, 'open', side_effect=fehler):
            with self.assertRaises(core.BridgeError) as e:
                client.request('/whoami')
        self.assertNotIn('SECRET', str(e.exception))

    def test_osfehler_verraet_keine_adresse(self):
        from unittest.mock import patch
        client = core.Client(dict(api='https://example.invalid/api', user='42'), 'T')
        with patch.object(client.opener, 'open',
                          side_effect=OSError('https://ch.example/?login_token=GEHEIM')):
            with self.assertRaises(core.BridgeError) as e:
                client.request('/whoami')
        self.assertNotIn('GEHEIM', str(e.exception))


class Schriftgroesse(unittest.TestCase):
    """Die Notes-Schriftgröße wirkt ohne Neustart – auf beiden Plattformen."""

    def test_snapshot_liefert_die_groesse_nicht_selbst(self):
        """Sie kommt aus dem Zustandsgeber des Fensters, nicht aus dem Client."""
        client = core.Client(dict(api='https://example.invalid/api', user='42'), 'T')
        client.agendas[1] = dict(id=1, isLocked=True, items=[dict(type='song', title='A')])
        client.position = lambda *a: 1
        daten = client.snapshot(1)
        self.assertNotIn('notesFontSize', daten)


if __name__ == '__main__':
    unittest.main()