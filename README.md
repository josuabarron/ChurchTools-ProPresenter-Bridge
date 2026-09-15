# ChurchTools ProPresenter Bridge

Eine Bridge, die die ChurchTools Live-Agenda per MIDI aus ProPresenter steuert. Für macOS und Windows.

```text
ProPresenter MIDI -> ChurchTools Bridge -> ChurchTools Live-Agenda
```

Das Repository enthält **zwei eigenständige Fassungen** derselben App, je in einem eigenen Ordner:

| Ordner | System | Umsetzung | Bauen |
| --- | --- | --- | --- |
| [`mac`](mac) | macOS 13+ | Swift/SwiftUI-Menüleisten-App | `mac/scripts/build-app.sh` |
| [`windows`](windows) | Windows 10/11 x64 | Python/Tk, EXE + Installer | `windows/build.ps1`, `windows/installer/build-installer.ps1` |

Beide sprechen dieselbe ChurchTools-API und dieselben MIDI-Befehle. Die Einrichtung unterscheidet sich, weil die Systeme verschiedene MIDI-Unterbauten haben.

## Wie das MIDI ankommt

ProPresenter sendet MIDI-Noten. Die Bridge lauscht auf einem virtuellen MIDI-Eingang namens `ChurchTools Bridge` und übersetzt jede Note in eine Aktion der Live-Agenda.

| Send | Standard-Note | Wirkung |
| --- | ---: | --- |
| `zurück` | 60 | einen Agenda-Punkt zurück |
| `vor` | 61 | einen Agenda-Punkt vor |
| `3` oder ein Agenda-Titel | 62 | Sprung zu dieser Position bzw. zum gleichnamigen Titel |

Die Sends sind in beiden Fassungen frei konfigurierbar: links das Ziel, rechts die MIDI-Note. Gesendet wird auf **Kanal 1** mit **Velocity > 0**; Note Off und Velocity 0 lösen nichts aus.

## Virtueller MIDI-Port

Der Port muss vom System bereitgestellt werden – beide Systeme können das nicht von Haus aus.

**macOS** bringt CoreMIDI mit: die App legt das virtuelle Ziel selbst an, es ist sofort da.

**Windows** braucht ein Hilfsprogramm. Die Bridge nutzt [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html), trägt den Port-Namen selbst in die Registry ein, startet loopMIDI neu und wartet, bis WinMM den Port sieht – die loopMIDI-Oberfläche muss nicht geöffnet werden. Alternativ lässt sich ein bereits vorhandenes MIDI-Gerät verwenden.

loopMIDI wird **nicht mitgeliefert** – der Installer holt es über winget direkt vom Hersteller. Es gilt die Lizenz von Tobias Erichsen: freie Nutzung für *„private, non-commercial use"*, jede Weitergabe ist ohne schriftliche Genehmigung untersagt. Für eine Gemeinde ist die Nutzung damit gedeckt; wer die Bridge gewerblich einsetzt, muss das vorher mit dem Hersteller klären.

## Lokale Anzeige-Ansichten

Beide Fassungen betreiben einen lokalen Server auf `127.0.0.1:8765`, dessen Ansichten für ProPresenter-Browser-Sources gedacht sind:

```text
http://127.0.0.1:8765/live          -> ChurchTools Live-Agenda (Weiterleitung)
http://127.0.0.1:8765/live/strip    -> kompakte Line-Ansicht
http://127.0.0.1:8765/live/notes    -> nur die Notizen des aktuellen Punktes
```

Der Server hört ausschließlich auf `localhost` und deaktiviert Browser-Caching. `/live` leitet zur ChurchTools Live-Agenda weiter und enthält den konfigurierten Login-Token — nutze diese URL nur auf einem vertrauenswürdigen Rechner mit einem eng eingeschränkten ChurchTools-Funktionsbenutzer.

`/live/strip` und `/live/notes` fragen die lokale Bridge ab, nicht ChurchTools direkt. Die Bridge cached den letzten Stand, bündelt gleichzeitige Anfragen und wartet bei HTTP 429 automatisch (60 Sekunden Backoff). Die Ansichten aktualisieren sich alle 2,5 Sekunden und zeigen den letzten bekannten Stand weiter an, wenn ChurchTools kurz nicht erreichbar ist.

## Features

- Virtuelles MIDI-Ziel `ChurchTools Bridge`
- Frei konfigurierbare MIDI-Sends für zurück, vor, Agenda-Position oder Agenda-Titel
- MIDI-Sends einzeln manuell auslösbar
- Automatische Auswahl des nächsten passenden ChurchTools-Events
- Manuelle Event-Auswahl, wenn an einem Tag mehrere passende Agenden vorhanden sind
- Optionale Beschränkung auf gesperrte Agenden
- Login-Token im macOS-Schlüsselbund bzw. unter Windows DPAPI-verschlüsselt

## Voraussetzungen

- macOS 13 oder neuer **oder** Windows 10/11 x64
- Eine ChurchTools-Instanz und ein Login-Token
- ProPresenter mit MIDI-Unterstützung
- Für unbeaufsichtigte Anzeigen wird ein eingeschränkter ChurchTools-Funktionsbenutzer empfohlen

## Einrichtung

1. Einstellungen öffnen.
2. API-URL eintragen, zum Beispiel `https://example.church.tools/api`.
3. Login-Token und ChurchTools-User-ID eintragen.
4. Bei Bedarf die MIDI-Sends anpassen.
5. Übernehmen.
6. In ProPresenter denselben Namen als MIDI-Ausgang und die Noten als Aktionen anlegen.


## Umsetzung

Events und Agenden kommen aus der öffentlichen ChurchTools-REST-API. Die Live-Position wird über den Legacy-Endpunkt `churchservice/ajax` mit `loadAgendaLivePosition` und `saveAgendaLivePosition` gesteuert.

## Sicherheit

- Dieses Repository enthält keine ChurchTools-URL, keine Tokens, keine User-IDs, keine Event-IDs und keine personenbezogenen Daten.
- Zugangsdaten liegen im macOS-Schlüsselbund mit gerätegebundener Verfügbarkeit bzw. unter Windows DPAPI-verschlüsselt; der Zugriff ist durch das Betriebssystem geschützt.
- Der lokale Server hört ausschließlich auf `127.0.0.1`.
- Verwende für den Login-Token einen Funktionsbenutzer mit möglichst wenigen ChurchTools-Rechten.

## Referenzen

- [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) – Tobias Erichsen; wird **nicht** mitgeliefert, sondern zur Laufzeit vom Hersteller installiert

## Lizenz

Lizenziert unter der [PolyForm Noncommercial License 1.0.0](LICENSE.md). Du darfst die Software für nicht-kommerzielle Zwecke verwenden, verändern und weitergeben. Kommerzielle Nutzung, Weiterverkauf und die Nutzung in einem kommerziellen Produkt oder Dienst sind nicht erlaubt.

Das ist eine source-available Lizenz, keine OSI-anerkannte Open-Source-Lizenz.