"""Tests für die Deinstallation und den Autostart-Pfad.

Zwei Fehler, die erst im echten Installationslauf sichtbar wurden:

1. Die Bridge lief während der Deinstallation. Windows konnte die gesperrte EXE
   nicht löschen und merkte sie nur für den nächsten Neustart vor – der Ordner
   blieb bestehen. Siehe StopBridge() im Inno-Skript und die Testklasse
   Deinstallationsreihenfolge.

2. Der Autostart-Eintrag zeigte auf die Arbeitskopie in %TEMP%\\ctp-cmd. Die
   wird nach dem Setup gelöscht, der Eintrag wäre also beim nächsten Anmelden
   ins Leere gelaufen. Siehe Klasse AutostartZiel.

3. Der MIDI-Port blieb stehen: der Aufruf über [UninstallRun] brauchte eine
   Bridge-EXE, die zu diesem Zeitpunkt schon gelöscht war. Jetzt räumt das
   Deinstallations-Skript selbst auf.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class AutostartZiel(unittest.TestCase):
    """Der Autostart darf nie auf die Temp-Arbeitskopie zeigen."""

    def test_arbeitskopie_wird_umgebogen(self):
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', r'C:\Users\Test\AppData\Local\Temp\ctp-cmd\ChurchToolsBridge.exe'), \
                patch.dict(os.environ, {'ProgramFiles': r'C:\Program Files'}):
            ziel = app.install_target()
        self.assertEqual(ziel, Path(r'C:\Program Files\ChurchTools Bridge\ChurchToolsBridge.exe'))

    def test_installierte_lage_bleibt(self):
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', r'C:\Program Files\ChurchTools Bridge\ChurchToolsBridge.exe'):
            ziel = app.install_target()
        self.assertEqual(ziel, Path(r'C:\Program Files\ChurchTools Bridge\ChurchToolsBridge.exe'))

    def test_ausdrueckliches_ziel_gewinnt(self):
        self.assertEqual(app.install_target(r'D:\woanders\Bridge.exe'),
                         Path(r'D:\woanders\Bridge.exe'))

    def test_eintrag_zeigt_nicht_auf_temp(self):
        """Der geschriebene Eintrag muss auf Program Files zeigen."""
        geschrieben = {}

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *rest):
                return False

        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', r'C:\Users\Test\AppData\Local\Temp\ctp-cmd\ChurchToolsBridge.exe'), \
                patch.dict(os.environ, {'ProgramFiles': r'C:\Program Files'}), \
                patch('winreg.CreateKey', return_value=FakeKey()), \
                patch('winreg.SetValueEx',
                      side_effect=lambda key, name, a, b, wert: geschrieben.update(wert=wert)):
            app.set_autostart(True)
        self.assertNotIn('Temp', geschrieben['wert'])
        self.assertIn(r'C:\Program Files\ChurchTools Bridge', geschrieben['wert'])


class Deinstallationsreihenfolge(unittest.TestCase):
    """Prüft das Inno-Skript statisch: die Bridge muss VOR dem Löschen weg sein."""

    @classmethod
    def setUpClass(cls):
        skript = Path(__file__).resolve().parents[1] / 'installer' / 'ChurchToolsBridge.iss'
        cls.text = skript.read_text(encoding='utf-8')

    def test_initializeuninstall_beendet_bridge(self):
        """InitializeUninstall läuft vor dem Löschen der Dateien."""
        start = self.text.index('function InitializeUninstall')
        block = self.text[start:start + 300]
        self.assertIn('StopBridge()', block)

    def test_usuninstall_beendet_bridge(self):
        start = self.text.index('procedure CurUninstallStepChanged')
        block = self.text[start:start + 600]
        self.assertIn('StopBridge()', block)

    def test_kein_restart_manager(self):
        """Der Restart Manager würde die Bridge nach der Deinstallation neu starten."""
        self.assertIn('CloseApplications=no', self.text)
        self.assertIn('RestartApplications=no', self.text)

    def test_kein_uninstallrun_auf_die_exe(self):
        """[UninstallRun] kann die EXE nicht zuverlässig aufrufen – sie ist schon weg."""
        start = self.text.index('[UninstallRun]')
        block = self.text[start:self.text.index('[UninstallDelete]')]
        ohne_kommentar = '\n'.join(zeile for zeile in block.splitlines()
                                   if not zeile.strip().startswith(';'))
        self.assertNotIn('MyAppExeName', ohne_kommentar)

    def test_aufraeumen_laeuft_im_usuninstall(self):
        """Port und Autostart müssen im Deinstaller selbst entfernt werden."""
        start = self.text.index('procedure CurUninstallStepChanged')
        block = self.text[start:start + 600]
        self.assertIn('RemoveEverything()', block)

    def test_autostart_und_port_werden_entfernt(self):
        start = self.text.index('procedure RemoveEverything')
        block = self.text[start:start + 1400]
        self.assertIn('CurrentVersion\\Run', block)
        self.assertIn('ChurchToolsBridge', block)
        self.assertIn('loopMIDI', block)

    def test_ordner_bleibt_nicht_leer(self):
        self.assertIn('[UninstallDelete]', self.text)
        self.assertIn('dirifempty', self.text)

    def test_arbeitskopie_liegt_nicht_direkt_in_app(self):
        """Eine laufende EXE direkt aus {app} würde den Ordner sperren.

        Sie liegt deshalb in einem Unterordner. Der ist nicht bloß Kosmetik:
        die Kopie wird ERHÖHT gestartet, also darf der Benutzer sie nicht
        austauschen können – %TEMP% und %ProgramData% scheiden damit aus.
        """
        i = self.text.index('#define BridgeBase')
        zeile = self.text[i:self.text.index('\n', i)]
        self.assertTrue(zeile.startswith('#define BridgeBase "{app}\\'),
                        f'Arbeitskopie muss unter {{app}} liegen, ist aber: {zeile.strip()}')
        self.assertNotIn('{tmp}', zeile)
        self.assertNotIn('{commonappdata}', zeile)

    def test_arbeitskopie_ist_erhoeht_nicht_austauschbar(self):
        """{app} gehört Administratoren – das ist die Voraussetzung dafür."""
        self.assertIn('#define BridgeBase "{app}\\ctp-cmd"', self.text)
        # Der erhöhte Aufruf muss genau diese Kopie starten.
        i = self.text.index('--ensure-midi-program')
        block = self.text[max(0, i - 400):i + 200]
        self.assertIn('{#BridgeBase}', block, 'erhöhter Aufruf startet nicht die Kopie')


if __name__ == '__main__':
    unittest.main()