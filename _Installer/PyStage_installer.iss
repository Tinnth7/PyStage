; ══════════════════════════════════════════════════════════
;  PyStage — Inno Setup Installer Script
;  Build: open this file in Inno Setup Compiler → Compile
; ══════════════════════════════════════════════════════════

#define AppName      "PyStage"
#define AppVersion   "1.0"
#define AppPublisher "LiTuz"
#define AppExeName   "PyStage.exe"
#define AppURL       "https://github.com/Tinnth7/PyStage"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#AppURL}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=installer_out
OutputBaseFilename=PyStage_Setup
SetupIconFile=pystage.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Installer window colors — dark theme to match PyStage's vibe
WizardSizePercent=110

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "Create a &desktop shortcut";    GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startmenuicon";  Description: "Create a &Start Menu shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
; Main executable — built by PyInstaller
Source: "{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Icon file (for uninstaller display)
Source: "pystage.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\{#AppName}";            Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\pystage.ico"
Name: "{group}\Uninstall {#AppName}";  Filename: "{uninstallexe}"

; Desktop shortcut (only if user ticked the box)
Name: "{autodesktop}\{#AppName}";      Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\pystage.ico"; Tasks: desktopicon

[Run]
; Offer to launch PyStage right after install
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up any leftover files in the install folder
Type: filesandordirs; Name: "{app}"

[Code]
// Optional: show a "Thanks for installing!" message on finish
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
  begin
    // Nothing extra needed — the [Run] section handles launch offer
  end;
end;
