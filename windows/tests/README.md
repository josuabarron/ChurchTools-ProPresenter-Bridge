# Tests

Die Tests sichern die Windows-Fassung ab: MIDI-Port, Tokenspeicher, lokaler
Server, Oberfläche, Installation und Deinstallation. Jeder Fehler, der im
echten Betrieb aufgetreten ist, hat hier einen Test bekommen.

## Ausführen

```powershell
cd windows
py -3 -m venv .venv          # nur beim ersten Mal
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Eine einzelne Datei geht über den Modulpfad:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_loopmidi
```

Mit `discover -s tests -p test_loopmidi.py` geht es ebenfalls. Nur die
Dateiendung darf nicht in den Modulpfad: `python -m unittest
tests.test_loopmidi.py` bricht ab (`AttributeError: module
'tests.test_loopmidi' has no attribute 'py'`). `tests` hat keine
`__init__.py` – für `unittest` ist das kein Hindernis.

Voraussetzungen: Windows, Python 3.12 mit `tkinter` (in der offiziellen
Installation enthalten). Kein MIDI-Port, keine loopMIDI-Installation, keine
Einstellungen des Nutzers werden gebraucht.

Die CI (`.github/workflows/windows-build.yml`, `release.yml`) und
`windows/build.ps1` rufen dieselbe Zeile auf und brechen bei Fehlschlag ab.

## Umfang

303 Tests, etwa 24 Sekunden, ein übersprungener Test (siehe unten).

| Datei | Tests | Zeit | Gegenstand |
| --- | ---: | ---: | --- |
| `test_ui.py` | 93 | 20,7 s | Oberflächenaufbau mit echten Tk-Widgets |
| `test_server_haertung.py` | 25 | 2,3 s | was der lokale Server ablehnt |
| `test_setup_flow.py` | 19 | 0,9 s | Einrichtung ohne Fenster (Installationspfad) |
| `test_loopmidi.py` | 43 | 0,5 s | Port anlegen, Einrichtung, Aufräumen |
| `test_bridge.py` | 12 | 0,4 s | MIDI-Auswertung, HTTP-Antworten, DPAPI |
| `test_client_haertung.py` | 9 | 0,3 s | CSRF-Erneuerung, Umleitungsschutz |
| `test_single_instance.py` | 20 | 0,2 s | Einzelinstanz, Beenden aus dem Installer |
| `test_redaction.py` | 15 | 0,2 s | Entschärfung von Meldungen vor dem Log |
| `test_tray.py` | 18 | 0,2 s | Infobereich-Symbol und Zustandswechsel |
| `test_elevated.py` | 14 | 0,2 s | erhöht gestartetes loopMIDI |
| `test_tokenspeicher.py` | 10 | 0,2 s | DPAPI-Ablage, Meldungen im Aufbau |
| `test_uninstall.py` | 13 | 0,2 s | Deinstallation und Autostart-Pfad |
| `test_not_elevated.py` | 12 | 0,2 s | Start aus erhöhtem Prozess |

## Was die Tests nicht anfassen

- Kein Test ruft `loopMIDI.exe`, `winget` oder `midi.exe` auf. `subprocess` ist
  überall ersetzt.
- Kein Test schreibt in die Registry. `winreg` ist ersetzt.
- Kein Test fasst die echten Einstellungen an: `LOCALAPPDATA` zeigt auf einen
  temporären Ordner.
- Kein Test spricht mit ChurchTools.
- `test_bridge.py` und `test_server_haertung.py` öffnen einen echten
  Socket auf `127.0.0.1` mit Port 0 (also vom System vergeben). Das ist
  gewollt – geprüft wird, was der Server tatsächlich ablehnt.

## Ein übersprungener Test

`test_verknuepfung_wird_nicht_verfolgt` legt eine symbolische Verknüpfung an
und prüft, dass ein Bericht darüber nicht hindurchschreibt. Windows erlaubt das
Anlegen ohne Entwicklermodus oder erhöhte Rechte nicht; der Test überspringt
sich dann selbst. Auf einem Rechner mit dieser Berechtigung läuft er mit.

## Bekannte Schwächen

- `test_ui.py` verbraucht mit rund 21 von 24 Sekunden fast die ganze Laufzeit.
  Grund: `DebugModus` und `PortAkkordeon` erben von `Fenster`, dessen 26 Tests
  dadurch dreimal laufen (26 × 3 = 78 der 93 Tests). Beide Unterklassen
  prüfen nur ihren eigenen Zusatz. Wer die Laufzeit senken will, zieht die
  geerbten Tests aus den Unterklassen heraus.
- Einige Tests in `test_ui.py` schreiben die Anordnung fest (Reihenfolge der
  Rahmen, Position von Note und Play-Knopf). Das ist gewollt – die Anordnung
  war der Fehler – kostet aber bei jeder Umgestaltung Arbeit.
- `test_verstecktes_menue_enthaelt_port_und_kanal` enthält einen toten Zweig
  (`... if False else ...`). Funktioniert, gehört aber aufgeräumt.
- Für die macOS-Fassung gibt es keine Tests. Die Prüfungen aus
  `test_client_haertung.py` wurden gegen den Swift-Code von Hand abgeglichen.

## Wenn ein Fehler auftritt

Der Test gehört dazu. Die Dateien sind nach Fehlern sortiert, nicht nach
Modulen – `test_tokenspeicher.py` enthält den Fall, dass zusätzliche Entropie
einen vorhandenen Token unlesbar machte, `test_elevated.py` den Fall, dass ein
erhöht gestartetes loopMIDI sich nicht beenden lässt. Jede Datei nennt in
ihrem Kopf den Anlass. Ein neuer Test gehört in die Datei, deren Gegenstand er
trifft; nur wenn es keinen gibt, kommt eine neue Datei dazu.
