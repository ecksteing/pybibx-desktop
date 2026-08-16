; installer_config.iss
; Builds the Windows installer for PyBibX Desktop.
; Prerequisites: PyInstaller --onedir output staged as run_pybibx.exe +
; _internal\ at the repo root, and Python-Portable prepared + critical-baked
; (prepare_python_portable.ps1 then bake_critical_packages.ps1).
;
; Core libs ship inside Python-Portable. Optional bootstrap task verifies /
; repairs them. Torch / AI wheels still install on first launch (background).

; --- Read version dynamically from version.txt ---
#define VerFile FileOpen("version.txt")
#define MyAppVersion FileRead(VerFile)
#expr FileClose(VerFile)

#define MyAppName "PyBibX Desktop"
#define MyAppPublisher "Gary Eckstein"
#define MyAppURL "https://github.com/ecksteing/pybibx-desktop"
#define MyAppExeName "run_pybibx.exe"

[Setup]
; IMPORTANT: keep this GUID stable across releases so upgrades/uninstall work.
AppId={{8F3C1A2B-6D4E-4F91-9B2C-7A5E0D1C4B8F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=Output
OutputBaseFilename=PyBibXSetup_{#MyAppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
CloseApplications=force
RestartIfNeededByRun=no
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "bootstrap"; Description: "Verify core PyBibX libraries (quick if already baked; repairs if needed)"; GroupDescription: "Runtime setup:"; Flags: checkedonce

[Files]
Source: "run_pybibx.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "launch_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "loading_status.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "loading.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "stop_pybibx.ps1"; DestDir: "{app}"; Flags: ignoreversion
; Also pack for ExtractTemporaryFile so upgrades use THIS script, not the old install's copy.
Source: "stop_pybibx.ps1"; Flags: dontcopy
Source: "scripts\bootstrap_runtime.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "scripts\critical_packages.txt"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "version.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "Python-Portable\*"; DestDir: "{app}\Python-Portable"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
; Usually a quick verify (core libs are baked). AI/Torch finish on first launch.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\bootstrap_runtime.ps1"" -AppDir ""{app}"""; \
  StatusMsg: "Verifying core PyBibX libraries (AI packages finish on first launch)..."; \
  Flags: waituntilterminated; Tasks: bootstrap
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; Remove the entire install folder, including runtime data Inno did not install
; (pip packages under Python-Portable, launcher.log leftovers, etc.).
[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure StopAppProcessesIn(const AppDir: String; const FromInstaller: Boolean);
var
  ResultCode: Integer;
  ScriptPath: String;
  Params: String;
begin
  if AppDir = '' then
    Exit;

  ScriptPath := '';

  { ExtractTemporaryFile is only valid during install/upgrade — never uninstall. }
  if FromInstaller then
  begin
    { Prefer the stop script packed in this setup (dontcopy), so upgrades are not
      stuck with a weaker script from the previously installed version. }
    ExtractTemporaryFile('stop_pybibx.ps1');
    ScriptPath := ExpandConstant('{tmp}\stop_pybibx.ps1');
  end;

  if (ScriptPath = '') or (not FileExists(ScriptPath)) then
    ScriptPath := AppDir + '\stop_pybibx.ps1';

  if FileExists(ScriptPath) then
  begin
    Params :=
      '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath +
      '" -AppDir "' + AppDir + '"';
    Exec(
      ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Params,
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode
    );
  end;
end;

function InitializeSetup(): Boolean;
begin
  StopAppProcessesIn(ExpandConstant('{localappdata}\{#MyAppName}'), True);
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  { Use the already-installed stop script; do not call ExtractTemporaryFile. }
  StopAppProcessesIn(ExpandConstant('{app}'), False);
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopAppProcessesIn(ExpandConstant('{app}'), True);
  Result := '';
end;
