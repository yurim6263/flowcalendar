; Flow Calendar 설치 파일 (Inno Setup 6). 만들기: packaging\build.ps1
; 버전을 올릴 때는 flowcalendar/__init__.py, pyproject.toml, packaging/version_info.txt 와 함께 바꾼다 (tests/test_packaging.py 가 확인한다).
#define AppName "Flow Calendar"
#define AppVersion "1.0.0"
#define AppExe "FlowCalendar.exe"

[Setup]
; 같은 앱을 다시 설치(업데이트)할 때 같은 곳을 쓰도록 고정된 ID. 바꾸지 않는다.
AppId={{6F3C8E1A-4B7D-4E52-9A36-5D1F2C0B7E91}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist
OutputBaseFilename=FlowCalendar-Setup-{#AppVersion}
SetupIconFile=..\assets\flowcalendar.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 관리자 권한 없이 내 계정에만 설치한다 (설치 위치는 사용자 폴더, 시작 메뉴·바탕화면도 내 것). 사용자가 "모든 사용자"를 고르면 그렇게도 된다.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} 설치

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"; Flags: unchecked
Name: "autostart"; Description: "Windows를 켤 때 트레이에서 자동으로 시작"; GroupDescription: "추가 작업:"; Flags: unchecked

[Files]
Source: "..\dist\FlowCalendar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; 앱 설정의 "Windows 시작 시 자동 실행"과 같은 위치/이름이라 설정 화면에서 켜고 끌 수 있다.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FlowCalendar"; ValueData: """{app}\{#AppExe}"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Flow Calendar 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 내 일정·할 일·메모(%APPDATA%\FlowCalendar)는 제거해도 지우지 않는다. 필요 없으면 그 폴더를 직접 지운다.
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { 앱 설정에서 켠 자동 실행도 같이 정리한다 (설치 때 고른 것과 같은 항목) }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FlowCalendar');
  end;
end;
