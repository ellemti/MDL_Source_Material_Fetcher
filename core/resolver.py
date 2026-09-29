"""
resolver.py

Given an MDLInfo (materials + cdmaterials search dirs) and a list of
"content root" directories (folders that directly contain a
materials/ subfolder -- e.g. a GarrysMod/garrysmod install, a
Half-Life 2 install, a custom addon folder), find every .vmt and its
referenced .vtf files, recursively following $-texture params and
patch/include chains.

This module only searches plain folders on disk. VPK archive support
is a separate, later stage (not part of this build).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from .mdl_parser import MDLInfo
from .vmt_parser import parse_vmt


@dataclass
class ResolveResult:
    # Absolute source path -> path relative to the output "materials/..." root
    found: dict[Path, str] = field(default_factory=dict)
    # Human-readable relative paths (e.g. "materials/models/x/body.vmt")
    # that were searched for but not found in any content root.
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _find_in_roots(roots: list[Path], relative_path: str) -> Path | None:
    """relative_path is like 'materials/models/x/body.vmt'.
    Windows filesystems are case-insensitive, so a direct join+exists
    check is sufficient there -- and it's the common case, since most
    candidate paths tried during resolution DON'T exist (we try several
    cdmaterials prefixes per material). Skipping the case-insensitive
    directory walk on Windows avoids doing that walk on every miss,
    which matters a lot once a search root has tens of thousands of
    files (a typical GMod addons folder).
    The walk fallback only runs on non-Windows platforms (Linux/Mac
    dev environments), where it's needed for correctness during
    testing/development.
    """
    rel = Path(relative_path)
    for root in roots:
        candidate = root / rel
        if candidate.is_file():
            return candidate
        if sys.platform != "win32":
            found = _case_insensitive_lookup(root, rel)
            if found is not None:
                return found
    return None


def _case_insensitive_lookup(root: Path, rel: Path) -> Path | None:
    current = root
    for part in rel.parts:
        if not current.is_dir():
            return None
        match = None
        try:
            for entry in current.iterdir():
                if entry.name.lower() == part.lower():
                    match = entry
                    break
        except OSError:
            return None
        if match is None:
            return None
        current = match
    return current if current.is_file() else None


def resolve_model(mdl: MDLInfo, roots: list[Path]) -> ResolveResult:
    result = ResolveResult()
    visited_vmt: set[str] = set()  # relative vmt path (no ext), to avoid re-processing

    def process_material(mat_rel: str, cdmaterials: list[str]) -> None:
        """mat_rel is like 'models/player/example/body' (no extension).
        Tries each cdmaterials prefix until one resolves.
        """
        key = mat_rel.lower()
        if key in visited_vmt:
            return
        visited_vmt.add(key)

        candidates = []
        # If the material path already looks absolute-ish (contains a
        # cdmaterials prefix already, common when following $basetexture
        # refs from a VMT, which are always materials/-relative), try it
        # directly first.
        candidates.append(f"materials/{mat_rel}.vmt")
        for cd in cdmaterials:
            candidates.append(f"materials/{cd}{mat_rel}.vmt")

        vmt_path = None
        chosen_rel = None
        for c in candidates:
            found = _find_in_roots(roots, c)
            if found is not None:
                vmt_path = found
                chosen_rel = c
                break

        if vmt_path is None:
            # Report the most specific candidate actually searched for
            # (the cdmaterials-prefixed one, if any) rather than always
            # the bare path, so the report reflects what was really tried.
            best_candidate = candidates[1] if len(candidates) > 1 else candidates[0]
            result.missing.append(best_candidate)
            return

        result.found[vmt_path] = chosen_rel

        try:
            text = vmt_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            result.warnings.append(f"Could not read {vmt_path}: {e}")
            return

        info = parse_vmt(text)

        if info.is_patch and info.include_path:
            process_material(info.include_path, cdmaterials)

        for tex_rel in info.textures:
            vtf_rel = f"materials/{tex_rel}.vtf"
            found = _find_in_roots(roots, vtf_rel)
            if found is not None:
                result.found[found] = vtf_rel
            else:
                result.missing.append(vtf_rel)

        for sub_mat in info.sub_materials:
            process_material(sub_mat, cdmaterials)

    for material in mdl.materials:
        process_material(material, mdl.cdmaterials)

    return result
