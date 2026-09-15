"""Erzeugt die Icon-Dateien aus mac/Resources/AppIcon-1024.png.

Ergebnis (windows/assets/):
  app.ico           – Programmsymbol (EXE, Verknüpfungen)
  tray-online.ico   – Infobereich: Bridge läuft
  tray-offline.ico  – Infobereich: Bridge gestoppt

Einmalig ausführen, wenn sich das Ausgangsbild ändert:

    python make-icons.py

Warum die Icons nicht zur Laufzeit entstehen: das Programm lädt sie mit
LoadImageW aus der Datei. Damit bleibt Pillow eine reine Bau-Abhängigkeit und
wandert nicht ins fertige Programm.
"""
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit('Pillow fehlt. Installieren mit: pip install pillow')

HIER = Path(__file__).resolve().parent
QUELLE = HIER.parent / 'mac' / 'Resources' / 'AppIcon-1024.png'
ZIEL = HIER / 'assets'

ONLINE = (46, 204, 113)     # grün: Bridge läuft
OFFLINE = (149, 165, 166)   # grau: Bridge gestoppt

# Windows skaliert aus dieser Liste, je nach Anzeigegröße und DPI.
GROESSEN = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
            (64, 64), (128, 128), (256, 256)]


def mit_statuspunkt(basis, farbe, kante=5, durchmesser=0.42):
    """Legt einen farbigen Punkt unten rechts auf das Symbol.

    Ohne den Punkt wäre online und offline nicht zu unterscheiden – das Symbol
    ist im Infobereich für gewöhnlich 16 Pixel groß.
    """
    for groesse in (64, 128, 256):
        bild = basis.resize((groesse, groesse), Image.LANCZOS).convert('RGBA')
        zeichner = ImageDraw.Draw(bild)
        punkt = int(groesse * durchmesser)
        rand = int(groesse * 0.06)
        x1, y1 = groesse - punkt - rand, groesse - punkt - rand
        # Weißer Ring, damit der Punkt auch auf dunklem Symbol auffällt.
        zeichner.ellipse((x1 - kante, y1 - kante, x1 + punkt + kante, y1 + punkt + kante),
                         fill=(255, 255, 255, 235))
        zeichner.ellipse((x1, y1, x1 + punkt, y1 + punkt), fill=farbe + (255,))
        if groesse == 64:
            ergebnis = bild
    return ergebnis


def main():
    if not QUELLE.exists():
        sys.exit(f'Ausgangsbild fehlt: {QUELLE}')
    ZIEL.mkdir(exist_ok=True)
    basis = Image.open(QUELLE).convert('RGBA')

    # Programmsymbol: das Ausgangsbild direkt.
    pfad = ZIEL / 'app.ico'
    basis.save(pfad, format='ICO', sizes=GROESSEN)
    print(f'{pfad.name:20s} {pfad.stat().st_size:7d} B  ({len(GROESSEN)} Größen)')

    for name, farbe in (('tray-online.ico', ONLINE), ('tray-offline.ico', OFFLINE)):
        bild = mit_statuspunkt(basis, farbe)
        pfad = ZIEL / name
        # Für den Infobereich genügen die kleinen Größen; mehr kostet nur Platz.
        bild.save(pfad, format='ICO', sizes=GROESSEN[:6])
        print(f'{pfad.name:20s} {pfad.stat().st_size:7d} B')


if __name__ == '__main__':
    main()