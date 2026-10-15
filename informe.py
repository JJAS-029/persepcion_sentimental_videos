"""Informe de comentarios en el formato solicitado:

    <Página>
     <Plataforma> <link>

    🟢<Autor> <comentario positivo>
    🔴<Autor> <comentario negativo>
"""
import io
import re

import pandas as pd

ICONOS = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}


def seleccionar(df: pd.DataFrame, por_tipo: int, incluir_neutros: bool = False) -> pd.DataFrame:
    """Los comentarios más claros de cada tipo (mayor probabilidad), sin repetidos ni mensajes vacíos."""
    d = df.copy()
    d["_norm"] = d["mensaje"].str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    d = d[d["_norm"].str.count(r"[a-záéíóúñü]") >= 8]          # descarta solo emojis / "hola"
    d = d.drop_duplicates("_norm")
    tipos = [("POS", "p_pos"), ("NEG", "p_neg")] + ([("NEU", "p_neu")] if incluir_neutros else [])
    bloques = [d[d["sentimiento"] == s].nlargest(por_tipo, p).sort_values("hora") for s, p in tipos]
    return pd.concat(bloques).drop(columns="_norm")


def _autor(nombre) -> str:
    return re.sub(r"^@", "", nombre or "").strip()


def texto(sel: pd.DataFrame, pagina: str, plataforma: str, link: str, resumen: str | None = None) -> str:
    lineas = [pagina.strip(), f" {plataforma.strip()} {link.strip()}".rstrip(), ""]
    if resumen:
        lineas += [resumen, ""]
    lineas += [f"{ICONOS[r.sentimiento]}{_autor(r.autor)} {r.mensaje.strip()}" for r in sel.itertuples()]
    return "\n".join(lineas)


def resumen(df: pd.DataFrame) -> str:
    n = len(df)
    pct = df["sentimiento"].value_counts(normalize=True) * 100
    return (f"Comentarios analizados: {n:,} · 🟢 {pct.get('POS', 0):.0f}% positivos · "
            f"🔴 {pct.get('NEG', 0):.0f}% negativos · ⚪ {pct.get('NEU', 0):.0f}% neutros")


def word(contenido: str) -> bytes:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name, estilo.font.size = "Calibri", Pt(11)
    primera, *resto = contenido.split("\n")
    doc.add_paragraph().add_run(primera).bold = True
    for linea in resto:
        doc.add_paragraph(linea)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
