; Inno Setup script: CAHON installer for Windows.
; Installs for the current user (no admin rights needed), adds Start menu and
; optional desktop shortcuts, and an uninstaller. User data in
; %LOCALAPPDATA%\CAHON is kept on uninstall.
;   iscc /DAppVersion=1.0.0 /DSourceDir=..\..\dist\CAHON packaging\windows\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\CAHON"
#endif

[Setup]
AppId={{C4A0F2D1-7B3E-4E58-9C61-2F8D5A1E6B37}
AppName=CAHON
AppVersion={#AppVersion}
AppPublisher=CAHON
DefaultDirName={localappdata}\Programs\CAHON
DefaultGroupName=CAHON
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=CAHON-Setup-{#AppVersion}
SetupIconFile=..\build\icons\icon.ico
UninstallDisplayIcon={app}\CAHON.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CAHON"; Filename: "{app}\CAHON.exe"
Name: "{group}\Uninstall CAHON"; Filename: "{uninstallexe}"
Name: "{userdesktop}\CAHON"; Filename: "{app}\CAHON.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CAHON.exe"; Description: "{cm:LaunchProgram,CAHON}"; Flags: nowait postinstall skipifsilent
; In-app updates run this installer silently: reopen the app afterwards.
Filename: "{app}\CAHON.exe"; Flags: nowait; Check: WizardSilent
