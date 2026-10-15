# Percepción sentimental de videos en vivo

Monitorea en tiempo real el chat de una transmisión en vivo de YouTube y clasifica
cada comentario por **sentimiento** (positivo / neutro / negativo), **emoción** y
**discurso de odio / agresividad**, usando modelos de [pysentimiento](https://github.com/pysentimiento/pysentimiento)
entrenados con texto de redes sociales en español. Todo corre local: los comentarios no salen del equipo.

```
YouTube chat ──► colector.py ──► data/comentarios.db (SQLite) ──► dashboard.py (Streamlit)
               (lotes cada 2 s,
                3 modelos NLP)
```

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

La primera ejecución descarga los modelos (~1 GB).

## Uso

Dos terminales:

```powershell
# 1) Colector
python colector.py "https://www.youtube.com/watch?v=XXXXXXXXXXX"

# 2) Dashboard (abre http://localhost:8501)
streamlit run dashboard.py
```

Opciones del colector:

| Opción | Descripción |
|---|---|
| `--fuente web` | (default) Lee el chat completo con el mismo endpoint que usa la página de YouTube. Sin API key. |
| `--fuente api` | YouTube Data API v3. Requiere `$env:YOUTUBE_API_KEY="..."`. Respaldo si `web` falla. |
| `--fuente pytchat` | Librería pytchat. En pruebas (oct 2026) solo recibía el chat "destacado" (muy pocos mensajes). |
| `--fuente chatdl` | Librería chat-downloader. En pruebas (oct 2026) no funcionaba con YouTube. |
| `--intervalo 2` | Segundos entre lotes de clasificación. |
| `--sin-odio` | No carga el modelo de discurso de odio (arranca más rápido). |

Se pueden correr varios colectores (uno por video) sobre la misma base; el dashboard filtra por video.

## Dashboard

- KPIs: total de mensajes, ritmo (msgs/min), % positivo y negativo, índice neto y alertas de odio/agresión.
- Mensajes por sentimiento a lo largo del tiempo e índice neto (positivo − negativo).
- Emociones y palabras más mencionadas.
- Últimos comentarios y comentarios más negativos/agresivos.
- Descarga a CSV.

## Limitaciones

- El modelo no detecta bien el sarcasmo ni el contexto político local; tómese como indicador de tendencia, no como verdad por comentario.
- La fuente `web` usa un endpoint no oficial; si YouTube lo cambia puede dejar de funcionar → usar `--fuente api`.
