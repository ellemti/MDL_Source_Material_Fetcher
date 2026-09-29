; Inno Setup script -- builds the Windows installer.
; Built automatically by .github/workflows/release.yml on every version tag.
; Installs PER-USER (no admin needed) so the in-app updater can replace
; the exe and the app can save its settings file next to it.

#define MyAppName "Source Material Fetcher"
#define MyAppExeName "SourceMaterialFetcher.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{D20ED804-0172-472B-9453-022CC63CE6F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Anas (ellemti)
AppPublisherURL=https://github.com/ellemti/MDL_Source_Material_Fetcher
AppSupportURL=https://github.com/ellemti/MDL_Source_Material_Fetcher/issues
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=SourceMaterialFetcher-Setup-{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\SourceMaterialFetcher.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\SourceMaterialFetcher_Settings.json"
