"""Windows desktop application. All Tk access stays on the UI thread."""
import argparse
import json
import re
import os
from pathlib import Path
import queue
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.parse import urlsplit
from core import Client, BridgeError
import loopmidi
import setupguide
import tray
from native import Midi, protect
from server import Server

DEFAULT = dict(api='https://example.church.tools/api', user='', midi='ChurchTools Bridge', channel=1,
               port=8765, days=14, filter='', locked=True, debounce=800, font=64, event=None,
               midi_mode='own', midi_own_name='ChurchTools Bridge',
               sends=[dict(note=60, target='zurück'), dict(note=61, target='vor'), dict(note=62, target='3')])

# Ersatz-Knöpfe für Text. Achtung: nicht jede Systemschrift hat jedes Zeichen.
# Tk holt fehlende Zeichen zwar aus einer anderen Schrift nach (nachgemessen
# mit einem Bildschirmabgriff), aber nur die hier geprüften sind gesetzt:
#   ▾ ▸  Dreieck, ▶  Abspielen, ⟳  Neuladen, ✕  Entfernen
ARROW = ('\u25be', '\u25b8')        # offen / zu
RELOAD = '\u27f3'
PLAY = '\u25b6'

OWN_TOOLTIP = ('Dieser Port wird automatisch angelegt. Denselben Namen in ProPresenter als '
               'MIDI-Ausgang auswählen.')


def midi_devices():
    """Alle MIDI-Eingänge laut WinMM."""
    try:
        return [name for _, name in Midi().devices()]
    except BridgeError:
        return []


def choose_mode(config):
    """Betriebsart ohne Zutun des Nutzers wählen.

    Eigener Port ist die Regel: die Bridge legt ihn selbst an. Wer bereits einen
    Port hat (loopMIDI, rtpMIDI oder ein physisches Gerät), bekommt diesen,
    solange er existiert.
    """
    if config.get('midi_mode') not in ('own', 'existing'):
        config['midi_mode'] = 'own'
    if config['midi_mode'] == 'existing' and config.get('midi') not in midi_devices():
        config['midi_mode'] = 'own'
    return config


def validate(config):
    url = urlsplit(config['api'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise BridgeError('Eine HTTPS-API-URL ohne Zugangsdaten, Query oder Fragment eingeben.')
    if config['midi_mode'] not in ('existing', 'own'):
        raise BridgeError('MIDI-Eingang: „Eigener Port“ oder „Vorhandenen Port“ wählen.')
    if config['midi_mode'] == 'own':
        name = loopmidi.clean_name(str(config['midi_own_name']))
        if not name:
            raise BridgeError('Für den eigenen Port einen Namen eingeben.')
        config['midi_own_name'] = name
    for key, low, high in [('channel', 1, 16), ('port', 1024, 65535),
                           ('debounce', 0, 10000), ('font', 12, 300)]:
        try:
            config[key] = int(config[key])
        except (TypeError, ValueError):
            raise BridgeError(f'{key}: Eine ganze Zahl eingeben.') from None
        if not low <= config[key] <= high:
            raise BridgeError(f'{key}: Erlaubt sind {low} bis {high}.')
    if config['user'] and (not str(config['user']).isdigit() or int(config['user']) < 1):
        raise BridgeError('User-ID muss eine positive Zahl sein.')
    seen = set()
    for send in config['sends']:
        if not 0 <= send['note'] <= 127 or send['note'] in seen or not send['target'].strip():
            raise BridgeError('MIDI-Noten: 0–127, keine Duplikate, Ziel darf nicht leer sein.')
        seen.add(send['note'])
    if not seen:
        raise BridgeError('Mindestens einen MIDI-Send eingeben.')
    return config


def read_sends(rows):
    """Liest die Send-Zeilen der Oberfläche: links Ziel, rechts MIDI-Note.

    Rückgabe: (Liste, Fehlertext). Der Fehlertext enthält die betroffene
    Zeilennummer – sonst müsste der Nutzer raten, was falsch ist.
    """
    sends = []
    for number, (target, note) in enumerate(rows, start=1):
        target, note = target.strip(), note.strip()
        if not target and not note:
            continue
        if not target:
            return None, f'Send {number}: Ziel eintragen.'
        if not note.isdigit() or not 0 <= int(note) <= 127:
            return None, f'Send {number}: MIDI-Note als Zahl von 0 bis 127 eintragen.'
        sends.append(dict(note=int(note), target=target))
    return sends, None


class App:
    def __init__(self, root):
        self.root = root
        self.folder = Path(os.environ['LOCALAPPDATA']) / 'ChurchToolsProPresenterBridge'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.config = DEFAULT.copy()
        self.token = ''
        # Meldungen, die vor dem Fensteraufbau anfallen.
        self.pending_messages = []
        try:
            path = self.folder / 'settings.json'
            if path.exists():
                self.config.update(json.loads(path.read_text(encoding='utf-8')))
            path = self.folder / 'token.dpapi'
            if path.exists():
                self.token = protect(path.read_bytes(), decrypt=True).decode()
        except Exception as error:
            # Hier gibt es noch kein Fenster: report() würde auf self.status
            # zugreifen und selbst abstürzen. Deshalb nur vormerken und später
            # ausgeben (siehe flush_startup_messages).
            self.startup_messages = [describe(error)]
        self.messages, self.commands = queue.Queue(), queue.Queue(maxsize=128)
        self.client = None
        self.event_id = None
        self.server = None
        self.midi = Midi()
        self.generation = 0
        self.closed = False
        self.setup_open = False
        self.hidden_visible = False
        self.taps = []
        self.events = []
        self.vars = {}
        self.send_rows = []
        self.tray = None
        self.poll_job = None
        root.title('ChurchTools Bridge · Windows')
        root.minsize(660, 520)
        self.set_window_icon(root)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Bereit')
        # Reihenfolge ist hier entscheidend: die Fußzeile wird zuerst am unteren
        # Rand eingeplant, danach der Hauptbereich. Später schiebt sich das
        # versteckte Menü zwischen beide – ohne etwas zu verdecken.
        self.footer = ttk.Frame(frame)
        self.footer.pack(side='bottom', fill='x', pady=(12, 0))
        self.main = ttk.Frame(frame)
        self.main.pack(fill='both', expand=True)
        # Verstecktes Menü am unteren Fensterrand: dort gehört der Log hin.
        self.hidden = ttk.Frame(frame, padding=(0, 10))
        self.build_hidden()
        self.debug = False
        self.debug_buttons = []
        self.debug_frame = None

        # 1. ChurchTools
        churchtools = ttk.LabelFrame(self.main, text='ChurchTools', padding=10)
        churchtools.pack(fill='x')
        for row, (key, label, geheim) in enumerate([
                ('api', 'API-URL', False),
                ('token', 'Login-Token', True),
                ('user', 'User-ID', False)]):
            ttk.Label(churchtools, text=label).grid(row=row, column=0, sticky='w', pady=3)
            var = tk.StringVar(value=self.token if key == 'token' else self.config[key])
            self.vars[key] = var
            ttk.Entry(churchtools, textvariable=var, show='•' if geheim else '').grid(
                row=row, column=1, sticky='ew', padx=10)
        churchtools.columnconfigure(1, weight=1)
        self.locked = tk.BooleanVar(value=self.config['locked'])
        ttk.Checkbutton(churchtools, text='Nur gesperrte Agenden',
                        variable=self.locked).grid(row=3, column=0, columnspan=2,
                                                   sticky='w', pady=(6, 0))

        # 2. MIDI-Sends
        sends = ttk.LabelFrame(self.main, text='MIDI-Sends', padding=10)
        sends.pack(fill='x', pady=(12, 0))
        ttk.Label(sends, text='Links das Ziel (Zahl, „vor“, „zurück“ oder ein Agenda-Titel), '
                              'rechts die MIDI-Note.', wraplength=680).pack(anchor='w', pady=(0, 6))
        self.rows = ttk.Frame(sends)
        self.rows.pack(fill='x')
        self.show_sends(self.config['sends'])
        self.add_button = ttk.Button(sends, text='Send hinzufügen', command=self.add_send)
        self.finish_sends()

        # 3. Agenda: Auswahl, URLs und Notes-Schriftgröße
        agenda = ttk.LabelFrame(self.main, text='Agenda', padding=10)
        agenda.pack(fill='x', pady=(12, 0))
        zeile = ttk.Frame(agenda)
        zeile.pack(fill='x')
        ttk.Label(zeile, text='Event').pack(side='left')
        self.eventbox = ttk.Combobox(zeile, state='readonly')
        self.eventbox.pack(side='left', fill='x', expand=True, padx=10)
        self.eventbox.bind('<<ComboboxSelected>>', self.select_event)
        urls = ttk.Frame(agenda)
        urls.pack(fill='x', pady=(8, 0))
        for label, suffix in [('CT-URL kopieren', '/live'), ('Line-URL kopieren', '/live/strip'),
                              ('Notes-URL kopieren', '/live/notes')]:
            ttk.Button(urls, text=label, command=lambda s=suffix: self.copy_url(s)).pack(side='left', padx=3)
        # Die Schriftgröße gilt nur für die Notes-Ansicht.
        ttk.Label(urls, text='Notes-Schriftgröße').pack(side='left', padx=(16, 6))
        self.notes_var = tk.StringVar(value=self.config['font'])
        self.vars['font'] = self.notes_var
        ttk.Entry(urls, textvariable=self.notes_var, width=5).pack(side='left')

        # 4. Autostart und MIDI-Port. Beide in einem eigenen Rahmen, damit der
        # Haken den MIDI-Port nicht aus dem Fenster drängt, wenn wenig Platz ist.
        unten = ttk.Frame(self.main)
        unten.pack(fill='x', pady=(12, 0))
        self.autostart = tk.BooleanVar(value=has_autostart())
        ttk.Checkbutton(unten, text='App bei Windows-Anmeldung öffnen', variable=self.autostart,
                        command=self.set_autostart).pack(anchor='w')
        # MIDI-Port ohne Rahmen: nur ein Dreieck und der Zustand, alles Weitere
        # klappt darunter auf.
        self.midi_port = ttk.Frame(unten)
        self.midi_port.pack(fill='x', pady=(10, 0))
        self.build_port()

        footer = self.footer
        self.start_button = ttk.Button(footer, text=RELOAD, width=3, command=self.start)
        self.start_button.pack(side='left')
        # Der Log-Knopf sitzt jetzt bei der Diagnose-Log-Sektion im versteckten
        # Menü. Hier bleibt nur das Übernehmen-Symbol.
        # Von rechts nach links gepackt: Windows setzt jedes weitere Element
        # links vom vorherigen. Die Reihenfolge hier ist also die Anzeige von
        # rechts nach links: Beenden, unsichtbare Fläche, Hilfe.
        ttk.Button(footer, text='Beenden', command=self.quit).pack(side='right')
        # Zwischen Hilfe und Beenden liegen drei unsichtbare Anschläge für das
        # versteckte Menü – so wie drei schnelle Klicks auf der Mac-Fassung.
        self.tap_spacer = tk.Canvas(footer, width=30, height=22, highlightthickness=0, bd=0)
        self.tap_spacer.pack(side='right')
        self.tap_spacer.bind('<Button-1>', self.tap)
        ttk.Button(footer, text='Hilfe', command=self.open_help).pack(side='right')

        root.protocol('WM_DELETE_WINDOW', self.hide)
        threading.Thread(target=self.worker, daemon=True).start()
        self.refresh_ports()
        self.toggle_own()
        self.start_tray()
        # Ganz am Ende, wenn alle Bereiche stehen: das Fenster auf den Inhalt
        # einstellen. Mit einer festen Größe wäre es bei abweichender
        # DPI-Skalierung zu klein, und die Fußzeile läge außerhalb.
        self.size_to_content(min_width=760)
        self.poll_job = self.root.after(100, self.poll)
        if self.token:
            self.root.after(300, self.start)

    # ---------------------------------------------------------------- Aufbau

    def build_port(self):
        """MIDI-Port-Bereich mit Akkordeon-Kopf."""
        header = ttk.Frame(self.midi_port)
        header.pack(fill='x')
        # Kein Knopf: nur ein Dreieck als Klickziel. Ein Knopf brächte einen
        # zweiten Rahmen mit, und der war hier nicht gewünscht.
        self.port_toggle = ttk.Label(header, text=ARROW[1], width=2, cursor='hand2')
        self.port_toggle.pack(side='left')
        self.port_toggle.bind('<Button-1>', lambda event: self.toggle_port())
        ttk.Label(header, text='MIDI-Port').pack(side='left')
        self.port_summary = ttk.Label(header, text='')
        self.port_summary.pack(side='left', padx=10)
        self.port_body = ttk.Frame(self.midi_port)
        self.port_body.pack(fill='x', pady=(10, 0))
        self.config['midi_mode'] = choose_mode(self.config)['midi_mode']
        self.midi_mode = tk.StringVar(value=self.config['midi_mode'])
        ttk.Radiobutton(self.port_body, text='Bridge legt den Port selbst an (empfohlen)',
                        value='own', variable=self.midi_mode,
                        command=self.toggle_own).pack(anchor='w')
        ttk.Radiobutton(self.port_body, text='Bereits vorhandenen Port verwenden (z. B. physisches Gerät)',
                        value='existing', variable=self.midi_mode,
                        command=self.toggle_own).pack(anchor='w')
        ownrow = ttk.Frame(self.port_body)
        ownrow.pack(fill='x', pady=(8, 0))
        self.own_label = ttk.Label(ownrow, text='Name des Ports')
        self.own_label.pack(side='left')
        self.own_name = tk.StringVar(value=self.config['midi_own_name'])
        self.own_entry = ttk.Entry(ownrow, textvariable=self.own_name)
        self.own_entry.pack(side='left', fill='x', expand=True, padx=10)
        ttk.Label(ownrow, text='max. 31 Zeichen').pack(side='right')
        ttk.Label(self.port_body, text=OWN_TOOLTIP, wraplength=680).pack(anchor='w', pady=(4, 0))
        portrow = ttk.Frame(self.port_body)
        portrow.pack(fill='x', pady=(6, 0))
        self.port_label = ttk.Label(portrow, text='Vorhandener Port')
        self.port_label.pack(side='left')
        self.portbox = ttk.Combobox(portrow, state='readonly', width=34)
        self.portbox.pack(side='left', fill='x', expand=True, padx=10)
        self.port_button = ttk.Button(portrow, text='Ports suchen', command=self.refresh_ports)
        self.port_button.pack(side='right')
        self.port_state = ttk.Label(self.port_body, text='', wraplength=680)
        self.port_state.pack(anchor='w', pady=(8, 0))
        buttons = ttk.Frame(self.port_body)
        buttons.pack(fill='x', pady=(6, 0))
        self.setup_button = ttk.Button(buttons, text='MIDI-Port jetzt einrichten',
                                       command=self.open_setup)
        self.setup_button.pack(side='left')
        ttk.Button(buttons, text='Diagnose', command=self.show_diagnosis).pack(side='left', padx=8)
        # Aufgeklappt anfangen: beim ersten Start ist die Einrichtung der Punkt,
        # um den es geht. Steht der Port, klappt update_port_summary gleich zu.
        self.set_port_open(True)

    def build_hidden(self):
        """Verstecktes Menü: erst die seltenen Einstellungen, unten der Log.

        Der Log sitzt am unteren Rand, damit er an derselben Stelle bleibt, egal
        wie viele Zeilen darüber stehen.
        """
        ttk.Separator(self.hidden, orient='horizontal').pack(fill='x', pady=(0, 8))
        ttk.Label(self.hidden, text='Erweiterte Einstellungen').pack(anchor='w', pady=(0, 6))
        grid = ttk.Frame(self.hidden)
        grid.pack(fill='x')
        for row, (key, label) in enumerate([('port', 'Lokaler HTTP-Port'),
                                            ('channel', 'MIDI-Kanal (1–16)')]):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky='w', pady=3)
            var = tk.StringVar(value=self.config[key])
            self.vars[key] = var
            ttk.Entry(grid, textvariable=var, width=12).grid(row=row, column=1, sticky='w', padx=10)
        ttk.Label(grid, text='Die Einstellungen für die Übertragung stehen oben im Fenster.',
                  wraplength=600).grid(row=2, column=0, columnspan=2, sticky='w', pady=(6, 0))
        logkopf = ttk.Frame(self.hidden)
        logkopf.pack(fill='x', pady=(12, 4))
        ttk.Label(logkopf, text='Diagnose-Log').pack(side='left')
        ttk.Button(logkopf, text='Log kopieren', command=self.copy_log).pack(side='right')
        ttk.Button(logkopf, text='Log leeren', command=self.clear_log).pack(side='right', padx=6)
        self.log = tk.Text(self.hidden, height=6, state='disabled', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True)
        # Jetzt stehen status und log. Meldungen aus dem Aufbau nachtragen.
        self.flush_pending_messages()

    def flush_pending_messages(self):
        """Gibt Meldungen aus, die vor dem Fensteraufbau angefallen sind.

        In __init__ gibt es status und log noch nicht; sie wurden deshalb
        vorgemerkt. Ohne das bliebe etwa ein nicht ladbarer Token stumm.
        """
        nachzutragen = list(getattr(self, 'pending_messages', []))
        self.pending_messages = []
        for text in nachzutragen:
            self.report(text)

    # ------------------------------------------------------------- Versteckt

    def tap(self, event=None):
        """Drei Klicks zwischen Hilfe und Beenden holen das Menü hervor."""
        now = time.monotonic()
        self.taps = [stamp for stamp in self.taps if now - stamp < 1.5]
        self.taps.append(now)
        if len(self.taps) >= 3:
            self.taps = []
            self.show_hidden(not self.hidden_visible)

    def show_hidden(self, visible=True):
        self.hidden_visible = bool(visible)
        if self.hidden_visible:
            # Über der Fußzeile, unter dem Hauptbereich.
            self.hidden.pack(side='bottom', fill='x', before=self.main)
            # Platz schaffen: sonst quetscht Tk den Hauptbereich zusammen und
            # die unterste Send-Zeile verschwindet hinter dem Log.
            self.report('Diagnose-Log und erweiterte Einstellungen eingeblendet.')
        else:
            self.hidden.pack_forget()
        # Erst die Knöpfe aufbauen, dann messen: das Fenster muss auch den
        # Bereich 'Manuell auslösen' fassen, der hier erst entsteht.
        self.toggle_debug(self.hidden_visible)
        self.grow_for_hidden(shrink=not self.hidden_visible)

    # ------------------------------------------------------------------ Debug

    def toggle_debug(self, on):
        """Im versteckten Menü zusätzlich jeden Ablauf von Hand auslösbar.

        Die Knöpfe entstehen erst hier: sie gehören nicht zur normalen
        Oberfläche und sollen sie auch nicht belasten.
        """
        self.debug = bool(on)
        if not self.debug:
            for knopf in self.debug_buttons:
                knopf.destroy()
            self.debug_buttons = []
            if self.debug_frame is not None:
                self.debug_frame.destroy()
                self.debug_frame = None
            return
        if self.debug_buttons:
            return
        rahmen = ttk.LabelFrame(self.hidden, text='Manuell auslösen', padding=10)
        rahmen.pack(fill='x', pady=(12, 0))
        # Ein Knopf je Ablauf, den die Bridge sonst von selbst fährt.
        ablauf = [
            ('Verbindung prüfen', self.debug_connect),
            ('Agenden laden', self.debug_events),
            ('MIDI verbinden', self.debug_midi),
            ('Ports suchen', self.refresh_ports),
            ('MIDI-Port einrichten', self.open_setup),
            ('Diagnose', self.show_diagnosis),
            ('CT-URL kopieren', lambda: self.copy_url('/live')),
            ('Notizen anzeigen', self.debug_notes),
            ('Diagnose-Log kopieren', self.copy_log),
            ('Log leeren', self.clear_log),
            ('Speichern & Start', self.start),
        ]
        for index, (text, befehl) in enumerate(ablauf):
            knopf = ttk.Button(rahmen, text=text, command=befehl)
            knopf.grid(row=index // 3, column=index % 3, sticky='ew', padx=3, pady=3)
            self.debug_buttons.append(knopf)
        for spalte in range(3):
            rahmen.columnconfigure(spalte, weight=1)
        self.debug_frame = rahmen
        self.report('Debug-Modus: Abläufe von Hand auslösbar.')

    def debug_connect(self):
        """Prüft den Zugang, ohne den Betrieb zu starten."""
        try:
            self.client = Client(dict(self.config, **{
                k: v.get().strip() for k, v in self.vars.items()}), self.vars['token'].get().strip())
            self.client.request('/whoami')
            self.report('Verbindung steht · Anmeldung akzeptiert.')
        except Exception as error:
            self.report(f'Verbindung fehlgeschlagen: {error}')

    def debug_events(self):
        """Lädt die Agenden einzeln und zeigt, was herauskommt."""
        try:
            config, device = self.read_config()
            client = Client(config, self.vars['token'].get().strip())
            events = client.events()
            self.report(f'{len(events)} Agenda(s) gefunden: '
                        + ', '.join(e.get('name', '?') for e in events[:4]))
        except Exception as error:
            self.report(f'Laden fehlgeschlagen: {error}')

    def debug_midi(self):
        """Öffnet den MIDI-Eingang von Hand."""
        self.config.update({k: v.get().strip() for k, v in self.vars.items()})
        self.config['midi'] = loopmidi.clean_name(self.own_name.get()) or setupguide.DEFAULT_PORT
        self.open_input()

    def debug_notes(self):
        """Holt genau die Daten, die die Notes-Ansicht anzeigt."""
        if not self.client or not self.event_id:
            self.report('Erst ein Event auswählen (Agenda-Bereich).')
            return
        try:
            daten = self.client.snapshot(self.event_id)
            self.report('Jetzt: ' + (daten.get('current') or '—')
                        + ' · Notizen: ' + (daten.get('notes') or '—'))
        except Exception as error:
            self.report(f'Notizen nicht abrufbar: {error}')

    def size_to_content(self, min_width=None, grow_only=True):
        """Fenster so weit aufziehen, dass der Inhalt vollständig sichtbar ist.

        Warum nicht eine feste Größe: die nötige Höhe hängt von DPI-Skalierung
        und Zeichensatz ab. Bei 133 % Skalierung braucht dasselbe Layout rund
        23 px mehr als bei 100 % – mit einer festen Zahl lag die Fußzeile
        deshalb außerhalb des Fensters und war nicht erreichbar.

        grow_only=True lässt ein vom Nutzer vergrößertes Fenster in Ruhe und
        zieht nur nach, wenn der Inhalt nicht mehr hineinpasst.

        Tk kennt die gewünschte Höhe erst, wenn die Kinder eingeplant sind;
        deshalb das update_idletasks() davor.
        """
        self.root.update_idletasks()
        hoehe = self.root.winfo_reqheight()
        breite = self.root.winfo_width()
        if breite <= 1:                     # vor dem ersten Zeichnen
            breite = min_width or self.root.winfo_reqwidth()
        zu_schmal = bool(min_width) and breite < min_width
        if zu_schmal:
            breite = min_width
        passt = self.root.winfo_height() >= hoehe
        # Beim Wachsen ein vom Nutzer vergrößertes Fenster in Ruhe lassen;
        # beim Schrumpfen (Log zu) bewusst kleiner werden.
        if grow_only and not zu_schmal and passt:
            return
        self.root.geometry(f'{breite}x{hoehe}')

    def grow_for_hidden(self, shrink=False):
        """Nach dem Ein-/Ausblenden des versteckten Menüs nachziehen.

        Beim Aufklappen darf das Fenster nur wachsen (sonst zappelt es
        beim Tippen). Beim Zuklappen muss es dagegen wieder kleiner
        werden – sonst bliebe eine leere Fläche stehen, wo der Log war.
        """
        self.size_to_content(grow_only=not shrink)

    # ------------------------------------------------------ Sends als Felder

    def show_sends(self, sends):
        """Zeilen mit Ziel, MIDI-Note und Löschen-Knopf aufbauen."""
        self.clear_sends()
        for send in sends:
            self.add_send(send)

    def clear_sends(self):
        for row in self.send_rows:
            row['frame'].destroy()
        self.send_rows = []

    def next_note(self):
        """Erste freie Note – die Vorgabe soll mit keiner Zeile kollidieren."""
        used = {int(note) for _, note in self.collect_sends() if note.isdigit()}
        return next((note for note in range(60, 128) if note not in used), 60)

    def add_send(self, send=None):
        """Neue Zeile anlegen. Ohne Vorlage mit der nächsten freien Note."""
        send = send or {}
        target = tk.StringVar(value=send.get('target', ''))
        note = tk.StringVar(value=str(send.get('note', self.next_note())))
        row = ttk.Frame(self.rows)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text='Ziel').pack(side='left')
        ttk.Entry(row, textvariable=target).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Label(row, text='MIDI-Note').pack(side='left')
        ttk.Entry(row, textvariable=note, width=6).pack(side='left', padx=8)
        record = dict(frame=row, target=target, note=note)
        # Abspielen: führt genau diesen Send aus, ohne auf MIDI zu warten.
        play = ttk.Button(row, text=PLAY, width=3, command=lambda: self.run_send(record))
        play.pack(side='left')
        record['play'] = play
        ttk.Button(row, text='\u2715', width=3,
                   command=lambda: self.remove_send(record)).pack(side='left')
        self.send_rows.append(record)
        # Mitwachsen: eine weitere Zeile braucht Platz, sonst wird die
        # Fußzeile aus dem Fenster geschoben.
        self.size_to_content()
        return record

    def finish_sends(self):
        """Hinzufügen-Knopf unter die Zeilen setzen."""
        self.add_button.pack(fill='x', pady=(8, 0))

    def remove_send(self, record):
        for index, row in enumerate(self.send_rows):
            if row is record:
                del self.send_rows[index]
                break
        record['frame'].destroy()
        self.size_to_content()

    def collect_sends(self):
        return [(row['target'].get(), row['note'].get()) for row in self.send_rows]

    def run_send(self, record):
        """Führt einen einzelnen Send aus – wie ein MIDI-Eingang, nur von Hand.

        Die Netzabfrage läuft im Hintergrund: ChurchTools antwortet nicht
        immer sofort, und ein hängendes Fenster wäre schlimmer als eine
        späte Meldung. Berichtet wird über dieselbe Schlange wie die
        MIDI-Befehle, damit alles in einer Reihenfolge im Log landet.
        """
        ziel = record['target'].get().strip()
        if not ziel:
            self.report('Dieser Send hat kein Ziel.')
            return
        client, event = self.client, self.event_id
        if not client or not event:
            self.report('Erst starten und ein Event auswählen – dann lässt sich der Send auslösen.')
            return
        generation = self.generation

        def ausfuehren():
            try:
                client.execute(event, ziel)
                self.messages.put((generation, 'status', f'Send „{ziel}“ ausgeführt'))
            except Exception as error:
                self.messages.put((generation, 'status', str(error) if isinstance(error, BridgeError)
                                   else f'Send „{ziel}“ fehlgeschlagen'))
        threading.Thread(target=ausfuehren, daemon=True).start()

    def open_help(self):
        webbrowser.open(Path(__file__).with_name('help.html').resolve().as_uri())

    # ---------------------------------------------------- MIDI-Port-Akkordeon

    def set_port_open(self, open_):
        """Klappt die Port-Einzelheiten ein oder aus."""
        self.port_open = bool(open_)
        self.port_toggle.configure(text=ARROW[0] if self.port_open else ARROW[1])
        if self.port_open:
            self.port_body.pack(fill='x', pady=(10, 0))
        else:
            self.port_body.pack_forget()

    def toggle_port(self):
        self.set_port_open(not self.port_open)

    def update_port_summary(self):
        """Eine Zeile, die auch eingeklappt sagt, woran der Nutzer ist."""
        if self.midi_mode.get() == 'existing':
            self.port_summary.configure(text='Vorhandener Port wird verwendet')
            return
        name = loopmidi.clean_name(self.own_name.get()) or setupguide.DEFAULT_PORT
        # Gewechselt wird nur, wenn sich der Name ändert: sonst klappte das
        # Akkordeon bei jedem Statuslauf wieder zu, während jemand darin tippt.
        if getattr(self, 'summary_name', None) != name:
            self.summary_name = name
            if loopmidi.port_visible(name):
                self.port_summary.configure(text=f'„{name}“ ist bereit')
                self.set_port_open(False)
            else:
                self.port_summary.configure(text=f'„{name}“ wird beim Start angelegt')
                self.set_port_open(True)

    def set_window_icon(self, root):
        """Setzt das Fenstersymbol (sonst zeigt Windows das Standardsymbol)."""
        pfad = tray.assets_dir() / 'app.ico'
        if pfad.exists():
            try:
                root.iconbitmap(default=str(pfad))
            except tk.TclError:
                pass

    def start_tray(self):
        """Legt das Symbol im Infobereich an. Fehlt es, läuft die App normal weiter."""
        try:
            self.tray = tray.TrayIcon(tooltip='ChurchTools Bridge',
                                      on_open=self.show, on_quit=self.quit)
            if not self.tray.install():
                self.tray = None
        except Exception:
            self.tray = None

    def sync_tray(self):
        """Führt Symbol und Zustand zusammen: grün, wenn die Bridge arbeitet."""
        if not self.tray:
            return
        try:
            aktiv = bool(self.client) and self.midi.handle
            text = self.status.get() or ('Bridge läuft' if aktiv else 'Bridge gestoppt')
            self.tray.set_online(aktiv, f'ChurchTools Bridge · {text}')
            self.tray.pump()
        except Exception:
            pass

    def hide(self):
        """Fenster in den Infobereich legen – die Bridge läuft weiter."""
        if self.tray:
            self.root.withdraw()
            self.report('Bridge läuft im Infobereich neben der Uhr weiter.')
        else:
            self.quit()

    def show(self):
        """Fenster wieder hervorholen."""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def report(self, text):
        # Jede Meldung laeuft hier durch und wird entschaerft: das Log laesst
        # sich mit einem Knopf in die Zwischenablage kopieren, und fremde
        # Fehlertexte koennen URLs mit Tokens enthalten.
        text = redact(str(text))
        # Während des Aufbaus (__init__) gibt es noch kein Fenster. Dann nur
        # vormerken, statt auf nicht vorhandene Widgets zuzugreifen.
        if not hasattr(self, 'status') or not hasattr(self, 'log'):
            self.pending_messages.append(text)
            return
        self.status.set(text)
        self.log.configure(state='normal')
        self.log_lines = getattr(self, 'log_lines', 0) + 1
        self.log.insert('end', time.strftime('%H:%M:%S ') + text + '\n')
        if self.log_lines > 300:
            self.log.delete('1.0', '2.0')
            self.log_lines = 299
        self.log.see('end')
        self.log.configure(state='disabled')

    def toggle_own(self):
        own = self.midi_mode.get() == 'own'
        self.portbox.configure(state='disabled' if own else 'readonly')
        self.port_button.state(['disabled'] if own else ['!disabled'])
        self.own_entry.configure(state='normal' if own else 'disabled')
        self.update_port_state()

    def update_port_state(self):
        """Sagt in einem Satz, woran der Nutzer ist."""
        self.update_port_summary()
        if self.midi_mode.get() == 'existing':
            self.port_state.configure(text='Vorhandenen MIDI-Eingang auswählen.')
            return
        name = loopmidi.clean_name(self.own_name.get()) or setupguide.DEFAULT_PORT
        if loopmidi.port_visible(name):
            self.port_state.configure(text=f'Port „{name}“ ist bereit. In ProPresenter als '
                                           f'MIDI-Ausgang wählen.')
        elif not loopmidi.installed():
            self.port_state.configure(text='Noch nicht eingerichtet. „MIDI-Port jetzt einrichten“ '
                                           'drücken – die Bridge erledigt alles.')
        else:
            self.port_state.configure(text=f'Port „{name}“ wird beim Start der Bridge angelegt.')

    def refresh_ports(self):
        try:
            self.devices = self.midi.devices()
            self.portbox['values'] = [f'{name} [{index}]' for index, name in self.devices]
            selected = next((i for i, (_, name) in enumerate(self.devices)
                             if name == self.config['midi']), -1)
            self.portbox.set('')
            if selected >= 0:
                self.portbox.current(selected)
        except BridgeError as error:
            self.report(str(error))

    def open_setup(self):
        """Führt die Einrichtung aus und übernimmt das Ergebnis."""
        if self.setup_open:
            return
        self.setup_open = True
        name = loopmidi.clean_name(self.own_name.get()) or setupguide.DEFAULT_PORT

        def done(port):
            self.own_name.set(port)
            self.midi_mode.set('own')
            self.toggle_own()
            self.refresh_ports()
            self.report(f'MIDI-Port „{port}“ ist bereit. In ProPresenter als MIDI-Ausgang wählen.')
        window = setupguide.SetupWindow(self.root, port_name=name, on_done=done)
        window.window.bind('<Destroy>', lambda event: self.finish_setup())

        def watch():
            if window.window.winfo_exists():
                self.root.after(200, watch)
        self.root.after(200, watch)

    def finish_setup(self):
        self.setup_open = False
        self.update_port_state()

    def show_diagnosis(self):
        """Zeigt in einfachen Worten, was fehlt."""
        name = loopmidi.clean_name(self.own_name.get()) or setupguide.DEFAULT_PORT
        state, message = setupguide.diagnose(name)
        devices = midi_devices()
        lines = [message, '',
                 f'MIDI-Hilfsprogramm installiert: {"ja" if loopmidi.installed() else "nein"}',
                 f'MIDI-Hilfsprogramm läuft: {"ja" if loopmidi.running() else "nein"}',
                 f'Port in Windows eingetragen: {"ja" if name in loopmidi.ports() else "nein"}',
                 f'Port sichtbar: {"ja" if loopmidi.port_visible(name) else "nein"}',
                 f'MIDI-Eingänge: {", ".join(devices) if devices else "keine"}']
        if state != 'ready':
            lines += ['', 'Mit „MIDI-Port jetzt einrichten“ kann die Bridge das beheben.']
        messagebox.showinfo('ChurchTools Bridge – Diagnose', '\n'.join(lines))

    def read_config(self):
        config = dict(self.config, **{k: v.get().strip() for k, v in self.vars.items()})
        if not self.vars['token'].get().strip():
            raise BridgeError('Login-Token eingeben.')
        sends, problem = read_sends(self.collect_sends())
        if problem:
            raise BridgeError(problem)
        config.update(sends=sends, locked=self.locked.get(), midi_mode=self.midi_mode.get(),
                      midi_own_name=loopmidi.clean_name(self.own_name.get()))
        config = validate(config)
        if config['midi_mode'] == 'existing':
            selected = self.portbox.current()
            if selected < 0:
                raise BridgeError('Vorhandenen MIDI-Eingang auswählen. Alternativ „Bridge legt den '
                                  'Port selbst an“.')
            config['midi'] = self.devices[selected][1]
        else:
            config['midi'] = config['midi_own_name']
        return config, config['midi']

    def save(self):
        # Der Token gehört nicht in die Einstellungsdatei: er bekommt eine
        # eigene, mit Windows DPAPI verschlüsselte Datei.
        settings = self.folder / 'settings.json'
        daten = {k: v for k, v in self.config.items() if k != 'token'}
        temporary = settings.with_suffix('.tmp')
        temporary.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(settings)

    def save_token(self):
        """Schreibt den Token verschlüsselt – nach demselben Muster wie save()."""
        temp = self.folder / 'token.tmp'
        temp.write_bytes(protect(self.token.encode()))
        temp.replace(self.folder / 'token.dpapi')

    def start(self):
        try:
            config, device = self.read_config()
            # Der Token wird hier verschlüsselt – er kommt aus dem Feld und
            # wird beim Speichern der Einstellungen abgelegt.
            self.token = config['token']
            self.stop()
            self.config = config
            self.save()
            self.save_token()
            self.client = Client(config, self.token)
            self.server = Server(config['port'], lambda: (self.client, self.event_id, self.config['font']))
            self.generation += 1
            generation, client = self.generation, self.client
            self.start_button.state(['disabled'])
            if config['midi_mode'] == 'own':
                self.report('MIDI-Port wird vorbereitet …')
                self.start_button.state(['!disabled'])
                port = config['midi_own_name']
                if loopmidi.port_visible(port):
                    self.connect_to_midi(port)
                else:
                    if not self.open_setup_window(port):
                        self.report('Die Einrichtung des MIDI-Ports wurde abgebrochen. '
                                    'Ohne Port kann ProPresenter nicht senden.')
                        self.stop()
                        return
                return
            self.report('Verbindung prüfen und Agenden laden …')

            def connect():
                try:
                    self.messages.put((generation, 'events', client.events()))
                except Exception as error:
                    self.messages.put((generation, 'failed', str(error) if isinstance(error, BridgeError)
                                       else 'Event-Suche fehlgeschlagen.'))
            threading.Thread(target=connect, daemon=True).start()
        except Exception as error:
            self.stop()
            self.report(describe(error))

    def open_setup_window(self, port):
        """Öffnet die Einrichtung und wartet, bis der Port steht. True, wenn bereit."""
        self.setup_done = threading.Event()
        self.setup_result = False
        if self.setup_open:
            return False
        self.setup_open = True

        def done(name):
            self.setup_result = True
            self.setup_done.set()
            self.report(f'MIDI-Port „{name}“ ist bereit.')
            self.root.after(50, lambda: self.connect_to_midi(name))

        window = setupguide.SetupWindow(self.root, port_name=port, on_done=done)
        window.window.bind('<Destroy>', lambda event: self.setup_done.set())
        self.root.after(500, lambda: self.wait_for_setup(port))
        return True

    def wait_for_setup(self, port):
        if self.setup_done.is_set():
            self.setup_open = False
            self.update_port_state()
            if not self.setup_result:
                self.stop()
            return
        self.root.after(200, lambda: self.wait_for_setup(port))

    def connect_to_midi(self, port):
        """Verbindet MIDI-Eingang und lädt die Agenden."""
        client = self.client
        if not client:
            return
        generation = self.generation
        self.report('Verbindung prüfen und Agenden laden …')

        def connect():
            try:
                self.messages.put((generation, 'events', client.events()))
            except Exception as error:
                self.messages.put((generation, 'failed', str(error) if isinstance(error, BridgeError)
                                   else 'Event-Suche fehlgeschlagen.'))
        threading.Thread(target=connect, daemon=True).start()

    def stop(self):
        self.generation += 1
        self.midi.close()
        self.event_id = None
        if self.client:
            self.client.cancelled = True
        self.client = None
        if self.server:
            self.server.close()
            self.server = None
        self.eventbox.set('')
        self.eventbox['values'] = []
        self.events = []
        try:
            self.start_button.state(['!disabled'])
        except tk.TclError:
            pass
        self.report('Gestoppt')

    def select_event(self, event=None):
        selected = self.eventbox.current()
        if selected >= 0:
            self.event_id = self.events[selected]['id']
            self.config['event'] = self.event_id
            try:
                self.save()
            except OSError:
                self.report('Event-Auswahl konnte nicht gespeichert werden.')

    def receive(self, note):
        # Called by WinMM: no UI or network work here. Capture selected event at receipt.
        try:
            self.commands.put_nowait((self.generation, self.client, self.event_id, note, time.monotonic()))
        except queue.Full:
            pass

    def worker(self):
        last = {}
        while True:
            generation, client, event, note, stamp = self.commands.get()
            if generation != self.generation or not client or not event or time.monotonic() - stamp > 2:
                continue
            send = next((s for s in client.config['sends'] if s['note'] == note), None)
            if not send:
                continue
            key = generation, note
            previous = last.get(key, -1e9)
            last[key] = stamp
            if stamp - previous < client.config['debounce'] / 1000:
                continue
            if len(last) > 256:
                last = {key: stamp}
            try:
                client.execute(event, send['target'])
                self.messages.put((generation, 'status', f'MIDI {note} · Befehl ausgeführt'))
            except Exception as error:
                self.messages.put((generation, 'status', str(error) if isinstance(error, BridgeError)
                                   else 'Befehl fehlgeschlagen.'))

    def poll(self):
        while not self.messages.empty():
            generation, kind, payload = self.messages.get_nowait()
            if generation != self.generation:
                continue
            if kind == 'events':
                self.start_button.state(['!disabled'])
                self.events = payload
                self.eventbox['values'] = [f"{e.get('startDate', '')} · {e['name']}" for e in self.events]
                if self.events:
                    index = next((i for i, e in enumerate(self.events) if e['id'] == self.config['event']), 0)
                    self.eventbox.current(index)
                    self.select_event()
                self.open_input()
            else:
                self.start_button.state(['!disabled'])
                self.report(payload)
        if not self.closed:
            self.sync_tray()
            self.poll_job = self.root.after(100, self.poll)

    def open_input(self):
        """Öffnet den MIDI-Eingang. WinMM-Indizes können sich zwischendurch geändert haben."""
        try:
            candidates = [(i, name) for i, name in self.midi.devices() if name == self.config['midi']]
            if len(candidates) != 1:
                raise BridgeError('MIDI-Port fehlt oder Name ist nicht eindeutig. Ports prüfen und '
                                  'neu starten.')
            self.midi.open(candidates[0][0], self.config['channel'], self.receive)
            self.report('Bridge läuft · MIDI verbunden' if self.events
                        else 'MIDI verbunden · Kein passendes Event gefunden')
        except BridgeError as error:
            self.report(str(error))

    def copy_url(self, suffix):
        self.root.clipboard_clear()
        self.root.clipboard_append(f"http://127.0.0.1:{self.config['port']}{suffix}")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get('1.0', 'end'))

    def clear_log(self):
        """Log leeren – wie in der macOS-Fassung."""
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.report('Log geleert.')

    def set_autostart(self):
        if not set_autostart(self.autostart.get()):
            self.autostart.set(has_autostart())
            self.report('Windows-Autostart konnte nicht geändert werden.')

    def quit(self):
        self.closed = True
        # Die wartende Nachfrage abbestellen: sie liefe sonst nach dem
        # Zerstören des Fensters an und Tk meldet einen Fehler.
        if self.poll_job:
            try:
                self.root.after_cancel(self.poll_job)
            except tk.TclError:
                pass
            self.poll_job = None
        self.stop()
        if self.tray:
            try:
                self.tray.close()
            except Exception:
                pass
            self.tray = None
        self.root.destroy()


def install_target(explicit=None):
    """Pfad, auf den der Autostart zeigen soll – die dauerhafte EXE.

    Fallstrick: Während der Installation läuft die Bridge aus einer Kopie unter
    %TEMP%\\<Setup-Temp>\\ctp-cmd. Dessen {tmp} ist der private Ordner des Setups
    (is-XXXXXXXX.tmp) und wird nach dem Setup gelöscht. Ein Autostart-Eintrag
    darauf wäre ab dem nächsten Anmelden tot. Der Installer übergibt deshalb
    --app-path mit dem dauerhaften Ziel; nur ohne diesen Hinweis wird geraten.
    """
    import os
    if explicit:
        return Path(explicit)
    if getattr(sys, 'frozen', False):
        running = Path(sys.executable)
        if running.parent.name == 'ctp-cmd':
            programs = os.environ.get('ProgramFiles') or r'C:\Program Files'
            return Path(programs) / 'ChurchTools Bridge' / running.name
        return running
    return Path(sys.executable)


def has_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.QueryValueEx(key, 'ChurchToolsBridge')
            return True
    except OSError:
        return False


def set_autostart(value=True, target=None):
    import subprocess
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if value:
                installed = install_target(target)
                command = [str(installed)]
                if not getattr(sys, 'frozen', False):
                    command.append(str(Path(__file__).resolve()))
                # --tray: beim Anmelden nur das Symbol zeigen, nicht das Fenster.
                command.append('--tray')
                winreg.SetValueEx(key, 'ChurchToolsBridge', 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, 'ChurchToolsBridge')
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def running_paths():
    """Prüft, ob loopMIDI gerade läuft und ob dieser Prozess es beenden kann."""
    return loopmidi.running(), loopmidi.stoppable()


def describe(error):
    """Kurztext für die Oberfläche – fremde Fehler ohne Inhalt.

    Ein BridgeError ist bereits entschärft (kein Antwortkörper, keine URL).
    Bei allem anderen bliebe der Text unkontrolliert; deshalb nur die Art.
    """
    if isinstance(error, BridgeError):
        return redact(str(error))
    return f'{type(error).__name__}: siehe Hilfe'


def redact(text):
    """Entfernt Token und Adressen aus einer Meldung.

    Die Muster decken die Fälle ab, die durch die Bridge laufen: der
    ChurchTools-Token, user_id, Login-Header-Reihen und die Adresse selbst.
    """
    text = re.sub(r'((?:login_)?token=)[^&\s"#]+', r'\1[entfernt]', text, flags=re.I)
    text = re.sub(r'(user_id=)\d+', r'\1[entfernt]', text)
    text = re.sub(r'((?:proxy-)?authorization\s*:)[^,;\r\n]*', r'\1 [entfernt]', text, flags=re.I)
    text = re.sub(r'(\bLogin\s+)([A-Za-z0-9._~+/=-]{16,}'
                     r'|[A-Za-z0-9._~+/=]*[0-9._~+/=-][A-Za-z0-9._~+/=]{8,})',
                     r'\1[entfernt]', text, flags=re.I)
    text = re.sub(r'\bhttps?://\S+', '[Adresse entfernt]', text)
    return text


def write_report(report_file, lines):
    """Schreibt den Bericht an den vom Installer vorgegebenen Pfad.

    Warum nicht einfach Path(...).write_text: der Pfad kommt von außen.
    Zeigt er auf einen Reparse-Point (Symlink/Junction), schriebe der
    Prozess - bei Schritt 1 erhöht - an eine Stelle seiner Wahl.
    """
    if not report_file:
        return False
    pfad = Path(report_file)
    try:
        if pfad.is_symlink():
            return False
        pfad.write_text('\n'.join(lines), encoding='utf-8')
    except OSError:
        return False
    return True


def ensure_midi_program(report_file=None):
    """Nur loopMIDI bereitstellen – läuft erhöht und ohne Fenster.

    Dieser Schritt installiert das Hilfsprogramm maschinenweit. Alles
    Benutzerspezifische (Port-Anlage, Autostart) gehört **nicht** hierher:
    bei einem erhöhten Lauf ist HKCU das Konto des Administrators, nicht das
    des angemeldeten Nutzers.

    Wichtig: der loopMIDI-Installer startet loopMIDI selbst mit – im erhöhten
    Kontext. Danach ließe es sich vom normalen Bridge-Prozess nicht mehr
    beenden, und ein neuer Port würde nicht sichtbar. Läuft es erhöht, wird es
    deshalb hier wieder beendet; die Bridge startet es später als normaler
    Benutzer neu.
    """
    lines = []
    ok = False
    try:
        if loopmidi.installed():
            ok, message = True, 'Das MIDI-Hilfsprogramm ist bereits vorhanden.'
        else:
            lines.append('MIDI-Hilfsprogramm wird installiert …')
            ok, message = loopmidi.install_via_winget()
        lines.append(message)
        # Vom Installer mitgestartetes, erhöht laufendes loopMIDI wieder beenden.
        if loopmidi.running() and not loopmidi.stoppable():
            lines.append('loopMIDI wurde vom Installer erhöht gestartet und wird beendet, '
                         'damit die Bridge es später selbst steuern kann.')
            loopmidi.kill_elevated()
        elif loopmidi.running():
            lines.append('loopMIDI wird beendet; die Bridge startet es später selbst.')
            loopmidi.stop()
    except Exception as error:
        lines.append(f'Installation fehlgeschlagen: {type(error).__name__}: {error}')
    write_report(report_file, lines)
    return 0 if ok else 1


def complete_setup(port_name=setupguide.DEFAULT_PORT, report_file=None, autostart=True,
                   app_path=None):
    """Einrichtung im Benutzerkonto: Port anlegen und Autostart setzen.

    Wird vom Installer mit `runasoriginaluser` aufgerufen, damit der MIDI-Port
    und der Autostart im richtigen Konto landen. Alle Meldungen gehen in
    *report_file*: die EXE läuft ohne Fenster, dort gäbe es sonst keine Ausgabe.

    *app_path* ist die dauerhafte Bridge (Installationsziel). Ohne diesen Hinweis
    müsste der Autostart-Pfad geraten werden – und die laufende EXE liegt während
    des Setups in einem Temp-Ordner, der danach verschwindet.
    """
    lines = []
    ok = False
    try:
        ok, message = setupguide.prepare(port_name, report=lambda text: lines.append(text))
        lines.append(message)
    except Exception as error:  # nie ohne Bericht enden: der Installer wartet darauf
        lines.append(f'Einrichtung fehlgeschlagen: {type(error).__name__}: {error}')
    if not ok:
        lines.append('Der MIDI-Port konnte nicht angelegt werden. Die Bridge holt das beim '
                     'nächsten Start nach: dort „MIDI-Port jetzt einrichten“ drücken.')
    lines.append(apply_autostart(autostart, app_path))
    write_report(report_file, lines)
    return 0 if ok else 1


def uninstall_cleanup(port_name=setupguide.DEFAULT_PORT, report_file=None):
    """Räumt MIDI-Port und Autostart ab – ohne die EXE zu brauchen.

    Wird vom Deinstaller aufgerufen. Ist die Arbeitskopie schon weg, kann kein
    Programm mehr gestartet werden; deshalb entfernt dieser Befehl zuerst den
    Autostart und den Port-Eintrag, und beendet loopMIDI, damit Windows die
    Ports loslässt.
    """
    lines = []
    try:
        lines.append(apply_autostart(False))
    except OSError as error:
        lines.append(f'Autostart konnte nicht entfernt werden: {error}')
    try:
        ok, message = setupguide.teardown(port_name)
        lines.append(message)
    except Exception as error:
        lines.append(f'MIDI-Port konnte nicht entfernt werden: {type(error).__name__}: {error}')
    write_report(report_file, lines)
    return 0


def apply_autostart(enabled=True, app_path=None):
    """Setzt oder entfernt den Autostart. Rückgabe: Klartext für den Bericht."""
    try:
        set_autostart(enabled, app_path)
    except OSError as error:
        return f'Autostart konnte nicht geändert werden: {error}'
    if enabled and has_autostart():
        return f'Autostart eingerichtet ({install_target(app_path)}).'
    if not enabled and not has_autostart():
        return 'Autostart entfernt.'
    return 'Der Autostart konnte nicht geändert werden.'


def main(argv=None):
    parser = argparse.ArgumentParser(description='ChurchTools Bridge')
    parser.add_argument('--ensure-midi-program', action='store_true',
                        help='Nur das MIDI-Hilfsprogramm bereitstellen (erhöht)')
    parser.add_argument('--complete-setup', action='store_true',
                        help='MIDI-Port und Autostart einrichten (im Benutzerkonto)')
    parser.add_argument('--port-name', default=setupguide.DEFAULT_PORT,
                        help='Name des MIDI-Ports')
    parser.add_argument('--report', default=None, help='Ergebnisdatei für den wartenden Prozess')
    parser.add_argument('--autostart', default='1', choices=['0', '1'],
                        help='Autostart einrichten (1) oder nicht (0)')
    parser.add_argument('--app-path', default=None,
                        help='Dauerhafte Bridge (Ziel des Autostart-Eintrags)')
    parser.add_argument('--remove-port', action='store_true', help='MIDI-Port wieder entfernen')
    parser.add_argument('--remove-autostart', action='store_true', help='Autostart entfernen')
    parser.add_argument('--uninstall-cleanup', action='store_true',
                        help='Port und Autostart zur Deinstallation entfernen')
    parser.add_argument('--tray', action='store_true',
                        help='Beim Start nur im Infobereich erscheinen')
    parser.add_argument('--quit', action='store_true',
                        help='Eine laufende Bridge beenden (räumt das Symbol weg)')
    parser.add_argument('--show', action='store_true',
                        help='Fenster einer laufenden Bridge hervorholen')
    arguments = parser.parse_args(argv)
    if arguments.quit:
        # Nur ein Bote: die laufende Bridge beendet sich selbst, damit ihr
        # Symbol neben der Uhr verschwindet statt als Leiche zu bleiben.
        laeuft = tray.Instance.running()
        tray.ask_to_quit()
        if laeuft:
            for _ in range(50):
                if not tray.Instance.running():
                    break
                time.sleep(0.1)
        return 0 if not tray.Instance.running() else 1
    if arguments.show:
        tray.ask_to_show()
        return 0
    if arguments.uninstall_cleanup:
        return uninstall_cleanup(arguments.port_name, arguments.report)
    if arguments.remove_autostart:
        print(apply_autostart(False))
        return 0
    if arguments.remove_port:
        ok, message = setupguide.teardown(arguments.port_name)
        print(message)
        return 0 if ok else 1
    if arguments.ensure_midi_program:
        return ensure_midi_program(arguments.report)
    if arguments.complete_setup:
        return complete_setup(arguments.port_name, arguments.report,
                              arguments.autostart == '1', arguments.app_path)
    # Nur einmal starten. Ein zweiter Doppelklick holt das vorhandene Fenster
    # hervor, statt eine zweite Bridge mit zweitem Symbol anzulegen.
    instance = tray.Instance()
    if not instance.acquire():
        tray.ask_to_show()
        return 0
    root = tk.Tk()
    if os.name != 'nt':
        root.withdraw()
        messagebox.showerror('ChurchTools Bridge',
                             'Diese App benötigt Windows. Für macOS die Swift-App verwenden.')
        root.destroy()
        return 1
    app = App(root)
    if arguments.tray and app.tray:
        # Beim Autostart nicht das Fenster aufdrängen – nur das Symbol.
        root.withdraw()
        app.report('Bridge läuft im Infobereich neben der Uhr.')
    try:
        root.mainloop()
    finally:
        instance.release()
    return 0


if __name__ == '__main__':
    sys.exit(main())