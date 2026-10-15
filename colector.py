"""Colector: lee el chat en vivo, clasifica sentimiento/emoción/odio y guarda en SQLite.

Uso:
    python colector.py "https://www.youtube.com/watch?v=XXXXXXXXXXX"
    python colector.py XXXXXXXXXXX --fuente api        # con YOUTUBE_API_KEY
"""
import argparse
import queue
import re
import threading
import time

import db
from fuentes import FUENTES, extraer_video_id

# Caracteres de control / símbolos raros que solo meten ruido al modelo
_RUIDO = re.compile(r"[​-‏⁠-⁯︀-️]")


def limpiar(texto: str) -> str:
    texto = _RUIDO.sub("", texto)
    texto = re.sub(r"(.)\1{4,}", r"\1\1\1", texto)  # "jajajaja!!!!!!!!" -> "!!!"
    return texto.strip()[:500]


class Clasificador:
    def __init__(self, odio: bool = True):
        from pysentimiento import create_analyzer

        print("Cargando modelos (la primera vez descarga ~1 GB)...")
        self.sent = create_analyzer(task="sentiment", lang="es")
        self.emo = create_analyzer(task="emotion", lang="es")
        self.odio = create_analyzer(task="hate_speech", lang="es") if odio else None
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


def productor(gen, cola: queue.Queue, fin: threading.Event):
    try:
        for m in gen:
            cola.put(m)
    except Exception as e:  # noqa: BLE001 - reportar y terminar limpio
        print(f"[fuente] error: {e!r}")
    finally:
        fin.set()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="URL o ID del video de YouTube")
    ap.add_argument("--fuente", choices=FUENTES, default="web")
    ap.add_argument("--intervalo", type=float, default=2.0, help="segundos entre lotes de clasificación")
    ap.add_argument("--lote-max", type=int, default=64)
    ap.add_argument("--sin-odio", action="store_true", help="no cargar el modelo de discurso de odio")
    args = ap.parse_args()

    video_id = extraer_video_id(args.video)
    clasificar = Clasificador(odio=not args.sin_odio)
    conn = db.connect()

    cola: queue.Queue = queue.Queue()
    fin = threading.Event()
    threading.Thread(target=productor, args=(FUENTES[args.fuente](video_id), cola, fin), daemon=True).start()
    print(f"Escuchando chat de {video_id} vía {args.fuente}. Ctrl+C para detener.")

    total = 0
    try:
        while not (fin.is_set() and cola.empty()):
            time.sleep(args.intervalo)
            lote = []
            while not cola.empty() and len(lote) < args.lote_max:
                lote.append(cola.get_nowait())
            if not lote:
                continue
            resultados = clasificar([limpiar(m["mensaje"]) or m["mensaje"] for m in lote])
            filas = [{**m, **r, "video_id": video_id} for m, r in zip(lote, resultados)]
            total += db.insertar(conn, filas)
            neg = sum(r["sentimiento"] == "NEG" for r in resultados)
            print(f"+{len(lote)} msgs (NEG {neg}) | total {total} | en cola {cola.qsize()}")
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
    print(f"Fin. {total} mensajes guardados en {db.DB_PATH}")


if __name__ == "__main__":
    main()
