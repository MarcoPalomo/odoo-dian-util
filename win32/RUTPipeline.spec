# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — RUT Pipeline.exe (Windows 10/11)

Build depuis le dossier win32\ :
  pyinstaller --noconfirm RUTPipeline.spec

Prérequis :
  python make_icon.py        # génère icon.ico
  pip install pyinstaller    # installé par build.ps1
"""
from pathlib import Path

ROOT    = Path(SPECPATH).parent              # win32\ → racine projet
SRC     = ROOT / "amd64" / "src"
SCRIPTS = ROOT / "amd64" / "scripts"
ICON    = str(Path(SPECPATH) / "icon.ico")

block_cipher = None

a = Analysis(
    [str(Path(SPECPATH) / "launcher.py")],
    pathex=[str(ROOT), str(SRC), str(SCRIPTS)],
    binaries=[],
    datas=[
        # Module pipeline (placé à la racine du bundle)
        (str(SRC / "pipeline"),  "pipeline"),
        # Scripts d'ingestion importés directement
        (str(SCRIPTS / "ingest_from_documents.py"), "."),
        (str(SCRIPTS / "process_rut.py"),           "."),
        (str(SCRIPTS / "retry_prequalification.py"),"."),
    ],
    hiddenimports=[
        # pdfplumber et dépendances
        "pdfplumber",
        "pdfminer",
        "pdfminer.high_level",
        "pdfminer.layout",
        "pdfminer.pdfinterp",
        "pdfminer.converter",
        "pdfminer.image",
        "pdfminer.pdffont",
        "pdfminer.pdfpage",
        "pdfminer.pdfparser",
        "pdfminer.pdfdocument",
        "pdfminer.pdfdevice",
        "pdfminer.utils",
        # Pydantic v2
        "pydantic",
        "pydantic_core",
        # Structlog
        "structlog",
        "structlog._frames",
        "structlog.stdlib",
        "structlog.dev",
        # Tenacity
        "tenacity",
        # Dotenv
        "dotenv",
        "dotenv.main",
        # Click
        "click",
        # Requests + dépendances SSL
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        # PostgreSQL
        "psycopg2",
        # MinIO
        "minio",
        # Tkinter
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        # unittest.mock (MagicMock storage)
        "unittest.mock",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "redis",
        "fastapi",
        "uvicorn",
        "jinja2",
        "python_multipart",
        "aiohttp",
        "pytest",
        "IPython",
        "matplotlib",
        "numpy",
        "pandas",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RUT Pipeline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Application fenêtrée — pas de terminal visible
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RUT Pipeline",
)
