; ─────────────────────────────────────────────────────────────────────
;  Chirpa — Windows install wizard (Inno Setup 6)
;
;  This produces a self-contained installer. Everything the app needs —
;  a private Python runtime and ffmpeg/ffprobe — is bundled, so the target
;  machine needs nothing pre-installed.
;
;  Build via build.ps1, which passes /DStagingDir and /DOutputDir.
;  To compile by hand:
;    ISCC.exe /DStagingDir=build\staging /DOutputDir=dist chirpa.iss
; ─────────────────────────────────────────────────────────────────────

#ifndef StagingDir
  #define StagingDir "build\staging"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif

#define AppName       "Chirpa"
#define AppPublisher  "Chirpa"
#define AppVersion    "1.0.0"
#define AppExeLauncher "Chirpa.cmd"
#define PyW           "python\pythonw.exe"

[Setup]
AppId={{1AE05D50-5D6C-431A-A462-534D0B42E400}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=ChirpaSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#AppName}
; pythonw.exe carries a usable default icon; drop a chirpa.ico next to this
; script and uncomment to brand the installer/shortcuts:
; SetupIconFile=chirpa.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startup";     Description: "Start Chirpa automatically when I log in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Bundle the entire staged app (app code + embedded Python + ffmpeg).
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}";            Filename: "{app}\{#PyW}"; Parameters: """{app}\birdnet_gui.py"""; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}";  Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";      Filename: "{app}\{#PyW}"; Parameters: """{app}\birdnet_gui.py"""; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}";      Filename: "{app}\{#PyW}"; Parameters: """{app}\birdnet_gui.py"""; WorkingDir: "{app}"; Tasks: startup

[Run]
; Offer to launch the dashboard once setup finishes.
Filename: "{app}\{#AppExeLauncher}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Full clean removal: delete the entire Chirpa data directory on uninstall
; (camera config, cached images, species DB, and the staged chart.min.js).
Type: filesandordirs; Name: "{%USERPROFILE}\.chirpa"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nChirpa is fully self-contained — a private Python runtime and the ffmpeg tools used to verify camera RTSP streams are included. Nothing else needs to be installed.%n%nIt is recommended that you close all other applications before continuing.
