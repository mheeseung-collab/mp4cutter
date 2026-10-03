; Inno Setup script - MP4 Cutter installer
[Setup]
AppName=MP4 Cutter
AppVersion=1.0
AppPublisher=MP4 Cutter
DefaultDirName={autopf}\MP4 Cutter
DefaultGroupName=MP4 Cutter
OutputDir=installer_output
OutputBaseFilename=MP4Cutter_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
UninstallDisplayIcon={app}\MP4Cutter.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\MP4Cutter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MP4 Cutter"; Filename: "{app}\MP4Cutter.exe"
Name: "{group}\Uninstall MP4 Cutter"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MP4 Cutter"; Filename: "{app}\MP4Cutter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MP4Cutter.exe"; Description: "{cm:LaunchProgram,MP4 Cutter}"; Flags: nowait postinstall skipifsilent
