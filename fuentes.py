"""Fuentes de chat en vivo de YouTube.

Cada fuente es un generador que produce dicts normalizados:
    {id, ts_utc, autor, mensaje, tipo}

- web    : endpoint interno del chat de YouTube (sin API key). Opción por defecto;
           recibe el chat completo, no solo el "destacado".
- pytchat: librería pytchat (sin API key). En pruebas solo recibió chat destacado.
- chatdl : librería chat-downloader (sin API key). Funciona también con
           transmisiones ya terminadas (replay), útil para probar.
- api    : YouTube Data API v3 oficial (requiere YOUTUBE_API_KEY). Más estable
           si YouTube cambia su HTML y rompe el scraping.
"""
import json
import os
import re
import time
from html import unescape
from datetime import datetime, timezone

import requests


def extraer_video_id(url_o_id: str) -> str:
    patrones = [r"[?&]v=([\w-]{11})", r"youtu\.be/([\w-]{11})", r"/(?:live|shorts|embed)/([\w-]{11})"]
    for p in patrones:
        m = re.search(p, url_o_id)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{11}", url_o_id):
        return url_o_id
    raise ValueError(f"No se pudo extraer el ID de video de: {url_o_id}")


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


def _texto_runs(msg: dict) -> str:
    partes = []
    for run in msg.get("runs", []):
        if "text" in run:
            partes.append(run["text"])
        elif "emoji" in run:  # emoji estándar -> el carácter; emoji custom -> su atajo
            em = run["emoji"]
            partes.append(em.get("emojiId", "") if not em.get("isCustomEmoji") else (em.get("shortcuts") or [""])[0])
    return "".join(partes)


def _continuacion(data: dict):
    for c in data.get("continuations", []):
        for k in ("invalidationContinuationData", "timedContinuationData",
                  "reloadContinuationData", "liveChatReplayContinuationData"):
            if k in c:
                return c[k]["continuation"], c[k].get("timeoutMs", 3000)
    return None, None


def _initial_data(html: str) -> dict | None:
    m = re.search(r'(?:window\["ytInitialData"\]|var ytInitialData)\s*=\s*(\{.+?\});\s*</script>', html)
    return json.loads(m.group(1)) if m else None


def _cont_chat_completo(chat: dict) -> str | None:
    """Del menú del chat elige "Chat en vivo" (todos) en lugar de "Chat destacado" (filtrado)."""
    try:
        submenu = chat["header"]["liveChatHeaderRenderer"]["viewSelector"]["sortFilterSubMenuRenderer"]["subMenuItems"]
        return submenu[-1]["continuation"]["reloadContinuationData"]["continuation"]
    except (KeyError, IndexError):
        return _continuacion(chat)[0]


def _mensajes(acciones: list, vistos: set):
    for act in acciones:
        # En repeticiones cada acción viene envuelta en replayChatItemAction
        internas = act.get("replayChatItemAction", {}).get("actions", [act])
        for a in internas:
            item = a.get("addChatItemAction", {}).get("item", {})
            for tipo in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
                if tipo not in item:
                    continue
                it = item[tipo]
                texto = _texto_runs(it.get("message", {}))
                if not texto.strip() or it["id"] in vistos:
                    continue
                vistos.add(it["id"])
                yield {
                    "id": it["id"],
                    "ts_utc": datetime.fromtimestamp(int(it["timestampUsec"]) / 1e6, tz=timezone.utc).isoformat(),
                    "autor": it.get("authorName", {}).get("simpleText"),
                    "mensaje": texto,
                    "tipo": tipo,
                }


def info_video(video_id: str) -> dict:
    """Título, estado (en vivo / repetición) y si tiene chat disponible."""
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "es-MX,es;q=0.9"})
    html = s.get("https://www.youtube.com/watch", params={"v": video_id}, timeout=20).text
    datos = _initial_data(html) or {}
    titulo = re.search(r"<title>(.*?)(?: - YouTube)?</title>", html)
    canal = re.search(r'"ownerChannelName":("(?:[^"\\]|\\.)*")', html)
    chat = (datos.get("contents", {}).get("twoColumnWatchNextResults", {})
                 .get("conversationBar", {}).get("liveChatRenderer"))
    return {
        "session": s,
        "html": html,
        "titulo": unescape(titulo.group(1)) if titulo else video_id,
        "canal": json.loads(canal.group(1)) if canal else None,
        "en_vivo": '"isLiveNow":true' in html,
        "repeticion": bool(chat and chat.get("isReplay")),
        "chat": chat,
    }


def fuente_web(video_id: str):
    """Lee el chat (en vivo o repetición) con el mismo endpoint que usa la página de YouTube."""
    info = info_video(video_id)
    s, html, chat = info["session"], info["html"], info["chat"]
    if not chat:
        raise RuntimeError("El video no tiene chat disponible (está desactivado o no es transmisión en vivo).")
    api_key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html).group(1)
    version = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html).group(1)
    ctx = {"client": {"clientName": "WEB", "clientVersion": version, "hl": "es", "gl": "MX"}}
    base = "https://www.youtube.com/youtubei/v1/live_chat"
    vistos: set[str] = set()

    if chat.get("isReplay"):
        cont = _continuacion(chat)[0]
        pagina = _initial_data(s.get("https://www.youtube.com/live_chat_replay",
                                     params={"continuation": cont}, timeout=20).text)
        if pagina and "liveChatRenderer" in pagina.get("contents", {}):
            cont = _cont_chat_completo(pagina["contents"]["liveChatRenderer"]) or cont
        offset = "0"
        while cont:
            r = s.post(f"{base}/get_live_chat_replay?key={api_key}&prettyPrint=false",
                       json={"context": ctx, "continuation": cont,
                             "currentPlayerState": {"playerOffsetMs": offset}}, timeout=20)
            r.raise_for_status()
            data = r.json().get("continuationContents", {}).get("liveChatContinuation")
            if not data:
                return
            acciones = data.get("actions", [])
            if acciones:
                ultimo = acciones[-1].get("replayChatItemAction", {}).get("videoOffsetTimeMsec")
                offset = ultimo or offset
            yield from _mensajes(acciones, vistos)
            cont, _ = _continuacion(data)
            time.sleep(0.3)
        return

    pagina = _initial_data(s.get("https://www.youtube.com/live_chat",
                                 params={"v": video_id, "is_popout": "1"}, timeout=20).text) or {}
    chat_vivo = pagina.get("contents", {}).get("liveChatRenderer")
    if not chat_vivo:
        raise RuntimeError("El chat en vivo está inhabilitado para esta transmisión.")
    cont = _cont_chat_completo(chat_vivo)
    while cont:
        r = s.post(f"{base}/get_live_chat?key={api_key}&prettyPrint=false",
                   json={"context": ctx, "continuation": cont}, timeout=20)
        r.raise_for_status()
        data = r.json().get("continuationContents", {}).get("liveChatContinuation")
        if not data:
            return  # la transmisión terminó
        yield from _mensajes(data.get("actions", []), vistos)
        cont, espera = _continuacion(data)
        time.sleep(min(max(espera / 1000, 1), 10))


def fuente_pytchat(video_id: str):
    import pytchat

    # interruptable=False: corre en un hilo secundario, sin manejar señales
    chat = pytchat.create(video_id=video_id, interruptable=False)
    while chat.is_alive():
        for m in chat.get().sync_items():
            if not (m.message or "").strip():
                continue
            yield {
                "id": m.id,
                "ts_utc": datetime.fromtimestamp(m.timestamp / 1000, tz=timezone.utc).isoformat(),
                "autor": m.author.name,
                "mensaje": m.message,
                "tipo": m.type,
            }
    chat.raise_for_status()


def fuente_chatdl(video_id: str):
    from chat_downloader import ChatDownloader

    url = f"https://www.youtube.com/watch?v={video_id}"
    chat = ChatDownloader().get_chat(url, message_types=["text_message", "paid_message"])
    for m in chat:
        texto = m.get("message") or ""
        if not texto.strip():
            continue
        ts = m.get("timestamp")  # microsegundos epoch
        ts_iso = (datetime.fromtimestamp(ts / 1e6, tz=timezone.utc) if ts else datetime.now(timezone.utc)).isoformat()
        yield {
            "id": m.get("message_id") or f"{ts}-{hash(texto)}",
            "ts_utc": ts_iso,
            "autor": (m.get("author") or {}).get("name"),
            "mensaje": texto,
            "tipo": m.get("message_type"),
        }


def fuente_api(video_id: str):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("Define la variable de entorno YOUTUBE_API_KEY para usar --fuente api")
    base = "https://www.googleapis.com/youtube/v3"
    r = requests.get(f"{base}/videos", params={"part": "liveStreamingDetails", "id": video_id, "key": key}, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    chat_id = items and items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
    if not chat_id:
        raise RuntimeError("El video no tiene chat en vivo activo (¿ya terminó o aún no empieza?)")

    token = None
    while True:
        params = {"liveChatId": chat_id, "part": "snippet,authorDetails", "maxResults": 2000, "key": key}
        if token:
            params["pageToken"] = token
        r = requests.get(f"{base}/liveChat/messages", params=params, timeout=15)
        if r.status_code == 403 and "liveChatEnded" in r.text:
            return
        r.raise_for_status()
        data = r.json()
        for it in data.get("items", []):
            sn = it["snippet"]
            texto = sn.get("displayMessage") or ""
            if not texto.strip():
                continue
            yield {
                "id": it["id"],
                "ts_utc": sn["publishedAt"],
                "autor": it.get("authorDetails", {}).get("displayName"),
                "mensaje": texto,
                "tipo": sn.get("type"),
            }
        token = data.get("nextPageToken")
        # Respetar el intervalo que pide YouTube; mínimo 5 s para cuidar la cuota diaria
        time.sleep(max(data.get("pollingIntervalMillis", 5000) / 1000, 5))


FUENTES = {"web": fuente_web, "pytchat": fuente_pytchat, "api": fuente_api, "chatdl": fuente_chatdl}
