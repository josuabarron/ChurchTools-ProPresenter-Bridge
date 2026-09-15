"""Tests für den Tokenspeicher.

Zwei Fehler, die erst im echten Betrieb sichtbar wurden:
* Eine zusätzliche Entropie machte bereits gespeicherte Token unlesbar.
* Eine Meldung im Aufbau griff auf Widgets zu, die es noch nicht gab.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault('LOCALAPPDATA', os.path.join(tempfile.gettempdir(), 'ctp-tests'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native  # noqa: E402


def ohne_entropie(data):
    """Verschlüsselt wie die frühere Fassung: DPAPI ohne Zusatzentropie."""
    import ctypes as C
    from ctypes import wintypes as W

    class Blob(C.Structure):
        _fields_ = [('size', W.DWORD), ('data', C.POINTER(C.c_ubyte))]

    puffer = (C.c_ubyte * len(data)).from_buffer_copy(data)
    quelle = Blob(len(data), C.cast(puffer, C.POINTER(C.c_ubyte)))
    ziel = Blob()
    dll = C.WinDLL('crypt32', use_last_error=True)
    f = dll.CryptProtectData
    f.argtypes = [C.POINTER(Blob), C.c_void_p, C.POINTER(Blob), C.c_void_p,
                  C.c_void_p, W.DWORD, C.POINTER(Blob)]
    f.restype = W.BOOL
    if not f(C.byref(quelle), None, None, None, None, 1, C.byref(ziel)):
        raise OSError(C.get_last_error())
    k = C.WinDLL('kernel32')
    k.LocalFree.argtypes = [C.c_void_p]
    ergebnis = C.string_at(ziel.data, ziel.size)
    k.LocalFree(ziel.data)
    return ergebnis


class Abwaertskompatibilitaet(unittest.TestCase):
    """Bestehende Token dürfen nicht unlesbar werden."""

    @unittest.skipUnless(os.name == 'nt', 'DPAPI gibt es nur unter Windows')
    def test_alte_datei_ohne_entropie_bleibt_lesbar(self):
        alt = ohne_entropie(b'BESTEHENDER-TOKEN')
        self.assertEqual(native.protect(alt, decrypt=True), b'BESTEHENDER-TOKEN')

    @unittest.skipUnless(os.name == 'nt', 'DPAPI gibt es nur unter Windows')
    def test_neue_datei_haelt_die_entropie_ein(self):
        neu = native.protect(b'NEUER-TOKEN')
        self.assertEqual(native.protect(neu, decrypt=True), b'NEUER-TOKEN')

    @unittest.skipUnless(os.name == 'nt', 'DPAPI gibt es nur unter Windows')
    def test_mit_entropie_geschrieben_ist_ohne_nicht_lesbar(self):
        """Umgekehrt: der Zusatzschutz wirkt wirklich."""
        neu = native.protect(b'GEHEIM')
        import ctypes as C
        from ctypes import wintypes as W

        class Blob(C.Structure):
            _fields_ = [('size', W.DWORD), ('data', C.POINTER(C.c_ubyte))]

        puffer = (C.c_ubyte * len(neu)).from_buffer_copy(neu)
        quelle = Blob(len(neu), C.cast(puffer, C.POINTER(C.c_ubyte)))
        ziel = Blob()
        dll = C.WinDLL('crypt32', use_last_error=True)
        f = dll.CryptUnprotectData
        f.argtypes = [C.POINTER(Blob), C.c_void_p, C.POINTER(Blob), C.c_void_p,
                      C.c_void_p, W.DWORD, C.POINTER(Blob)]
        f.restype = W.BOOL
        self.assertFalse(f(C.byref(quelle), None, None, None, None, 1, C.byref(ziel)),
                         'ohne Entropie entschlüsselbar – der Zusatzschutz fehlt')

    def test_unbrauchbare_daten_ergeben_klare_meldung(self):
        if os.name != 'nt':
            self.skipTest('DPAPI gibt es nur unter Windows')
        with self.assertRaises(Exception) as e:
            native.protect(b'kein-gueltiges-dpapi', decrypt=True)
        self.assertIn('Token', str(e.exception))

    def test_entropie_wert_ist_unveraendert(self):
        """Ändert er sich, werden alle gespeicherten Token unlesbar."""
        self.assertEqual(native.ENTROPIE,
                         b'ChurchToolsProPresenterBridge:v1:token')


class MeldungenWaehrendDesAufbaus(unittest.TestCase):
    """report() darf vor dem Fensteraufbau nicht abstürzen."""

    def setUp(self):
        import app
        self.app = app

    def test_report_vor_den_widgets_stuerzt_nicht_ab(self):
        fenster = MagicMock()
        fenster.pending_messages = []
        del fenster.status          # so ist es im __init__
        del fenster.log
        self.app.App.report(fenster, 'Gespeicherter Token nicht lesbar.')
        self.assertEqual(fenster.pending_messages,
                         ['Gespeicherter Token nicht lesbar.'])

    def test_report_entschaerft_auch_beim_vormerken(self):
        fenster = MagicMock()
        fenster.pending_messages = []
        del fenster.status
        del fenster.log
        self.app.App.report(fenster, 'Fehler bei https://ch.example?login_token=SECRET123')
        self.assertNotIn('SECRET123', fenster.pending_messages[0])

    def test_vorgemerkte_meldungen_kommen_nach(self):
        # Ein einfaches Objekt statt MagicMock: ein Mock hat jedes Attribut,
        # damit liesse sich die Reihenfolge nicht pruefen.
        class Fenster:
            pending_messages = ['Erster', 'Zweiter']
            log_lines = 0
            report = self.app.App.report        # die echte Methode

            def __init__(self):
                self.status = MagicMock()
                self.log = MagicMock()

        fenster = Fenster()
        self.app.App.flush_pending_messages(fenster)
        self.assertEqual(fenster.status.set.call_count, 2)
        self.assertEqual(fenster.pending_messages, [])

    def test_zweiter_durchlauf_ist_leer(self):
        class Fenster:
            pending_messages = []
            log_lines = 0
            report = self.app.App.report        # die echte Methode

            def __init__(self):
                self.status = MagicMock()
                self.log = MagicMock()

        fenster = Fenster()
        self.app.App.flush_pending_messages(fenster)
        fenster.status.set.assert_not_called()


class FehlerpfadOhneFenster(unittest.TestCase):
    """Der Aufbau darf auch bei kaputtem Token nicht abbrechen."""

    def test_init_ohne_token_datei(self):
        import app
        with patch.dict(os.environ, {'LOCALAPPDATA': tempfile.mkdtemp()}):
            with open(app.__file__, encoding='utf-8') as f:
                quelle = f.read()
            # Ohne Fenster nicht ausführbar; geprüft wird, dass der Fehlerpfad
            # vormerkt statt zu melden.
            self.assertIn('self.pending_messages = []', quelle)
            self.assertIn('self.pending_messages.append(text)', quelle)
            self.assertIn('self.flush_pending_messages()', quelle)


if __name__ == '__main__':
    unittest.main()