@echo off
chcp 65001 >nul
title Instalando Monitor de percepcion
cd /d "%~dp0"

echo ============================================================
echo   Instalacion del Monitor de percepcion (solo la primera vez)
echo ============================================================
echo.

rem --- 1. Buscar Python (3.10 o superior) -------------------------
set "PY="
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo No se encontro Python. Intentando instalarlo con winget...
    winget install -e --id Python.Python.3.14 --scope user --accept-package-agreements --accept-source-agreements
    echo.
    echo Python instalado. CIERRA esta ventana y vuelve a ejecutar Instalar.bat
    echo Si winget no esta disponible, instala Python desde https://www.python.org/downloads/
    echo marcando la casilla "Add python.exe to PATH".
    pause
    exit /b 1
)

rem --- 2. Entorno virtual y dependencias -------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creando entorno de Python...
    %PY% -m venv .venv || goto :error
)
echo [2/3] Instalando librerias (puede tardar 5-10 minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || goto :error

rem --- 3. Descargar los modelos de lenguaje ----------------------
echo [3/3] Descargando modelos de lenguaje (~1 GB, solo la primera vez)...
".venv\Scripts\python.exe" -c "from colector import Clasificador; Clasificador()" || goto :error

rem --- Acceso directo en el escritorio ---------------------------
powershell -NoProfile -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Monitor de percepcion.lnk');" ^
  "$s.TargetPath = '%~dp0Iniciar monitor.bat'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = 'imageres.dll,144'; $s.Save()"

echo.
echo ============================================================
echo   Listo. Se creo el acceso "Monitor de percepcion" en el
echo   escritorio. Usalo para abrir la aplicacion.
echo ============================================================
pause
exit /b 0

:error
echo.
echo *** Ocurrio un error durante la instalacion. Revisa los mensajes de arriba. ***
pause
exit /b 1
