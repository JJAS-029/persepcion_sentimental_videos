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
import streamlit as st

import db
import informe
from fuentes import extraer_video_id
from rutas import LOGS, comando_colector

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
st.title("📊 Monitor de percepción en YouTube")
st.caption("Pega el link de una transmisión en vivo (o ya terminada con chat) y presiona **Iniciar**. "
           "Cada comentario se clasifica como positivo, neutro o negativo, con su emoción.")

with st.form("nuevo", clear_on_submit=True, border=True):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    link = c1.text_input("Link del video de YouTube", placeholder="https://www.youtube.com/watch?v=...")
    enviar = c2.form_submit_button("▶ Iniciar", type="primary", width="stretch")
if enviar and link:
    try:
        vid = extraer_video_id(link.strip())
    except ValueError:
        st.error("Ese link no parece de un video de YouTube. Copia la dirección completa del video.")
    else:
        actual = sesiones().set_index("video_id")
        if vid in actual.index and actual.loc[vid, "estado"] in ("iniciando", "recolectando"):
            st.warning("Ese video ya se está analizando.")
        else:
            iniciar(vid)
            st.session_state["video"] = vid
            st.toast("Recolección iniciada. Los primeros resultados tardan ~1 minuto.", icon="✅")

ses = sesiones()
if ses.empty:
    st.info("Aún no hay videos analizados. Pega un link arriba para empezar.")
    st.stop()

etiquetas = {r.video_id: f"{ESTADOS.get(r.estado, r.estado)} · {r.titulo or r.video_id}" for r in ses.itertuples()}
ids = list(etiquetas)
previo = st.session_state.get("video")
video = st.selectbox("Video", ids, index=ids.index(previo) if previo in ids else 0, format_func=etiquetas.get)
st.session_state["video"] = video

c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
desde = c1.time_input("Desde (hora)", value=None, step=60, key=f"desde_{video}",
                      help="Vacío = desde el inicio. Úsalo para analizar solo una participación.")
hasta = c2.time_input("Hasta (hora)", value=None, step=60, key=f"hasta_{video}",
                      help="Vacío = hasta el último comentario.")
ventana = c3.select_slider("Agrupar gráficas por", options=["30s", "1min", "2min", "5min", "10min"], value="1min")
refresco = c4.number_input("Actualizar cada (s)", 2, 60, 5)


@st.fragment(run_every=refresco)
def panel():
    s = sesiones().set_index("video_id").loc[video]
    corriendo = s["estado"] in ("iniciando", "recolectando")
    e1, e2 = st.columns([5, 1], vertical_alignment="center")
    e1.markdown(f"**{ESTADOS.get(s['estado'], s['estado'])}** · {s['modo'] or ''} · {s['detalle'] or ''}  \n"
                f"[Abrir video en YouTube](https://www.youtube.com/watch?v={video})")
    if corriendo and e2.button("⏹ Detener", width="stretch"):
        detener(s["pid"])
        db.sesion(conexion(), video, estado="detenido", detalle="Detenido desde la app")
        st.rerun()
    if s["estado"] in ("error", "interrumpido") and e2.button("↻ Reintentar", width="stretch"):
        iniciar(video)
        st.rerun()

    df = cargar(video, desde, hasta)
    if df.empty:
        st.info("Sin mensajes en este periodo todavía. "
                "(Al iniciar, la primera vez tarda en cargar los modelos de lenguaje.)")
        return

    st.caption(f"Periodo mostrado: {df['hora'].min():%H:%M} a {df['hora'].max():%H:%M} (hora del centro)")
    n = len(df)
    pct = df["Sentimiento"].value_counts(normalize=True).reindex(ORDEN, fill_value=0) * 100
    ultimos5 = df[df["hora"] >= df["hora"].max() - pd.Timedelta(minutes=5)]
    k = st.columns(6)
    k[0].metric("Mensajes", f"{n:,}")
    k[1].metric("Msgs/min (últ. 5 min)", f"{len(ultimos5) / 5:.1f}")
    k[2].metric("Positivo", f"{pct['Positivo']:.0f}%")
    k[3].metric("Negativo", f"{pct['Negativo']:.0f}%")
    k[4].metric("Índice neto", f"{pct['Positivo'] - pct['Negativo']:+.0f}",
                help="% positivos − % negativos. Va de −100 (todo negativo) a +100 (todo positivo).")
    k[5].metric("Odio / agresión", int(df["odio"].sum() + df["agresivo"].sum()),
                help="Mensajes que el modelo marca como discurso de odio o agresivos.")

    serie = (df.groupby([pd.Grouper(key="hora", freq=ventana), "Sentimiento"]).size()
               .rename("Mensajes").reset_index())
    fig = px.bar(serie, x="hora", y="Mensajes", color="Sentimiento", color_discrete_map=COLORES,
                 category_orders={"Sentimiento": ORDEN}, title=f"Mensajes por sentimiento (cada {ventana})")
    fig.update_layout(bargap=0.15, legend_title_text="", xaxis_title="", hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    tabla = (df.groupby(pd.Grouper(key="hora", freq=ventana))["Sentimiento"]
               .value_counts(normalize=True).unstack(fill_value=0).reindex(columns=ORDEN, fill_value=0))
    neto = ((tabla["Positivo"] - tabla["Negativo"]) * 100).rename("Índice neto").reset_index()
    fig2 = px.line(neto, x="hora", y="Índice neto", markers=True,
                   title="Índice neto de sentimiento (positivo − negativo)")
    fig2.update_traces(line_color="#2a78d6", line_width=2)
    fig2.add_hline(y=0, line_color="#9b9a94", line_dash="dot")
    fig2.update_layout(yaxis_range=[-100, 100], xaxis_title="")
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

    cols = ["hora", "autor", "mensaje", "Sentimiento", "Emoción"]
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
           "Se eligen los comentarios positivos y negativos más claros, sin repetidos.")
s = ses.set_index("video_id").loc[video]
with st.form(f"informe_{video}", border=True):
    c1, c2, c3 = st.columns([2, 1, 3])
    pagina = c1.text_input("Página", value=s.get("canal") or "")
    plataforma = c2.text_input("Plataforma", value="YouTube")
    link_inf = c3.text_input("Link (puedes pegar uno acortado)", value=f"https://www.youtube.com/watch?v={video}")
    c1, c2, c3 = st.columns(3)
    por_tipo = c1.number_input("Comentarios por tipo", 1, 200, 10)
    neutros = c2.checkbox("Incluir neutros (⚪)")
    con_resumen = c3.checkbox("Incluir resumen con porcentajes")
    generar = st.form_submit_button("Generar informe", type="primary")

datos = cargar(video, desde, hasta)
if generar:
    if datos.empty:
        st.warning("No hay comentarios en el periodo elegido.")
    else:
        sel = informe.seleccionar(datos, por_tipo, neutros)
        st.session_state[f"texto_informe_{video}"] = informe.texto(sel, pagina, plataforma, link_inf,
                                                    informe.resumen(datos) if con_resumen else None)
if st.session_state.get(f"texto_informe_{video}"):
    st.code(st.session_state[f"texto_informe_{video}"], language=None, wrap_lines=True)  # tiene botón de copiar
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button("⬇ Informe en Word", informe.word(st.session_state[f"texto_informe_{video}"]),
                       file_name=f"informe_{video}_{sello}.docx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    d2.download_button("⬇ Informe en texto", st.session_state[f"texto_informe_{video}"].encode("utf-8"),
                       file_name=f"informe_{video}_{sello}.txt", mime="text/plain", width="stretch")

if not datos.empty:
    st.download_button(f"⬇ Todos los comentarios del periodo ({len(datos):,}) en CSV para Excel",
                       datos.drop(columns=["hora"]).to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"comentarios_{video}.csv", mime="text/csv")
