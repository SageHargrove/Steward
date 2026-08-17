; Inno Setup script for a real, distributable installer.
;
; This is not needed to use the tool. `INSTALL.bat` puts it on your own Start
; Menu with no compiler involved, and that is the right answer while the code
; changes daily, because the shortcuts point at the working folder and a
; `git pull` updates what they launch.
;
; This file is for the day it ships to somebody who does not have a checkout:
; one .exe, a normal Programs and Features entry, no terminal at any point.
;
; To build:
;   1. Install Inno Setup 6 from https://jrsoftware.org/isdl.php  (free)
;   2. Open this file in the Inno Setup Compiler and press F9
;   3. The installer lands in install\dist\
;
; Read "The Python problem" at the bottom before shipping this to anyone.

#define AppName        "Server Setup for Discord"
#define AppShortName   "CommunityOps"
; Kept in step with the VERSION file by hand. tools/release.py bumps that
; one; this line is the only other place a version number lives.
#define AppVersion     "0.3.1"
#define AppPublisher   "SageHargrove"
#define AppExeName     "START.bat"

[Setup]
AppId={{8C6F2A41-7D3E-4B29-9F15-6A0C4E8D2B37}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\brand\steward.ico
UninstallDisplayName={#AppName}
OutputDir=dist
OutputBaseFilename=CommunityOps-Setup-{#AppVersion}
SetupIconFile=..\brand\steward.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

; Per-user by default, so no administrator prompt and no shared-machine
; surprises. The ledger database lives beside the program and a per-machine
; install would put it somewhere the user cannot write.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\START.bat";            DestDir: "{app}";            Flags: ignoreversion
Source: "..\README.md";            DestDir: "{app}";            Flags: ignoreversion
Source: "..\SETUP.md";             DestDir: "{app}";            Flags: ignoreversion
Source: "..\ui\*";                 DestDir: "{app}\ui";         Flags: ignoreversion recursesubdirs
Source: "..\provision\*";          DestDir: "{app}\provision";  Flags: ignoreversion recursesubdirs
Source: "..\blueprint\*";          DestDir: "{app}\blueprint";  Flags: ignoreversion recursesubdirs
Source: "..\brand\steward.ico";    DestDir: "{app}\brand";      Flags: ignoreversion
Source: "..\docs\*";               DestDir: "{app}\docs";       Flags: ignoreversion recursesubdirs

; The bot, minus its data directory and its secrets. .env holds a live bot
; token and steward.sqlite3 holds members' activity; neither belongs in an
; installer, and shipping either would be a straightforward breach.
Source: "..\steward\*.py";         DestDir: "{app}\steward";    Flags: ignoreversion
Source: "..\steward\*.bat";        DestDir: "{app}\steward";    Flags: ignoreversion
Source: "..\steward\requirements.txt"; DestDir: "{app}\steward"; Flags: ignoreversion
Source: "..\steward\.env.example"; DestDir: "{app}\steward";    Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    WorkingDir: "{app}"; IconFilename: "{app}\brand\steward.ico"
Name: "{group}\Steward ledger only"; Filename: "{app}\steward\START-LEDGER.bat"; \
    WorkingDir: "{app}\steward"; IconFilename: "{app}\brand\steward.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    WorkingDir: "{app}"; IconFilename: "{app}\brand\steward.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Open the setup page now"; \
    WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
; Python's caches are made after install, so the uninstaller does not know
; about them and would leave the folders behind.
Type: filesandordirs; Name: "{app}\ui\__pycache__"
Type: filesandordirs; Name: "{app}\provision\__pycache__"
Type: filesandordirs; Name: "{app}\steward\__pycache__"

; Deliberately NOT deleted on uninstall:
;   {app}\steward\data       the activity ledger. Discord cannot rebuild it,
;                            and an uninstall is not consent to destroy it.
;   {app}\steward\.env       holds a bot token the person may still need.

[Code]
// Refuse early and in plain language rather than letting START.bat fail after
// the install looks like it worked.
function InitializeSetup(): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if not Exec('cmd.exe', '/c python --version', '', SW_HIDE,
              ewWaitUntilTerminated, Code) or (Code <> 0) then
  begin
    if MsgBox('Python does not appear to be installed, and this program needs it.'
      + #13#10#13#10
      + 'Install Python from python.org first, and tick "Add python.exe to PATH"'
      + ' on the first screen of its installer.'
      + #13#10#13#10
      + 'Carry on with this installation anyway?',
      mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
