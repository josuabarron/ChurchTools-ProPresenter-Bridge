"""Windows desktop application. All Tk access stays on the UI thread."""
import json
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
from native import Midi, protect
from server import Server

DEFAULT = dict(api='https://example.church.tools/api', user='', midi='ChurchTools Bridge', channel=1,
               port=8765, days=14, filter='', locked=True, debounce=800, font=64, event=None,
               sends=[dict(note=60, target='zurück'), dict(note=61, target='vor'), dict(note=62, target='3')])


def validate(config):
    url = urlsplit(config['api'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise BridgeError('Eine HTTPS-API-URL ohne Zugangsdaten, Query oder Fragment eingeben.')
    for key, low, high in [('channel', 1, 16), ('port', 1024, 65535), ('days', 1, 365),
                           ('debounce', 0, 10000), ('font', 12, 300)]:
        try:
            config[key] = int(config[key])
        except ValueError:
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


class App:
    def __init__(self, root):
        self.root = root
        self.folder = Path(os.environ['LOCALAPPDATA']) / 'ChurchToolsProPresenterBridge'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.config = DEFAULT.copy()
        self.token = ''
        load_error = None
        try:
            path = self.folder / 'settings.json'
            if path.exists():
                self.config.update(json.loads(path.read_text(encoding='utf-8')))
            path = self.folder / 'token.dpapi'
            if path.exists():
                self.token = protect(path.read_bytes(), decrypt=True).decode()
        except Exception:
            load_error = 'Gespeicherte Einstellungen/Token konnten nicht geladen werden. Bitte neu eingeben.'
        self.messages, self.commands = queue.Queue(), queue.Queue(maxsize=128)
        self.client = None
        self.event_id = None
        self.server = None
        self.midi = Midi()
        self.generation = 0
        self.closed = False
        self.events = []
        self.vars = {}
        root.title('ChurchTools Bridge · Windows')
        root.geometry('720x820')
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Bereit · loopMIDI starten und Port auswählen')
        ttk.Label(frame, textvariable=self.status, wraplength=660).pack(anchor='w', pady=(0, 12))
        fields = ttk.Frame(frame)
        fields.pack(fill='x')
        for row, (key, label) in enumerate([
            ('api', 'ChurchTools API-URL'), ('token', 'Login-Token'), ('user', 'ChurchTools User-ID'),
            ('channel', 'MIDI-Kanal (1–16)'), ('port', 'Lokaler HTTP-Port'), ('days', 'Event-Suche: Tage'),
            ('filter', 'Event-Name enthält'), ('debounce', 'Entprellzeit in ms'), ('font', 'Notes-Schriftgröße')]):
            ttk.Label(fields, text=label).grid(row=row, column=0, sticky='w', pady=3)
            var = tk.StringVar(value=self.token if key == 'token' else self.config[key])
            self.vars[key] = var
            ttk.Entry(fields, textvariable=var, show='•' if key == 'token' else '').grid(row=row, column=1, sticky='ew', padx=10)
        fields.columnconfigure(1, weight=1)
        self.locked = tk.BooleanVar(value=self.config['locked'])
        ttk.Checkbutton(frame, text='Nur gesperrte Agenden', variable=self.locked).pack(anchor='w', pady=5)
        portrow = ttk.Frame(frame)
        portrow.pack(fill='x', pady=6)
        ttk.Label(portrow, text='MIDI-Eingang').pack(side='left')
        self.portbox = ttk.Combobox(portrow, state='readonly', width=40)
        self.portbox.pack(side='left', fill='x', expand=True, padx=10)
        ttk.Button(portrow, text='Ports suchen', command=self.refresh_ports).pack(side='right')
        ttk.Label(frame, text='MIDI-Sends: eine Zeile pro Send, Format Note = Ziel').pack(anchor='w')
        self.sends = tk.Text(frame, height=5, font=('Consolas', 11))
        self.sends.pack(fill='x', pady=5)
        self.sends.insert('1.0', '\n'.join(f"{s['note']} = {s['target']}" for s in self.config['sends']))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=6)
        self.start_button = ttk.Button(buttons, text='Speichern & Start / Neustart', command=self.start)
        self.start_button.pack(side='left')
        ttk.Button(buttons, text='Hilfe', command=lambda: webbrowser.open(
            Path(__file__).with_name('help.html').resolve().as_uri())).pack(side='left', padx=8)
        ttk.Button(buttons, text='Stopp', command=self.stop).pack(side='left', padx=8)
        ttk.Button(buttons, text='Beenden', command=self.quit).pack(side='right')
        self.eventbox = ttk.Combobox(frame, state='readonly')
        self.eventbox.pack(fill='x', pady=5)
        self.eventbox.bind('<<ComboboxSelected>>', self.select_event)
        urls = ttk.Frame(frame)
        urls.pack(fill='x', pady=6)
        for label, suffix in [('CT-URL kopieren', '/live'), ('Line-URL kopieren', '/live/strip'), ('Notes-URL kopieren', '/live/notes')]:
            ttk.Button(urls, text=label, command=lambda s=suffix: self.copy_url(s)).pack(side='left', padx=3)
        self.autostart = tk.BooleanVar(value=self.has_autostart())
        ttk.Checkbutton(frame, text='App bei Windows-Anmeldung öffnen', variable=self.autostart,
                        command=self.set_autostart).pack(anchor='w', pady=6)
        ttk.Label(frame, text='Minimieren lässt die Bridge weiterlaufen. Schließen beendet sie.').pack(anchor='w')
        self.log = tk.Text(frame, height=6, state='disabled', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, pady=8)
        ttk.Button(frame, text='Diagnose-Log kopieren', command=self.copy_log).pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW', self.quit)
        threading.Thread(target=self.worker, daemon=True).start()
        self.refresh_ports()
        self.root.after(100, self.poll)
        if load_error:
            self.report(load_error)
        elif self.token:
            self.root.after(300, self.start)

    def report(self, text):
        self.status.set(text)
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S ') + text + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 300:
            self.log.delete('1.0', '2.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh_ports(self):
        try:
            self.devices = self.midi.devices()
            self.portbox['values'] = [f'{name} [{index}]' for index, name in self.devices]
            selected = next((i for i, (_, name) in enumerate(self.devices) if name == self.config['midi']), -1)
            self.portbox.set('')
            if selected >= 0:
                self.portbox.current(selected)
        except BridgeError as error:
            self.report(str(error))

    def read_config(self):
        config = dict(self.config, **{k: v.get().strip() for k, v in self.vars.items() if k != 'token'})
        sends = []
        try:
            for line in self.sends.get('1.0', 'end').splitlines():
                if line.strip():
                    note, target = line.split('=', 1)
                    sends.append(dict(note=int(note.strip()), target=target.strip()))
        except ValueError:
            raise BridgeError('MIDI-Sends im Format 60 = zurück eingeben.') from None
        config.update(sends=sends, locked=self.locked.get())
        selected = self.portbox.current()
        if selected < 0:
            raise BridgeError('loopMIDI starten, Port anlegen und hier auswählen.')
        config['midi'] = self.devices[selected][1]
        if not self.vars['token'].get().strip():
            raise BridgeError('Login-Token eingeben.')
        return validate(config), self.devices[selected][0]

    def save(self):
        settings = self.folder / 'settings.json'
        temporary = settings.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(settings)

    def start(self):
        try:
            config, device = self.read_config()
            encrypted = protect(self.vars['token'].get().strip().encode())
            self.stop()
            self.config = config
            self.save()
            temp = self.folder / 'token.tmp'
            temp.write_bytes(encrypted)
            temp.replace(self.folder / 'token.dpapi')
            self.client = Client(config, self.vars['token'].get().strip())
            self.server = Server(config['port'], lambda: (self.client, self.event_id, self.config['font']))
            self.generation += 1
            generation, client = self.generation, self.client
            self.start_button.state(['disabled'])
            self.report('Verbindung prüfen und Agenden laden …')
            def connect():
                try:
                    self.messages.put((generation, 'events', (client.events(), device)))
                except Exception as error:
                    self.messages.put((generation, 'failed', str(error) if isinstance(error, BridgeError) else 'Event-Suche fehlgeschlagen.'))
            threading.Thread(target=connect, daemon=True).start()
        except Exception as error:
            self.stop()
            self.report(str(error) if isinstance(error, BridgeError) else 'Start fehlgeschlagen. Port belegt oder Einstellungen nicht speicherbar.')

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
        self.start_button.state(['!disabled'])
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
                self.messages.put((generation, 'status', str(error) if isinstance(error, BridgeError) else 'Befehl fehlgeschlagen.'))

    def poll(self):
        while not self.messages.empty():
            generation, kind, payload = self.messages.get_nowait()
            if generation != self.generation:
                continue
            if kind == 'events':
                self.start_button.state(['!disabled'])
                self.events, device = payload
                self.eventbox['values'] = [f"{e.get('startDate', '')} · {e['name']}" for e in self.events]
                if self.events:
                    index = next((i for i, e in enumerate(self.events) if e['id'] == self.config['event']), 0)
                    self.eventbox.current(index)
                    self.select_event()
                try:
                    # Re-enumerate: WinMM device indexes may change during the HTTP lookup.
                    candidates = [(i, name) for i, name in self.midi.devices() if name == self.config['midi']]
                    if len(candidates) != 1:
                        raise BridgeError('MIDI-Port fehlt oder Name ist nicht eindeutig. Ports prüfen und neu starten.')
                    self.midi.open(candidates[0][0], self.config['channel'], self.receive)
                    self.report('Bridge läuft · MIDI verbunden' if self.events else 'MIDI verbunden · Kein passendes Event gefunden')
                except BridgeError as error:
                    self.report(str(error))
            else:
                self.start_button.state(['!disabled'])
                self.report(payload)
        if not self.closed:
            self.root.after(100, self.poll)

    def copy_url(self, suffix):
        self.root.clipboard_clear()
        self.root.clipboard_append(f"http://127.0.0.1:{self.config['port']}{suffix}")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get('1.0', 'end'))

    def has_autostart(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                winreg.QueryValueEx(key, 'ChurchToolsBridge')
                return True
        except OSError:
            return False

    def set_autostart(self):
        import subprocess
        import winreg
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                if self.autostart.get():
                    command = [sys.executable]
                    if not getattr(sys, 'frozen', False):
                        command.append(str(Path(__file__).resolve()))
                    winreg.SetValueEx(key, 'ChurchToolsBridge', 0, winreg.REG_SZ, subprocess.list2cmdline(command))
                else:
                    try:
                        winreg.DeleteValue(key, 'ChurchToolsBridge')
                    except FileNotFoundError:
                        pass
        except OSError:
            self.autostart.set(self.has_autostart())
            self.report('Windows-Autostart konnte nicht geändert werden.')

    def quit(self):
        self.closed = True
        self.stop()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    if os.name != 'nt':
        root.withdraw()
        messagebox.showerror('ChurchTools Bridge', 'Diese App benötigt Windows. Für macOS die Swift-App verwenden.')
        root.destroy()
    else:
        App(root)
        root.mainloop()
