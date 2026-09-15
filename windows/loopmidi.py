"""Virtuellen MIDI-Port anlegen – ohne Zutun des Nutzers.

Hintergrund
-----------
Die Bridge braucht einen MIDI-*Eingang*, den ProPresenter als MIDI-Ausgang
sieht. Windows selbst kann das nur über „Windows MIDI Services" – und dieses
Feature ist auf ausgelieferten Windows-11-PCs noch nicht freigeschaltet
(`midi.exe` meldet „feature does not appear to be enabled", die Freischaltung
kommt erst per Windows-Update).

Deshalb nutzt dieses Modul loopMIDI von Tobias Erichsen. loopMIDI speichert
seine Ports unter::

    HKCU\\SOFTWARE\\Tobias Erichsen\\loopMIDI\\Ports

Je Port ein Wert mit dem Port-Namen als Namen. Dieser Schlüssel wird hier
geschrieben – der Nutzer muss die loopMIDI-Oberfläche nie öffnen. Nach einem
Neustart von loopMIDI legt das Programm die eingetragenen Ports an, und WinMM
sieht sie als MIDI-Eingang.

loopMIDI wird **nicht** mitgeliefert: es wird bei Bedarf über winget installiert
oder vom Hersteller geladen (siehe `install_via_winget`).
"""
import os
from pathlib import Path
import subprocess
import sys
import time

PRODUCT = 'loopMIDI'
WINGET_ID = 'TobiasErichsen.loopMIDI'
# Version mit anheften: ohne sie entscheidet die lokale winget-
# Quellenkonfiguration, WAS installiert wird. Gemessen mit
# `winget show --id TobiasErichsen.loopMIDI`: 1.0.16.27.
WINGET_VERSION = '1.0.16.27'
MANUFACTURER_URL = 'https://www.tobias-erichsen.de/software/loopmidi.html'
PORTS_KEY = r'SOFTWARE\Tobias Erichsen\loopMIDI\Ports'
MAX_NAME = 31  # WinMM-Grenze (MAXPNAMELEN)
DETACHED = 0x00000008
NO_WINDOW = 0x08000000


def elevated():
    """Läuft dieser Prozess mit Administratorrechten?"""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def paths(environment=None):
    """Bekannte Installationsorte von loopMIDI."""
    environment = environment or os.environ
    found = []
    for key in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432'):
        root = environment.get(key)
        if not root:
            continue
        base = Path(root) / 'Tobias Erichsen' / 'loopMIDI'
        found.append(base / 'loopMIDI.exe')
        found.append(base / 'teVirtualMIDI64.dll')
    return found


def installed(environment=None):
    return any(path.exists() for path in paths(environment))


def executable(environment=None):
    for path in paths(environment):
        if path.name.lower() == 'loopmidi.exe' and path.exists():
            return str(path)
    return None


def _run(command, timeout=30):
    """Kurzer Aufruf ohne aufblitzendes Konsolenfenster."""
    return subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout,
                          creationflags=NO_WINDOW if os.name == 'nt' else 0)


def running():
    """Ist loopMIDI gerade gestartet?"""
    if os.name != 'nt':
        return False
    try:
        result = _run(['tasklist', '/FI', 'IMAGENAME eq loopMIDI.exe', '/NH'], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return 'loopMIDI.exe' in (result.stdout or '')


def stoppable():
    """Läuft loopMIDI so, dass dieser Prozess es beenden kann?

    Wurde loopMIDI erhöht gestartet (etwa aus einem Installer mit
    Administratorrechten), kann ein normaler Prozess es nicht beenden. Dann
    lässt sich ein neuer Port nicht wirksam machen.
    """
    if not running():
        return True
    result = _run(['tasklist', '/FI', 'IMAGENAME eq loopMIDI.exe', '/FO', 'CSV', '/NH'], timeout=20)
    pid = None
    for zeile in (result.stdout or '').splitlines():
        teile = [teil.strip('"') for teil in zeile.split(',')]
        if len(teile) > 1 and teile[0].lower() == 'loopmidi.exe':
            pid = teile[1]
            break
    if not pid:
        return True
    probe = _run(['taskkill', '/PID', pid], timeout=30)
    ausgabe = ((probe.stdout or '') + (probe.stderr or '')).lower()
    if 'zugriff verweigert' in ausgabe or 'access is denied' in ausgabe:
        return False
    return True


def start():
    """Startet loopMIDI. Rückgabe: (gestartet, Meldung).

    Wichtig: **nie** aus einem erhöhten Prozess starten. Ein erhöht gestartetes
    loopMIDI lässt sich später vom normalen Bridge-Prozess nicht beenden, und
    dann bleibt ein neu eingetragener Port unsichtbar. Läuft dieser Prozess
    erhöht (etwa der Installer), wird der Start abgelehnt; die Bridge startet
    zu einem späteren Zeitpunkt als normaler Benutzer.
    """
    target = executable()
    if not target:
        return False, f'{PRODUCT} wurde nicht gefunden.'
    if elevated():
        return False, (f'{PRODUCT} wird nicht aus einem erhöhten Prozess gestartet, da es sich '
                       'danach nicht mehr steuern ließe. Der Start erfolgt durch die Bridge '
                       'beim nächsten Start.')
    try:
        subprocess.Popen([target], creationflags=DETACHED if os.name == 'nt' else 0, close_fds=True)
    except OSError as error:
        return False, f'{PRODUCT} konnte nicht gestartet werden: {error}'
    return True, f'{PRODUCT} wird gestartet.'


def _key():
    import winreg
    return winreg


def ports():
    """Eingetragene Port-Namen aus der Registry. Leere Liste, wenn es keine gibt."""
    if os.name != 'nt':
        return []
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PORTS_KEY) as key:
            names = []
            index = 0
            while True:
                try:
                    name, _, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                if name:
                    names.append(name)
                index += 1
            return names
    except (FileNotFoundError, OSError):
        return []


def remember(name):
    """Trägt den Port ein. Rückgabe: (ok, Meldung)."""
    name = clean_name(name)
    if not name:
        return False, 'Der Name des Ports darf nicht leer sein.'
    if os.name != 'nt':
        return False, 'Ein virtueller Port lässt sich nur unter Windows anlegen.'
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PORTS_KEY, 0, winreg.KEY_ALL_ACCESS) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, '')
    except OSError as error:
        return False, f'Der Port konnte nicht eingetragen werden: {error}'
    return True, f'Port „{name}“ ist eingetragen.'


def forget(name):
    """Entfernt einen eingetragenen Port wieder."""
    if os.name != 'nt':
        return False, 'Nur unter Windows möglich.'
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PORTS_KEY, 0, winreg.KEY_ALL_ACCESS) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        return True, f'Port „{name}“ war nicht eingetragen.'
    except OSError as error:
        return False, f'Der Port konnte nicht entfernt werden: {error}'
    return True, f'Port „{name}“ ist entfernt.'


def clean_name(name):
    """Kürzt auf die WinMM-Grenze und entfernt unmögliche Zeichen."""
    text = ''.join(character for character in (name or '') if character >= ' ').strip()
    return text[:MAX_NAME]


def devices():
    """Alle MIDI-Eingänge laut WinMM."""
    try:
        from native import Midi
        return [str(name) for _, name in Midi().devices()]
    except Exception:
        return []


def port_visible(name):
    """Sieht WinMM den Port bereits?"""
    return bool(name) and any(name == device or name in device for device in devices())


def _pids():
    """Alle laufenden loopMIDI-Prozesse mit ihrer PID."""
    if os.name != 'nt':
        return []
    try:
        ergebnis = _run(['tasklist', '/FI', 'IMAGENAME eq loopMIDI.exe', '/FO', 'CSV', '/NH'], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    nummern = []
    for zeile in (ergebnis.stdout or '').splitlines():
        teile = [teil.strip('"') for teil in zeile.split(',')]
        if len(teile) > 1 and teile[0].lower() == 'loopmidi.exe' and teile[1].isdigit():
            nummern.append(teile[1])
    return nummern


def stop():
    """Beendet loopMIDI, damit ein neuer Port beim Start angelegt wird."""
    if os.name != 'nt':
        return False, 'Nur unter Windows möglich.'
    if not running():
        return True, f'{PRODUCT} läuft nicht.'
    # Über die PID beenden: mit /IM werden mehrere Sitzungen nicht erfasst.
    for pid in _pids():
        try:
            _run(['taskkill', '/F', '/PID', pid], timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for _ in range(20):
        if not running():
            return True, f'{PRODUCT} wurde beendet.'
        time.sleep(0.25)
    if not stoppable():
        return False, RAISED_MESSAGE
    return False, f'{PRODUCT} ließ sich nicht beenden.'


def restart():
    """Startet loopMIDI neu, damit neue Ports wirksam werden.

    Läuft der aufrufende Prozess erhöht, wird nur beendet und nicht neu
    gestartet: ein erhöht gestartetes loopMIDI ließe sich später nicht mehr
    steuern. Die Bridge startet es dann selbst.
    """
    ok, message = stop()
    if not ok:
        return False, message
    if elevated():
        return True, (f'{PRODUCT} wurde beendet. Es wird nicht aus einem erhöhten Prozess neu '
                      'gestartet – die Bridge übernimmt das.')
    ok, message = start()
    if not ok:
        return False, message
    for _ in range(40):
        if running():
            return True, f'{PRODUCT} läuft mit den neuen Ports.'
        time.sleep(0.25)
    return False, f'{PRODUCT} ist nicht wieder gestartet.'


def ensure_port(name, wait=15):
    """Sorgt dafür, dass *name* als MIDI-Eingang verfügbar ist.

    Rückgabe: (ok, Meldung). Ist der Port schon da, passiert nichts.
    """
    name = clean_name(name)
    if not name:
        return False, 'Bitte einen Namen für den MIDI-Port angeben.'
    if port_visible(name):
        return True, f'Port „{name}“ ist bereits verfügbar.'
    if not installed():
        return False, (f'{PRODUCT} ist nicht installiert. Ohne dieses Hilfsprogramm kann '
                       'Windows keinen zusätzlichen MIDI-Port bereitstellen.')
    if running() and not stoppable():
        return False, RAISED_MESSAGE
    already = name in ports()
    if not already:
        ok, message = remember(name)
        if not ok:
            return False, message
    # Ein neuer Registry-Eintrag wird erst beim Start von loopMIDI wirksam.
    ok, message = stop()
    if not ok:
        return False, message
    if not running():
        ok, message = start()
        if not ok:
            return False, message
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if port_visible(name):
            return True, f'Port „{name}“ ist verfügbar.'
        time.sleep(0.5)
    if not stoppable():
        return False, RAISED_MESSAGE
    return False, (f'Port „{name}“ ist eingetragen, aber noch nicht sichtbar. '
                   f'{PRODUCT} einmal beenden und neu starten.')


def raised_fix_steps():
    """Was der Nutzer tun kann, wenn loopMIDI erhöht läuft."""
    return ('1. Rechtsklick auf den Startknopf → „Task-Manager“.\n'
            '2. Im Reiter „Details“ (oder „Prozesse“) den Eintrag loopMIDI.exe suchen.\n'
            '3. Rechtsklick darauf → „Task beenden“.\n'
            '4. In der Bridge erneut „MIDI-Port jetzt einrichten“ drücken.')


RAISED_MESSAGE = (
    f'{PRODUCT} läuft mit erhöhten Rechten und lässt sich deshalb nicht neu starten. '
    'Ein neu angelegter MIDI-Port würde nicht sichtbar werden.')


def kill_elevated():
    """Beendet ein erhöht gestartetes loopMIDI – nur aus erhöhtem Kontext.

    Diese Funktion ist für den Installer-Schritt gedacht, der selbst mit
    Administratorrechten läuft und den Prozess deshalb beenden darf. Aus einem
    normalen Prozess heraus gelingt das nicht; dort meldet `stoppable()` den
    Zustand, und die Bridge erklärt dem Nutzer, was zu tun ist.
    """
    if not running():
        return True, f'{PRODUCT} läuft nicht.'
    ok, message = stop()
    if ok:
        return True, f'{PRODUCT} wurde beendet.'
    return False, message


def verify_signature(path):
    """Prüft die Herstellersignatur einer Datei. Rückgabe: (ok, Meldung).

    loopMIDI wird erhöht installiert und bekommt MIDI-Zugriff; ein
    untergeschobenes Programm wäre hier besonders schädlich.
    """
    if os.name != 'nt':
        return True, ''
    if not path or not Path(path).exists():
        return False, f'{PRODUCT} wurde nicht gefunden.'
    script = ('$s = Get-AuthenticodeSignature -LiteralPath $args[0]; '
              'if ($s.Status -eq "Valid") { "OK" } else { "ABGELEHNT: $($s.Status)" }')
    try:
        result = _run(['powershell', '-NoProfile', '-NonInteractive',
                       '-ExecutionPolicy', 'Bypass', '-Command', script,
                       str(path)], timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        # Prüfung nicht möglich (kein PowerShell, Richtlinie, Zeitüberschreitung).
        # Das blockiert die Installation bewusst NICHT: winget hat den SHA-256
        # des Installers bereits gegen das Manifest geprüft. Gemeldet wird es.
        return True, 'Signatur nicht prüfbar'
    ausgabe = ((result.stdout or '') + (result.stderr or '')).strip()
    if ausgabe.startswith('OK'):
        return True, 'signiert'
    return False, (f'{PRODUCT} hat keine gültige Herstellersignatur '
                   f'({ausgabe or "keine Auskunft"}).')


def install_via_winget(timeout=900):
    """Installiert loopMIDI über winget. Rückgabe: (ok, Meldung).

    Version und Quelle sind festgelegt: sonst entscheidet die lokale
    winget-Quellenkonfiguration, was installiert wird.
    """
    if installed():
        return True, f'{PRODUCT} ist bereits installiert.'
    command = ['winget', 'install', '--id', WINGET_ID, '--exact']
    if WINGET_VERSION:
        command += ['--version', WINGET_VERSION]
    command += ['--source', 'winget', '--accept-package-agreements',
                '--accept-source-agreements', '--disable-interactivity']
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout,
                                creationflags=NO_WINDOW if os.name == 'nt' else 0)
    except FileNotFoundError:
        return False, ('winget ist auf diesem PC nicht verfügbar. Bitte loopMIDI über '
                       f'{MANUFACTURER_URL} installieren.')
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f'Die Installation konnte nicht ausgeführt werden: {error}'
    if not installed():
        lines = [line for line in ((result.stdout or '') + (result.stderr or '')).splitlines() if line.strip()]
        if result.returncode != 0 and lines:
            return False, lines[-1]
        return False, 'Die Installation wurde nicht abgeschlossen.'
    # "Datei ist da" heißt noch nicht "richtiges Programm": Signatur prüfen.
    ok, meldung = verify_signature(executable())
    if not ok:
        return False, meldung
    return True, f'{PRODUCT} ist installiert ({meldung}).'


def main(argv=None):
    argv = argv or []
    print(f'{PRODUCT} installiert :', installed())
    print(f'{PRODUCT} läuft       :', running())
    print('Eingetragene Ports  :', ports())
    print('MIDI-Eingänge       :', devices())
    if '--create' in argv:
        name = argv[argv.index('--create') + 1] if len(argv) > argv.index('--create') + 1 else 'ChurchTools Bridge'
        print(ensure_port(name))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))