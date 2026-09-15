"""Tests für den Umgang mit erhöht gestartetem loopMIDI.

Hintergrund: der loopMIDI-Installer startet loopMIDI im Kontext des
Setup-Prozesses mit – also erhöht, wenn das Setup erhöht läuft. Ein erhöhter
Prozess lässt sich vom normalen Bridge-Prozess nicht beenden, und dann wird ein
neu eingetragener Port nie sichtbar. Diese Tests sichern die Erkennung und den
Ausweg ab.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import loopmidi


class Beendbarkeit(unittest.TestCase):
    """stoppable() erkennt einen erhöhten Prozess über die Antwort von taskkill."""

    def test_laeuft_nicht_ist_beendbar(self):
        with patch.object(loopmidi, 'running', return_value=False):
            self.assertTrue(loopmidi.stoppable())

    def test_zugriff_verweigert_bedeutet_nicht_beendbar(self):
        abweisend = MagicMock(returncode=1, stdout='',
                              stderr='FEHLER: Zugriff verweigert.')
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, '_run', side_effect=[
                    MagicMock(stdout='"loopMIDI.exe","58396","Console","1","22.492 K"'),
                    abweisend]):
            self.assertFalse(loopmidi.stoppable())

    def test_englische_meldung_wird_ebenfalls_erkannt(self):
        abweisend = MagicMock(returncode=1, stdout='ERROR: Access is denied.', stderr='')
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, '_run', side_effect=[
                    MagicMock(stdout='"loopMIDI.exe","1234","Console","1","20 K"'),
                    abweisend]):
            self.assertFalse(loopmidi.stoppable())

    def test_normaler_prozess_ist_beendbar(self):
        # taskkill ohne /F beendet nicht, meldet aber auch keinen Zugriffsfehler.
        antwort = MagicMock(returncode=0, stdout='', stderr='')
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, '_run', side_effect=[
                    MagicMock(stdout='"loopMIDI.exe","1234","Console","1","20 K"'),
                    antwort]):
            self.assertTrue(loopmidi.stoppable())

    def test_ohne_pid_gilt_als_beendbar(self):
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, '_run',
                             return_value=MagicMock(stdout='INFORMATION: keine Aufgaben')):
            self.assertTrue(loopmidi.stoppable())


class ErhoehtGestartetBleibtUnsichtbar(unittest.TestCase):
    """ensure_port darf bei erhöhtem loopMIDI nicht raten, sondern muss helfen."""

    def test_bricht_ab_wenn_erhoeht(self):
        with patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, 'stoppable', return_value=False), \
                patch.object(loopmidi, 'remember') as merken:
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertFalse(ok)
        self.assertIn('erhöhten Rechten', message)
        self.assertIn('Task-Manager', loopmidi.raised_fix_steps())
        merken.assert_not_called()

    def test_meldet_erhoeht_wenn_eintrag_da_aber_unsichtbar(self):
        with patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=['ChurchTools Bridge']), \
                patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, 'stoppable', return_value=True), \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')), \
                patch.object(loopmidi.time, 'sleep'), \
                patch.object(loopmidi.time, 'monotonic', side_effect=[0, 0, 1, 999]):
            ok, message = loopmidi.ensure_port('ChurchTools Bridge', wait=2)
        self.assertFalse(ok)
        self.assertTrue('erhöhten Rechten' in message or 'nicht sichtbar' in message)

    def test_normaler_ablauf_bleibt_erfolgreich(self):
        with patch.object(loopmidi, 'port_visible', side_effect=[False, True]), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=[]), \
                patch.object(loopmidi, 'running', return_value=False), \
                patch.object(loopmidi, 'remember', return_value=(True, 'eingetragen')), \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')):
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertTrue(ok)
        self.assertIn('verfügbar', message)


class ErhoehtesProgrammBeenden(unittest.TestCase):
    def test_beendet_erhoehten_prozess(self):
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')):
            ok, message = loopmidi.kill_elevated()
        self.assertTrue(ok)
        self.assertIn('beendet', message)

    def test_erhoeht_nicht_beendbar(self):
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, 'stop', return_value=(False, 'haengt')):
            ok, message = loopmidi.kill_elevated()
        self.assertFalse(ok)
        self.assertEqual(message, 'haengt')

    def test_laeuft_gar_nicht(self):
        with patch.object(loopmidi, 'running', return_value=False):
            ok, message = loopmidi.kill_elevated()
        self.assertTrue(ok)
        self.assertIn('läuft nicht', message)


class InstallerSchrittBeendetErhoehtes(unittest.TestCase):
    """ensure_midi_program() in app.py schließt das mitgestartete loopMIDI wieder."""

    def test_beendet_mitgestartetes_erhoehtes_programm(self):
        import app
        with patch.object(app.loopmidi, 'installed', return_value=False), \
                patch.object(app.loopmidi, 'install_via_winget', return_value=(True, 'installiert')), \
                patch.object(app.loopmidi, 'running', return_value=True), \
                patch.object(app.loopmidi, 'stoppable', return_value=False), \
                patch.object(app.loopmidi, 'kill_elevated', return_value=(True, 'beendet')) as toeten:
            code = app.ensure_midi_program()
        self.assertEqual(code, 0)
        toeten.assert_called_once()

    def test_beendet_normal_laufendes_programm(self):
        import app
        with patch.object(app.loopmidi, 'installed', return_value=True), \
                patch.object(app.loopmidi, 'running', return_value=True), \
                patch.object(app.loopmidi, 'stoppable', return_value=True), \
                patch.object(app.loopmidi, 'stop', return_value=(True, 'beendet')) as anhalten:
            code = app.ensure_midi_program()
        self.assertEqual(code, 0)
        anhalten.assert_called_once()

    def test_ruehrt_nicht_an_wenn_nichts_laeuft(self):
        import app
        with patch.object(app.loopmidi, 'installed', return_value=True), \
                patch.object(app.loopmidi, 'running', return_value=False), \
                patch.object(app.loopmidi, 'stop') as anhalten, \
                patch.object(app.loopmidi, 'kill_elevated') as toeten:
            code = app.ensure_midi_program()
        self.assertEqual(code, 0)
        anhalten.assert_not_called()
        toeten.assert_not_called()


if __name__ == '__main__':
    unittest.main()