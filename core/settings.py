"""
settings.py

Small JSON-backed settings store, kept next to the executable so the
app remembers configured search locations and the last output folder
between runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_SETTINGS = {
    "search_roots": [],   # list[str] absolute paths to content roots
    "last_output_dir": "",
    "window_geometry": "",  # base64 QByteArray from QMainWindow.saveGeometry(), stored as hex
}


def settings_path() -> Path:
    # In the built .exe, __file__ points into a temp folder that is
    # deleted every time the app closes, so settings must be saved next
    # to the .exe itself. When running from source, use the project folder.
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "SourceMaterialFetcher_Settings.json"


def load_settings() -> dict:
    p = settings_path()
    if not p.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(data: dict) -> None:
    p = settings_path()
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
