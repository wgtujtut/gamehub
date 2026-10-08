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
function GameHubRunning: Boolean;
var
  Code: Integer;
begin
  // find вернёт 0, если в списке процессов есть GameHub.exe
  Result := Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq GameHub.exe" /NH | find /I "GameHub.exe" >nul',
                 '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// Закрыть GameHub (трей и окно) и дождаться, пока процессы правда исчезнут:
// пока они живы, их файлы заняты, и установка поверх них ломает программу.
function KillGameHub: Boolean;
var
  Code, I: Integer;
begin
  for I := 1 to 30 do
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM GameHub.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(500);
    if not GameHubRunning then
    begin
      Sleep(500);   // система отпускает файлы не мгновенно
      Result := True;
      Exit;
    end;
  end;
  Result := False;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // до удаления старых файлов: не закрылся — отменяем, установленная версия остаётся рабочей
  if KillGameHub then
    Result := ''
  else
    Result := 'Не удалось закрыть GameHub. Закрой его (трей → Выход) и запусти установку ещё раз.';
end;

function InitializeUninstall(): Boolean;
begin
  KillGameHub;
  Result := True;
end;
