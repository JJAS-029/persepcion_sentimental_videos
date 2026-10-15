"""Monitor de percepción: pega el link de un video de YouTube y analiza su chat.

Ejecutar con:  streamlit run app.py   (o con el .exe / "Iniciar monitor.bat")
"""
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime

import pandas as pd
import plotly.express as px
import psutil
import requests
import streamlit as st

import db
import facebook
import informe
from fuentes import extraer_video_id, link_video, plataforma
from rutas import LOGS, comando_colector, comando_login_facebook

TZ = "America/Mexico_City"
COLORES = {"Positivo": "#2a78d6", "Neutro": "#9b9a94", "Negativo": "#e34948"}
ORDEN = ["Positivo", "Neutro", "Negativo"]
SENT = {"POS": "Positivo", "NEU": "Neutro", "NEG": "Negativo"}
EMO = {"joy": "Alegría", "anger": "Enojo", "sadness": "Tristeza", "fear": "Miedo",
       "surprise": "Sorpresa", "disgust": "Asco", "others": "Otra / ninguna"}
ESTADOS = {"iniciando": "⏳ Iniciando", "recolectando": "🔴 Recolectando", "terminado": "✅ Terminado",
           "detenido": "⏹️ Detenido", "error": "⚠️ Error", "interrumpido": "⚠️ Interrumpido"}
STOPWORDS = set("""a al algo ante antes como con contra cual cuando de del desde donde e el ella ellos en entre era es esa
ese eso esta este esto estos ha hay la las le les lo los mas me mi muy nada ni no nos o otra para pero por porque que
quien se ser si sin sobre solo son su sus tambien te tiene todo tu un una uno unos y ya yo q k xd jaja jajaja""".split())

st.set_page_config(page_title="Monitor de percepción", page_icon="📊", layout="wide")


@st.cache_resource
def conexion():
    return db.connect()


# ---------------------------------------------------------------- colector
def colector_vivo(pid) -> bool:
    try:
        return bool(pid) and "colector" in " ".join(psutil.Process(int(pid)).cmdline())
    except (psutil.Error, ValueError):
        return False


def sesiones() -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM sesiones ORDER BY inicio DESC", conexion())
    df = df.astype(object).where(df.notna(), None)  # NaN -> None, para que "titulo or video_id" funcione
    # Si el proceso murió sin avisar (se cerró la ventana, se apagó el equipo...)
    caidos = df["estado"].isin(["iniciando", "recolectando"]) & ~df["pid"].map(colector_vivo)
    df.loc[caidos, "estado"] = "interrumpido"
    return df


def iniciar(video_id: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"{video_id}.log", "a", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(comando_colector(video_id, "--padre", str(os.getpid())),
                            stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    db.sesion(conexion(), video_id, pid=proc.pid, estado="iniciando", detalle="Arrancando...")


def detener(pid) -> None:
    try:
        p = psutil.Process(int(pid))
        for hijo in p.children(recursive=True):
            hijo.kill()
        p.kill()
    except (psutil.Error, ValueError):
        pass


# ---------------------------------------------------------------- datos
def cargar(video_id: str, desde=None, hasta=None) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM mensajes WHERE video_id = ?", conexion(), params=(video_id,))
    if df.empty:
        return df
    df["hora"] = pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601").dt.tz_convert(TZ)
    reloj = df["hora"].dt.time
    if desde:
        df = df[reloj >= desde]
    if hasta:
        df = df[reloj.loc[df.index] <= hasta]
    df = df.copy()
    df["Sentimiento"] = df["sentimiento"].map(SENT)
    df["Emoción"] = df["emocion"].map(EMO).fillna(df["emocion"])
    return df.sort_values("hora")


def palabras_top(textos: pd.Series, n: int = 15) -> pd.DataFrame:
    c = Counter()
    for t in textos:
        for w in re.findall(r"[a-záéíóúñü]{3,}", t.lower()):
            if w not in STOPWORDS:
                c[w] += 1
    return pd.DataFrame(c.most_common(n), columns=["Palabra", "Menciones"])


# ---------------------------------------------------------------- interfaz
st.title("📊 Monitor de percepción")
st.caption("Pega el link de un video de **YouTube** o **Facebook** (en vivo o ya publicado) y presiona **Iniciar**. "
           "Cada comentario se clasifica como positivo, neutro o negativo, con su emoción.")


def conectar_facebook() -> None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(comando_login_facebook(), creationflags=flags)
    st.toast("Se abrió una ventana de Edge: inicia sesión en Facebook. Se cerrará sola al terminar.", icon="📘")


with st.form("nuevo", clear_on_submit=True, border=True):
    links = st.text_area("Links de los videos (YouTube y Facebook) — uno por línea o separados por coma", height=110,
                         placeholder="https://www.youtube.com/watch?v=...\nhttps://www.facebook.com/.../videos/...")
    enviar = st.form_submit_button("▶ Iniciar", type="primary")
fb1, fb2 = st.columns([5, 1], vertical_alignment="center")
if facebook.sesion_conectada():
    fb1.caption("📘 Facebook: cuenta conectada ✅")
    fb2.button("Cambiar cuenta", on_click=conectar_facebook, width="stretch")
else:
    fb1.caption("📘 Facebook: **sin cuenta conectada**. Para analizar videos de Facebook, conecta una cuenta "
                "(de preferencia institucional) una sola vez.")
    fb2.button("Conectar Facebook", on_click=conectar_facebook, width="stretch")

if enviar and links.strip():
    actual = sesiones().set_index("video_id")
    iniciados, avisos = [], []
    # Acepta links por línea, separados por coma/espacio/punto y coma, o pegados uno tras otro
    partes = re.split(r"[\s,;]+|(?=https?://)", links)
    for linea in dict.fromkeys(l.strip() for l in partes if l and l.strip()):
        try:
            vid = extraer_video_id(linea)
        except (ValueError, requests.RequestException):
            avisos.append(f"No parece un video de YouTube o Facebook: {linea}")
            continue
        if vid in actual.index and actual.loc[vid, "estado"] in ("iniciando", "recolectando"):
            avisos.append(f"Ya se está analizando: {linea}")
        elif vid.startswith("fb_") and not facebook.sesion_conectada():
            avisos.append(f"Conecta una cuenta de Facebook antes de analizar: {linea}")
        elif vid not in iniciados:
            iniciar(vid)
            iniciados.append(vid)
    for a in avisos:
        st.warning(a)
    if iniciados:
        st.session_state["nuevos"] = iniciados
        st.toast(f"Recolección iniciada en {len(iniciados)} video(s). Los primeros resultados tardan ~1 minuto. "
                 "Los videos ya terminados se leen completos; los que están en vivo se siguen monitoreando.", icon="✅")

ses = sesiones()
if ses.empty:
    st.info("Aún no hay videos analizados. Pega un link arriba para empezar.")
    st.stop()

ICONO_PLATAFORMA = {"YouTube": "▶️", "Facebook": "📘"}
# Colores por video, fijos según el orden en que se agregaron (no cambian al filtrar)
PALETA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
orden_alta = list(ses["video_id"][::-1])
color_video = {v: PALETA[i % len(PALETA)] for i, v in enumerate(orden_alta)}
etiquetas = {r.video_id: f"{ESTADOS.get(r.estado, r.estado)} · {ICONO_PLATAFORMA[plataforma(r.video_id)]} "
                         f"{r.titulo or r.video_id}" for r in ses.itertuples()}
cortas = {r.video_id: f"{ICONO_PLATAFORMA[plataforma(r.video_id)]} {(r.titulo or r.video_id)[:45]}"
          for r in ses.itertuples()}
ids = list(etiquetas)

activos = [v for v in ids if ses.set_index("video_id").loc[v, "estado"] in ("iniciando", "recolectando")]
if "videos" not in st.session_state:
    st.session_state["videos"] = activos or ids[:1]
nuevos = st.session_state.pop("nuevos", [])
st.session_state["videos"] = list(dict.fromkeys(
    [v for v in st.session_state["videos"] if v in ids] + [v for v in nuevos if v in ids]))
videos = st.multiselect("Videos en el tablero", ids, key="videos", format_func=etiquetas.get,
                        help="Elige uno o varios: el tablero los muestra juntos y los compara.")

c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
desde = c1.time_input("Desde (hora)", value=None, step=60, key="desde",
                      help="Vacío = desde el inicio. Úsalo para analizar solo una participación. "
                           "Aplica a las gráficas, al informe y al CSV.")
hasta = c2.time_input("Hasta (hora)", value=None, step=60, key="hasta",
                      help="Vacío = hasta el último comentario.")
ventana = c3.select_slider("Agrupar gráficas por", options=["30s", "1min", "2min", "5min", "10min"], value="1min")
refresco = c4.number_input("Actualizar cada (s)", 2, 60, 5)


def indicadores(d: pd.DataFrame) -> dict:
    pct = d["Sentimiento"].value_counts(normalize=True).reindex(ORDEN, fill_value=0) * 100
    ult5 = d[d["hora"] >= d["hora"].max() - pd.Timedelta(minutes=5)]
    return {"Mensajes": len(d), "Msgs/min (últ. 5 min)": round(len(ult5) / 5, 1),
            "Positivo %": round(pct["Positivo"]), "Negativo %": round(pct["Negativo"]),
            "Índice neto": round(pct["Positivo"] - pct["Negativo"]),
            "Odio / agresión": int(d["odio"].sum() + d["agresivo"].sum())}


@st.fragment(run_every=refresco)
def panel():
    if not videos:
        st.info("Elige al menos un video en **Videos en el tablero**.")
        return
    estado = sesiones().set_index("video_id")
    with st.container(border=True):
        for v in videos:
            s = estado.loc[v]
            e1, e2 = st.columns([6, 1], vertical_alignment="center")
            e1.markdown(f"**{cortas[v]}** — {ESTADOS.get(s['estado'], s['estado'])} · {s['modo'] or ''} · "
                        f"{s['detalle'] or ''} · [abrir]({link_video(v)})")
            if s["estado"] in ("iniciando", "recolectando") and e2.button("⏹ Detener", key=f"det_{v}", width="stretch"):
                detener(s["pid"])
                db.sesion(conexion(), v, estado="detenido", detalle="Detenido desde la app")
                st.rerun()
            if s["estado"] in ("error", "interrumpido") and e2.button("↻ Reintentar", key=f"rei_{v}", width="stretch"):
                iniciar(v)
                st.rerun()

    partes = [cargar(v, desde, hasta).assign(Video=cortas[v], video_id=v) for v in videos]
    partes = [d for d in partes if not d.empty]
    if not partes:
        st.info("Sin mensajes en este periodo todavía. "
                "(Al iniciar, la primera vez tarda en cargar los modelos de lenguaje.)")
        return
    df = pd.concat(partes).sort_values("hora")

    st.caption(f"Periodo mostrado: {df['hora'].min():%H:%M} a {df['hora'].max():%H:%M} (hora del centro)"
               + (f" · {len(partes)} videos combinados" if len(partes) > 1 else ""))
    tot = indicadores(df)
    k = st.columns(6)
    k[0].metric("Mensajes", f"{tot['Mensajes']:,}")
    k[1].metric("Msgs/min (últ. 5 min)", f"{tot['Msgs/min (últ. 5 min)']:.1f}")
    k[2].metric("Positivo", f"{tot['Positivo %']}%")
    k[3].metric("Negativo", f"{tot['Negativo %']}%")
    k[4].metric("Índice neto", f"{tot['Índice neto']:+d}",
                help="% positivos − % negativos. Va de −100 (todo negativo) a +100 (todo positivo).")
    k[5].metric("Odio / agresión", tot["Odio / agresión"],
                help="Mensajes que el modelo marca como discurso de odio o agresivos.")

    if len(partes) > 1:
        st.subheader("Comparativo por video")
        comp = pd.DataFrame([{"Video": d["Video"].iat[0], **indicadores(d)} for d in partes])
        st.dataframe(comp, hide_index=True, width="stretch", column_config={
            "Índice neto": st.column_config.NumberColumn(format="%+d")})

    serie = (df.groupby([pd.Grouper(key="hora", freq=ventana), "Sentimiento"]).size()
               .rename("Mensajes").reset_index())
    titulo_barras = "Mensajes por sentimiento" + (" (todos los videos)" if len(partes) > 1 else "")
    fig = px.bar(serie, x="hora", y="Mensajes", color="Sentimiento", color_discrete_map=COLORES,
                 category_orders={"Sentimiento": ORDEN}, title=f"{titulo_barras}, cada {ventana}")
    fig.update_layout(bargap=0.15, legend_title_text="", xaxis_title="", hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    tabla = (df.groupby([pd.Grouper(key="hora", freq=ventana), "Video"])["Sentimiento"]
               .value_counts(normalize=True).unstack(fill_value=0).reindex(columns=ORDEN, fill_value=0))
    neto = ((tabla["Positivo"] - tabla["Negativo"]) * 100).rename("Índice neto").reset_index()
    fig2 = px.line(neto, x="hora", y="Índice neto", color="Video", markers=True,
                   color_discrete_map={cortas[v]: color_video[v] for v in videos},
                   title="Índice neto de sentimiento (positivo − negativo)" + (" por video" if len(partes) > 1 else ""))
    fig2.update_traces(line_width=2)
    fig2.add_hline(y=0, line_color="#9b9a94", line_dash="dot")
    fig2.update_layout(yaxis_range=[-100, 100], xaxis_title="", legend_title_text="",
                       showlegend=len(partes) > 1, legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig2, width="stretch")

    a, b = st.columns(2)
    emo = df[df["emocion"] != "others"]["Emoción"].value_counts().sort_values().reset_index()
    emo.columns = ["Emoción", "Mensajes"]
    fig3 = px.bar(emo, x="Mensajes", y="Emoción", orientation="h", title="Emociones detectadas")
    fig3.update_traces(marker_color="#2a78d6")
    a.plotly_chart(fig3, width="stretch")

    pal = palabras_top(df["mensaje"]).sort_values("Menciones")
    fig4 = px.bar(pal, x="Menciones", y="Palabra", orientation="h", title="Palabras más mencionadas")
    fig4.update_traces(marker_color="#2a78d6")
    b.plotly_chart(fig4, width="stretch")

    cols = ["hora", "Video", "autor", "mensaje", "Sentimiento", "Emoción"] if len(partes) > 1 else \
           ["hora", "autor", "mensaje", "Sentimiento", "Emoción"]
    a, b = st.columns(2)
    a.subheader("Últimos comentarios")
    a.dataframe(df[cols].iloc[::-1].head(50).assign(hora=lambda d: d["hora"].dt.strftime("%H:%M:%S")),
                hide_index=True, width="stretch", height=400)
    b.subheader("Más negativos / agresivos")
    criticos = df.assign(score=df["p_neg"] + df["odio"] + df["agresivo"]).sort_values("score", ascending=False)
    b.dataframe(criticos[cols].head(50).assign(hora=lambda d: d["hora"].dt.strftime("%H:%M:%S")),
                hide_index=True, width="stretch", height=400)


panel()

# ---------------------------------------------------------------- informe (fuera del auto-refresco)
st.divider()
st.header("📝 Informe")
st.caption("Usa **Desde / Hasta** (arriba) para limitar el informe y el CSV a una participación. "
           "Puedes combinar varios videos, por ejemplo la misma transmisión en YouTube y en Facebook: "
           "sale un bloque por cada uno. Se eligen los comentarios positivos y negativos más claros, sin repetidos.")
ses_idx = ses.set_index("video_id")
elegidos = st.multiselect("Videos a incluir", ids, default=videos, format_func=etiquetas.get,
                          key="inf_" + "_".join(videos))
if elegidos:
    base = pd.DataFrame({
        "video_id": elegidos,
        "Página": [ses_idx.loc[v, "canal"] or "" for v in elegidos],
        "Plataforma": [plataforma(v) for v in elegidos],
        "Link": [link_video(v) for v in elegidos],
    })
    with st.form("informe", border=True):
        st.caption("Puedes corregir el nombre de la página y pegar links acortados directamente en la tabla.")
        tabla = st.data_editor(base, hide_index=True, width="stretch", column_config={"video_id": None},
                               key=f"tabla_{'_'.join(elegidos)}")
        c1, c2, c3 = st.columns(3)
        por_tipo = c1.number_input("Comentarios por tipo (en cada video)", 1, 200, 10)
        neutros = c2.checkbox("Incluir neutros (⚪)")
        con_resumen = c3.checkbox("Incluir resumen con porcentajes")
        generar = st.form_submit_button("Generar informe", type="primary")

    datos = {v: cargar(v, desde, hasta) for v in elegidos}
    if generar:
        bloques, vacios = [], []
        for fila in tabla.to_dict("records"):
            d = datos[fila["video_id"]]
            if d.empty:
                vacios.append(etiquetas[fila["video_id"]])
                continue
            sel = informe.seleccionar(d, por_tipo, neutros)
            bloques.append(informe.bloque(sel, fila["Página"], fila["Plataforma"], fila["Link"],
                                          informe.resumen(d) if con_resumen else None))
        st.session_state["texto_informe"] = informe.unir(bloques) if bloques else None
        if vacios:
            st.warning("Sin comentarios en el periodo elegido: " + "; ".join(vacios))
    if st.session_state.get("texto_informe"):
        st.code(st.session_state["texto_informe"], language=None, wrap_lines=True)  # tiene botón de copiar
        sello = datetime.now().strftime("%Y%m%d_%H%M")
        d1, d2, _ = st.columns([1, 1, 3])
        d1.download_button("⬇ Informe en Word", informe.word(st.session_state["texto_informe"]),
                           file_name=f"informe_{sello}.docx", width="stretch",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        d2.download_button("⬇ Informe en texto", st.session_state["texto_informe"].encode("utf-8"),
                           file_name=f"informe_{sello}.txt", mime="text/plain", width="stretch")

    todos = pd.concat([d.assign(plataforma=plataforma(v)) for v, d in datos.items() if not d.empty] or [pd.DataFrame()])
    if not todos.empty:
        st.download_button(f"⬇ Todos los comentarios de estos videos en el periodo ({len(todos):,}) en CSV para Excel",
                           todos.drop(columns=["hora"]).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"comentarios_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv")
