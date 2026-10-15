"""Rutas de la aplicación, iguales en desarrollo y dentro del .exe (PyInstaller)."""
import os
import sys
from pathlib import Path

CONGELADO = getattr(sys, "frozen", False)  # True cuando corre como .exe

# Archivos de solo lectura que viajan con la app (app.py, modelos)
RECURSOS = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
MODELOS = RECURSOS / "modelos"

# Datos que la app escribe: en el .exe van al perfil del usuario (Program Files no es escribible)
if CONGELADO:
    DATOS = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MonitorPercepcion"
else:
    DATOS = Path(__file__).parent / "data"
LOGS = DATOS / "logs"


def comando_colector(*args: str) -> list[str]:
    """Comando para lanzar el colector como proceso aparte."""
    if CONGELADO:
        return [sys.executable, "--colector", *args]
    return [sys.executable, str(Path(__file__).parent / "colector.py"), *args]
