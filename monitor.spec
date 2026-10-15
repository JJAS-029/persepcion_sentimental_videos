# PyInstaller: genera dist/Monitor de percepcion/Monitor de percepcion.exe
# Uso:  python exportar_modelos.py  &&  pyinstaller monitor.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = [("app.py", "."), ("modelos", "modelos")]
for paquete in ("streamlit", "plotly", "emoji", "docx", "tzdata", "certifi", "altair"):
    datas += collect_data_files(paquete)
# Paquetes que verifican versiones de sus dependencias vía importlib.metadata
for paquete in ("streamlit", "transformers", "tokenizers", "huggingface-hub", "safetensors", "torch",
                "accelerate", "datasets", "tqdm", "regex", "requests", "packaging", "filelock", "numpy",
                "pyyaml", "pysentimiento", "pandas", "pyarrow", "plotly", "psutil"):
    datas += copy_metadata(paquete)

# app.py lo carga Streamlit en tiempo de ejecución: sus importaciones no se detectan solas
hiddenimports = ["app", "db", "fuentes", "informe", "rutas", "colector", "docx", "psutil", "plotly.express"]
hiddenimports += collect_submodules("streamlit")
hiddenimports += collect_submodules("transformers.models.roberta")
hiddenimports += collect_submodules("pysentimiento", filter=lambda m: "baselines" not in m)

a = Analysis(
    ["monitor.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["spacy", "thinc", "tensorflow", "keras", "jax", "matplotlib", "IPython", "tkinter",
              "sklearn", "torchvision", "torchaudio", "pytest", "chat_downloader", "pytchat"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Monitor de percepcion",
    console=True,  # la ventana muestra "no cerrar" y mantiene vivo el servidor
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Monitor de percepcion")
