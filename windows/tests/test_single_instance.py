"""Tests für die Einzelinstanz, das Beenden aus dem Installer und das Symbol-Ende.

Hintergrund – drei Dinge, die zusammenhängen:

1. Der Deinstaller rief `taskkill /F`. Das beendet den Prozess, aber Windows
   entfernt das Symbol im Infobereich dann nicht: es bleibt als Leiche stehen,
   bis der Mauszeiger darüberfährt. Der Deinstaller ruft deshalb zuerst
   `--quit` und die Bridge räumt selbst auf.

2. Wird die Bridge zweimal geöffnet, gäbe es zwei Symbole und zwei Zugriffe auf
   denselben MIDI-Port. Der Benutzer bekommt stattdessen das vorhandene Fenster.

3. `--quit`/`--show` sind Botendienste: sie starten keine Oberfläche, sondern
   schicken eine Fenster-Nachricht an die laufende Bridge.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import tray


class NachrichtenNamen(unittest.TestCase):
    def test_namen_sind_verschieden(self):
        self.assertNotEqual(tray.QUIT_MESSAGE_NAME, tray.SHOW_MESSAGE_NAME)

    def test_namen_sind_stabil(self):
        """Zwei Prozesse müssen dieselbe Nummer bekommen – also denselben Text."""
        self.assertEqual(tray.QUIT_MESSAGE_NAME, 'ChurchToolsBridge:Quit')
        self.assertEqual(tray.SHOW_MESSAGE_NAME, 'ChurchToolsBridge:Show')

    def test_mutex_name_ist_lokalsitzung(self):
        """Local\\ verhindert, dass sich Sitzungen gegenseitig blockieren."""
        self.assertTrue(tray.MUTEX_NAME.startswith('Local\\'))


class Botendienst(unittest.TestCase):
    """--quit und --show dürfen keine Oberfläche aufbauen."""

    def test_quit_ohne_laufende_bridge(self):
        with patch.object(tray.Instance, 'running', return_value=False), \
                patch.object(tray, 'ask_to_quit') as boten:
            self.assertEqual(app.main(['--quit']), 0)
        boten.assert_called_once()

    def test_quit_wartet_bis_beendet(self):
        """Erst wird gefragt, dann gewartet – der Deinstaller verlässt sich darauf."""
        zustaende = iter([True, True, False, False])

        def laeuft(name=None):
            return next(zustaende, False)

        with patch.object(tray.Instance, 'running', side_effect=laeuft), \
                patch.object(tray, 'ask_to_quit'), \
                patch('time.sleep'):
            self.assertEqual(app.main(['--quit']), 0)

    def test_quit_meldet_wenn_es_nicht_klappt(self):
        with patch.object(tray.Instance, 'running', return_value=True), \
                patch.object(tray, 'ask_to_quit'), \
                patch('time.sleep'):
            self.assertEqual(app.main(['--quit']), 1)

    def test_show_schickt_nur_die_nachricht(self):
        with patch.object(tray, 'ask_to_show') as boten:
            self.assertEqual(app.main(['--show']), 0)
        boten.assert_called_once()

    def test_tray_schalter_akzeptiert(self):
        """Der Autostart ruft --tray; ohne den Schalter startet die Bridge nicht."""
        with patch.object(app, 'App') as gui, patch('tkinter.Tk'):
            gui.return_value.tray = None
            self.assertEqual(app.main(['--tray']), 0)


class Einzelinstanz(unittest.TestCase):
    def test_zweiter_start_holt_das_fenster(self):
        with patch.object(tray, 'Instance') as art, patch('tkinter.Tk') as tk:
            art.return_value.acquire.return_value = False
            with patch.object(tray, 'ask_to_show') as zeigen:
                self.assertEqual(app.main([]), 0)
            zeigen.assert_called_once()
            tk.assert_not_called()

    def test_mutex_wird_beim_ende_freigegeben(self):
        with patch.object(tray, 'Instance') as art, patch.object(app, 'App'), \
                patch('tkinter.Tk'):
            art.return_value.acquire.return_value = True
            app.main([])
            art.return_value.release.assert_called_once()


class InstancePruefung(unittest.TestCase):
    """Die echten Win32-Aufrufe – Mutex anlegen, prüfen, freigeben."""

    def test_erster_erhaelt_zweiter_nicht(self):
        erste, zweite = tray.Instance(f'Local\\CTP-Test-{id(self)}'), \
                        tray.Instance(f'Local\\CTP-Test-{id(self)}')
        try:
            self.assertTrue(erste.acquire())
            self.assertFalse(zweite.acquire())
        finally:
            erste.release()
            zweite.release()

    def test_freigabe_beendet_laufende_pruefung(self):
        name = f'Local\\CTP-Test-running-{id(self)}'
        halter = tray.Instance(name)
        self.assertTrue(halter.acquire())
        self.assertTrue(tray.Instance.running(name))
        halter.release()
        self.assertFalse(tray.Instance.running(name))

    def test_freigabe_ist_wiederholbar(self):
        art = tray.Instance(f'Local\\CTP-Test-mehrfach-{id(self)}')
        art.acquire()
        art.release()
        art.release()

    def test_nach_freigabe_ist_der_platz_frei(self):
        name = f'Local\\CTP-Test-wieder-{id(self)}'
        erste = tray.Instance(name)
        self.assertTrue(erste.acquire())
        erste.release()
        zweite = tray.Instance(name)
        try:
            self.assertTrue(zweite.acquire())
        finally:
            zweite.release()


class SymbolVerschwindet(unittest.TestCase):
    def test_quit_nachricht_ist_verschieden_von_show(self):
        self.assertNotEqual(tray.QUIT_MESSAGE_NAME, tray.SHOW_MESSAGE_NAME)

    def test_announce_ohne_nummer_scheitert_leise(self):
        with patch.object(tray, 'registered_message', return_value=0):
            self.assertFalse(tray.announce('irgendwas'))
            self.assertFalse(tray.ask_to_quit())

    def test_nachrichten_werden_registriert(self):
        nummer = tray.registered_message('ChurchToolsBridge:Test')
        self.assertGreater(nummer, 0)


class InnoSkript(unittest.TestCase):
    """Der Deinstaller muss höflich fragen, bevor er hart beendet."""

    @classmethod
    def setUpClass(cls):
        cls.text = (Path(__file__).resolve().parents[1] /
                    'installer' / 'ChurchToolsBridge.iss').read_text(encoding='utf-8')

    def test_stopbridge_ruft_quit(self):
        start = self.text.index('function StopBridge')
        block = self.text[start:self.text.index('procedure PrepareBridgeCopy')]
        self.assertIn("'--quit'", block)

    @staticmethod
    def _ohne_kommentare(text):
        """Nur echte Codezeilen.

        Inno kennt zwei Kommentarformen: `;` bis Zeilenende und `{ ... }`, das
        auch mehrzeilig und mitten in einer Zeile stehen darf. Ein reiner
        Zeilenfilter genügt deshalb nicht – der Kommentarblock würde als Code
        durchgehen und die Reihenfolgeprüfung verfälschen.
        """
        import re
        ohne_bloecke = re.sub(r'\{[^}]*\}', ' ', text, flags=re.S)
        zeilen = [zeile for zeile in ohne_bloecke.splitlines()
                  if zeile.strip() and not zeile.strip().startswith(';')]
        return '\n'.join(zeilen)

    def test_quit_kommt_vor_taskkill(self):
        """Zuerst fragen, dann hart beenden – sonst bleibt das Symbol stehen."""
        start = self.text.index('function StopBridge')
        block = self._ohne_kommentare(
            self.text[start:self.text.index('procedure PrepareBridgeCopy')])
        self.assertLess(block.index("'--quit'"), block.index('taskkill'))

    def test_taskkill_bleibt_als_rueckfall(self):
        start = self.text.index('function StopBridge')
        block = self.text[start:self.text.index('procedure PrepareBridgeCopy')]
        self.assertIn('taskkill', block)


if __name__ == '__main__':
    unittest.main()