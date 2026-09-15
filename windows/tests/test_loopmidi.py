"""Tests für Port-Anlage, Einrichtung und Aufräumen.

Kein Test startet loopMIDI, lädt etwas herunter oder schreibt in die Registry:
subprocess und winreg sind immer ersetzt.
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import loopmidi


class Installation(unittest.TestCase):
    def test_installiert_wenn_exe_oder_dll_da_ist(self):
        exe = Path(r'C:\PF86\Tobias Erichsen\loopMIDI\loopMIDI.exe')
        with patch.object(loopmidi, 'paths', return_value=[exe]), \
                patch.object(Path, 'exists', return_value=True):
            self.assertTrue(loopmidi.installed())
        with patch.object(loopmidi, 'paths', return_value=[exe]), \
                patch.object(Path, 'exists', return_value=False):
            self.assertFalse(loopmidi.installed())

    def test_pfade_nutzen_beide_programmordner(self):
        texte = ' '.join(str(p) for p in loopmidi.paths(
            {'ProgramFiles(x86)': r'C:\PF86', 'ProgramFiles': r'C:\PF'}))
        self.assertIn(r'C:\PF86', texte)
        self.assertIn(r'C:\PF', texte)
        self.assertIn('teVirtualMIDI64.dll', texte)

    def test_exe_bevorzugt(self):
        exe = Path(r'C:\PF86\Tobias Erichsen\loopMIDI\loopMIDI.exe')
        dll = Path(r'C:\PF86\Tobias Erichsen\loopMIDI\teVirtualMIDI64.dll')
        with patch.object(loopmidi, 'paths', return_value=[dll, exe]), \
                patch.object(Path, 'exists', return_value=True):
            self.assertEqual(loopmidi.executable(), str(exe))
        with patch.object(loopmidi, 'paths', return_value=[dll]), \
                patch.object(Path, 'exists', return_value=True):
            self.assertIsNone(loopmidi.executable())

    def test_winget_befehl_ist_still(self):
        with patch.object(loopmidi, 'installed', side_effect=[False, True]), \
                patch.object(loopmidi, 'verify_signature', return_value=(True, 'signiert')), \
                patch.object(loopmidi.subprocess, 'run',
                             return_value=MagicMock(stdout='installiert', stderr='')) as lauf:
            ok, message = loopmidi.install_via_winget()
        self.assertTrue(ok)
        befehl = lauf.call_args[0][0]
        self.assertEqual(befehl[:2], ['winget', 'install'])
        self.assertIn('TobiasErichsen.loopMIDI', befehl)
        self.assertIn('--disable-interactivity', befehl)

    def test_winget_heftet_version_und_quelle(self):
        """Ohne Version/Quelle bestimmt die lokale winget-Konfiguration, was kommt."""
        with patch.object(loopmidi, 'installed', side_effect=[False, True]), \
                patch.object(loopmidi, 'verify_signature', return_value=(True, 'signiert')), \
                patch.object(loopmidi.subprocess, 'run',
                             return_value=MagicMock(stdout='', stderr='')) as lauf:
            loopmidi.install_via_winget()
        befehl = lauf.call_args[0][0]
        self.assertIn('--version', befehl)
        self.assertIn(loopmidi.WINGET_VERSION, befehl)
        self.assertIn('--source', befehl)
        self.assertIn('winget', befehl)

    def test_ohne_gueltige_signatur_keine_freigabe(self):
        """Erst wird installiert, dann geprüft – nicht umgekehrt."""
        with patch.object(loopmidi, 'installed', side_effect=[False, True]), \
                patch.object(loopmidi.subprocess, 'run',
                             return_value=MagicMock(stdout='', stderr='')), \
                patch.object(loopmidi, 'verify_signature',
                             return_value=(False, 'loopMIDI hat keine gültige Herstellersignatur.')):
            ok, message = loopmidi.install_via_winget()
        self.assertFalse(ok)
        self.assertIn('signatur', message.lower())

    def test_bereits_installiert_meldet_ohne_installation(self):
        with patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi.subprocess, 'run') as lauf:
            ok, message = loopmidi.install_via_winget()
        self.assertTrue(ok)
        self.assertIn('bereits installiert', message)
        lauf.assert_not_called()

    def test_signaturpruefung_meldet_ungueltig(self):
        with patch.object(loopmidi, '_run',
                          return_value=MagicMock(stdout='ABGELEHNT: HashMismatch', stderr='')), \
                patch.object(Path, 'exists', return_value=True):
            ok, message = loopmidi.verify_signature(r'C:\PF86\loopMIDI.exe')
        self.assertFalse(ok)
        self.assertIn('signatur', message.lower())

    def test_signaturpruefung_akzeptiert_gueltig(self):
        with patch.object(loopmidi, '_run',
                          return_value=MagicMock(stdout='OK', stderr='')), \
                patch.object(Path, 'exists', return_value=True):
            ok, message = loopmidi.verify_signature(r'C:\PF86\loopMIDI.exe')
        self.assertTrue(ok)

    def test_ohne_winget_verweis_auf_hersteller(self):
        with patch.object(loopmidi, 'installed', return_value=False), \
                patch.object(loopmidi.subprocess, 'run', side_effect=FileNotFoundError):
            ok, message = loopmidi.install_via_winget()
        self.assertFalse(ok)
        self.assertIn('tobias-erichsen.de', message)

    def test_installationsfehler_meldet_winget_ausgabe(self):
        with patch.object(loopmidi, 'installed', return_value=False), \
                patch.object(loopmidi.subprocess, 'run',
                             return_value=MagicMock(returncode=1, stdout='',
                                                    stderr='Kein Paket\nAbbruch')):
            ok, message = loopmidi.install_via_winget()
        self.assertFalse(ok)
        self.assertEqual(message, 'Abbruch')


class Namenspflege(unittest.TestCase):
    def test_namen_werden_gekuerzt(self):
        self.assertEqual(len(loopmidi.clean_name('W' * 80)), loopmidi.MAX_NAME)

    def test_leere_und_steuerzeichen_werden_entfernt(self):
        self.assertEqual(loopmidi.clean_name('  Kanal 1 \x01 '), 'Kanal 1')
        self.assertEqual(loopmidi.clean_name(None), '')
        self.assertEqual(loopmidi.clean_name('\n\t'), '')


class PortsSchreiben(unittest.TestCase):
    """winreg wird ersetzt: es darf nichts wirklich geschrieben werden."""

    def test_eintragen_prueft_namen(self):
        ok, message = loopmidi.remember('')
        self.assertFalse(ok)
        self.assertIn('leer', message)

    def test_eintragen_schreibt_registry(self):
        schluessel = MagicMock()
        schluessel.__enter__ = MagicMock(return_value=schluessel)
        schluessel.__exit__ = MagicMock(return_value=False)
        with patch.object(loopmidi, 'os', MagicMock(name='nt', spec=[])) as system, \
                patch('winreg.CreateKeyEx', return_value=schluessel) as anlegen, \
                patch('winreg.SetValueEx') as setzen:
            system.name = 'nt'
            ok, message = loopmidi.remember('ChurchTools Bridge')
        self.assertTrue(ok)
        self.assertIn('ChurchTools Bridge', message)

    def test_entfernen_meldet_fehlenden_eintrag(self):
        with patch.object(loopmidi, 'os', MagicMock(name='nt', spec=[])) as system, \
                patch('winreg.OpenKey', side_effect=FileNotFoundError):
            system.name = 'nt'
            ok, message = loopmidi.forget('Fehlt')
        self.assertTrue(ok)
        self.assertIn('war nicht eingetragen', message)

    def test_portnamen_werden_gelesen(self):
        schluessel = MagicMock()
        schluessel.__enter__ = MagicMock(return_value=schluessel)
        schluessel.__exit__ = MagicMock(return_value=False)
        with patch.object(loopmidi, 'os', MagicMock(name='nt', spec=[])) as system, \
                patch('winreg.OpenKey', return_value=schluessel), \
                patch('winreg.EnumValue', side_effect=[('Eins', '', 1), ('Zwei', '', 1), OSError()]):
            system.name = 'nt'
            self.assertEqual(loopmidi.ports(), ['Eins', 'Zwei'])

    def test_fehlender_schluessel_ergibt_leere_liste(self):
        with patch.object(loopmidi, 'os', MagicMock(name='nt', spec=[])) as system, \
                patch('winreg.OpenKey', side_effect=FileNotFoundError):
            system.name = 'nt'
            self.assertEqual(loopmidi.ports(), [])


class StartUndStop(unittest.TestCase):
    def test_start_ohne_programm(self):
        with patch.object(loopmidi, 'executable', return_value=None):
            ok, message = loopmidi.start()
        self.assertFalse(ok)
        self.assertIn('nicht gefunden', message)

    def test_start_ruft_programm_auf(self):
        with patch.object(loopmidi, 'executable', return_value=r'C:\l\loopMIDI.exe'), \
                patch.object(loopmidi.subprocess, 'Popen') as gestartet:
            ok, _ = loopmidi.start()
        self.assertTrue(ok)
        self.assertEqual(gestartet.call_args[0][0], [r'C:\l\loopMIDI.exe'])

    def test_start_meldet_fehler(self):
        with patch.object(loopmidi, 'executable', return_value=r'C:\l\loopMIDI.exe'), \
                patch.object(loopmidi.subprocess, 'Popen', side_effect=OSError('gesperrt')):
            ok, message = loopmidi.start()
        self.assertFalse(ok)
        self.assertIn('gesperrt', message)

    def test_stop_wenn_nichts_laeuft(self):
        with patch.object(loopmidi, 'running', return_value=False):
            ok, message = loopmidi.stop()
        self.assertTrue(ok)
        self.assertIn('läuft nicht', message)

    def test_stop_beendet_und_wartet(self):
        """Über die PID, damit auch mehrere Sitzungen erfasst werden."""
        with patch.object(loopmidi, 'running', side_effect=[True, True, False]), \
                patch.object(loopmidi, '_pids', return_value=['4711']), \
                patch.object(loopmidi, '_run') as lauf:
            ok, _ = loopmidi.stop()
        self.assertTrue(ok)
        befehle = [aufruf[0][0] for aufruf in lauf.call_args_list]
        self.assertIn(['taskkill', '/F', '/PID', '4711'], befehle)

    def test_stop_ohne_prozess(self):
        with patch.object(loopmidi, 'running', return_value=False):
            ok, message = loopmidi.stop()
        self.assertTrue(ok)
        self.assertIn('läuft nicht', message)

    def test_stop_meldet_wenn_programm_bleibt(self):
        with patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, '_run'), patch.object(loopmidi.time, 'sleep'):
            ok, message = loopmidi.stop()
        self.assertFalse(ok)
        self.assertIn('nicht beenden', message)

    def test_restart_startet_neu(self):
        with patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')), \
                patch.object(loopmidi, 'running', return_value=True):
            ok, message = loopmidi.restart()
        self.assertTrue(ok)
        self.assertIn('neuen Ports', message)


class PortSicherstellen(unittest.TestCase):
    def test_bereits_sichtbar_tut_nichts(self):
        with patch.object(loopmidi, 'port_visible', return_value=True), \
                patch.object(loopmidi, 'remember') as merken:
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertTrue(ok)
        merken.assert_not_called()

    def test_ohne_installation_klare_meldung(self):
        with patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'installed', return_value=False):
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertFalse(ok)
        self.assertIn('nicht installiert', message)

    def test_neuer_port_merken_stoppen_starten(self):
        """Ein neuer Eintrag wird erst nach Neustart von loopMIDI wirksam."""
        with patch.object(loopmidi, 'port_visible', side_effect=[False, True]), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=[]), \
                patch.object(loopmidi, 'remember', return_value=(True, 'eingetragen')) as merken, \
                patch.object(loopmidi, 'running', return_value=False), \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')) as anhalten, \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')) as starten:
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertTrue(ok)
        merken.assert_called_once()
        anhalten.assert_called_once()
        starten.assert_called_once()
        self.assertIn('verfügbar', message)

    def test_eingetragener_port_wird_nicht_doppelt_gemerkt(self):
        with patch.object(loopmidi, 'port_visible', side_effect=[False, True]), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=['ChurchTools Bridge']), \
                patch.object(loopmidi, 'remember') as merken, \
                patch.object(loopmidi, 'running', return_value=False), \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')):
            ok, _ = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertTrue(ok)
        merken.assert_not_called()

    def test_port_erscheint_nicht(self):
        with patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=['ChurchTools Bridge']), \
                patch.object(loopmidi, 'running', return_value=False), \
                patch.object(loopmidi, 'stop', return_value=(True, 'beendet')), \
                patch.object(loopmidi, 'start', return_value=(True, 'gestartet')), \
                patch.object(loopmidi.time, 'sleep'), \
                patch.object(loopmidi.time, 'monotonic', side_effect=[0, 0, 1, 999]):
            ok, message = loopmidi.ensure_port('ChurchTools Bridge', wait=5)
        self.assertFalse(ok)
        self.assertIn('nicht sichtbar', message)

    def test_leerer_name(self):
        ok, message = loopmidi.ensure_port('')
        self.assertFalse(ok)
        self.assertIn('Namen', message)

    def test_stop_scheitert_meldet_erhoeht(self):
        """Scheitert stop(), steckt meist ein erhöht laufender Prozess dahinter."""
        with patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=['ChurchTools Bridge']), \
                patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, 'stoppable', return_value=False):
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertFalse(ok)
        self.assertIn('erhöhten Rechten', message)

    def test_stop_scheitert_ohne_erhoehung(self):
        with patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=['ChurchTools Bridge']), \
                patch.object(loopmidi, 'running', return_value=True), \
                patch.object(loopmidi, 'stoppable', return_value=True), \
                patch.object(loopmidi, 'stop', return_value=(False, 'haengt')):
            ok, message = loopmidi.ensure_port('ChurchTools Bridge')
        self.assertFalse(ok)
        self.assertEqual(message, 'haengt')


class Einrichtung(unittest.TestCase):
    def test_zustand_ohne_programm(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=False):
            state, text = setupguide.diagnose()
        self.assertEqual(state, 'install')
        self.assertIn('installiert', text)

    def test_zustand_bereit(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'port_visible', return_value=True):
            state, text = setupguide.diagnose('ChurchTools Bridge')
        self.assertEqual(state, 'ready')
        self.assertIn('ChurchTools Bridge', text)

    def test_zustand_anlegen(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=[]), \
                patch.object(loopmidi, 'port_visible', return_value=False):
            state, _ = setupguide.diagnose('ChurchTools Bridge')
        self.assertEqual(state, 'create')

    def test_zustand_starten(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'ports', return_value=['ChurchTools Bridge']), \
                patch.object(loopmidi, 'port_visible', return_value=False):
            state, _ = setupguide.diagnose('ChurchTools Bridge')
        self.assertEqual(state, 'start')

    def test_vorbereiten_installiert_und_legt_an(self):
        import setupguide
        meldungen = []
        with patch.object(loopmidi, 'installed', side_effect=[False, True]), \
                patch.object(loopmidi, 'install_via_winget', return_value=(True, 'installiert')) as installieren, \
                patch.object(loopmidi, 'port_visible', side_effect=[False, False, True]), \
                patch.object(loopmidi, 'ensure_port', return_value=(True, 'angelegt')) as anlegen:
            ok, message = setupguide.prepare('ChurchTools Bridge', report=meldungen.append)
        self.assertTrue(ok)
        installieren.assert_called_once()
        anlegen.assert_called_once()
        self.assertIn('bereit', message)

    def test_vorbereiten_scheitert_bei_installation(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=False), \
                patch.object(loopmidi, 'install_via_winget', return_value=(False, 'kein winget')):
            ok, message = setupguide.prepare('ChurchTools Bridge', report=lambda text: None)
        self.assertFalse(ok)
        self.assertEqual(message, 'kein winget')

    def test_vorbereiten_ueberspringt_fertigen_port(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'port_visible', return_value=True), \
                patch.object(loopmidi, 'ensure_port') as anlegen:
            ok, _ = setupguide.prepare('ChurchTools Bridge', report=lambda text: None)
        self.assertTrue(ok)
        anlegen.assert_not_called()

    def test_entfernen_raeumt_auf(self):
        import setupguide
        with patch.object(loopmidi, 'forget', return_value=(True, 'weg')) as vergessen, \
                patch.object(loopmidi, 'restart', return_value=(True, 'neu')):
            ok, message = setupguide.teardown('ChurchTools Bridge')
        self.assertTrue(ok)
        self.assertIn('entfernt', message)
        vergessen.assert_called_once()

    def test_namen_der_oberflaeche_werden_gekuerzt(self):
        import setupguide
        with patch.object(loopmidi, 'installed', return_value=True), \
                patch.object(loopmidi, 'port_visible', return_value=False), \
                patch.object(loopmidi, 'ports', return_value=[]):
            state, text = setupguide.diagnose('W' * 90)
        self.assertEqual(state, 'create')
        self.assertEqual(len(text.split('„')[1].split('“')[0]), loopmidi.MAX_NAME)


if __name__ == '__main__':
    unittest.main()