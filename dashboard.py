"""Dashboard en tiempo real: streamlit run dashboard.py"""
import re
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st

import db

TZ = "America/Mexico_City"
COLORES = {"Positivo": "#2a78d6", "Neutro": "#9b9a94", "Negativo": "#e34948"}
ORDEN = ["Positivo", "Neutro", "Negativo"]
SENT = {"POS": "Positivo", "NEU": "Neutro", "NEG": "Negativo"}
EMO = {"joy": "Alegría", "anger": "Enojo", "sadness": "Tristeza", "fear": "Miedo",
       "surprise": "Sorpresa", "disgust": "Asco", "others": "Otra / ninguna"}
STOPWORDS = set("""a al algo ante antes como con contra cual cuando de del desde donde e el ella ellos en entre era es esa
ese eso esta este esto estos ha hay la las le les lo los mas me mi muy nada ni no nos o otra para pero por porque que
quien se ser si sin sobre solo son su sus tambien te tiene todo tu un una uno unos y ya yo q k xd jaja jajaja""".split())

st.set_page_config(page_title="Percepción en vivo", page_icon="📊", layout="wide")


@st.cache_resource
def conexion():
    return db.connect()


def cargar(video_id: str | None) -> pd.DataFrame:
    sql, params = "SELECT * FROM mensajes", ()
    if video_id:
        sql, params = sql + " WHERE video_id = ?", (video_id,)
    df = pd.read_sql_query(sql, conexion(), params=params)
    if df.empty:
        return df
    df["hora"] = pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601").dt.tz_convert(TZ)
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


st.title("Percepción del chat en vivo")

videos = [r[0] for r in conexion().execute("SELECT DISTINCT video_id FROM mensajes").fetchall()]
c1, c2, c3 = st.columns([2, 2, 1])
video = c1.selectbox("Video", videos or ["(sin datos aún)"])
ventana = c2.select_slider("Agrupar por", options=["30s", "1min", "2min", "5min", "10min"], value="1min")
refresco = c3.number_input("Refresco (s)", 2, 60, 5)


@st.fragment(run_every=refresco)
def panel():
    df = cargar(video if videos else None)
    if df.empty:
        st.info("Esperando mensajes... Inicia el colector: `python colector.py <URL del video>`")
        return

    n = len(df)
    pct = df["Sentimiento"].value_counts(normalize=True).reindex(ORDEN, fill_value=0) * 100
    indice = pct["Positivo"] - pct["Negativo"]
    ultimos5 = df[df["hora"] >= df["hora"].max() - pd.Timedelta(minutes=5)]
    k = st.columns(6)
    k[0].metric("Mensajes", f"{n:,}")
    k[1].metric("Msgs/min (últ. 5 min)", f"{len(ultimos5) / 5:.1f}")
    k[2].metric("Positivo", f"{pct['Positivo']:.0f}%")
    k[3].metric("Negativo", f"{pct['Negativo']:.0f}%")
    k[4].metric("Índice neto", f"{indice:+.0f}", help="% positivos − % negativos (de −100 a +100)")
    k[5].metric("Odio / agresión", int(df["odio"].sum() + df["agresivo"].sum()))

    # Volumen por sentimiento en el tiempo
    serie = (df.groupby([pd.Grouper(key="hora", freq=ventana), "Sentimiento"]).size()
               .rename("Mensajes").reset_index())
    fig = px.bar(serie, x="hora", y="Mensajes", color="Sentimiento", color_discrete_map=COLORES,
                 category_orders={"Sentimiento": ORDEN}, title=f"Mensajes por sentimiento (cada {ventana})")
    fig.update_layout(bargap=0.15, legend_title_text="", xaxis_title="", hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    # Índice neto en el tiempo
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

    st.download_button("Descargar CSV", df.drop(columns=["hora"]).to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"comentarios_{video}.csv", mime="text/csv")


panel()
