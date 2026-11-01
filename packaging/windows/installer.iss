; Inno Setup script: Search Anything installer for Windows.
; Installs for the current user (no admin rights needed), adds Start menu and
; optional desktop shortcuts, and an uninstaller. User data in
; %LOCALAPPDATA%\SearchAnything is kept on uninstall.
;   iscc /DAppVersion=1.0.0 /DSourceDir=..\..\dist\Search Anything packaging\windows\installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Search Anything"
#endif

[Setup]
AppId={{6E2A6B57-5B7B-4C61-9A3E-3E1E7C0B5A11}
AppName=Search Anything
AppVersion={#AppVersion}
AppPublisher=Search Anything
DefaultDirName={localappdata}\Programs\Search Anything
DefaultGroupName=Search Anything
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=SearchAnything-Setup-{#AppVersion}
SetupIconFile=..\build\icons\icon.ico
UninstallDisplayIcon={app}\Search Anything.exe
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
Name: "{group}\Search Anything"; Filename: "{app}\Search Anything.exe"
Name: "{group}\Uninstall Search Anything"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Search Anything"; Filename: "{app}\Search Anything.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Search Anything.exe"; Description: "{cm:LaunchProgram,Search Anything}"; Flags: nowait postinstall skipifsilent
