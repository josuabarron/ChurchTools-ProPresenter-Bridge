# Baut den einen Installer: output\ChurchToolsBridge-Setup.exe
#
# Ablauf: Tests -> Bridge-EXE (.spec) -> Inno-Setup-Installer.
# Voraussetzungen: Python 3.10+ (mit Tcl/Tk), Inno Setup 6 (winget install JRSoftware.InnoSetup)

$ErrorActionPreference = 'Stop'
$windows = Join-Path $PSScriptRoot '..'
$repo = Join-Path $windows '..'
$output = Join-Path $PSScriptRoot 'output'

# Version aus der einen Quelle im Repo-Wurzelverzeichnis.
$versionFile = Join-Path $repo 'VERSION'
if (-not (Test-Path $versionFile)) { throw "VERSION fehlt: $versionFile" }
$version = (Get-Content $versionFile -Raw).Trim()
if (-not $version) { throw 'VERSION ist leer.' }

function Find-InnoSetup {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    # winget installiert je nach Aufruf pro Benutzer oder pro Maschine.
    foreach ($root in @($env:LOCALAPPDATA, $env:ProgramData, ${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        $found = Get-ChildItem -Path $root -Filter 'ISCC.exe' -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    throw 'Inno Setup 6 nicht gefunden. Installieren mit: winget install JRSoftware.InnoSetup'
}

Push-Location $windows
try {
    Write-Host '== Tests =='
    py -3 -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw 'Tests fehlgeschlagen.' }

    Write-Host '== Bridge-EXE =='
    if (-not (Test-Path '.venv')) { py -3 -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --quiet -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Build-Abhängigkeiten konnten nicht installiert werden.' }
    # Icons aus dem Ausgangsbild erzeugen (idempotent, braucht Pillow).
    & .\.venv\Scripts\python.exe make-icons.py
    if ($LASTEXITCODE -ne 0) { throw 'Icons konnten nicht erzeugt werden.' }
    # Über die .spec bauen: dort sind assets/ und das EXE-Symbol eingetragen.
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ChurchToolsBridge.spec
    if ($LASTEXITCODE -ne 0) { throw 'EXE-Build fehlgeschlagen.' }
}
finally {
    Pop-Location
}

$bridge = Join-Path $windows 'dist\ChurchToolsBridge.exe'
if (-not (Test-Path $bridge)) { throw "Bridge-EXE nicht gefunden: $bridge" }

Write-Host '== Installer =='
$iscc = Find-InnoSetup
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $iscc (Join-Path $PSScriptRoot 'ChurchToolsBridge.iss') `
    "/DBridgeExe=$bridge" `
    "/DOutDir=$output" `
    "/DMyAppVersion=$version"
if ($LASTEXITCODE -ne 0) { throw 'Installer-Build fehlgeschlagen.' }

$setup = Join-Path $output 'ChurchToolsBridge-Setup.exe'
Write-Host ''
Write-Host "Fertig: $setup"
Write-Host "Version: $version"
Write-Host ('Größe: {0:N1} MB' -f ((Get-Item $setup).Length / 1MB))
Write-Host ''
Write-Host 'Der Installer richtet den MIDI-Port automatisch ein.'
Write-Host 'Dafür wird loopMIDI bei Bedarf über winget vom Hersteller geholt –'
Write-Host 'loopMIDI selbst wird nicht mitgeliefert (Weitergabe nicht gestattet).'