; Inno Setup script - QuickSplit installer
[Setup]
AppId=MP4 Cutter
AppName=QuickSplit
AppVersion=2.0
AppPublisher=QuickSplit
DefaultDirName={autopf}\QuickSplit
DefaultGroupName=QuickSplit
UsePreviousGroup=no
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
UninstallDisplayName=QuickSplit

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\MP4Cutter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{autodesktop}\MP4 Cutter.lnk"
Type: filesandordirs; Name: "{group}\..\MP4 Cutter"

[Icons]
Name: "{group}\QuickSplit"; Filename: "{app}\MP4Cutter.exe"
Name: "{group}\Uninstall QuickSplit"; Filename: "{uninstallexe}"
Name: "{autodesktop}\QuickSplit"; Filename: "{app}\MP4Cutter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MP4Cutter.exe"; Description: "{cm:LaunchProgram,QuickSplit}"; Flags: nowait postinstall skipifsilent
