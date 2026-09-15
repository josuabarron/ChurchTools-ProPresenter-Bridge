# ChurchTools Bridge für Windows

**Status: auf einem Windows-11-Rechner (Build 26200) verifiziert: die Bridge legt den
MIDI-Port selbst an, Windows/WinMM sieht ihn als MIDI-Eingang, und die MIDI-Sends lassen
sich einzeln manuell auslösen. Nicht verifiziert: der Durchlauf mit einer echten
ProPresenter-Installation im Gottesdienst.**

Windows-Port der Swift-App mit Python/Tk-Oberfläche, ohne zusätzliche Python-Laufzeitbibliotheken. Ein EXE-Build bündelt Python und Tk. Vorgesehen für Windows 10/11 x64.

Die Schaltfläche **Hilfe** öffnet die Setup-Anleitung auch vor dem ersten Bridge-Start. Bei laufendem Server ist sie zusätzlich unter `/help` und `/live/help` erreichbar.

## MIDI-Port: die Bridge richtet ihn selbst ein

```text
ProPresenter MIDI-Ausgang → MIDI-Port „ChurchTools Bridge“ → Bridge → ChurchTools
```

Die Bridge liest MIDI über Windows **WinMM** (`midiInOpen`). Den Eingang muss ein Port bereitstellen – Windows kann das nicht von Haus aus. Zwei Betriebsarten:

**Bridge legt den Port selbst an (Standard).** Die Bridge installiert bei Bedarf loopMIDI, trägt den Port-Namen ein, startet loopMIDI neu und wartet, bis WinMM den Port sieht. Der Nutzer muss die loopMIDI-Oberfläche **nicht** öffnen und keinen Namen eintippen.

**Bereits vorhandenen Port verwenden.** Für ein physisches MIDI-Gerät oder einen selbst angelegten Port.

Der Port heißt wie im Feld **Name des Ports** (höchstens 31 Zeichen, Vorgabe `ChurchTools Bridge`).

### Wie die Bridge den Port anlegt

loopMIDI speichert seine Ports in der Registry:

```text
HKCU\SOFTWARE\Tobias Erichsen\loopMIDI\Ports
```

Dort schreibt je Port ein Wert mit dem Port-Namen. Die Bridge

1. lädt loopMIDI über winget (falls nicht vorhanden),
2. schreibt den gewünschten Namen in diesen Schlüssel,
3. startet loopMIDI neu,
4. wartet, bis `midiInGetDevCaps` den Port meldet.

Verifiziert auf Windows 11 Build 26200: nach Schritt 2 und 3 erscheint der Port in der WinMM-Geräteliste. Voraussetzung: loopMIDI ist installiert und läuft.

### Warum nicht die Windows-eigene Lösung

Windows 11 hat mit **Windows MIDI Services** eine eigene Möglichkeit für virtuelle Ports – die aber noch nicht freigeschaltet ist. Auf einem normalen Windows-11-Rechner meldet das Microsoft-Werkzeug `midi.exe`:

```text
The Windows MIDI Services feature does not appear to be enabled on this PC.
Enablement for supported versions of Windows will come through Windows Update.
```

Auch `midicheckservice.exe` antwortet: *„The new Windows MIDI Services stack is not functional on this PC."* Zusätzlich verlangt das Vorschau-Paket für den *MIDI 1.0 Basic Loopback*-Transport den Entwicklermodus. Die Freischaltung per Update ist für Ende 2026 bis Anfang 2027 angekündigt.

Die Bridge nutzt deshalb loopMIDI. Sobald Microsoft das Feature ausrollt, kann ein zweiter Weg daneben gebaut werden – die Port-Erstellung ist in `loopmidi.py` gekapselt.

### loopMIDI wird nicht mitgeliefert

Die Weitergabe ist **nicht gestattet**:

- *„Distribution in any form without prior written permission by the author is prohibited!"* (Lizenzdatei des Herstellers)
- *„may not be distributed via any means without prior written consent by the author"*

Freie Nutzung gilt für *„private, non-commercial use"*. Für den Einsatz in einer Gemeinde ist das gedeckt. Wer die Bridge **gewerblich** einsetzt, muss die Nutzung vorher mit dem Hersteller klären.

Deshalb installiert die Bridge loopMIDI über `winget install --id TobiasErichsen.loopMIDI`: Windows lädt es vom Hersteller. Die Bridge liefert nichts Fremdes aus. Ohne winget verweist sie auf die [Herstellerseite](https://www.tobias-erichsen.de/software/loopmidi.html).

Ein gebündelter eigener Treiber ist eine mögliche spätere Erweiterung – dafür wäre das virtualMIDI-SDK samt schriftlicher Freigabe des Herstellers nötig.

### Voraussetzungen

- **Windows 10 oder 11, x64.** Keine Administratorrechte für den Betrieb nötig (winget-Installation und Treiberinstallation erhöhen selbst).
- **winget**, auf Windows 11 vorhanden. Fehlt es, loopMIDI von der Herstellerseite installieren – die Bridge erkennt es danach.
- loopMIDI muss **laufen**. Die Bridge startet es und findet es unter `C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe` wieder.

### Eigenheiten

- Nach dem Eintragen braucht loopMIDI einen **Neustart**; die Bridge erledigt das selbst.
- Der Port verschwindet, wenn loopMIDI beendet oder der Nutzer abgemeldet wird – loopMIDI-Ports sind benutzerspezifisch und nicht dauerhaft. Die Bridge startet loopMIDI bei Bedarf neu.
- Mehrere Ports sind möglich; die Bridge rührt nur ihren eigenen an.

## Aus Quellcode starten

Python 3.10 oder neuer für Windows mit Tcl/Tk installieren, dann im Ordner `windows`:

```powershell
py -3 app.py
```

API-URL (HTTPS, z. B. `https://example.church.tools/api`), Login-Token und User-ID eintragen und **⟳** („Speichern & Neustart“, nur das Symbol
im Knopf) drücken. Fehlt der MIDI-Port, öffnet die Bridge die Einrichtung und legt ihn an. Nach späteren Starts läuft die Bridge mit gespeicherten Zugangsdaten automatisch an.

Die Felder **Name des Ports** und der Radiobutton **Bridge legt den Port selbst an** sind die Vorgabe. Für einen vorhandenen Eingang auf **Bereits vorhandenen Port verwenden** umschalten und **Ports suchen** drücken.

Der MIDI-Port-Bereich klappt sich selbst zusammen, sobald der Port steht; die Kopfzeile nennt ihn dann samt Zustand („… ist bereit“). Zum Nachsehen auf das Dreieck klicken.

**Diagnose** öffnet ein eigenes Fenster und zeigt im Klartext, was fehlt: Programm installiert, Programm läuft, Port eingetragen, Port sichtbar, verfügbare MIDI-Eingänge.

MIDI-Sends stehen untereinander als Zeilen: links das Ziel, rechts die MIDI-Note, daneben **✕** zum Entfernen. **Send hinzufügen** hängt eine Zeile an; die neue Note ist die erste freie ab 60. Zahlen springen zu einer Position; jeder andere Text sucht den gleichnamigen Agenda-Titel.

### Verstecktes Menü

Drei kurze Klicks auf die schmale Fläche zwischen **Hilfe** und **Beenden** öffnen bzw. schließen das versteckte Menü am unteren Fensterrand. Darin:

- **Erweiterte Einstellungen** – lokaler HTTP-Port, MIDI-Kanal (1–16).
- **Diagnose-Log** unten – Meldungen mit Uhrzeit, die letzten 300 Einträge; **Log kopieren** legt sie in die Zwischenablage (Token und Adressen sind vorher entfernt), **Log leeren** räumt auf.

## MIDI-Ziele

`zurück`, `zurueck`, `previous`, `back`; `vor`, `weiter`, `next`, `forward`; eine Position oder ein Agenda-Titel. Position 0 ist „nicht gestartet“, die Position nach dem letzten Eintrag ist „Ende“. Überschriften zählen nicht mit, Songs mit Dauer 0 werden bei „vor“ übersprungen. Titel werden ohne Beachtung von Großschreibung/Akzenten verglichen. Entprellung gilt pro Note; Note Off und Note On mit Velocity 0 lösen nichts aus.

## MIDI-Kanal

Die Windows-Fassung hört auf Kanal 1 – wie die macOS-Fassung. Alles andere, was
früher im Hauptfenster stand, ist jetzt fest verdrahtet oder nur noch über das
versteckte Menü erreichbar:

| Wert | Vorgabe | Wo es steckt |
| --- | --- | --- |
| MIDI-Kanal | 1 | im versteckten Menü änderbar |
| Event-Suche: Tage | 14 | keine Oberfläche; aus `settings.json` |
| Event-Name enthält | leer | keine Oberfläche; aus `settings.json` |
| Entprellzeit | 800 ms | keine Oberfläche; aus `settings.json` |
| Notes-Schriftgröße | 64 | im versteckten Menü änderbar |

Die letzten drei haben kein Feld im Fenster. Sie liegen in `settings.json` und
werden beim Start gelesen: `%LOCALAPPDATA%\ChurchToolsProPresenterBridge\settings.json`.
Wer sie ändern will, bearbeitet die Datei und startet die Bridge neu. Alte
Werte fallen nicht weg. Port und MIDI-Kanal stehen im versteckten Menü.

Die Event-Suche nimmt dabei nur den ersten Tag und bis zu 25 Events: passende Agenden, optional nur gesperrte Agenden. Bei mehreren Events lässt sich die Auswahl im Agenda-Bereich (Feld **Event**) ändern. Der Knopf **⟳** lädt Events und Agenden neu. **Stopp** gibt es nicht mehr; ein laufender Vorgang wird durch einen Neustart ersetzt, beendet wird über **Beenden**.

## Lokale Ansichten

- `http://127.0.0.1:8765/live` – Weiterleitung zur ChurchTools Live-Agenda.
- `http://127.0.0.1:8765/live/strip` – Jetzt/Dann.
- `http://127.0.0.1:8765/live/notes` – Notizen, Schriftgröße konfigurierbar.

Als Browser-Source in ProPresenter verwenden. Die Ansichten pollen die Bridge, die ChurchTools-Abfragen bündelt und mindestens drei Sekunden cached. Bei Ausfällen bleiben bereits geladene Daten erhalten; HTTP 429 löst mindestens 60 Sekunden Backoff aus. Ein Neustart übernimmt geänderte Anzeige-Einstellungen.

### Wer auf den Server zugreifen darf

Der Server bindet ausschließlich an `127.0.0.1`. Das hält das Netzwerk draußen,
ist aber **keine Zugriffskontrolle**: jeder lokale Prozess und jede Seite im
selben Browser erreicht den Port. Deshalb wird jede Anfrage geprüft:

| Prüfung | Was sie verhindert |
| --- | --- |
| `Host` muss `127.0.0.1`, `localhost` oder `::1` sein | DNS-Rebinding: die fremde Seite verbindet sich auf 127.0.0.1, schickt aber ihren eigenen Domainnamen mit |
| `Origin` muss fehlen oder lokal sein; `Origin: null` wird abgelehnt | fremde Seiten und Sandbox-Inhalte lesen die Ansichten mit |
| `Sec-Fetch-Site` muss `none`, `same-origin` oder `same-site` sein | seitenübergreifende Abrufe |

Alles andere bekommt `403`. Fehlende Köpfe (ProPresenter-Browser-Source, `curl`)
werden nicht abgelehnt, sonst bräche die Ansicht in ProPresenter.

### Der Login-Token in `/live`

`/live` antwortet mit einer Umleitung, in deren Adresse der ChurchTools-Token
steht (wie in der macOS-Fassung). Das ist **beabsichtigt** und der einzige Weg,
den die Bridge von sich aus anbietet: ProPresenter-Browser-Sources melden sich
nicht an, sie brauchen die fertige Adresse.

Was der Token bedeutet – und was nicht:

- Ein **lokal** laufender Prozess desselben Benutzers kommt auch ohne `/live` an
  den Token: er liest ihn mit demselben Benutzerkonto über DPAPI direkt aus
  `token.dpapi`. Der Endpunkt öffnet dort nichts Neues.
- Eine **fremde Webseite** kommt nicht mehr heran – dafür sorgen die Prüfungen
  oben.
- Die Anweisung bleibt deshalb: **einen eingeschränkten ChurchTools-Funktionsbenutzer**
  verwenden, nicht das eigene Konto. Das gilt unverändert und ist die einzige
  wirksame Begrenzung, wenn ein Prozess auf demselben Rechner kompromittiert ist.

Titel und Notizen werden als Text dargestellt, nicht als ausführbares HTML.

Einstellungen liegen unter `%LOCALAPPDATA%\ChurchToolsProPresenterBridge\settings.json`, der Token separat unter `token.dpapi`, mit Windows DPAPI für den Benutzer verschlüsselt. Beim Kopieren auf einen anderen Rechner/Benutzer muss der Token neu eingegeben werden. Diagnosemeldungen enthalten keine API-Antwortkörper oder Tokens.

## EXE und Installer bauen

Für den fertigen Installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\build-installer.ps1
```

Ergebnis: `installer\output\ChurchToolsBridge-Setup.exe`. Siehe `installer\README.md`.
Das Skript liest die Versionsnummer aus `VERSION` im Repo-Wurzelverzeichnis und
schreibt sie in den Installer.

Nur die EXE, im Ordner `windows`:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Das Skript erstellt eine lokale virtuelle Python-Umgebung, installiert PyInstaller, führt die Tests aus und baut über `ChurchToolsBridge.spec` die `dist\ChurchToolsBridge.exe`. Die `.spec` ist maßgeblich: nur dort sind die Symbole (`assets\`) und das Programmsymbol eingetragen. Diese Datei benötigt beim Empfänger keine Python-Installation. Die EXE ist nicht codesigniert. Alternativ kann der manuell auslösbare GitHub-Actions-Workflow **Build Windows bridge** verwendet werden. Er erzeugt ein herunterladbares EXE-Artefakt, veröffentlicht aber kein Release.

Die Bridge sitzt im Infobereich neben der Uhr. Schließen legt sie dorthin; das Symbol zeigt den Zustand auf einen Blick – **grün: Bridge läuft**, grau: gestoppt. Links-Klick holt das Fenster zurück (auch doppelt), Rechtsklick öffnet das Menü (Fenster öffnen / Beenden).

Beendet wird die Bridge ausschließlich über **Beenden** im Fenster oder im Symbolmenü.

**App bei Windows-Anmeldung öffnen** registriert den Pfad der installierten EXE unter HKCU Run mit dem Schalter `--tray` – beim Anmelden erscheint also nur das Symbol, nicht das Fenster. Vor Verschieben/Löschen der App den Schalter deaktivieren, anschließend bei Bedarf am neuen Ort aktivieren.

## Tests und Abnahme

```powershell
py -3 -m unittest discover -s tests -v
```

Die Tests bauen echte Tk-Fenster auf (weit außerhalb des Bildschirms) und legen ihre
Einstellungen in einem temporären Ordner ab – echte Daten bleiben unberührt.

Automatisierte Tests prüfen MIDI-Filter, Positionsgrenzen, Titelsuche, Song-Überspringen, Legacy-Payloads, Authentifizierung/CSRF, Event-Auswahl, Snapshot-Bündelung, Cache, Backoff und HTTP-Ansichten. Unter Windows kommen DPAPI-Roundtrip und WinMM-Geräteauflistung hinzu.

Die Port-Erstellung wird in `tests\test_loopmidi.py` mit Doppeln geprüft: Namen kürzen, Registry-Eintrag schreiben und löschen, winget-Aufruf, Neustart von loopMIDI, Warten auf Sichtbarkeit, Fehlerfälle (kein winget, Programm bleibt hängen, Port erscheint nicht) und die Diagnose-Zustände. Es wird dabei nie wirklich etwas installiert, gestartet oder geschrieben.

Einzelne Bausteine lassen sich direkt prüfen:

```powershell
py -3 loopmidi.py                     # Zustand: installiert, läuft, Ports, Eingänge
py -3 setupguide.py --check           # Was fehlt noch?
py -3 setupguide.py --silent          # Einrichtung ausführen und melden
py -3 setupguide.py --remove          # Port wieder entfernen
```

Vor dem Einsatz im Gottesdienst auf einem Windows-Rechner testen:

1. **MIDI-Port jetzt einrichten** drücken: loopMIDI wird bei Bedarf installiert, der Port angelegt, Ergebnis gemeldet.
2. **Speichern & Start / Neustart** drücken und in Windows sowie in ProPresenter prüfen, dass der Port erscheint (ProPresenter bei Bedarf neu starten).
3. Test-Event in ChurchTools verwenden; in ProPresenter 60/61/62 senden und Zuordnung, Kanal, Velocity-0-Filter und Entprellung kontrollieren.
4. Titel-Sprung und Event-Wechsel testen; Line-/Notes-Source parallel öffnen.
5. Bridge stoppen und prüfen, ob der Port in ProPresenter/Windows bleibt (loopMIDI verwaltet ihn, unabhängig von der Bridge).
6. Netzwerk kurz trennen: Darstellung bleibt erhalten; nach Wiederverbindung aktualisiert sie sich.
7. Rechner neu starten (Bridge-Autostart). Port und MIDI-Verbindung müssen von selbst wiederkommen; das Symbol im Infobereich muss grün sein, ohne dass sich das Fenster öffnet.
8. loopMIDI im Task-Manager beenden und die Bridge neu starten: sie muss loopMIDI erneut starten.
9. Zweite Betriebsart prüfen: ein physischer MIDI-Eingang muss unter **Bereits vorhandenen Port verwenden** funktionieren.
10. Deinstallation prüfen: Bridge, Port, Autostart-Eintrag **und das Symbol im Infobereich** müssen verschwinden.

Noch offen: der praktische Test unter Windows mit ProPresenter. Bisher lokal geprüft wurden die automatisierten Tests, die Port-Erstellung und die WinMM-Sichtbarkeit. Der echte ChurchTools-/ProPresenter-Durchlauf steht aus. Bereits laufende HTTP-Anfragen können beim Stoppen noch abschließen; noch nicht versendete Anfragen werden verworfen.

## Referenzen und Lizenz

- [Microsoft: midiInOpen](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-midiinopen)
- [Microsoft: CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
- [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) – Tobias Erichsen; wird **nicht** mitgeliefert, sondern zur Laufzeit installiert
- [Windows MIDI Services](https://microsoft.github.io/MIDI/) – Microsoft; derzeit noch nicht freigeschaltet, deshalb nicht verwendet
- [Mindestanforderungen Windows MIDI Services](https://microsoft.github.io/MIDI/kb/minimum-requirements/) – Windows 11, 64 Bit; nur zur Information
- Für diesen Port gilt die [Repository-Lizenz](../LICENSE.md).