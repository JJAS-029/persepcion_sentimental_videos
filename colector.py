"""Colector: lee el chat de YouTube o los comentarios de Facebook, clasifica sentimiento/emoción/odio y guarda en SQLite.

Uso:
    python colector.py "https://www.youtube.com/watch?v=XXXXXXXXXXX"
    python colector.py XXXXXXXXXXX --fuente api        # con YOUTUBE_API_KEY
"""
import argparse
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone

import psutil

import db
import facebook
from fuentes import FUENTES, extraer_video_id, info_video
from rutas import MODELOS

# Caracteres de control / símbolos raros que solo meten ruido al modelo
_RUIDO = re.compile(r"[\u200b-\u200f\u2060-\u206f\ufe00-\ufe0f]")


def limpiar(texto: str) -> str:
    texto = _RUIDO.sub("", texto)
    texto = re.sub(r"(.)\1{4,}", r"\1\1\1", texto)  # "jajajaja!!!!!!!!" -> "!!!"
    return texto.strip()[:500]


def crear_analizador(tarea: str):
    """Usa la copia local de los modelos si existe (versión .exe); si no, los descarga de Hugging Face."""
    from pysentimiento.analyzer import create_analyzer, models

    local = MODELOS / tarea
    if local.exists():
        prepro = dict(models["es"][tarea].get("preprocessing_args", {}))
        return create_analyzer(task=tarea, lang="es", model_name=str(local), preprocessing_args=prepro)
    return create_analyzer(task=tarea, lang="es")


class Clasificador:
    def __init__(self, odio: bool = True):
        print("Cargando modelos (la primera vez descarga ~1 GB)...")
        self.sent = crear_analizador("sentiment")
        self.emo = crear_analizador("emotion")
        self.odio = crear_analizador("hate_speech") if odio else None
        print("Modelos listos.")

    def __call__(self, textos: list[str]) -> list[dict]:
        sent = self.sent.predict(textos)
        emo = self.emo.predict(textos)
        odio = self.odio.predict(textos) if self.odio else [None] * len(textos)
        out = []
        for s, e, h in zip(sent, emo, odio):
            etiquetas_odio = set(h.output) if h is not None else set()
            out.append({
                "sentimiento": s.output,
                "p_pos": s.probas.get("POS"),
                "p_neg": s.probas.get("NEG"),
                "p_neu": s.probas.get("NEU"),
                "emocion": e.output,
                "odio": int("hateful" in etiquetas_odio),
                "agresivo": int("aggressive" in etiquetas_odio),
            })
        return out


def productor(gen, cola: queue.Queue, fin: threading.Event, errores: list):
    try:
        for m in gen:
            cola.put(m)
    except Exception as e:  # noqa: BLE001 - reportar y terminar limpio
        print(f"[fuente] error: {e!r}")
        errores.append(str(e))
    finally:
        fin.set()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="URL o ID del video (YouTube o Facebook)")
    ap.add_argument("--fuente", choices=FUENTES, default="web")
    ap.add_argument("--intervalo", type=float, default=2.0, help="segundos de espera cuando no hay mensajes nuevos")
    ap.add_argument("--lote-max", type=int, default=256)
    ap.add_argument("--sin-odio", action="store_true", help="no cargar el modelo de discurso de odio")
    ap.add_argument("--padre", type=int, help="PID de la app; si se cierra, el colector se detiene")
    args = ap.parse_args()

    video_id = extraer_video_id(args.video)
    conn = db.connect()
    db.sesion(conn, video_id, pid=os.getpid(), inicio=datetime.now(timezone.utc).isoformat(),
              estado="iniciando", detalle="Consultando el video...")
    if video_id.startswith("fb_"):
        def guardar_info(titulo, canal, en_vivo):  # se llama desde el hilo del navegador
            db.sesion(db.connect(), video_id, titulo=titulo, canal=canal,
                      modo="en vivo" if en_vivo else "publicado")

        db.sesion(conn, video_id, detalle="Cargando modelos de lenguaje...")
        generador = facebook.fuente_facebook(video_id, guardar_info)
    else:
        try:
            info = info_video(video_id)
            db.sesion(conn, video_id, titulo=info["titulo"], canal=info["canal"],
                      modo="en vivo" if info["en_vivo"] else ("repetición" if info["repeticion"] else "sin chat"),
                      detalle="Cargando modelos de lenguaje...")
        except Exception as e:  # noqa: BLE001 - el título es informativo; seguimos sin él
            print(f"[info] no se pudo consultar el video: {e!r}")
        generador = FUENTES[args.fuente](video_id)
    clasificar = Clasificador(odio=not args.sin_odio)

    cola: queue.Queue = queue.Queue()
    fin = threading.Event()
    errores: list[str] = []
    threading.Thread(target=productor, args=(generador, cola, fin, errores), daemon=True).start()
    print(f"Escuchando comentarios de {video_id}. Ctrl+C para detener.")
    db.sesion(conn, video_id, estado="recolectando", detalle="Esperando mensajes...")

    total = 0
    try:
        while not (fin.is_set() and cola.empty()):
            if args.padre and not psutil.pid_exists(args.padre):
                db.sesion(conn, video_id, estado="detenido", detalle="Se cerró la aplicación")
                return
            if cola.empty():
                time.sleep(args.intervalo)
            lote = []
            while not cola.empty() and len(lote) < args.lote_max:
                lote.append(cola.get_nowait())
            if not lote:
                continue
            resultados = clasificar([limpiar(m["mensaje"]) or m["mensaje"] for m in lote])
            filas = [{**m, **r, "video_id": video_id} for m, r in zip(lote, resultados)]
            total += db.insertar(conn, filas)
            pendientes = cola.qsize()
            guardados = conn.execute("SELECT COUNT(*) FROM mensajes WHERE video_id = ?", (video_id,)).fetchone()[0]
            db.sesion(conn, video_id, recibidos=guardados,
                      detalle=f"{pendientes:,} mensajes por analizar" if pendientes else "Al corriente")
            neg = sum(r["sentimiento"] == "NEG" for r in resultados)
            print(f"+{len(lote)} msgs (NEG {neg}) | total {total} | en cola {pendientes}")
    except KeyboardInterrupt:
        print("Detenido por el usuario.")
        db.sesion(conn, video_id, estado="detenido", detalle="Detenido por el usuario")
        return
    if errores:
        db.sesion(conn, video_id, estado="error", detalle=errores[0])
    else:
        db.sesion(conn, video_id, estado="terminado", detalle="La transmisión terminó")
    print(f"Fin. {total} mensajes guardados en {db.DB_PATH}")


if __name__ == "__main__":
    main()
