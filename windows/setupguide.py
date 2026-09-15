"""Automatische Einrichtung des MIDI-Ports.

Der Nutzer soll nichts einstellen müssen: dieses Modul installiert loopMIDI bei
Bedarf, legt den Port an, startet loopMIDI und wartet, bis WinMM den Port sieht.

Warum loopMIDI und nicht Microsofts eigener Weg?
------------------------------------------------
Windows kann virtuelle MIDI-Ports nur über „Windows MIDI Services" anlegen. Auf
ausgelieferten Windows-11-PCs ist dieses Feature noch nicht freigeschaltet
(`midi.exe` meldet „feature does not appear to be enabled"; die Freischaltung
kommt erst per Windows-Update). loopMIDI ist deshalb heute der einzige Weg zu
einem Port, den die Bridge selbst anlegt.

loopMIDI wird **nicht mitgeliefert** – es wird über winget installiert
(Verteilung durch den Hersteller) oder vom Hersteller geladen.
"""
import sys
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

import loopmidi

DEFAULT_PORT = 'ChurchTools Bridge'
VENDOR_URL = loopmidi.MANUFACTURER_URL


def diagnose(port_name=DEFAULT_PORT):
    """Ermittelt, was zu tun ist. Rückgabe: (Zustand, Klartext)."""
    port_name = loopmidi.clean_name(port_name) or DEFAULT_PORT
    if not loopmidi.installed():
        return 'install', 'Das Hilfsprogramm für virtuelle MIDI-Ports wird installiert.'
    if loopmidi.port_visible(port_name):
        return 'ready', f'Der MIDI-Port „{port_name}“ ist bereit.'
    if port_name in loopmidi.ports():
        return 'start', f'Der MIDI-Port „{port_name}“ ist eingetragen und wird gestartet.'
    return 'create', f'Der MIDI-Port „{port_name}“ wird angelegt.'


def prepare(port_name=DEFAULT_PORT, report=None, wait=60):
    """Richtet alles ein. Rückgabe: (ok, Meldung)."""
    say = report or (lambda message: None)
    port_name = loopmidi.clean_name(port_name) or DEFAULT_PORT
    if not loopmidi.installed():
        say('Das Hilfsprogramm für virtuelle MIDI-Ports wird installiert …')
        ok, message = loopmidi.install_via_winget()
        if not ok:
            return False, message
        say(message)
    if not loopmidi.port_visible(port_name):
        say(f'Der MIDI-Port „{port_name}“ wird eingerichtet …')
        ok, message = loopmidi.ensure_port(port_name, wait=wait)
        if not ok:
            return False, message
        say(message)
    say(f'Fertig. In ProPresenter „{port_name}“ als MIDI-Ausgang wählen.')
    return True, f'Der MIDI-Port „{port_name}“ ist bereit.'


def teardown(port_name=DEFAULT_PORT):
    """Entfernt den Port wieder. Rückgabe: (ok, Meldung).

    Wird vom Deinstaller aufgerufen und läuft damit erhöht. loopMIDI wird
    deshalb nur beendet, nicht neu gestartet: aus einem erhöhten Prozess heraus
    gestartet, ließe es sich später nicht mehr steuern. Beendet schließt es
    seine Ports – das ist genau der Zweck.
    """
    port_name = loopmidi.clean_name(port_name) or DEFAULT_PORT
    ok, message = loopmidi.forget(port_name)
    if not ok:
        return False, message
    loopmidi.stop()
    return True, f'Der MIDI-Port „{port_name}“ ist entfernt.'


class SetupWindow:
    """Fenster, das die Einrichtung selbst ausführt und dabei berichtet."""

    def __init__(self, master=None, port_name=DEFAULT_PORT, on_done=None):
        self.on_done = on_done
        self.result = None
        self.busy = False
        self.port_name = loopmidi.clean_name(port_name) or DEFAULT_PORT
        self.window = tk.Toplevel(master) if master else tk.Tk()
        self.root = master or self.window
        self.window.title('MIDI-Port einrichten')
        self.window.geometry('640x380')
        self.window.resizable(False, False)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='MIDI-Port einrichten',
                  font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        ttk.Label(frame, wraplength=580, text=(
            'ProPresenter sendet MIDI an einen MIDI-Port, den Windows bereitstellen muss. '
            'Die Bridge richtet das jetzt automatisch ein – es ist nichts weiter zu tun.')).pack(
            anchor='w', pady=(6, 12))
        self.state = ttk.Label(frame, text='', font=('Segoe UI', 10, 'bold'), wraplength=580)
        self.state.pack(anchor='w')
        self.log = tk.Text(frame, height=8, wrap='word', relief='solid', borderwidth=1)
        self.log.pack(fill='both', expand=True, pady=10)
        self.log.configure(state='disabled')
        foot = ttk.Frame(frame)
        foot.pack(fill='x')
        self.retry = ttk.Button(foot, text='Erneut versuchen', command=self.run_setup,
                                state='disabled')
        self.retry.pack(side='left')
        ttk.Button(foot, text='Infos zum Hilfsprogramm',
                   command=lambda: webbrowser.open(VENDOR_URL)).pack(side='left', padx=8)
        ttk.Button(foot, text='Schließen', command=self.close).pack(side='right')
        self.apply_button = ttk.Button(foot, text='Übernehmen', command=self.apply,
                                       state='disabled')
        self.apply_button.pack(side='right', padx=8)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.after(150, self.run_setup)

    def write(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def report(self, message):
        self.window.after(0, lambda: self.write(message))

    def say(self, message):
        self.window.after(0, lambda: self.state.configure(text=message))

    def run_setup(self):
        if self.busy:
            return
        self.busy = True
        self.retry.state(['disabled'])
        self.apply_button.state(['disabled'])
        _, text = diagnose(self.port_name)
        self.say(text)
        self.report(text)

        def work():
            ok, message = prepare(self.port_name, report=self.report)
            self.window.after(0, lambda: self.finished(ok, message))
        threading.Thread(target=work, daemon=True).start()

    def finished(self, ok, message):
        self.busy = False
        self.say(message)
        self.report(message)
        if ok:
            self.apply_button.state(['!disabled'])
            self.retry.state(['disabled'])
        else:
            self.retry.state(['!disabled'])

    def apply(self):
        self.result = self.port_name
        if self.on_done:
            self.on_done(self.port_name)
        self.close()

    def close(self):
        self.window.destroy()


def run(port_name=DEFAULT_PORT, on_done=None):
    """Öffnet den Assistenten mit eigenem Hauptfenster."""
    assistant = SetupWindow(None, port_name=port_name, on_done=on_done)
    assistant.root.mainloop()
    return assistant.result


def main(argv=None):
    argv = argv or []
    name = DEFAULT_PORT
    if '--port' in argv:
        index = argv.index('--port')
        if len(argv) > index + 1:
            name = argv[index + 1]
    if '--check' in argv:
        state, message = diagnose(name)
        print(state, '|', message)
        return 0
    if '--silent' in argv:
        ok, message = prepare(name, report=lambda text: print(text, flush=True))
        print('ERGEBNIS:', 'ok' if ok else 'fehlgeschlagen', '|', message, flush=True)
        return 0 if ok else 1
    if '--remove' in argv:
        ok, message = teardown(name)
        print(message)
        return 0 if ok else 1
    run(name)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))