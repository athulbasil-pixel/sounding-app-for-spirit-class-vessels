; MarineSense Engine Room Watch Log — Windows installer (Inno Setup 6)
; Build with BUILD_INSTALLER_WINDOWS.bat (it runs PyInstaller first, then this script).
; Per-user install: no administrator rights needed on the ship PC.

#define AppName "MarineSense Watch Log"
#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif

[Setup]
AppId={{6B0E3F2A-6C3B-4E8B-9F4E-2D7A9C1E5B11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=MarineSense
DefaultDirName={localappdata}\Programs\MarineSense Watch Log
DefaultGroupName=MarineSense Watch Log
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=Output
OutputBaseFilename=MarineSense_WatchLog_Setup_{#AppVersion}
SetupIconFile=watchlog.ico
UninstallDisplayIcon={app}\WatchLog.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard-large.bmp
WizardSmallImageFile=wizard-small.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
InfoAfterFile=AFTER_INSTALL.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\WatchLog\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "REVIEWER_GUIDE.html"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MarineSense Watch Log"; Filename: "{app}\WatchLog.exe"; WorkingDir: "{app}"
Name: "{group}\Watch Log - Training (sample data)"; Filename: "{app}\WatchLog.exe"; Parameters: "--demo"; WorkingDir: "{app}"
Name: "{group}\Watch Log - Tablet access (LAN)"; Filename: "{app}\WatchLog.exe"; Parameters: "--lan"; WorkingDir: "{app}"
Name: "{group}\Reviewer guide"; Filename: "{app}\REVIEWER_GUIDE.html"
Name: "{group}\Uninstall MarineSense Watch Log"; Filename: "{uninstallexe}"
Name: "{userdesktop}\MarineSense Watch Log"; Filename: "{app}\WatchLog.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\REVIEWER_GUIDE.html"; Description: "Open the reviewer guide"; Flags: postinstall shellexec skipifsilent
Filename: "{app}\WatchLog.exe"; Parameters: "--demo"; Description: "Start in Training mode (sample data)"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; program files only — the user's watch data in %LOCALAPPDATA%\MarineSense\WatchLog is kept
Type: filesandordirs; Name: "{app}\_internal"
