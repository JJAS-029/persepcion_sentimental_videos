"""Almacenamiento en SQLite (modo WAL para que colector y dashboard convivan)."""
import sqlite3
from pathlib import Path

from rutas import DATOS

DB_PATH = DATOS / "comentarios.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mensajes (
    id            TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL,
    ts_utc        TEXT NOT NULL,      -- ISO-8601 UTC
    autor         TEXT,
    mensaje       TEXT NOT NULL,
    tipo          TEXT,               -- text_message, paid_message, ...
    sentimiento   TEXT,               -- POS / NEG / NEU
    p_pos         REAL,
    p_neg         REAL,
    p_neu         REAL,
    emocion       TEXT,               -- joy, anger, sadness, fear, surprise, disgust, others
    odio          INTEGER DEFAULT 0,  -- 1 si el modelo marca discurso de odio
    agresivo      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_video_ts ON mensajes(video_id, ts_utc);

CREATE TABLE IF NOT EXISTS sesiones (
    video_id    TEXT PRIMARY KEY,
    titulo      TEXT,
    canal       TEXT,
    modo        TEXT,                 -- "en vivo" / "repetición"
    pid         INTEGER,              -- proceso del colector
    inicio      TEXT,
    estado      TEXT,                 -- iniciando, recolectando, terminado, detenido, error
    recibidos   INTEGER DEFAULT 0,
    detalle     TEXT
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    try:  # bases creadas antes de existir la columna
        conn.execute("ALTER TABLE sesiones ADD COLUMN canal TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def insertar(conn: sqlite3.Connection, filas: list[dict]) -> int:
    cols = ["id", "video_id", "ts_utc", "autor", "mensaje", "tipo", "sentimiento",
            "p_pos", "p_neg", "p_neu", "emocion", "odio", "agresivo"]
    sql = f"INSERT OR IGNORE INTO mensajes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    cur = conn.executemany(sql, [tuple(f.get(c) for c in cols) for f in filas])
    conn.commit()
    return cur.rowcount


def sesion(conn: sqlite3.Connection, video_id: str, **campos) -> None:
    """Crea o actualiza el registro de estado de la recolección de un video."""
    conn.execute("INSERT OR IGNORE INTO sesiones (video_id) VALUES (?)", (video_id,))
    if campos:
        asignaciones = ", ".join(f"{k} = ?" for k in campos)
        conn.execute(f"UPDATE sesiones SET {asignaciones} WHERE video_id = ?", (*campos.values(), video_id))
    conn.commit()
