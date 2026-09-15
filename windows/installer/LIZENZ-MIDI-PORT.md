# Rechtliche Lage der MIDI-Port-Erstellung

Diese Datei hält fest, **warum** die Bridge den MIDI-Port über loopMIDI anlegt und
warum weder loopMIDI noch ein eigener Treiber mitgeliefert wird. Alles ist aus
Originalquellen belegt; die Zitate sind wörtlich.

## Kurzfassung

| Frage | Antwort |
| --- | --- |
| Dürfen wir loopMIDI mitliefern? | **Nein.** Weitergabe ausdrücklich verboten. |
| Dürfen wir es installieren lassen? | **Ja.** winget bezieht es vom Hersteller; seine Verteilung bleibt seine. |
| Dürfen wir den virtualMIDI-Treiber bündeln? | **Nein**, ohne schriftliche Erlaubnis. |
| Ist die Nutzung für eine Gemeinde gedeckt? | **Ja**, *„free for private, non-commercial use"*. |
| Und gewerblich? | **Offen.** Beim Hersteller zu klären. |
| Gibt es einen kaufbaren Lizenzschlüssel? | **Nein.** Nur Kontakt per E-Mail. |
| Preis? | **Nicht veröffentlicht.** |

## loopMIDI und virtualMIDI

Hersteller: Tobias Erichsen, Alte Kolonie 16, 38442 Wolfsburg
Kontakt: info@tobias-erichsen.de

### Zitate

Aus der Lizenzdatei `License.htm` des SDK-Pakets (1.3.0.43):

> „You may use this SDK for personal, internal use"
> „Distribution in any form without prior written permission by the author is prohibited!"
> „If you want to distribute software using this SDK, contact the author about licensing."

Aus dem SDK-PDF:

> „You may not distribute this SDK fully or in part in any way to 3rd parties"
> „Any kind of distribution of software that is using this SDK is forbidden without prior
> written permission by Tobias Erichsen."

Aus der Software-Übersicht:

> „free for private, non-commercial use"
> „may not be distributed via any means without prior written consent by the author.
> If you have commercial interest in any of the software, please let me know via email."

### Was das für dieses Projekt heißt

- **Die DLL darf nicht mit PyInstaller gebündelt werden.** Schon das Einbetten nur
  der `teVirtualMIDI64.dll` ist eine Verteilung.
- Der **kernel-modale, EV-signierte Treiber** `tevirtualMIDI64.sys` ist der Grund:
  er lässt sich nicht frei weitergeben. Nutzbar ist nur das User-Mode-Frontend.
- Die Bridge nutzt deshalb **nur den öffentlichen Port** – sie schreibt den
  Port-Namen in die Registry und startet loopMIDI. Sie lädt keine DLL, ruft keine
  SDK-Funktion auf.
- Die **Installation** über winget geht in Ordnung: Windows lädt das Programm
  vom Hersteller, wir liefern nichts aus.

### Eine spätestens dann nötige Klärung

Wer die Bridge **gewerblich** einsetzt, braucht vorher die schriftliche Erlaubnis.
Es gibt **keinen Shop**. Der einzige Weg ist eine E-Mail an den Hersteller.

Technisch wäre eine spätere eigene Port-Erstellung über das virtualMIDI-SDK
möglich (`virtualMIDICreatePortEx3`). Dafür wäre ein Lizenz-MSI des Herstellers
nötig – und damit dieselbe Klärung.

## Windows MIDI Services (Microsoft)

Nicht verwendet, weil zurzeit nicht funktionsfähig. Zum Nachweis:

`midi.exe` auf einem Retail-Windows-11 (Build 26200):

```
The Windows MIDI Services feature does not appear to be enabled on this PC.
Enablement for supported versions of Windows will come through Windows Update.
```

`midicheckservice.exe`:

```
wdmaud2.drv is not present in registry in values midi-midi9. Most likely, the feature has
not yet been enabled on this PC.
- The new Windows MIDI Services stack is not functional on this PC.
```

Dazu: das Basic-Loopback-Vorschau-Paket verlangt den **Entwicklermodus**, der
im Log mit `0x80073CFF` abbricht.

Selbst wenn es liefe: die Binaries dürfen **nicht** mitgeliefert werden
(„Do not redistribute any of the installers or transports"), auch wenn der
Quellcode MIT-lizenziert ist.

**Wiedervorlage:** Sobald das Feature per Windows-Update ausgerollt ist, kann ein
zweiter Weg neben loopMIDI gebaut werden. Die Port-Erstellung ist bereits in
`windows/loopmidi.py` gekapselt.

## Nicht geprüft

Die Frage, ob loopMIDI **gewerblich** kostenfrei ist. Die Seiten nennen für die
kommerzielle Nutzung keine Bedingungen außer dem Verweis auf den Kontakt. Für den
Einsatz in einer Gemeinde unkritisch; für kommerziellen Einsatz **vorher klären**.