# Baut die Bridge zu einer EXE. Ergebnis: dist\ChurchToolsBridge.exe
#
# Gebaut wird über die .spec, nicht über Kommandozeilen-Schalter: nur dort sind
# assets/ und das EXE-Symbol eingetragen. Ohne assets/ im Bündel findet die
# Bridge ihre Symbole zur Laufzeit nicht und zeigt das Python-Symbol.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3 mit Tcl/Tk installieren.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build-Abhängigkeiten konnten nicht installiert werden.' }
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests fehlgeschlagen.' }
# Icon-Dateien aus Resources\AppIcon-1024.png erzeugen (idempotent, braucht Pillow).
& .\.venv\Scripts\python.exe make-icons.py
if ($LASTEXITCODE -ne 0) { throw 'Icons konnten nicht erzeugt werden.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ChurchToolsBridge.spec
if ($LASTEXITCODE -ne 0) { throw 'EXE-Build fehlgeschlagen.' }
Write-Host 'Fertig: dist\ChurchToolsBridge.exe'