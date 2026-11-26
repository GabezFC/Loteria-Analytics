#ifdef FixtureBuild
  #define ProductName "Cassino Installer Fixture"
  #define ProductId "Cassino.Launcher.InstallerFixture"
#else
  #define ProductName "Cassino"
  #define ProductId "Cassino.Launcher"
#endif

[Setup]
AppId={#ProductId}
AppName={#ProductName}
AppVersion={#ReleaseVersion}
VersionInfoVersion={#NumericVersion}
DefaultDirName={localappdata}\Programs\{#ProductName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\CassinoLauncher.exe
CloseApplications=no
RestartApplications=no
SourceDir={#PayloadRoot}
OutputBaseFilename=Cassino-Setup
Compression=lzma2
SolidCompression=yes

[Files]
#include "CassinoPayload.iss"

[Icons]
Name: "{userprograms}\{#ProductName}"; Filename: "{app}\CassinoLauncher.exe"; WorkingDir: "{app}"
