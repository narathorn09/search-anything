; Inno Setup script: CAHON installer for Windows.
; Installs for the current user (no admin rights needed), adds Start menu and
; optional desktop shortcuts, and an uninstaller. User data in
; %LOCALAPPDATA%\CAHON is kept on uninstall. The AppId is the one of the
; earlier name (Search Anything), so this installer upgrades that install.
;   iscc /DAppVersion=1.0.0 /DSourceDir=..\..\dist\CAHON packaging\windows\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\CAHON"
#endif

[Setup]
AppId={{6E2A6B57-5B7B-4C61-9A3E-3E1E7C0B5A11}
AppName=CAHON
AppVersion={#AppVersion}
AppPublisher=CAHON
DefaultDirName={localappdata}\Programs\CAHON
UsePreviousAppDir=no
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

[InstallDelete]
; The app under its earlier name (v1.0.0): its folder and shortcuts.
Type: filesandordirs; Name: "{localappdata}\Programs\Search Anything"
Type: filesandordirs; Name: "{userprograms}\Search Anything"
Type: files; Name: "{userdesktop}\Search Anything.lnk"

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
