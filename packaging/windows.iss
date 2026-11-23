; Build with Inno Setup 6. Runtime and resources have already been frozen.
#ifndef BundleDir
  #error BundleDir must name the PyInstaller output directory
#endif
[Setup]
AppId={{50B7A928-985B-4DC2-A57C-F3401AF1EA4E}
AppName=Gaiascapes
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Gaiascapes
DefaultGroupName=Gaiascapes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#SourceRoot}\src\gaiascapes_host\static\gaia-scape-desktop-icon.ico
UninstallDisplayIcon={app}\Gaiascapes.exe
LicenseFile={#SourceRoot}\LICENSE
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
WizardStyle=modern
InfoAfterFile={#SourceRoot}\packaging\windows-after.txt

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\user_guide.pdf"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\create_catalog.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#WebViewSetup}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: deleteafterinstall

[Icons]
Name: "{group}\Gaiascapes"; Filename: "{app}\Gaiascapes.exe"
Name: "{group}\Gaiascapes User Guide"; Filename: "{app}\user_guide.pdf"
Name: "{group}\Uninstall Gaiascapes"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Gaiascapes"; Filename: "{app}\Gaiascapes.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Flags: waituntilterminated; Check: NeedsWebView2
Filename: "{app}\Gaiascapes.exe"; Description: "Open Gaiascapes"; Flags: postinstall nowait skipifsilent

[Code]
function NeedsWebView2: Boolean;
var Version: String;
begin
  Result := not ((RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not IsDotNetInstalled(net48, 0)) then
    MsgBox('The desktop window requires .NET Framework 4.8. Install it using Windows Update. The bundled server remains available.', mbInformation, MB_OK);
  if (CurStep = ssDone) and NeedsWebView2 then
    MsgBox('WebView2 Runtime installation did not complete. Install it from Microsoft before opening the desktop app. See the included installation notes.', mbError, MB_OK);
end;
