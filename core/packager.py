"""
packager.py

Takes the combined resolve results for one or more models and writes
them to disk under an output folder, preserving the
materials/... relative structure, then zips the result.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def write_package(found: dict[Path, str], output_dir: Path) -> list[str]:
    """Copies each (absolute_src -> relative_dest) pair into output_dir.
    Returns the list of relative paths actually written (dedup-safe).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    seen: set[str] = set()
    for src, rel in found.items():
        rel_norm = rel.replace("\\", "/")
        if rel_norm.lower() in seen:
            continue
        seen.add(rel_norm.lower())
        dest = output_dir / rel_norm
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest)
            written.append(rel_norm)
        except OSError:
            continue
    return written


def zip_package(output_dir: Path, zip_path: Path, relative_paths: list[str]) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in relative_paths:
            zf.write(output_dir / rel, arcname=rel)
    return zip_path
