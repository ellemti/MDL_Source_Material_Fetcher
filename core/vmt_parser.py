"""
vmt_parser.py

Parser for Source Engine .vmt material files (Valve "KeyValues" text
format). Extracts every $-parameter that points at a texture (.vtf),
across all common shaders, and follows "patch" / "include" VMTs
recursively.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Every known shader parameter that references a texture path (no
# extension, relative to materials/). This list is intentionally
# broad -- covers VertexLitGeneric, LightmappedGeneric, Character,
# Cable, UnlitGeneric, Eyes, EyeRefract, Refract, Water, Decal shaders
# and common $-flags used across HL2/CS:S/TF2/GMod-era content.
TEXTURE_PARAMS = {
    "$basetexture",
    "$basetexture2",
    "$bumpmap",
    "$bumpmap2",
    "$normalmap",
    "$envmapmask",
    "$envmap",
    "$detail",
    "$selfillummask",
    "$phongexponenttexture",
    "$phongwarptexture",
    "$lightwarptexture",
    "$blendmodulatetexture",
    "$flowmap",
    "$flow_noise_texture",
    "$flow_normaltexture",
    "$iris",                # eyes
    "$corneatexture",       # eyerefract
    "$ambientoccltexture",
    "$emissiveblendtexture",
    "$emissiveblendbasetexture",
    "$emissiveblendflowtexture",
    "$refracttinttexture",
    "$bottommaterial",      # water/blend
    "$underwateroverlay",
    "$decaltexture",
    "$displacementmap",
    "$maskstexture",
    "$translucencytexture",
    "$parallaxmap",
}

# Keys that themselves reference another material rather than a
# texture directly (e.g. water shaders referencing a bottom material).
MATERIAL_PARAMS = {
    "$bottommaterial",
}


@dataclass
class VMTInfo:
    shader: str
    textures: list[str] = field(default_factory=list)     # relative, no extension
    sub_materials: list[str] = field(default_factory=list)  # relative .vmt paths (no ext)
    raw: dict = field(default_factory=dict)
    is_patch: bool = False
    include_path: str | None = None


def _strip_comments(text: str) -> str:
    # Remove // line comments (not inside quotes -- VMTs rarely need that nuance,
    # but we avoid stripping inside quoted strings to be safe).
    out = []
    i = 0
    in_quotes = False
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            in_quotes = not in_quotes
            out.append(c)
            i += 1
            continue
        if not in_quotes and c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


_TOKEN_RE = re.compile(r'"([^"]*)"|(\{)|(\})|([^\s{}"]+)')


def _tokenize(text: str) -> list[str]:
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            tokens.append(m.group(1))
        elif m.group(2):
            tokens.append("{")
        elif m.group(3):
            tokens.append("}")
        elif m.group(4):
            tokens.append(m.group(4))
    return tokens


def _parse_block(tokens: list[str], i: int) -> tuple[dict, int]:
    """Parse a {...} keyvalues block starting at tokens[i] == '{'."""
    result: dict = {}
    i += 1  # skip '{'
    while i < len(tokens):
        tok = tokens[i]
        if tok == "}":
            return result, i + 1
        key = tok
        i += 1
        if i >= len(tokens):
            break
        if tokens[i] == "{":
            value, i = _parse_block(tokens, i)
        else:
            value = tokens[i]
            i += 1
        # VMTs can repeat keys (rare); last one wins, matching engine behavior.
        result[key.lower()] = value
    return result, i


def parse_vmt(text: str) -> VMTInfo:
    """Parse VMT source text into a VMTInfo.

    Handles both normal shader blocks and "patch" blocks
    (patch { include "..." insert { ... } replace { ... } }).
    """
    cleaned = _strip_comments(text)
    tokens = _tokenize(cleaned)
    if not tokens:
        return VMTInfo(shader="", textures=[])

    shader = tokens[0]
    body = {}
    if len(tokens) > 1 and tokens[1] == "{":
        body, _ = _parse_block(tokens, 1)

    if shader.lower() == "patch":
        include_path = None
        merged: dict = {}
        inc = body.get("include")
        if isinstance(inc, str):
            include_path = inc.replace("\\", "/")
            if include_path.lower().startswith("materials/"):
                include_path = include_path[len("materials/"):]
            include_path = include_path[:-4] if include_path.lower().endswith(".vmt") else include_path
        for section_key in ("insert", "replace"):
            section = body.get(section_key)
            if isinstance(section, dict):
                merged.update(section)
        info = VMTInfo(shader="patch", raw=merged, is_patch=True, include_path=include_path)
        _extract_textures(merged, info)
        return info

    info = VMTInfo(shader=shader, raw=body)
    _extract_textures(body, info)
    return info


def _extract_textures(kv: dict, info: VMTInfo) -> None:
    for key, value in kv.items():
        if not isinstance(value, str):
            continue
        if key in TEXTURE_PARAMS:
            # "$envmap" "env_cubemap" is a special keyword meaning "use the
            # nearest env_cubemap entity's reflection", not a texture path --
            # there is no materials/env_cubemap.vtf to resolve.
            if key == "$envmap" and value.strip().lower() == "env_cubemap":
                continue
            v = value.replace("\\", "/").strip("/")
            if v.lower().startswith("materials/"):
                v = v[len("materials/"):]
            if v:
                info.textures.append(v)
        if key in MATERIAL_PARAMS:
            v = value.replace("\\", "/").strip("/")
            if v.lower().startswith("materials/"):
                v = v[len("materials/"):]
            if v.lower().endswith(".vmt"):
                v = v[:-4]
            if v:
                info.sub_materials.append(v)
