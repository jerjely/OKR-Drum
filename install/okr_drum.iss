; Inno Setup script for OKR Drum. Per-user install, no admin rights needed.
; iscc /DMyVersion=1.2.3 install\okr_drum.iss   (run from the repository root after PyInstaller)
#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

[Setup]
AppId={{8B7F0E52-3C1A-4E4B-9D2E-0A6C4F1B7D21}
AppName=OKR Drum
AppVersion={#MyVersion}
AppVerName=OKR Drum {#MyVersion}
AppPublisher=Gergely Szarka
AppPublisherURL=https://github.com/jerjely/OKR-Drum
DefaultDirName={autopf}\OKR Drum
DefaultGroupName=OKR Drum
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=OKR-Drum-{#MyVersion}-Windows-setup
SetupIconFile=..\assets\icon\okr_drum.ico
UninstallDisplayIcon={app}\OKR-Drum.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\OKR-Drum\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OKR Drum"; Filename: "{app}\OKR-Drum.exe"
Name: "{group}\Uninstall OKR Drum"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OKR Drum"; Filename: "{app}\OKR-Drum.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OKR-Drum.exe"; Description: "Start OKR Drum"; Flags: nowait postinstall skipifsilent
