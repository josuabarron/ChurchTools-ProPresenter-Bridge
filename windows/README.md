# ChurchTools Bridge für Windows

**Status: Ungetestet (untested). Der praktische Test unter Windows mit loopMIDI und ProPresenter steht noch aus. Automatisierte Tests und ein erfolgreicher EXE-Build ersetzen diesen Funktionstest nicht.**

Windows-Port der Swift-App mit Python/Tk-Oberfläche, ohne zusätzliche Python-Laufzeitbibliotheken. Ein EXE-Build bündelt Python und Tk. Vorgesehen für Windows 10/11 x64; ein echter Windows-/ProPresenter-Test steht noch aus.

Die Schaltfläche **Hilfe** öffnet die Setup-Anleitung auch vor dem ersten Bridge-Start. Bei laufendem Server ist sie zusätzlich unter `/help` und `/live/help` erreichbar.

## MIDI: loopMIDI als virtuelles Kabel

```text
ProPresenter MIDI-Ausgang → loopMIDI „ChurchTools Bridge“ → Windows-Bridge → ChurchTools
```

1. [loopMIDI vom Hersteller](https://www.tobias-erichsen.de/software/loopmidi.html) separat installieren.
2. In loopMIDI einen Port namens **ChurchTools Bridge** erstellen und dessen Autostart aktivieren. loopMIDI muss laufen; das Schließen des Konfigurationsfensters minimiert es in den Infobereich.
3. Bridge starten, **Ports suchen** drücken und diesen MIDI-Eingang auswählen.
4. In ProPresenter denselben Port als MIDI-Ausgang auswählen. ProPresenter bei Bedarf nach dem Erstellen des Ports neu starten.
5. Note On auf Kanal 1, Velocity > 0 senden: standardmäßig 60 zurück, 61 vor, 62 Position 3. Die App erlaubt Kanal 1–16 und frei wählbare Noten/Ziele.

Die Bridge öffnet einen vorhandenen Eingang über Windows **WinMM** (`midiInOpen`). Sie erstellt keinen eigenen virtuellen MIDI-Port. Es wird kein loopMIDI-/virtualMIDI-Code kopiert oder mitgeliefert. Ein physischer MIDI-Eingang kann ebenfalls ausgewählt werden. Für eine spätere integrierte Port-Erstellung wäre das [virtualMIDI SDK](https://www.tobias-erichsen.de/software/virtualmidi.html) einschließlich gesonderter Klärung der Vertriebsbedingungen eine mögliche Erweiterung.

## Aus Quellcode starten

Python 3.10 oder neuer für Windows mit Tcl/Tk installieren, dann im Ordner `windows`:

```powershell
py -3 app.py
```

API-URL (HTTPS, z. B. `https://example.church.tools/api`), Login-Token und User-ID eintragen, MIDI-Port auswählen und **Speichern & Start / Neustart** drücken. Damit wird auch die Verbindung geprüft. Nach späteren Starts läuft die Bridge mit gespeicherten Zugangsdaten automatisch an. Ist loopMIDI noch nicht bereit, nach dessen Start die Ports neu suchen und die Bridge neu starten.

MIDI-Ziele: `zurück`, `zurueck`, `previous`, `back`; `vor`, `weiter`, `next`, `forward`; eine Position oder ein Agenda-Titel. Position 0 ist „nicht gestartet“, die Position nach dem letzten Eintrag ist „Ende“. Überschriften zählen nicht mit, Songs mit Dauer 0 werden bei „vor“ übersprungen. Titel werden ohne Beachtung von Großschreibung/Akzenten verglichen. Entprellung gilt pro Note; Note Off und Note On mit Velocity 0 lösen nichts aus.

Die Event-Suche übernimmt die bisherige Auswahl: bis zu 25 Events im Suchzeitraum, passende Agenden am ersten passenden Tag, optional nur gesperrte Agenden. Bei mehreren Events kann die Auswahl im Fenster geändert werden. Neustart lädt Events und Agenden neu. Nach Verbindungsfehlern ohne Event-Auswahl ebenfalls neu starten.

## Lokale Ansichten

- `http://127.0.0.1:8765/live` – Weiterleitung zur ChurchTools Live-Agenda.
- `http://127.0.0.1:8765/live/strip` – Jetzt/Dann.
- `http://127.0.0.1:8765/live/notes` – Notizen, Schriftgröße konfigurierbar.

Als Browser-Source in ProPresenter verwenden. Die Ansichten pollen die Bridge, die ChurchTools-Abfragen bündelt und mindestens drei Sekunden cached. Bei Ausfällen bleiben bereits geladene Daten erhalten; HTTP 429 löst mindestens 60 Sekunden Backoff aus. Ein Neustart übernimmt geänderte Anzeige-Einstellungen.

Der Server bindet ausschließlich an `127.0.0.1`. `/live` enthält den Login-Token in der Weiterleitungsadresse wie die macOS-Version. Nur einen eingeschränkten ChurchTools-Funktionsbenutzer verwenden; die endgültige Weiterleitungsadresse nicht weitergeben. Titel und Notizen werden als Text dargestellt, nicht als ausführbares HTML.

Einstellungen liegen unter `%LOCALAPPDATA%\ChurchToolsProPresenterBridge\settings.json`, der Token separat unter `token.dpapi`, mit Windows DPAPI für den Benutzer verschlüsselt. Beim Kopieren auf einen anderen Rechner/Benutzer muss der Token neu eingegeben werden. Diagnosemeldungen enthalten keine API-Antwortkörper oder Tokens.

## EXE bauen

Auf Windows im Ordner `windows`:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Das Skript erstellt eine lokale virtuelle Python-Umgebung, installiert PyInstaller, führt die Tests aus und baut `dist\ChurchToolsBridge.exe`. Diese Datei benötigt beim Empfänger keine Python-Installation; loopMIDI bleibt eine separate Voraussetzung. Der Build ist nicht codesigniert. Alternativ kann der manuell auslösbare GitHub-Actions-Workflow **Build Windows bridge** im Repository verwendet werden. Er erzeugt ein herunterladbares EXE-Artefakt, veröffentlicht aber kein Release.

Die Oberfläche ist ein normales Windows-Fenster. Minimieren lässt die Bridge weiterlaufen; Schließen beendet sie. **App bei Windows-Anmeldung öffnen** registriert den aktuellen EXE-/Skriptpfad unter HKCU Run. Vor Verschieben/Löschen der App den Schalter deaktivieren, anschließend bei Bedarf am neuen Ort aktivieren. loopMIDI-Autostart separat aktivieren.

## Tests und Abnahme

```powershell
py -3 -m unittest discover -s tests -v
```

Automatisierte Tests prüfen MIDI-Filter, Positionsgrenzen, Titelsuche, Song-Überspringen, Legacy-Payloads, Authentifizierung/CSRF, Event-Auswahl, Snapshot-Bündelung, Cache, Backoff und HTTP-Ansichten. Unter Windows kommen DPAPI-Roundtrip und WinMM-Geräteauflistung hinzu.

Vor dem Einsatz im Gottesdienst auf einem Windows-Rechner testen:

1. EXE starten und loopMIDI-Port auswählen; Test-Event in ChurchTools verwenden.
2. In ProPresenter 60/61/62 senden; Zuordnung, Kanal, Velocity-0-Filter und Entprellung kontrollieren.
3. Titel-Sprung und Event-Wechsel testen; Line-/Notes-Source parallel öffnen.
4. Netzwerk kurz trennen: Darstellung bleibt erhalten; nach Wiederverbindung aktualisiert sie sich.
5. Bridge neu starten und prüfen, dass Token/Port/Event erhalten bleiben.
6. loopMIDI beenden und neu starten, dann Bridge neu starten. Automatisches Wiederverbinden nach einem verlorenen MIDI-Port ist noch nicht implementiert.
7. Windows neu anmelden und beide Autostarts prüfen.

Bisher lokal geprüft: plattformunabhängige Tests auf macOS. Windows-EXE, Windows-GUI, WinMM, DPAPI und der echte ChurchTools-/ProPresenter-Durchlauf müssen unter Windows verifiziert werden. Bereits laufende HTTP-Anfragen können beim Stoppen noch abschließen; noch nicht versendete Anfragen werden verworfen.

## Referenzen und Lizenz

- [Microsoft: midiInOpen](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-midiinopen)
- [Microsoft: CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
- Für diesen Port gilt die [Repository-Lizenz](../LICENSE.md). loopMIDI wird unabhängig vom Hersteller bezogen.
