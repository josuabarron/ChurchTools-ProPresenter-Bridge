"""Tests für die Entschärfung von Meldungen.

Das Diagnose-Log lässt sich mit einem Knopf in die Zwischenablage kopieren.
Deshalb darf keine Meldung einen Token oder eine vollständige Adresse
enthalten – auch nicht mittelbar über einen fremden Fehlertext.
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

os.environ.setdefault('LOCALAPPDATA', os.path.join(tempfile.gettempdir(), 'ctp-tests'))

import app  # noqa: E402
import core  # noqa: E402


class Redact(unittest.TestCase):
    """Muster, die in echten Meldungen vorkommen."""

    def test_login_token_in_adresse(self):
        ergebnis = app.redact('https://ch.example/api?q=x&login_token=SECRET123&user_id=42')
        self.assertNotIn('SECRET123', ergebnis)
        self.assertNotIn('42', ergebnis)

    def test_token_allein_im_query(self):
        self.assertNotIn('SECRET123', app.redact('?token=SECRET123&x=1'))

    def test_authorization_kopfzeile(self):
        """'Authorization: Login TOKEN' – das nackte \\S+ würde nur 'Login' treffen."""
        for text in ('Authorization: Login SECRET123',
                     'Authorization: Login SECRET123, weiter',
                     'authorization: token SECRET123'):
            self.assertNotIn('SECRET123', app.redact(text), text)

    def test_bearer_token(self):
        self.assertNotIn('eyJhbGci', app.redact('Authorization: Bearer eyJhbGciOiJIUzI1NiJ9'))

    def test_login_zeile_ohne_kopfzeile(self):
        self.assertNotIn('SECRET1234567890AB', app.redact('Login SECRET1234567890ABCD'))

    def test_adresse_wird_entfernt(self):
        ergebnis = app.redact('Siehe https://ch.example/api?q=x')
        self.assertNotIn('ch.example', ergebnis)

    def test_kurze_login_werte_bleiben_lesbar(self):
        """Nur Token-artige Werte sind Zugangsdaten, keine gewöhnlichen Wörter."""
        for text in ('Login fehlgeschlagen', 'Login erforderlich',
                     'Login: siehe Hilfe', 'Login nicht möglich'):
            self.assertEqual(app.redact(text), text, text)

    def test_login_mit_token_artigem_wert(self):
        for text in ('Login SECRET1234567890ABCD',
                     'Login AbCdEf0123456789',
                     'Login ey0',
                     'Login AAAAAAAAAAAAAAAA'):
            self.assertNotIn('SECRET', app.redact(text), text)
            self.assertNotIn('AAAAAAAAAAAAAAAA', app.redact(text), text)
            self.assertNotIn('AbCdEf0123456789', app.redact(text), text)

    def test_normale_meldungen_bleiben_unveraendert(self):
        for text in ('ChurchTools HTTP 429', 'Bridge läuft',
                     'Gespeicherte Einstellungen konnten nicht geladen werden.',
                     'MIDI 60 · Befehl ausgeführt'):
            self.assertEqual(app.redact(text), text, text)


class Describe(unittest.TestCase):
    """Die Oberfläche bekommt nur Meldungen, die geprüft sind."""

    def test_bridgefehler_kommt_durch(self):
        fehler = core.BridgeError('ChurchTools HTTP 429')
        self.assertEqual(app.describe(fehler), 'ChurchTools HTTP 429')

    def test_bridgefehler_wird_entschaerft(self):
        fehler = core.BridgeError('Fehler bei https://ch.example?login_token=SECRET123')
        ergebnis = app.describe(fehler)
        self.assertNotIn('SECRET123', ergebnis)

    def test_fremder_fehler_zeigt_nur_die_art(self):
        ergebnis = app.describe(ValueError('https://ch.example?login_token=SECRET123'))
        self.assertEqual(ergebnis, 'ValueError: siehe Hilfe')
        self.assertNotIn('SECRET123', ergebnis)

    def test_fremder_fehler_ohne_meldung(self):
        self.assertEqual(app.describe(KeyError()), 'KeyError: siehe Hilfe')


class LogAusgabe(unittest.TestCase):
    """report() ist die einzige Stelle, die ins Log schreibt."""

    def test_report_entschaerft(self):
        von = MagicMock()
        fenster = MagicMock()
        fenster.status = von
        fenster.log = MagicMock()
        fenster.log_lines = 0          # report() vergleicht mit 300
        app.App.report(fenster, 'https://ch.example?login_token=SECRET123')
        geschrieben = fenster.log.insert.call_args[0][1]
        self.assertNotIn('SECRET123', geschrieben)

    def test_report_zeigt_entschaerft_im_status(self):
        """Der Zustandstext geht ins Infobereich-Symbol – also auch entschärfen."""
        fenster = MagicMock()
        fenster.log = MagicMock()
        fenster.log_lines = 0
        app.App.report(fenster, 'Login SECRET1234567890ABCD')
        self.assertNotIn('SECRET1234567890ABCD', fenster.status.set.call_args[0][0])


if __name__ == '__main__':
    unittest.main()