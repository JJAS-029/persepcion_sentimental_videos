@echo off
chcp 65001 >nul
title Monitor de percepcion - NO CERRAR esta ventana mientras se usa
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo La aplicacion aun no esta instalada. Ejecutando el instalador...
    call Instalar.bat || exit /b 1
)

echo Abriendo el Monitor de percepcion en el navegador...
echo (Para cerrar la aplicacion, cierra esta ventana.)
start "" /b cmd /c "timeout /t 5 /nobreak >nul & start "" http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py
