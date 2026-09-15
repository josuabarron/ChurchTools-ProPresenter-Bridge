"""Tests gegen das erhöhte Starten von loopMIDI.

Gefundener Fehler (zweimal aufgetreten):
Der loopMIDI-Installer UND die Bridge starten loopMIDI aus einem erhöhten
Prozess heraus. Danach läuft loopMIDI in einer höheren Integritätsstufe und
lässt sich vom normalen Bridge-Prozess nicht mehr beenden ('Zugriff
verweigert'). Ein neu eingetragener Port wird dann nie sichtbar.

Regel: loopMIDI wird ausschließlich aus einem normalen Prozess gestartet.
Erhöhte Prozesse (Installer, Deinstaller) beenden es nur.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import loopmidi
import setupguide


class StartVerweigertAusErhoehtemProzess(unittest.TestCase):
    def test_erhoeht_startet_nicht(self):
        with patch.object(loopmidi, 'executable', return_value=r'C:\l\loopMIDI.exe'), \
                patch.object(loopmidi, 'elevated', return_value=True), \
                patch.object(loopmidi.subprocess, 'Popen') as starten:
            ok, message = loopmidi.start()
        self.assertFalse(ok)
        self.assertIn('erhöhten Prozess', message)
        starten.assert_not_called()

    def test_normal_startet(self):
        with patch.object(loopmidi, 'executable', return_value=r'C:\l\loopMIDI.exe'), \
                patch.object(loopmidi, 'elevated', return_value=False), \
                patch.object(loopmidi.subprocess, 'Popen') as starten:
            ok, _ = loopmidi.start()
        self.assertTrue(ok)
        starten.assert_called_once()

    def test_isuseradmin_wird_gelesen(self):
        """elevated() fragt Windows, nicht die Umgebung."""
        with patch('ctypes.windll', create=True) as windll:
            windll.shell32.IsUserAnAdmin.return_value = 1
            self.assertTrue(loopmidi.elevated())
            windll.shell32.IsUserAnAdmin.return_value = 0
            self.assertFalse(loopmidi.elevated())

    def test_fehler_bei_isuseradmin_gilt_als_nicht_erhoeht(self):
        with patch('ctypes.windll', create=True) as windll:
            windll.shell32.IsUserAnAdmin.side_effect = OSError('nope')
            self.assertFalse(loopmidi.elevated())


class NeustartAusErhoehtemProzess(unittest.TestCase):
    def test_restart_startet_erhoeht_nicht_neu(self):
        with patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'elevated', return_value=True), \
                patch.object(loopmidi, 'start') as starten:
            ok, message = loopmidi.restart()
        self.assertTrue(ok)
        self.assertIn('nicht aus einem erhöhten Prozess', message)
        starten.assert_not_called()

    def test_restart_startet_normal_neu(self):
        with patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'elevated', return_value=False), \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')), \
                patch.object(loopmidi, 'running', return_value=True):
            ok, message = loopmidi.restart()
        self.assertTrue(ok)
        self.assertIn('neuen Ports', message)


class StopUeberPid(unittest.TestCase):
    """taskkill /IM erfasst mehrere Sitzungen nicht – deshalb über die PID."""

    def test_beendet_jede_pid(self):
        aufrufe = []
        with patch.object(loopmidi, 'running', side_effect=[True, False]), \
                patch.object(loopmidi, '_pids', return_value=['111', '222']), \
                patch.object(loopmidi, '_run', side_effect=lambda c, **k: aufrufe.append(c)):
            ok, message = loopmidi.stop()
        self.assertTrue(ok)
        self.assertIn(['taskkill', '/F', '/PID', '111'], aufrufe)
        self.assertIn(['taskkill', '/F', '/PID', '222'], aufrufe)

    def test_meldet_erhoeht_wenn_nicht_beendbar(self):
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, '_pids', return_value=['111']), \
                patch.object(loopmidi, '_run'), \
                patch.object(loopmidi, 'stoppable', return_value=False), \
                patch.object(loopmidi.time, 'sleep'):
            ok, message = loopmidi.stop()
        self.assertFalse(ok)
        self.assertIn('erhöhten Rechten', message)

    def test_pids_werden_gelesen(self):
        antwort = MagicMock(stdout='"loopMIDI.exe","58396","Console","1","22.492 K"\n'
                                   '"loopMIDI.exe","999","Console","1","20 K"')
        with patch.object(loopmidi, '_run', return_value=antwort):
            self.assertEqual(loopmidi._pids(), ['58396', '999'])

    def test_leere_ausgabe_ergibt_keine_pids(self):
        with patch.object(loopmidi, '_run',
                          return_value=MagicMock(stdout='INFORMATION: keine Aufgaben')):
            self.assertEqual(loopmidi._pids(), [])


class DeinstallationStartetNichtNeu(unittest.TestCase):
    def test_teardown_beendet_nur(self):
        with patch.object(loopmidi, 'forget', return_value=(True, 'weg')) as vergessen, \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')) as anhalten, \
                patch.object(loopmidi, 'restart') as neustart:
            ok, message = setupguide.teardown('ChurchTools Bridge')
        self.assertTrue(ok)
        self.assertIn('entfernt', message)
        vergessen.assert_called_once()
        anhalten.assert_called_once()
        neustart.assert_not_called()


class InstallerSchrittBeendetNur(unittest.TestCase):
    def test_ensure_midi_program_startet_nicht(self):
        """Der erhöhte Installer-Schritt darf loopMIDI nicht starten."""
        import app
        with patch.object(app.loopmidi, 'installed', return_value=True), \
                patch.object(app.loopmidi, 'running', return_value=True), \
                patch.object(app.loopmidi, 'stoppable', return_value=True), \
                patch.object(app.loopmidi, 'stop', return_value=(True, 'beendet')) as anhalten, \
                patch.object(app.loopmidi, 'start') as starten:
            code = app.ensure_midi_program()
        self.assertEqual(code, 0)
        anhalten.assert_called_once()
        starten.assert_not_called()


if __name__ == '__main__':
    unittest.main()