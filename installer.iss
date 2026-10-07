; Установщик GameHub (Inno Setup 6). Собирается из build.py: ISCC /DAppVersion=x.y.z installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F1C2A4E-5B7D-4C3A-9E2F-6A1B0C9D8E7F}
AppName=GameHub
AppVersion={#AppVersion}
AppVerName=GameHub {#AppVersion}
AppPublisher=wgtujtut
AppPublisherURL=https://github.com/wgtujtut/gamehub
AppSupportURL=https://github.com/wgtujtut/gamehub/issues
AppUpdatesURL=https://github.com/wgtujtut/gamehub/releases
; без прав администратора, как Discord: по умолчанию %LOCALAPPDATA%\Programs\GameHub, папку можно выбрать
PrivilegesRequired=lowest
DefaultDirName={autopf}\GameHub
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=GameHub-Setup-{#AppVersion}
SetupIconFile=build\gamehub.ico
UninstallDisplayIcon={app}\GameHub.exe
UninstallDisplayName=GameHub
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; GameHub закрываем сами (см. [Code]), без окна «закрыть приложения»
CloseApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать вместе с Windows (тихо, в трее)"; GroupDescription: "Дополнительно:"

[InstallDelete]
; при обновлении убрать старые библиотеки, чтобы не смешались с новыми
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\GameHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GameHub"; Filename: "{app}\GameHub.exe"
Name: "{autodesktop}\GameHub"; Filename: "{app}\GameHub.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GameHub"; \
  ValueData: """{app}\GameHub.exe"" --hidden"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; и после обычной установки, и после тихого обновления — запустить новую версию
Filename: "{app}\GameHub.exe"; Description: "Запустить GameHub"; Flags: nowait postinstall

[Code]
procedure KillGameHub;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM GameHub.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillGameHub;
  Sleep(800);
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  KillGameHub;
  Result := True;
end;
