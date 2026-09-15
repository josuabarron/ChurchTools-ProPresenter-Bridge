"""Tests für die Einrichtung ohne Fenster (Installationspfad).

Es wird nichts installiert, gestartet oder geschrieben: loopmidi und setupguide
sind ersetzt, winreg wird nicht angefasst.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class ProgrammBereitstellen(unittest.TestCase):
    def test_bereits_vorhanden(self):
        with patch.object(app.loopmidi, 'installed', return_value=True), \
                patch.object(app.loopmidi, 'install_via_winget') as installieren:
            code = app.ensure_midi_program()
        self.assertEqual(code, 0)
        installieren.assert_not_called()

    def test_wird_installiert(self):
        with patch.object(app.loopmidi, 'installed', return_value=False), \
                patch.object(app.loopmidi, 'install_via_winget', return_value=(True, 'ok')):
            self.assertEqual(app.ensure_midi_program(), 0)

    def test_scheitert(self):
        with patch.object(app.loopmidi, 'installed', return_value=False), \
                patch.object(app.loopmidi, 'install_via_winget',
                             return_value=(False, 'kein winget')):
            self.assertEqual(app.ensure_midi_program(), 1)

    def test_fehler_wird_berichtet(self):
        with tempfile.TemporaryDirectory() as folder:
            bericht = Path(folder) / 'bericht.txt'
            with patch.object(app.loopmidi, 'installed', return_value=False), \
                    patch.object(app.loopmidi, 'install_via_winget',
                                 side_effect=RuntimeError('kaputt')):
                code = app.ensure_midi_program(str(bericht))
            self.assertEqual(code, 1)
            inhalt = bericht.read_text(encoding='utf-8')
            self.assertIn('kaputt', inhalt)


class EinrichtenImBenutzerkonto(unittest.TestCase):
    def test_port_und_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            bericht = Path(folder) / 'bericht.txt'
            with patch.object(app.setupguide, 'prepare', return_value=(True, 'Port ist bereit.')), \
                    patch.object(app, 'apply_autostart', return_value='Autostart eingerichtet.'):
                code = app.complete_setup('ChurchTools Bridge', str(bericht))
            self.assertEqual(code, 0)
            inhalt = bericht.read_text(encoding='utf-8')
            self.assertIn('Port ist bereit.', inhalt)
            self.assertIn('Autostart eingerichtet.', inhalt)

    def test_ohne_autostart_wenn_abgewaehlt(self):
        with patch.object(app.setupguide, 'prepare', return_value=(True, 'bereit')), \
                patch.object(app, 'apply_autostart', return_value='Autostart entfernt.') as setzen:
            code = app.complete_setup('ChurchTools Bridge', None, False)
        self.assertEqual(code, 0)
        setzen.assert_called_once_with(False, None)

    def test_port_scheitert_ergibt_code_1(self):
        with patch.object(app.setupguide, 'prepare', return_value=(False, 'kein winget')), \
                patch.object(app, 'apply_autostart', return_value='Autostart eingerichtet.'):
            self.assertEqual(app.complete_setup('ChurchTools Bridge', None), 1)

    def test_bericht_entsteht_auch_bei_ausnahme(self):
        with tempfile.TemporaryDirectory() as folder:
            bericht = Path(folder) / 'bericht.txt'
            with patch.object(app.setupguide, 'prepare', side_effect=ValueError('unerwartet')), \
                    patch.object(app, 'apply_autostart', return_value='egal'):
                code = app.complete_setup('ChurchTools Bridge', str(bericht))
            self.assertEqual(code, 1)
            inhalt = bericht.read_text(encoding='utf-8')
            self.assertIn('unerwartet', inhalt)
            self.assertIn('nächsten Start', inhalt)

    def test_unschreibbarer_bericht_stuerzt_nicht_ab(self):
        with patch.object(app.setupguide, 'prepare', return_value=(True, 'bereit')), \
                patch.object(app, 'apply_autostart', return_value='ok'), \
                patch.object(Path, 'write_text', side_effect=OSError('gesperrt')):
            self.assertEqual(app.complete_setup('ChurchTools Bridge', r'C:\gesperrt\x.txt'), 0)


class AutostartSetzen(unittest.TestCase):
    def test_eingerichtet(self):
        with patch.object(app, 'set_autostart') as setzen, \
                patch.object(app, 'has_autostart', return_value=True):
            self.assertIn('eingerichtet', app.apply_autostart(True))
        setzen.assert_called_once_with(True, None)

    def test_entfernt(self):
        with patch.object(app, 'set_autostart'), \
                patch.object(app, 'has_autostart', return_value=False):
            self.assertIn('entfernt', app.apply_autostart(False))

    def test_fehler_wird_gemeldet(self):
        with patch.object(app, 'set_autostart', side_effect=OSError('kein Zugriff')), \
                patch.object(app, 'has_autostart', return_value=False):
            self.assertIn('kein Zugriff', app.apply_autostart(True))

    def test_wirkungslos(self):
        with patch.object(app, 'set_autostart'), \
                patch.object(app, 'has_autostart', return_value=False):
            self.assertIn('nicht geändert', app.apply_autostart(True))


class Schalter(unittest.TestCase):
    """Der Installer übergibt die Schalter – jeder muss ankommen."""

    def test_remove_autostart(self):
        with patch.object(app, 'apply_autostart', return_value='Autostart entfernt.') as setzen, \
                patch('sys.stdout'):
            self.assertEqual(app.main(['--remove-autostart']), 0)
        setzen.assert_called_once_with(False)

    def test_remove_port(self):
        with patch.object(app.setupguide, 'teardown', return_value=(True, 'Port weg')), \
                patch('sys.stdout'):
            self.assertEqual(app.main(['--remove-port', '--port-name', 'Test']), 0)

    def test_uninstall_cleanup(self):
        with patch.object(app, 'uninstall_cleanup', return_value=0) as aufraeumen:
            self.assertEqual(app.main(['--uninstall-cleanup', '--port-name', 'Test']), 0)
        aufraeumen.assert_called_once_with('Test', None)

    def test_complete_setup_ohne_autostart(self):
        with patch.object(app, 'complete_setup', return_value=0) as einrichten:
            app.main(['--complete-setup', '--autostart', '0', '--port-name', 'Test'])
        einrichten.assert_called_once_with('Test', None, False, None)

    def test_complete_setup_mit_autostart(self):
        with patch.object(app, 'complete_setup', return_value=0) as einrichten:
            app.main(['--complete-setup', '--port-name', 'Test', '--report', 'x.txt'])
        einrichten.assert_called_once_with('Test', 'x.txt', True, None)

    def test_app_path_wird_durchgereicht(self):
        """Ohne diesen Pfad zeigt der Autostart auf den Temp-Ordner des Setups."""
        ziel = r'C:\Program Files\ChurchTools Bridge\ChurchToolsBridge.exe'
        with patch.object(app, 'complete_setup', return_value=0) as einrichten:
            app.main(['--complete-setup', '--app-path', ziel])
        einrichten.assert_called_once_with('ChurchTools Bridge', None, True, ziel)


if __name__ == '__main__':
    unittest.main()
