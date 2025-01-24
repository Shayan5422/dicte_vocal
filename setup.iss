[Setup]
AppName=MedTranscribe
AppVersion=1.0
AppPublisher=Alasuite
AppPublisherURL=https://www.alasuite.com/
WizardStyle=modern
DefaultDirName={autopf}\MedTranscribe
DefaultGroupName=MedTranscribe
UninstallDisplayIcon={app}\MedTranscribe.exe
OutputBaseFilename=MedTranscribe_Setup
SetupIconFile=app_icon.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Start with Windows"; GroupDescription: "Additional Options:"

[Files]
Source: "dist\MedTranscribe.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\MedTranscribe"; Filename: "{app}\MedTranscribe.exe"
Name: "{group}\Uninstall MedTranscribe"; Filename: "{uninstallexe}"
Name: "{commondesktop}\MedTranscribe"; Filename: "{app}\MedTranscribe.exe"; Tasks: desktopicon
Name: "{commonstartup}\MedTranscribe"; Filename: "{app}\MedTranscribe.exe"; Tasks: startupicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Visual C++ Redistributable..."; Flags: waituntilterminated
Filename: "{app}\MedTranscribe.exe"; Description: "{cm:LaunchProgram,MedTranscribe}"; Flags: nowait postinstall skipifsilent