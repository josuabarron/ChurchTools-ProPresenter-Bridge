"""Tests für den Oberflächenaufbau: was sichtbar ist, was versteckt liegt.

Legt echte Tk-Widgets an (das ist der Prüfgegenstand), hält das Fenster aber
weit außerhalb des Bildschirms. Kein MIDI-Port, keine Einstellungsdatei des
Nutzers: LOCALAPPDATA zeigt auf einen temporären Ordner.

Aufbau von oben nach unten: ChurchTools, MIDI-Sends, Agenda, MIDI-Port.
Ein Statuszeile gibt es nicht mehr; Meldungen stehen im Diagnose-Log des
versteckten Menüs (drei Klicks zwischen Hilfe und Beenden).
"""
import json
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as bridge


class FakeMidi:
    handle = None

    def devices(self):
        return [(0, 'ChurchTools Bridge')]

    def close(self):
        pass


class UnechtesSymbol:
    """Ersatz für das Infobereich-Symbol: tut so, als ließe es sich nicht anlegen."""

    def __init__(self, *args, **kwargs):
        pass

    def install(self):
        return False


def visible(widget):
    """Sichtbar heißt: im Elternteil eingeplant und alle Vorfahren ebenso."""
    eltern = widget
    while eltern is not None:
        if eltern.winfo_manager() == 'pack' and not eltern.pack_info():
            return False
        eltern = eltern.master
    return widget.winfo_manager() == 'pack'


class Fenster(unittest.TestCase):
    """Einmal ein echtes Fenster bauen, dann daran prüfen."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix='ctp-fenster-')
        os_environ = patch.dict('os.environ', {'LOCALAPPDATA': cls.folder})
        os_environ.start()
        cls.addClassCleanup(os_environ.stop)

    def setUp(self):
        self.patches = [
            # Feste Reihenfolge: erst die Randbedingungen, dann das Fenster.
            patch.object(bridge, 'Midi', lambda: FakeMidi()),
            patch.object(bridge.loopmidi, 'port_visible', lambda name: True),
            patch.object(bridge.loopmidi, 'installed', lambda: True),
            patch.object(bridge.tray, 'TrayIcon', UnechtesSymbol),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.root = tk.Tk()
        self.addCleanup(self.schliessen)
        # Nicht withdraw(): ein zurückgezogenes Fenster bekommt keine Größen,
        # dann sind alle Lageprüfungen wertlos. Stattdessen weit außerhalb.
        self.root.geometry('760x560+-3000+-3000')
        self.window = bridge.App(self.root)
        self.root.update()

    def schliessen(self):
        """Fenster zu wie im Betrieb: quit() bestellt die Nachfrage ab."""
        try:
            self.window.quit()
        except tk.TclError:
            self.root.destroy()

    # ------------------------------------------------------------- Werkzeuge

    def finden(self, eltern, art):
        """Alle Widgets einer Art – auch in Unterrahmen."""
        gefunden = []
        for kind in eltern.winfo_children():
            if isinstance(kind, art):
                gefunden.append(kind)
            gefunden += self.finden(kind, art)
        return gefunden

    def knopf(self, text, eltern):
        """Ersten Knopf mit dieser Beschriftung finden – auch in Unterrahmen."""
        for kind in self.finden(eltern, tk.ttk.Button):
            if kind.cget('text') == text:
                return kind
        return None

    def rahmen(self, name):
        """Ein Abschnitt im Hauptbereich, über seine Überschrift."""
        for art in self.finden(self.window.main, tk.ttk.LabelFrame):
            if art.cget('text') == name:
                return art
        self.fail(f'Abschnitt fehlt: {name}')

    def texte(self):
        gefunden = []

        def sammeln(widget):
            for kind in widget.winfo_children():
                try:
                    gefunden.append(str(kind.cget('text')))
                except tk.TclError:
                    pass
                sammeln(kind)
        sammeln(self.root)
        return gefunden

    # --------------------------------------------------------------- Felder

    def test_obere_felder_vollstaendig(self):
        """URL, Token, User-ID und Notes-Größe gehören ins Fenster."""
        for schluessel in ('api', 'token', 'user', 'font'):
            with self.subTest(feld=schluessel):
                self.assertIn(schluessel, self.window.vars)

    def test_ohne_tageszahl_und_entprellzeit(self):
        """Weder als Feld noch als Text – die Bridge setzt sie selbst."""
        for schluessel in ('days', 'debounce', 'filter'):
            self.assertNotIn(schluessel, self.window.vars)

    def test_token_feld_ist_verdeckt(self):
        felder = self.finden(self.rahmen('ChurchTools'), tk.ttk.Entry)
        verdeckt = [f for f in felder if f.cget('show')]
        self.assertEqual(len(verdeckt), 1, 'genau ein verdecktes Feld (Token)')
        self.assertEqual(str(verdeckt[0].cget('textvariable')), str(self.window.vars['token']))

    def test_verstecktes_menue_enthaelt_port_und_kanal(self):
        self.assertEqual(sorted(self.window.vars)[4:] if False else
                         sorted(set(self.window.vars) - {'api', 'token', 'user', 'font'}),
                         ['channel', 'port'])

    # ------------------------------------------------------------ Anordnung

    def test_anordnung_der_abschnitte(self):
        """Erst ChurchTools, dann Sends, dann Agenda."""
        namen = [k.cget('text') for k in self.finden(self.window.main, tk.ttk.LabelFrame)]
        self.assertEqual(namen, ['ChurchTools', 'MIDI-Sends', 'Agenda'])
        y = [k.winfo_rooty() for k in self.finden(self.window.main, tk.ttk.LabelFrame)]
        self.assertEqual(y, sorted(y), 'Rahmen stehen in falscher Reihenfolge')
        # Autostart und MIDI-Port stehen unterhalb der drei Rahmen.
        self.assertGreater(self.window.midi_port.winfo_rooty(), max(y))

    def test_fenster_fasst_den_ganzen_inhalt(self):
        """Der gefundene Fehler: mit fester Groesse lag die Fußzeile außerhalb.

        Das Fenster wird beim Aufbau aus dem Inhalt bemessen (size_to_content).
        Kommt eine Zeile hinzu oder geht das Log auf, muss es nachwachsen –
        sonst sind die Knöpfe unten nicht mehr erreichbar.
        """
        def passt(was):
            self.root.update_idletasks()
            self.root.update()
            noetig = self.root.winfo_reqheight()
            if self.root.winfo_screenheight() < noetig:
                self.skipTest(f'Test-Desktop ist zu niedrig: {self.root.winfo_screenheight()} px, benötigt {noetig} px')
            self.assertGreaterEqual(
                self.root.winfo_height(), noetig,
                f'{was}: Fenster {self.root.winfo_height()} px, Inhalt braucht {noetig} px')
            # Die Fußzeile muss innerhalb des Fensters liegen.
            unten = self.window.footer.winfo_rooty() + self.window.footer.winfo_height()
            fenster_unten = self.root.winfo_rooty() + self.root.winfo_height()
            self.assertLessEqual(unten, fenster_unten, f'{was}: Fußzeile abgeschnitten')

        passt('beim Start')
        hoehe_start = self.root.winfo_height()
        self.window.add_send({'target': 'Test', 'note': 70})
        passt('nach einer Zeile mehr')
        hoehe_mit_zeile = self.root.winfo_height()
        self.assertGreater(hoehe_mit_zeile, hoehe_start, 'Fenster wuchs nicht mit')
        self.window.show_hidden(True)
        passt('mit offenem Log')
        hoehe_offen = self.root.winfo_height()
        self.assertGreater(hoehe_offen, hoehe_mit_zeile, 'Fenster wuchs fürs Log nicht')
        self.window.show_hidden(False)
        passt('mit geschlossenem Log')
        self.assertLess(self.root.winfo_height(), hoehe_offen,
                        'Fenster bleibt nach dem Zuklappen zu groß')

    def test_fenster_waechst_auch_bei_offenem_log(self):
        """Das Log darf die unterste Send-Zeile nicht verdecken."""
        self.window.show_hidden(True)
        self.root.update_idletasks()
        self.root.update()
        if self.root.winfo_screenheight() < self.root.winfo_reqheight():
            self.skipTest(
                f'Test-Desktop ist zu niedrig: {self.root.winfo_screenheight()} px, '
                f'benötigt {self.root.winfo_reqheight()} px'
            )
        unten_add = self.window.add_button.winfo_rooty()
        self.assertLessEqual(unten_add, self.window.hidden.winfo_rooty(),
                             'Log überdeckt den Hinzufügen-Knopf')

    def test_gesperrte_agenden_bei_den_churchtools_einstellungen(self):
        """Der Haken gehört in den ChurchTools-Rahmen, nicht zu den Sends."""
        im_rahmen = [w.cget('text') for w in
                     self.finden(self.rahmen('ChurchTools'), tk.ttk.Checkbutton)]
        self.assertIn('Nur gesperrte Agenden', im_rahmen)

    def test_agenda_auswahl_oben_in_den_agenda_einstellungen(self):
        agenda = self.rahmen('Agenda')
        self.assertIs(self.window.eventbox.master.master, agenda)
        knoepfe = [w.cget('text') for w in self.finden(agenda, tk.ttk.Button)]
        for text in ('CT-URL kopieren', 'Line-URL kopieren', 'Notes-URL kopieren'):
            self.assertIn(text, knoepfe)
        texte = [w.cget('text') for w in self.finden(agenda, tk.ttk.Label)]
        self.assertIn('Notes-Schriftgröße', texte)
        self.assertIn('Event', texte)

    def test_midi_port_ohne_rahmen_und_titel(self):
        """Kein Kasten um den MIDI-Port, kein Titel 'sendet hierhin'."""
        self.assertEqual(self.window.midi_port.winfo_class(), 'TFrame')
        texte = [w.cget('text') for w in self.finden(self.window.midi_port, tk.ttk.Label)]
        self.assertIn('MIDI-Port', texte)
        alle = self.texte()
        self.assertNotIn('MIDI-Port (ProPresenter sendet hierhin)', alle)

    def test_keine_zeile_mehr_oben(self):
        """Die Statuszeile ist weg; Meldungen stehen im Log (und im Symbol)."""
        self.assertFalse(hasattr(self.window, 'status_label'))
        # Der Status selbst wird weitergeführt – das Infobereich-Symbol braucht ihn.
        self.assertIsInstance(self.window.status, tk.StringVar)

    # ------------------------------------------------------ Verstecktes Menü

    def test_menue_wartet_auf_drei_klicks(self):
        self.assertFalse(visible(self.window.hidden))
        self.window.tap()
        self.window.tap()
        self.assertFalse(visible(self.window.hidden))
        self.window.tap()
        self.root.update_idletasks()
        self.assertTrue(visible(self.window.hidden))
        for _ in range(3):
            self.window.tap()
        self.root.update_idletasks()
        self.assertFalse(visible(self.window.hidden))

    def test_log_liegt_im_versteckten_menue(self):
        self.assertIs(self.window.log.master, self.window.hidden)

    def test_log_sitzt_unten_und_die_einstellungen_darueber(self):
        """Ein Log, der je nach Zeilenzahl springt, wäre unbrauchbar."""
        self.window.show_hidden(True)
        self.root.update()
        felder = self.finden(self.window.hidden, tk.ttk.Entry)
        self.assertEqual([f.get() for f in felder],
                         [str(self.window.config['port']), str(self.window.config['channel'])])
        for feld in felder:
            self.assertLess(feld.winfo_rooty() + feld.winfo_height(),
                            self.window.log.winfo_rooty())
        self.assertLess(self.window.log.winfo_rooty(), self.window.log.winfo_rooty()
                        + self.window.log.winfo_height())

    def test_fenster_bleibt_lesbar_wenn_das_menue_aufgeht(self):
        """Der Log darf die unterste Send-Zeile nicht verdecken."""
        self.window.show_hidden(True)
        self.root.update()
        if self.root.winfo_screenheight() < self.root.winfo_reqheight():
            self.skipTest(
                f'Test-Desktop ist zu niedrig: {self.root.winfo_screenheight()} px, '
                f'benötigt {self.root.winfo_reqheight()} px'
            )
        unten = self.window.add_button.winfo_rooty() + self.window.add_button.winfo_height()
        self.assertLessEqual(unten, self.window.hidden.winfo_rooty())

    def test_log_knopf_sitzt_bei_der_diagnose(self):
        """Der Knopf gehört zur Log-Sektion, nicht mehr in die Fußzeile."""
        self.assertIsNone(self.knopf('Log kopieren', self.window.footer))
        self.assertIsNotNone(self.knopf('Log kopieren', self.window.hidden))

    def test_fußzeile_ohne_erklaertext(self):
        texte = [w.cget('text') for w in self.finden(self.window.footer, tk.ttk.Label)]
        self.assertNotIn('Speichern & Neustart', texte)

    # ------------------------------------------------------------ Send-Zeilen

    def test_sends_sind_felder(self):
        self.assertFalse(hasattr(self.window, 'sends'))
        self.assertEqual(len(self.window.send_rows), 3)

    def test_zeile_entfernen_und_anhaengen(self):
        self.assertEqual(len(self.window.send_rows), 3)
        neu = self.window.add_send()
        self.root.update_idletasks()
        self.assertEqual(len(self.window.send_rows), 4)
        self.assertEqual(neu['note'].get(), '63')       # 60–62 sind belegt
        self.window.remove_send(neu)
        self.root.update_idletasks()
        self.assertEqual(len(self.window.send_rows), 3)

    def test_jede_zeile_hat_ziel_note_play_und_kreuz(self):
        for zeile in self.window.send_rows:
            with self.subTest(ziel=zeile['target'].get()):
                knoepfe = [w.cget('text') for w in self.finden(zeile['frame'], tk.ttk.Button)]
                self.assertIn(bridge.PLAY, knoepfe)
                self.assertIn('\u2715', knoepfe)

    def test_play_steht_zwischen_note_und_kreuz(self):
        """Der Knopf sitzt rechts der Note und links vom Entfernen-Kreuz."""
        zeile = self.window.send_rows[0]
        knoepfe = {w.cget('text'): w for w in self.finden(zeile['frame'], tk.ttk.Button)}
        note = self.finden(zeile['frame'], tk.ttk.Entry)[1]
        play, kreuz = knoepfe[bridge.PLAY], knoepfe['\u2715']
        self.assertGreater(play.winfo_rootx(), note.winfo_rootx())
        self.assertGreater(kreuz.winfo_rootx(), play.winfo_rootx())

    def test_play_ohne_ziel_sagt_was_fehlt(self):
        zeile = self.window.send_rows[0]
        zeile['target'].set('')
        zeile['play'].invoke()
        self.root.update()
        self.assertIn('kein Ziel', self.window.log.get('1.0', 'end'))

    def test_play_ohne_start_verlangt_den_start(self):
        zeile = self.window.send_rows[0]
        self.assertIsNone(self.window.client)
        zeile['play'].invoke()
        self.root.update()
        self.assertIn('Erst starten', self.window.log.get('1.0', 'end'))

    # ---------------------------------------------------------------- Fußzeile

    def test_neustart_ist_ein_symbol(self):
        self.assertEqual(self.window.start_button.cget('text'), bridge.RELOAD)

    def test_kein_stopp_knopf(self):
        self.assertNotIn('Stopp', self.texte())

    def test_hilfe_und_beenden_liegen_aussen(self):
        """Zwischen beiden muss Platz für die drei Klicks sein."""
        fuss = self.window.tap_spacer.master
        hilfe = self.knopf('Hilfe', fuss)
        beenden = self.knopf('Beenden', fuss)
        self.assertIsNotNone(hilfe)
        self.assertIsNotNone(beenden)
        # Beenden ganz rechts, Hilfe links daneben, die Klickfläche dazwischen.
        self.assertLess(hilfe.winfo_rootx(), beenden.winfo_rootx())
        mitte = self.window.tap_spacer.winfo_rootx()
        self.assertGreater(mitte, hilfe.winfo_rootx())
        self.assertLess(mitte, beenden.winfo_rootx())


class DebugModus(Fenster):
    """Drei Klicks zeigen das Menü – darin jeden Ablauf von Hand auslösen."""

    def knoepfe(self):
        return [k.cget('text') for k in self.finden(self.window.hidden, tk.ttk.Button)]

    def test_ohne_menue_keine_knoepfe(self):
        self.assertFalse(self.window.debug)
        self.assertEqual(self.window.debug_buttons, [])

    def test_drei_klicks_bringen_die_knoepfe(self):
        for _ in range(3):
            self.window.tap()
        self.root.update()
        self.assertTrue(self.window.debug)
        texte = self.knoepfe()
        for erwartet in ('Verbindung prüfen', 'Agenden laden', 'MIDI verbinden',
                         'Diagnose', 'Speichern & Start'):
            self.assertIn(erwartet, texte)

    def test_drei_weitere_klicks_raeumen_sie_weg(self):
        for _ in range(3):
            self.window.tap()
        self.root.update()
        self.assertTrue(self.window.debug_buttons)
        for _ in range(3):
            self.window.tap()
        self.root.update()
        self.assertFalse(self.window.debug)
        self.assertEqual(self.window.debug_buttons, [])
        self.assertIsNone(self.window.debug_frame)

    def test_jeder_knopf_hat_einen_befehl(self):
        for _ in range(3):
            self.window.tap()
        self.root.update()
        for knopf in self.window.debug_buttons:
            self.assertTrue(knopf.cget('command'), f'{knopf.cget("text")} ohne Befehl')

    def test_verbindung_pruefen_reicht_keine_ausnahme_durch(self):
        for _ in range(3):
            self.window.tap()
        self.root.update()
        self.window.debug_connect()
        self.assertIn('Verbindung', self.window.log.get('1.0', 'end'))

    def test_agenden_laden_reicht_keine_ausnahme_durch(self):
        for _ in range(3):
            self.window.tap()
        self.root.update()
        self.window.debug_events()
        self.assertIn('fehlgeschlagen', self.window.log.get('1.0', 'end'))

    def test_notizen_ohne_event_sagt_was_fehlt(self):
        for _ in range(3):
            self.window.tap()
        self.root.update()
        self.window.debug_notes()
        self.assertIn('Event', self.window.log.get('1.0', 'end'))


class PortAkkordeon(Fenster):
    def test_bei_bereitem_port_zugeklappt(self):
        self.assertEqual(self.window.port_summary.cget('text'), '„ChurchTools Bridge“ ist bereit')
        self.window.set_port_open(False)
        self.root.update_idletasks()
        self.assertFalse(visible(self.window.port_body))

    def test_ohne_port_aufgeklappt(self):
        with patch.object(bridge.loopmidi, 'port_visible', lambda name: False):
            self.window.summary_name = None
            self.window.toggle_own()
            self.root.update_idletasks()
        self.assertTrue(visible(self.window.port_body))
        self.assertIn('angelegt', self.window.port_summary.cget('text'))

    def test_dreieck_zeigt_den_zustand(self):
        self.window.set_port_open(True)
        self.assertEqual(self.window.port_toggle.cget('text'), bridge.ARROW[0])
        self.assertEqual(str(self.window.port_toggle.cget('cursor')), 'hand2')
        self.window.set_port_open(False)
        self.assertEqual(self.window.port_toggle.cget('text'), bridge.ARROW[1])

    def test_klick_auf_das_dreieck_klappt_um(self):
        vorher = self.window.port_open
        self.window.toggle_port()
        self.root.update()
        self.assertEqual(self.window.port_open, not vorher)
        self.window.toggle_port()


class SendsLesen(unittest.TestCase):
    def test_gueltige_zeilen(self):
        sends, problem = bridge.read_sends([('zurück', '60'), ('  vor  ', ' 61 ')])
        self.assertIsNone(problem)
        self.assertEqual(sends, [dict(note=60, target='zurück'), dict(note=61, target='vor')])

    def test_leere_zeile_zaehlt_nicht(self):
        sends, problem = bridge.read_sends([('zurück', '60'), ('', '')])
        self.assertIsNone(problem)
        self.assertEqual(len(sends), 1)

    def test_fehler_nennt_die_zeile(self):
        for ziel, note, erwartet in [('', '60', 'Ziel'), ('vor', 'abc', 'MIDI-Note'),
                                     ('vor', '200', 'MIDI-Note'), ('vor', '-1', 'MIDI-Note')]:
            with self.subTest(ziel=ziel, note=note):
                sends, problem = bridge.read_sends([('zurück', '60'), (ziel, note)])
                self.assertIsNone(sends)
                self.assertIn(erwartet, problem)
                self.assertIn('Send 2', problem)


class AlteEinstellungen(unittest.TestCase):
    """Eine settings.json aus einer früheren Fassung darf nichts verlieren."""

    def test_alle_werte_bleiben_erhalten(self):
        with tempfile.TemporaryDirectory() as folder:
            datei = Path(folder) / 'ChurchToolsProPresenterBridge'
            datei.mkdir()
            (datei / 'settings.json').write_text(json.dumps(
                dict(api='https://x.church.tools/api', port=9999, channel=4,
                     days=99, debounce=42, filter='Gottesdienst')), encoding='utf-8')
            root = tk.Tk()
            root.geometry('760x560+-3000+-3000')
            with patch.dict('os.environ', {'LOCALAPPDATA': folder}), \
                    patch.object(bridge, 'Midi', lambda: FakeMidi()), \
                    patch.object(bridge.tray, 'TrayIcon', UnechtesSymbol), \
                    patch.object(bridge.loopmidi, 'port_visible', lambda name: True):
                fenster = bridge.App(root)
                self.addCleanup(fenster.quit)
            root.update()
            # Übernommen wird alles. days/debounce/filter braucht der
            # ChurchTools-Client; sie stehen nur nicht mehr im Fenster.
            self.assertEqual(fenster.config['port'], 9999)
            self.assertEqual(fenster.config['channel'], 4)
            self.assertEqual(fenster.config['api'], 'https://x.church.tools/api')
            self.assertEqual(fenster.config['days'], 99)
            self.assertEqual(fenster.config['debounce'], 42)
            self.assertEqual(fenster.config['filter'], 'Gottesdienst')
            self.assertEqual(fenster.vars['api'].get(), 'https://x.church.tools/api')


if __name__ == '__main__':
    unittest.main()
