# -*- mode: python ; coding: utf-8 -*-
"""
SourceMaterialFetcher.spec

Single source of truth for the PyInstaller build. All build scripts
and CI workflows run `pyinstaller SourceMaterialFetcher.spec` instead
of repeating the same flags in four different places.

Qt module excludes: PySide6 ships dozens of Qt modules (WebEngine,
Qml/Quick, Multimedia, Sql, Charts, ...) this app doesn't use, and
PyInstaller's default hooks bundle far more of them than the app
actually imports. Excluding the ones we genuinely don't touch
meaningfully shrinks the exe and -- for --onefile builds -- speeds up
the self-extraction that happens on every launch, since there's less
to unpack. If you add a feature that needs one of these later (e.g.
QtNetwork for something beyond urllib), remove it from this list.

UPX is intentionally left off (upx=False): it shrinks the file further
but slows down onefile's launch-time decompression and is a common
trigger for antivirus false positives on distributed exes -- not
worth it for a tool people will download and run.
"""

EXCLUDED_QT_MODULES = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",       # updater uses stdlib urllib, not QtNetwork
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtPrintSupport",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
]

EXCLUDED_STDLIB_MODULES = [
    "unittest",
    "pydoc",
    "doctest",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_QT_MODULES + EXCLUDED_STDLIB_MODULES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SourceMaterialFetcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon="assets/icon.ico",
)
