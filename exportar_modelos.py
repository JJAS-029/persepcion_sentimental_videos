"""Copia los 3 modelos de pysentimiento a ./modelos/<tarea> para empaquetarlos en el .exe."""
from pathlib import Path

from pysentimiento import create_analyzer

DESTINO = Path(__file__).parent / "modelos"

for tarea in ("sentiment", "emotion", "hate_speech"):
    a = create_analyzer(task=tarea, lang="es")
    a.model.save_pretrained(DESTINO / tarea)
    a.tokenizer.save_pretrained(DESTINO / tarea)
    print(f"{tarea}: listo")
