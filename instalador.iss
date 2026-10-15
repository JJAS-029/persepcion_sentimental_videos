; Inno Setup: genera instalador\Instalar_Monitor_de_percepcion.exe a partir de dist\Monitor de percepcion
; Requiere compilar antes el .exe:  python exportar_modelos.py  &&  pyinstaller monitor.spec --noconfirm

#define AppName "Monitor de percepcion"
#define AppVersion "1.0"

[Setup]
AppId={{6F3B2C1A-8E4D-4B7A-9C2E-5D1F0A3B7E64}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=instalador
OutputBaseFilename=Instalar_Monitor_de_percepcion
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=no
WizardStyle=modern
UninstallDisplayName={#AppName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\Monitor de percepcion\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Monitor de percepcion.exe"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\Monitor de percepcion.exe"; Tasks: escritorio

[Run]
Filename: "{app}\Monitor de percepcion.exe"; Description: "Abrir {#AppName} ahora"; Flags: nowait postinstall skipifsilent
