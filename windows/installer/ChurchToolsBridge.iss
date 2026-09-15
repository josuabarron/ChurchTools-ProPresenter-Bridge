; ChurchTools Bridge – Installer
;
; Ein Setup für alles: Bridge kopieren, MIDI-Port einrichten, Autostart setzen.
;
; Der MIDI-Port entsteht über loopMIDI (Tobias Erichsen). loopMIDI wird NICHT
; mitgeliefert – es wird während der Installation über winget vom Hersteller
; geholt. Grund: die Weitergabe von loopMIDI ist nicht gestattet; winget
; installiert es vom Hersteller, also bleibt die Verteilung dort, wo sie
; hingehört. Fehlt winget auf dem Rechner, holt die Bridge es später über den
; Assistenten nach (Schaltfläche „MIDI-Port jetzt einrichten“).
;
; Drei Fallen, die hier bewusst umgangen werden:
;
; 1. KEIN [Registry]-Eintrag für den Autostart. Das Setup läuft erhöht, HKCU
;    wäre dann das Konto des Administrators. Stattdessen setzt die Bridge den
;    Eintrag selbst (Schritt 2, mit runasoriginaluser).
;
; 2. Laufende Bridge VOR dem Deinstallieren beenden. Sonst sperrt die EXE sich
;    selbst, Windows kann sie nicht löschen und markiert sie nur für einen
;    Neustart – der Ordner bliebe bestehen. Siehe StopBridge() und
;    InitializeUninstall(). CloseApplications ist deshalb AUS: der Restart
;    Manager würde die Bridge nach der Deinstallation wieder starten.
;
; 3. Die Bridge-EXE wird NICHT aus {app} heraus aufgerufen, sondern aus einer
;    Kopie in einem Administratoren-Ordner (siehe BridgeBase). Eine laufende
;    EXE sperrt sich selbst – liefe sie aus {app}, könnte der Deinstaller den
;    Ordner nicht restlos entfernen. Der Ordner ist bewusst KEIN Benutzer-Temp:
;    die Kopie wird erhöht gestartet, ein beschreibbarer Ort wäre eine
;    Rechteausweitung.
;
; Bauen:  powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
; Ohne /DBridgeExe wird nach ..\dist\ChurchToolsBridge.exe gesucht.

#ifndef BridgeExe
  #define BridgeExe "..\dist\ChurchToolsBridge.exe"
#endif
#ifndef OutDir
  #define OutDir "output"
#endif
#ifndef PortName
  #define PortName "ChurchTools Bridge"
#endif
#define MyAppName "ChurchTools Bridge"
; Die Version kommt von außen (build-installer.ps1 liest VERSION aus dem
; Repo-Wurzelverzeichnis). Der Wert hier ist nur ein Notnagel für den direkten
; iscc-Aufruf – sonst müsste die Nummer an drei Stellen gepflegt werden.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "ChurchTools ProPresenter Bridge"
#define MyAppExeName "ChurchToolsBridge.exe"
; Arbeitskopie, aus der die Einrichtungsschritte laufen (siehe Punkt 3 oben).
; NICHT {tmp}: dort hat der Benutzer Vollzugriff, und der Installer startet
; die Kopie erhoeht - zwischen Kopieren und Start liesse sie sich austauschen
; (Rechteausweitung). {app} liegt unter C:\Program Files: Benutzer duerfen
; dort nur lesen (gemessen: Schreiben verweigert), Administratoren schreiben.
; {commonappdata} waere FALSCH - C:\ProgramData erlaubt Benutzern das Anlegen
; eigener Dateien (WD,AD) und gibt dem Ersteller Vollzugriff.
#define BridgeBase "{app}\ctp-cmd"
; Bericht aus Schritt 1. Dieser Schritt laeuft ERHOEHT und darf deshalb
; nur in einen Administratorenordner schreiben - {tmp} waere eine
; Rechteausweitung (Datei austauschbar, Reparse-Point).
#define ProgramReport BridgeBase + "\ctp-program.txt"
; Bericht aus Schritt 2/3. Diese laufen mit runasoriginaluser, also als
; normaler Benutzer. Fuer die ist der Benutzer-Temp der richtige Ort:
; hier entsteht keine Rechteausweitung, weil der schreibende Prozess
; bereits normale Rechte hat. {app} ginge hier NICHT - dort darf ein
; Benutzer nicht schreiben, der Bericht bliebe leer.
#define MidiReportFile "{tmp}\ctp-midi.txt"

[Setup]
AppId={{7E3C1F2A-9B44-4D5E-8A31-6C0D5A9E41B7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ChurchTools Bridge
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=ChurchToolsBridge-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
UninstallDisplayName={#MyAppName}
SetupLogging=yes
AllowNoIcons=yes
; Symbole: die Setup-Datei selbst und der Eintrag unter „Apps“.
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Wir beenden die Bridge selbst (StopBridge). Der Restart Manager würde sie
; nach der Deinstallation wieder starten – das wäre falsch.
CloseApplications=no
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "autostart"; Description: "Bridge beim Anmelden automatisch starten (empfohlen)"; GroupDescription: "Zusätzlich:"
Name: "desktopicon"; Description: "Verknüpfung auf den Desktop anlegen"; GroupDescription: "Zusätzlich:"

[Files]
Source: "{#BridgeExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\help.html"; DestDir: "{app}"; Flags: ignoreversion
; Arbeitskopie für die Einrichtungsschritte: nicht aus {app} starten, damit die
; Bridge nicht sich selbst im Weg steht. Der Ort gehört Administratoren, damit
; der Benutzer die Datei nicht vor dem erhöhten Start austauschen kann.
Source: "{#BridgeExe}"; DestDir: "{#BridgeBase}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion deleteafterinstall
Source: "..\help.html"; DestDir: "{#BridgeBase}"; Flags: ignoreversion deleteafterinstall

[Icons]
Name: "{autoprograms}\ChurchTools Bridge"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\ChurchTools Bridge-Hilfe"; Filename: "{app}\help.html"
Name: "{autodesktop}\ChurchTools Bridge"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Schritt 1: MIDI-Hilfsprogramm maschinenweit bereitstellen. Läuft erhöht.
; Dieser Schritt installiert loopMIDI und beendet es danach wieder: aus einem
; erhöhten Prozess gestartet, ließe es sich später nicht mehr steuern.
Filename: "{#BridgeBase}\{#MyAppExeName}"; \
    Parameters: "--ensure-midi-program --report ""{#ProgramReport}"""; \
    StatusMsg: "MIDI-Hilfsprogramm wird bereitgestellt (loopMIDI wird bei Bedarf installiert)..."; \
    Flags: runhidden waituntilterminated

; Schritt 2: MIDI-Port anlegen und Autostart setzen – im Konto des angemeldeten
; Nutzers (runasoriginaluser). Hier startet die Bridge loopMIDI selbst, als
; normaler Benutzer; nur so bleibt es steuerbar.
; --app-path: die Bridge läuft aus der Arbeitskopie (siehe Punkt 3). Ohne diesen
; Hinweis zeigte der Autostart auf einen Ordner, den das Setup später räumt.
Filename: "{#BridgeBase}\{#MyAppExeName}"; Tasks: autostart; \
    Parameters: "--complete-setup --autostart 1 --app-path ""{app}\{#MyAppExeName}"" --port-name ""{#PortName}"" --report ""{#MidiReportFile}"""; \
    StatusMsg: "MIDI-Port wird eingerichtet..."; \
    Flags: runhidden waituntilterminated runasoriginaluser

Filename: "{#BridgeBase}\{#MyAppExeName}"; Tasks: not autostart; \
    Parameters: "--complete-setup --autostart 0 --app-path ""{app}\{#MyAppExeName}"" --port-name ""{#PortName}"" --report ""{#MidiReportFile}"""; \
    StatusMsg: "MIDI-Port wird eingerichtet..."; \
    Flags: runhidden waituntilterminated runasoriginaluser

; Start aus {app}: die Bridge liegt dort dauerhaft. nowait, weil sie weiterläuft.
Filename: "{app}\{#MyAppExeName}"; Description: "ChurchTools Bridge jetzt starten"; \
    Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
; Hier steht bewusst NICHTS. Ein Aufruf der Bridge-EXE wäre unzuverlässig:
; sie muss vor dem Löschen laufen, die Arbeitskopie kann aber fehlen. Port und
; Autostart räumt stattdessen das Deinstallations-Skript ab
; (CurUninstallStepChanged/usUninstall + RemoveEverything).

[UninstallDelete]
; Der Ordner soll nicht leer zurückbleiben.
Type: dirifempty; Name: "{app}"
; Die Arbeitskopie und die Berichtdateien des Setups entfernen.
Type: filesandordirs; Name: "{#BridgeBase}"

[Code]
const
  KEPT = 'Der MIDI-Port wurde entfernt. Falls loopMIDI auf diesem Rechner nicht '
       + 'anderweitig gebraucht wird, kann es in den Windows-Einstellungen unter '
       + '„Apps“ deinstalliert werden.';

{ Beendet eine laufende Bridge. Ohne das sperrt die EXE sich selbst und Windows
  kann sie nicht löschen; sie bliebe bis zum nächsten Neustart liegen. }
function StopBridge(): Boolean;
var
  resultCode: Integer;
  attempt: Integer;
  target: string;
begin
  Result := True;
  target := '{#MyAppExeName}';

  { Zuerst höflich fragen: nur so räumt die Bridge ihr Symbol neben der Uhr weg.
    Ein hartes taskkill ließe das Symbol als Leiche stehen, bis der Mauszeiger
    darüberfährt. Ist die Bridge nicht erreichbar, greift die Schleife unten. }
  if FileExists(ExpandConstant('{app}\{#MyAppExeName}')) then
  begin
    if Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--quit', '', SW_HIDE,
            ewWaitUntilTerminated, resultCode) then
      Log('Bridge um Beendigung gebeten (Rückgabewert ' + IntToStr(resultCode) + ').')
    else
      Log('Bridge konnte nicht um Beendigung gebeten werden.');
  end;

  for attempt := 1 to 10 do
  begin
    if not Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ' + target,
                '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    begin
      Log('taskkill konnte nicht ausgeführt werden (Versuch ' + IntToStr(attempt) + ').');
      Result := False;
      Sleep(300);
      Continue;
    end;
    { 0 = beendet, 128 = lief nicht. Alles andere ist ein echter Fehler. }
    if resultCode = 0 then
    begin
      Log('Laufende Bridge beendet (Versuch ' + IntToStr(attempt) + ').');
      Sleep(700);
      Continue;   { nochmal prüfen, ob wirklich keine mehr läuft }
    end;
    if resultCode = 128 then
    begin
      Log('Keine laufende Bridge gefunden.');
      Exit;
    end;
    Log('taskkill Rückgabewert ' + IntToStr(resultCode) + '.');
    Sleep(500);
  end;
  Log('Bridge ließ sich nicht sicher beenden.');
end;

{ Legt die Arbeitskopie an, aus der die Schritte laufen. Der Ort ist
  absichtlich KEIN Temp-Ordner des Benutzers: die Kopie wird erhoeht
  gestartet, ein beschreibbarer Ort waere eine Rechteausweitung. }
procedure PrepareBridgeCopy();
var
  base, source: string;
begin
  base := ExpandConstant('{#BridgeBase}');
  source := ExpandConstant('{app}\{#MyAppExeName}');
  ForceDirectories(base);
  if not FileExists(base + '\{#MyAppExeName}') then
  begin
    if not CopyFile(source, base + '\{#MyAppExeName}', False) then
      Log('Arbeitskopie der Bridge konnte nicht angelegt werden.');
  end;
  if (not FileExists(base + '\help.html')) and FileExists(ExpandConstant('{app}\help.html')) then
    CopyFile(ExpandConstant('{app}\help.html'), base + '\help.html', False);
end;

procedure RemoveBridgeCopy();
var
  base: string;
begin
  base := ExpandConstant('{#BridgeBase}');
  DeleteFile(base + '\{#MyAppExeName}');
  DeleteFile(base + '\help.html');
  RemoveDir(base);
end;

function MidiReport(): string;
var
  lines: TArrayOfString;
  path: string;
  index: Integer;
  text: string;
begin
  text := '';
  path := ExpandConstant('{#MidiReportFile}');
  if FileExists(path) then
  begin
    if LoadStringsFromFile(path, lines) then
    begin
      for index := 0 to GetArrayLength(lines) - 1 do
      begin
        if Trim(lines[index]) <> '' then
        begin
          text := text + lines[index] + #13#10;
        end;
      end;
    end;
  end;
  Result := text;
end;

{ Läuft noch vor dem Kopieren der Dateien: eine laufende Bridge (etwa beim
  Aktualisieren) würde sich sonst selbst im Weg stehen. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopBridge();
  Result := '';
end;

{ Läuft ganz am Anfang der Deinstallation – also BEVOR Windows Dateien löscht.
  Hier wird die laufende Bridge beendet und die Arbeitskopie bereitgestellt. }
function InitializeUninstall(): Boolean;
begin
  StopBridge();
  PrepareBridgeCopy();
  Result := True;
end;

{ Entfernt Autostart-Eintrag und MIDI-Port. Läuft im Deinstaller, weil ein
  separater EXE-Aufruf unzuverlässig wäre (die Dateien werden gerade gelöscht).
  Alles hier ist best effort: Fehler dürfen die Deinstallation nicht aufhalten. }
procedure RemoveEverything();
var
  resultCode: Integer;
  script: string;
begin
  { Autostart im Benutzerkonto entfernen. }
  if not Exec(ExpandConstant('{sys}\reg.exe'),
              'delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" '
              + '/v ChurchToolsBridge /f', '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    Log('Autostart-Eintrag konnte nicht entfernt werden.');
  Log('Autostart-Eintrag entfernt (Rückgabewert ' + IntToStr(resultCode) + ').');

  { MIDI-Port aus der loopMIDI-Konfiguration entfernen. }
  script := 'Remove-ItemProperty -Path ''HKCU:\SOFTWARE\Tobias Erichsen\loopMIDI\Ports'' '
            + '-Name ''{#PortName}'' -ErrorAction SilentlyContinue; '
            + 'Stop-Process -Name loopMIDI -Force -ErrorAction SilentlyContinue';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
              '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + script + '"',
              '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    Log('MIDI-Port konnte nicht entfernt werden.');
  Log('loopMIDI-Eintrag bereinigt (Rückgabewert ' + IntToStr(resultCode) + ').');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  report: string;
begin
  if CurStep = ssPostInstall then
  begin
    PrepareBridgeCopy();
    report := MidiReport();
    if report <> '' then
    begin
      if Pos('ist bereit', report) <= 0 then
      begin
        MsgBox('Der MIDI-Port konnte noch nicht automatisch angelegt werden:' + #13#10 + #13#10
               + report + #13#10
               + 'Die Bridge holt das beim ersten Start nach: dort „MIDI-Port jetzt einrichten“ '
               + 'drücken.', mbInformation, MB_OK);
      end;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    { Vor dem Löschen: Bridge beenden und die letzten Spuren beseitigen. }
    StopBridge();
    RemoveEverything();
    PrepareBridgeCopy();
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    StopBridge();
    RemoveBridgeCopy();
    MsgBox('Die Bridge wurde entfernt.' + #13#10 + #13#10 + KEPT, mbInformation, MB_OK);
  end;
end;