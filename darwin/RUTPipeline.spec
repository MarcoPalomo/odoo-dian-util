# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — RUT Pipeline.app (macOS)

Build depuis le dossier darwin/ :
  pyinstaller --noconfirm RUTPipeline.spec

Prérequis :
  pip install pyinstaller
  pip install -e ../.[dev]    # installe toutes les dépendances pipeline
"""
from pathlib import Path

ROOT    = Path(SPECPATH).parent        # darwin/ → racine projet
SRC     = ROOT / "src"
SCRIPTS = ROOT / "scripts"

block_cipher = None

a = Analysis(
    [str(Path(SPECPATH) / "launcher.py")],
    pathex=[str(ROOT), str(SRC), str(SCRIPTS)],
    binaries=[],
    datas=[
        # Modules pipeline
        (str(SRC / "pipeline"),  "pipeline"),
        # Scripts d'ingestion (importés directement par le launcher)
        (str(SCRIPTS / "ingest_from_documents.py"), "scripts"),
        (str(SCRIPTS / "process_rut.py"),           "scripts"),
        (str(SCRIPTS / "retry_prequalification.py"),"scripts"),
    ],
    hiddenimports=[
        # pdfplumber et ses dépendances
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
        # Requests
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        # PostgreSQL
        "psycopg2",
        # MinIO
        "minio",
        # Tkinter (normalement inclus, mais au cas où)
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        # Unittest.mock (utilisé pour MagicMock storage)
        "unittest.mock",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclure ce qui n'est pas nécessaire (réduit la taille du bundle)
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
    console=False,          # Fenêtré — pas de terminal visible
    argv_emulation=True,    # macOS : supporte le drag-and-drop de fichiers sur l'icône
    target_arch=None,       # None = architecture hôte ; "universal2" pour fat binary
    codesign_identity=None,
    entitlements_file=None,
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

app = BUNDLE(
    coll,
    name="RUT Pipeline.app",
    icon=None,              # Remplacer par "icon.icns" si disponible
    bundle_identifier="com.industriaspico.rutpipeline",
    version="1.0.0",
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleName": "RUT Pipeline",
        "CFBundleDisplayName": "RUT Pipeline",
        "NSHumanReadableCopyright": "Industrias Pico SAS",
        # Permissions macOS nécessaires
        "NSAppleEventsUsageDescription":
            "RUT Pipeline accède aux fichiers PDF pour les importer dans Odoo.",
    },
)
