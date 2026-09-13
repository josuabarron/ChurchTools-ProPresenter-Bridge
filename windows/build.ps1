$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3 mit Tcl/Tk installieren.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build-Abhängigkeiten konnten nicht installiert werden.' }
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests fehlgeschlagen.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name ChurchToolsBridge --add-data "help.html:." app.py
if ($LASTEXITCODE -ne 0) { throw 'EXE-Build fehlgeschlagen.' }
Write-Host 'Fertig: dist\ChurchToolsBridge.exe'
