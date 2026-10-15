"""Comentarios de videos de Facebook (en vivo o ya publicados) con una cuenta iniciada.

Facebook solo muestra unos pocos comentarios sin sesión, así que se usa un perfil de Edge
propio de la app (rutas.PERFIL_FACEBOOK) donde alguien inicia sesión una vez con
`iniciar_sesion()`. El colector abre el video en ese perfil sin ventana, pide "Todos los
comentarios", pagina con "Ver más comentarios" y lee los datos que Facebook entrega a la
página (no el texto de la pantalla). Mientras el video siga en vivo, recarga cada minuto.

Ojo: automatizar Facebook va contra sus condiciones de uso; usar una cuenta institucional
y ritmos moderados para no provocar bloqueos.
"""
import json
import re
import shutil
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import requests

from rutas import DATOS

PERFIL = DATOS / "perfil_facebook"
MARCA_SESION = DATOS / "facebook_conectado.txt"
ESPERA_EN_VIVO = 120         # segundos entre revisiones en vivo (más seguido aumenta el riesgo de bloqueo)
MAX_PAGINAS = 200            # tope de clics en "Ver más comentarios" por pasada


def url_video(video_id: str) -> str:
    return f"https://www.facebook.com/watch/?v={video_id.removeprefix('fb_')}"


def sesion_conectada() -> bool:
    return MARCA_SESION.exists()


def _copia_perfil(video_id: str) -> Path:
    """Copia de la sesión para un video: Edge no permite abrir el mismo perfil dos veces,
    así que cada video de Facebook corre con su propia copia y pueden ir en paralelo."""
    destino = DATOS / "perfiles_tmp" / video_id
    shutil.rmtree(destino, ignore_errors=True)
    basura = shutil.ignore_patterns("Singleton*", "lockfile", "*Cache*", "Service Worker", "*.log", "Crashpad")
    shutil.copytree(PERFIL, destino, ignore=basura)
    return destino


def _navegador(p, visible: bool, perfil: Path = PERFIL):
    perfil.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(perfil), channel="msedge", headless=not visible, locale="es-MX",
        viewport={"width": 1700, "height": 1000})


def iniciar_sesion() -> None:
    """Abre Edge visible en facebook.com para que el usuario inicie sesión; se cierra solo al lograrlo."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _navegador(p, visible=True)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://www.facebook.com/login")
        for _ in range(900):  # hasta 15 minutos
            sesion = any(c["name"] == "c_user" for c in ctx.cookies("https://www.facebook.com"))
            # Con sesión pero en verificación (código por SMS/correo, checkpoint): esperar a que la termine
            if sesion and ctx.pages and not _en_verificacion(ctx.pages[0].url) and _cuenta_usable(ctx.pages[0]):
                MARCA_SESION.write_text(datetime.now().isoformat(), encoding="utf-8")
                pg.wait_for_timeout(2000)
                break
            if not ctx.pages:  # el usuario cerró la ventana
                break
            time.sleep(1)
        ctx.close()


def _en_verificacion(url: str) -> bool:
    return any(x in url for x in ("confirmemail", "checkpoint", "/login", "two_step_verification"))


def _cuenta_usable(pg) -> bool:
    """Facebook puede dejar la sesión iniciada pero bloquear todo hasta confirmar la cuenta:
    abre un video público y comprueba que no redirija a una página de verificación."""
    try:
        pg.goto("https://www.facebook.com/watch", wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
        return not _en_verificacion(pg.url)
    except Exception:  # noqa: BLE001 - el usuario cerró la ventana a media carga
        return False


def _comentarios_en(obj):
    """Recorre el JSON de Facebook y devuelve los nodos de comentario."""
    if isinstance(obj, dict):
        cuerpo, autor = obj.get("body"), obj.get("author")
        if isinstance(cuerpo, dict) and cuerpo.get("text") and isinstance(autor, dict) and obj.get("id"):
            yield obj
        for v in obj.values():
            yield from _comentarios_en(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _comentarios_en(v)


def _a_mensaje(c: dict) -> dict:
    ts = c.get("created_time")
    fecha = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return {"id": f"fb_{c['id']}", "ts_utc": fecha.isoformat(), "autor": c["author"].get("name"),
            "mensaje": c["body"]["text"], "tipo": "facebook_comment"}


def _clic(pg, *textos, espera=2500) -> bool:
    for t in textos:
        loc = pg.get_by_text(t, exact=True)
        if loc.count():
            try:
                loc.first.click(timeout=3000)
                pg.wait_for_timeout(espera)
                return True
            except Exception:  # noqa: BLE001 - elemento oculto o tapado; probar el siguiente
                pass
    return False


def _bloquear_pesado(route):
    # El video y las imágenes no hacen falta para leer comentarios y tiran la pestaña en los en vivo largos
    if route.request.resource_type in ("media", "image", "font"):
        route.abort()
    else:
        route.continue_()


def _pasada(ctx, video_id: str, vistos: set, al_obtener_info):
    """Abre el video en una pestaña nueva, lee todos los comentarios y devuelve si sigue en vivo."""
    recibidos: list = []

    def al_responder(r):
        if "graphql" not in r.url:
            return
        try:
            for linea in r.text().splitlines():
                if linea.strip():
                    recibidos.extend(_comentarios_en(json.loads(linea)))
        except Exception:  # noqa: BLE001 - respuestas binarias o cortadas
            pass

    pg = ctx.new_page()
    try:
        pg.route("**/*", _bloquear_pesado)
        pg.on("response", al_responder)
        pg.goto(url_video(video_id), wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
        if _en_verificacion(pg.url):
            MARCA_SESION.unlink(missing_ok=True)
            raise PermissionError("Facebook pide verificar la cuenta (código de confirmación o revisión de "
                                  "seguridad). Usa 'Conectar Facebook' en la app y completa la verificación.")
        if pg.locator("input[name=email]").count() and pg.locator("input[name=pass]").count():
            MARCA_SESION.unlink(missing_ok=True)
            raise PermissionError("La sesión de Facebook no está iniciada. Usa 'Conectar Facebook' en la app.")
        html = pg.content()
        en_vivo = "/live" in pg.url or '"is_live_streaming":true' in html or '"broadcast_status":"LIVE"' in html
        if al_obtener_info:
            # publish_time = inicio de la transmisión; sirve para saltar al minuto de cada comentario
            m = re.search(r'"publish_time":(\d{10})', html)
            al_obtener_info(en_vivo, int(m.group(1)) if m else None)

        for s in pg.locator('script[type="application/json"]').all():
            try:
                recibidos.extend(_comentarios_en(json.loads(s.inner_text())))
            except Exception:  # noqa: BLE001
                pass
        # En los en vivo (y a veces en videos) los comentarios están tras el enlace "N comentarios"
        enlace = pg.get_by_text(re.compile(r"^\d[\d,.]*\s*(mil\s*)?comentarios?$", re.I))
        if enlace.count():
            try:
                enlace.first.click(timeout=3000)
                pg.wait_for_timeout(4000)
            except Exception:  # noqa: BLE001
                pass
        # Orden "Todos los comentarios" (por defecto Facebook filtra a "Más relevantes")
        if _clic(pg, "Más relevantes", "Most relevant"):
            _clic(pg, "Todos los comentarios", "All comments", "Más recientes", "Newest")
        sin_nuevos = 0
        for _ in range(MAX_PAGINAS):
            antes = len(vistos)
            yield from _nuevos(recibidos, vistos)
            if not _clic(pg, "Ver más comentarios", "View more comments"):
                # Sin botón: desplazarse dentro de la lista para que cargue más
                articulos = pg.locator("div[role=article]")
                if articulos.count():
                    try:
                        articulos.last.scroll_into_view_if_needed(timeout=2000)
                    except Exception:  # noqa: BLE001
                        pass
                    pg.mouse.wheel(0, 2500)
                pg.wait_for_timeout(2000)
            yield from _nuevos(recibidos, vistos)
            sin_nuevos = sin_nuevos + 1 if len(vistos) == antes else 0
            if sin_nuevos >= 3:
                break
        return en_vivo
    finally:
        try:
            pg.close()
        except Exception:  # noqa: BLE001 - la pestaña ya se había caído
            pass


def fuente_facebook(video_id: str, al_obtener_info=None):
    from playwright.sync_api import sync_playwright

    info_enviada = False

    def avisar(en_vivo, inicio):
        nonlocal info_enviada
        if al_obtener_info and not info_enviada:
            inicio_iso = datetime.fromtimestamp(inicio, tz=timezone.utc).isoformat() if inicio else None
            al_obtener_info(**_titulo_publico(video_id), en_vivo=en_vivo, inicio_video=inicio_iso)
            info_enviada = True

    perfil = _copia_perfil(video_id)
    vistos: set[str] = set()
    fallos = 0
    try:
        with sync_playwright() as p:
            ctx = _navegador(p, visible=False, perfil=perfil)
            while True:
                try:
                    en_vivo = yield from _pasada(ctx, video_id, vistos, avisar)
                    fallos = 0
                except PermissionError as e:
                    raise RuntimeError(str(e)) from None
                except Exception as e:  # noqa: BLE001 - pestaña caída, red, etc.: reintentar
                    fallos += 1
                    print(f"[facebook] reintento {fallos}/3: {e!r}")
                    if fallos >= 3:
                        raise
                    try:  # si se cayó el navegador completo, abrir otro
                        ctx.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ctx = _navegador(p, visible=False, perfil=perfil)
                    time.sleep(10)
                    continue
                if not en_vivo:
                    break
                time.sleep(ESPERA_EN_VIVO)
            ctx.close()
    finally:
        shutil.rmtree(perfil, ignore_errors=True)


def _titulo_publico(video_id: str) -> dict:
    """Título y página desde la vista pública (con sesión, los en vivo solo dicen "Facebook Live")."""
    try:
        html = requests.get(url_video(video_id), timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/140.0 Safari/537.36", "Accept-Language": "es-MX,es;q=0.9"}).text
        titulo = unescape(re.search(r"<title>(.*?)</title>", html, re.S).group(1)).removesuffix(" | Facebook")
    except Exception:  # noqa: BLE001 - solo informativo
        return {"titulo": video_id, "canal": None}
    nombre, _, pagina = titulo.rpartition(" | ")
    return {"titulo": nombre or titulo, "canal": pagina if nombre else None}


def _nuevos(recibidos: list, vistos: set):
    while recibidos:
        c = recibidos.pop(0)
        if c["id"] not in vistos:
            vistos.add(c["id"])
            yield _a_mensaje(c)


if __name__ == "__main__":
    iniciar_sesion()
