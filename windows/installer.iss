#ifndef AppVersion
  #error AppVersion is required
#endif
[Setup]
AppId=AgentHubLocalPreview
AppName=Agent Hub
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Agent Hub
DefaultGroupName=Agent Hub
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Agent-Hub-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AgentHub.exe
CloseApplications=yes
[Files]
Source: "..\dist\AgentHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Agent Hub"; Filename: "{app}\AgentHub.exe"; AppUserModelID: "AgentHub"
Name: "{autodesktop}\Agent Hub"; Filename: "{app}\AgentHub.exe"; AppUserModelID: "AgentHub"
[Run]
Filename: "{app}\AgentHub.exe"; Description: "Open Agent Hub"; Flags: nowait postinstall skipifsilent
[Registry]
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\AgentHub"; ValueType: string; ValueName: "DisplayName"; ValueData: "Agent Hub"; Flags: uninsdeletekey
