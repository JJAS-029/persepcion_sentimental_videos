# Monitor de percepción en YouTube

Analiza el chat de una transmisión de YouTube (en vivo o ya terminada) y clasifica cada
comentario por **sentimiento** (positivo / neutro / negativo), **emoción** y
**discurso de odio / agresividad**, con modelos de [pysentimiento](https://github.com/pysentimiento/pysentimiento)
entrenados con texto de redes sociales en español. Todo corre en el equipo: los comentarios no se envían a ningún servicio externo.

## Para usuarios

### Instalación (una sola vez)

1. Descarga o copia esta carpeta al equipo (por ejemplo en `Documentos`).
2. Doble clic en **`Instalar.bat`**. Tarda unos 10–15 minutos: instala Python si hace falta,
   las librerías y descarga los modelos (~1 GB). Requiere internet.
3. Al terminar aparece en el escritorio el acceso **"Monitor de percepcion"**.

> Si dice que no encontró Python y no logra instalarlo, instálalo desde
> <https://www.python.org/downloads/> marcando **"Add python.exe to PATH"** y vuelve a ejecutar `Instalar.bat`.

### Uso

1. Doble clic en **"Monitor de percepcion"** (escritorio) o en `Iniciar monitor.bat`.
   Se abre una ventana negra (**no cerrarla**) y el navegador con la aplicación.
2. Pega el link del video de YouTube y presiona **▶ Iniciar**.
3. En ~1 minuto empiezan a aparecer resultados; la página se actualiza sola.
4. Para terminar, presiona **⏹ Detener**. Con **⬇ Descargar** obtienes los comentarios en CSV (abre en Excel).

Los videos analizados quedan guardados y se pueden volver a consultar desde el selector **Video**.

### ¿Qué significa cada indicador?

| Indicador | Significado |
|---|---|
| Positivo / Negativo | % de comentarios con ese sentimiento. |
| Índice neto | % positivos − % negativos. De −100 (todo negativo) a +100 (todo positivo). |
| Odio / agresión | Comentarios que el modelo marca como discurso de odio o agresivos. |
| Emociones | Alegría, enojo, tristeza, miedo, sorpresa, asco (se excluyen los que no expresan ninguna). |

### Limitaciones

- El modelo no detecta bien el sarcasmo, ironía ni el contexto político local: úsese como **indicador de tendencia**, no como verdad comentario por comentario.
- Si el chat del video está desactivado, no hay nada que analizar.
- Videos ya terminados: se analiza la repetición del chat completa; en CPU tarda ~20 min por cada 10 mil mensajes.
- La lectura del chat usa la interfaz interna de la página de YouTube; si YouTube la cambia, puede requerir ajuste (ver `--fuente api` abajo).

## Para desarrolladores

```
app.py (Streamlit) ──lanza──► colector.py ──► data/comentarios.db (SQLite, WAL) ◄──lee── app.py
                               fuentes.py: chat de YouTube
                               pysentimiento: sentimiento, emoción, odio
```

- `app.py`: interfaz; inicia/detiene colectores como subprocesos y muestra resultados.
- `colector.py`: puede usarse solo por consola: `python colector.py <URL> [--fuente web|api|pytchat|chatdl]`.
- `fuentes.py`: lectores de chat.
  - `web` (default): chat completo, en vivo y repetición, sin API key.
  - `api`: YouTube Data API v3 oficial (`$env:YOUTUBE_API_KEY`), solo en vivo.
  - `pytchat` / `chatdl`: en pruebas de oct 2026, pytchat solo recibía el chat destacado y chat-downloader no funcionaba.
- `db.py`: tablas `mensajes` y `sesiones` (estado de cada recolección). Logs en `data/logs/`.

Instalación manual: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`, luego `.venv\Scripts\streamlit run app.py`.
