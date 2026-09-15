# ChurchTools Bridge – Installer

Ein Setup für alles: `ChurchToolsBridge-Setup.exe`.

## Was der Installer macht

1. Kopiert die Bridge nach `C:\Program Files\ChurchTools Bridge`.
2. Legt den MIDI-Port an, den ProPresenter als Ausgang sieht.
   Dafür wird **loopMIDI** (Tobias Erichsen) über winget installiert, falls es
   fehlt. loopMIDI ist das Hilfsprogramm, das virtuelle MIDI-Ports bereitstellt.
3. Richtet den Autostart ein (abwählbar).
4. Startet die Bridge auf Wunsch direkt.

Der Nutzer muss **nichts** weiter einstellen. Insbesondere muss die
loopMIDI-Oberfläche nicht geöffnet werden: die Bridge schreibt den Port selbst
in die Registry und startet loopMIDI neu.

## loopMIDI wird nicht mitgeliefert

Das ist Absicht und keine Nachlässigkeit.

Die Weitergabe von loopMIDI und des dahinterliegenden virtualMIDI-Treibers ist
nicht gestattet. Zwei Originalstellen:

- loopMIDI-/SDK-Seite: *„Distribution in any form without prior written
  permission by the author is prohibited!"*
- Software-Übersicht: *„may not be distributed via any means without prior
  written consent by the author"*; freie Nutzung gilt für *„private,
  non-commercial use"*

Wer die Bridge gewerblich einsetzen will, muss das mit dem Hersteller klären.
Für den Einsatz in einer Gemeinde ist die private Nutzung gedeckt.

Deshalb dieser Weg: `winget install --id TobiasErichsen.loopMIDI` — Windows lädt
das Programm vom Hersteller. Die Bridge liefert nichts Fremdes aus, sie stößt
nur die Installation an. Fehlt winget, verweist die Bridge auf die
Herstellerseite.

## Warum nicht Microsofts eigener Weg

Windows 11 kann virtuelle MIDI-Ports selbst anlegen — aber erst nach einem
Windows-Update (angekündigt Ende 2026 bis Anfang 2027). Heute meldet das
Microsoft-Werkzeug auf einem normalen Windows-11-Rechner:

```
The Windows MIDI Services feature does not appear to be enabled on this PC.
Enablement for supported versions of Windows will come through Windows Update.
```

Zusätzlich verlangt das Vorschau-Paket für den Basic-Loopback-Transport den
Entwicklermodus. Beides ist für den Endnutzer nicht zumutbar. Sobald Microsoft
das Feature per Windows-Update freischaltet, kann ein zweiter Weg daneben
gebaut werden — die Bridge kapselt die Port-Erstellung bereits in
`..\loopmidi.py`.

## Bauen

Voraussetzungen: Python 3.10+ (mit Tcl/Tk), Inno Setup 6.
`Inno Setup: winget install JRSoftware.InnoSetup`

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\build-installer.ps1
```

Ablauf: Tests → Bridge-EXE (PyInstaller) → Installer (Inno Setup).
Ergebnis: `installer\output\ChurchToolsBridge-Setup.exe`.
Die Versionsnummer kommt aus `VERSION` im Repo-Wurzelverzeichnis.

## Installation ohne Fenster (für Tests)

```
ChurchToolsBridge-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Log unter `%LOCALAPPDATA%\Temp\Setup Log*.txt`, Ergebnis des MIDI-Schritts in
`{tmp}\ctp-midi.txt`.

## Über den Port-Namen

Standardname: `ChurchTools Bridge` (max. 31 Zeichen, WinMM-Grenze).
Anpassbar über `#define PortName` im `.iss` oder per
`--port-name "Eigener Name"` beim Aufruf mit `--complete-setup`.

Der Name muss in ProPresenter als MIDI-Ausgang ausgewählt werden. Er wird beim
Öffnen der Bridge automatisch angelegt — ProPresenter neu starten, wenn der
Ausgang dort noch nicht auftaucht.

## Deinstallation

Entfernt die Bridge, den MIDI-Port und den Autostart-Eintrag. loopMIDI bleibt
installiert (andere Programme können es nutzen) — die Deinstallation sagt das
und nennt den Weg über die Windows-Einstellungen.

## Dateien

| Datei | Zweck |
| --- | --- |
| `ChurchToolsBridge.iss` | Inno-Setup-Skript |
| `build-installer.ps1` | Baut EXE und Installer |
| `output/` | Fertiger Installer (nicht unter Versionskontrolle) |