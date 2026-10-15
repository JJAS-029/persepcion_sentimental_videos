"""Punto de entrada del ejecutable "Monitor de percepcion.exe".

- Sin argumentos: levanta la app (Streamlit) y abre el navegador.
- Con --colector: corre el colector (la app se relanza a sí misma así para cada video).
"""
import os
import socket
import sys
import threading
import webbrowser

PUERTO = int(os.environ.get("MONITOR_PUERTO", 8501))
URL = f"http://localhost:{PUERTO}"


def puerto_ocupado() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PUERTO)) == 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--colector":
        import colector

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        colector.main()
        return

    if puerto_ocupado():  # ya hay una ventana abierta: solo mostrar la app
        webbrowser.open(URL)
        return

    from streamlit.web import cli

    from rutas import RECURSOS

    print("=" * 60)
    print("  Monitor de percepción")
    print(f"  Abriendo {URL} en el navegador...")
    print("  NO cierres esta ventana mientras uses la aplicación.")
    print("=" * 60)
    threading.Timer(3, webbrowser.open, args=[URL]).start()
    sys.argv = ["streamlit", "run", str(RECURSOS / "app.py"),
                "--global.developmentMode=false", "--server.headless=true", f"--server.port={PUERTO}",
                "--server.address=localhost",  # solo accesible desde este equipo
                "--browser.gatherUsageStats=false", "--client.toolbarMode=minimal",
                "--server.fileWatcherType=none"]
    sys.exit(cli.main())


if __name__ == "__main__":
    main()
