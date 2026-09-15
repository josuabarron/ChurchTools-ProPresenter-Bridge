"""Tests für das Infobereich-Symbol.

Ohne Symbol war nicht zu erkennen, ob die Bridge arbeitet – sie lief
unsichtbar im Hintergrund. Diese Tests brauchen kein echtes Fenster: geprüft
wird der Zustandswechsel und die Zuordnung Symbol → Status.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tray


class SymbolDateien(unittest.TestCase):
    def test_alle_drei_vorhanden(self):
        for name in ('app.ico', 'tray-online.ico', 'tray-offline.ico'):
            self.assertTrue((tray.assets_dir() / name).exists(), f'{name} fehlt')

    def test_pfad_zeigt_auf_assets(self):
        self.assertEqual(tray.assets_dir().name, 'assets')


class Zustandswechsel(unittest.TestCase):
    """set_online darf ohne echtes Fenster nichts anfassen."""

    def setUp(self):
        self.icon = tray.TrayIcon(tooltip='Test')
        self.icon._icons = {'online': 1, 'offline': 2}

    def test_start_ist_offline(self):
        self.assertIsNone(self.icon.online)
        self.assertEqual(self.icon._icon_for(), 2)

    def test_online_waehlt_gruenes_symbol(self):
        self.icon.online = True
        self.assertEqual(self.icon._icon_for(), 1)

    def test_offline_waehlt_graues_symbol(self):
        self.icon.online = False
        self.assertEqual(self.icon._icon_for(), 2)

    def test_fehlendes_online_faellt_auf_offline_zurueck(self):
        del self.icon._icons['online']
        self.icon.online = True
        self.assertEqual(self.icon._icon_for(), 2)

    def test_hinweistext_wird_gesetzt(self):
        self.icon.set_online(True, 'Bridge läuft · Event Gottesdienst')
        self.assertEqual(self.icon.online, True)
        self.assertIn('Event Gottesdienst', self.icon.tooltip)

    def test_ohne_text_kommt_standard(self):
        self.icon.set_online(True)
        self.assertEqual(self.icon.tooltip, 'Bridge läuft')
        self.icon.set_online(False)
        self.assertEqual(self.icon.tooltip, 'Bridge gestoppt')

    def test_hinweistext_ist_laengenbegrenzt(self):
        self.icon.set_online(True, 'x' * 300)
        self.assertLessEqual(len(self.icon.tooltip), 127)


class OhneFenster(unittest.TestCase):
    """Ohne angelegtes Fenster darf keine Win32-Funktion gerufen werden."""

    def test_set_online_ohne_fenster(self):
        icon = tray.TrayIcon()
        icon.set_online(True)          # darf nicht abstürzen
        self.assertTrue(icon.online)

    def test_notify_ohne_fenster(self):
        tray.TrayIcon().notify('Titel', 'Text')

    def test_pump_ohne_fenster(self):
        tray.TrayIcon().pump()

    def test_close_ohne_fenster(self):
        tray.TrayIcon().close()

    def test_close_ist_wiederholbar(self):
        icon = tray.TrayIcon()
        icon.close()
        icon.close()


class MenuBefehle(unittest.TestCase):
    def test_konstanten_sind_verschieden(self):
        werte = [tray.TrayIcon.OPEN, tray.TrayIcon.STATUS, tray.TrayIcon.QUIT]
        self.assertEqual(len(set(werte)), len(werte))


class AppBindung(unittest.TestCase):
    """Die App muss das Symbol anlegen und den Zustand durchreichen."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import app
        cls.app = app

    def test_tray_wird_importiert(self):
        self.assertTrue(hasattr(self.app, 'tray'))

    def test_schalter_tray_existiert(self):
        """Der Autostart-Eintrag ruft --tray auf; ohne den Schalter bricht er ab.

        Die Einzelinstanz-Sperre wird ersetzt: sie ist global (Local\...), und
        eine daneben laufende Bridge würde diesen Test sonst zufällig
        scheitern lassen, ohne dass der Schalter etwas damit zu tun hat.
        """
        import io
        import contextlib
        with patch.object(self.app, 'App') as fakes, \
                patch.object(self.app.tray.Instance, 'acquire', return_value=True):
            fakes.return_value.tray = None
            with patch('tkinter.Tk'):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.app.main(['--tray'])
        fakes.assert_called_once()

    def test_unbekannter_schalter_faellt_auf(self):
        """Gegenprobe: ein wirklich unbekannter Schalter muss auffallen."""
        with self.assertRaises(SystemExit):
            with patch('sys.stderr'):
                self.app.main(['--gibt-es-nicht'])


if __name__ == '__main__':
    unittest.main()