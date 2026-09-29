"""
mdl_parser.py

Minimal binary reader for Source Engine .mdl (studiomdl) files.

We only need two things out of the MDL for material resolution:
  1) The list of texture ("material") names referenced by the model
     (e.g. "models/player/example/body")
  2) The list of cdmaterials search directories the engine would
     prepend to each texture name when looking for the .vmt
     (e.g. "models/player/example/", "" for the materials/ root)

This covers the studiohdr_t layout used by MDL versions 44-49, which
is the range covering essentially all HL2-era Source 1 / GMod content.
Older/newer/exotic versions may fail to parse cleanly -- the parser
raises MDLParseError with a clear message rather than silently
returning wrong data.

Reference layout (relevant fields only, offsets in bytes, all
little-endian int32 unless noted):

    0   char id[4]              "IDST"
    4   int  version
    8   int  checksum
    12  char name[64]
    76  int  length
    ... (bounding boxes, flags, bone/hitbox/localanim/localseq/etc
         are all skipped -- we jump straight to the fields we need
         and use the section's own index fields, so we don't need to
         hand-decode every field in between)

Rather than hand-track every offset (fragile across the exact minor
layout), we read the header as a flat array of int32 words after the
fixed 76-byte name block, using the well-known field ORDER instead of
raw byte offsets. This mirrors the approach used by community tools
(e.g. Crowbar, SourceIO) for the numtextures/textureindex and
numcdtextures/cdtextureindex fields specifically.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path


class MDLParseError(Exception):
    pass


# mstudiotexture_t is a fixed 64-byte struct in v44-49:
#   int sznameindex;   (offset relative to the START of this struct)
#   int flags;
#   int used;
#   int unused1;
#   int material;         (runtime pointer, 0 on disk)
#   int client_material;  (runtime pointer, 0 on disk)
#   int unused[10];
MSTUDIOTEXTURE_SIZE = 64

# Byte offsets of the fields we need within studiohdr_t, valid for
# MDL versions 44-49 (the vast majority of Source 1 content).
OFF_ID = 0
OFF_VERSION = 4
OFF_NAME = 12
OFF_LENGTH = 76

# These offsets are computed directly from Valve's public
# studiohdr_t definition (source-sdk-2013, public/studio.h), walking
# the struct field-by-field from the start of the file:
#   id, version, checksum          : 0, 4, 8      (4 bytes each)
#   name[64]                       : 12            -> 76
#   length                         : 76            -> 80
#   eyeposition..view_bbmax        : 80             (6 Vectors x 12 bytes = 72) -> 152
#   flags                          : 152           -> 156
#   numbones, boneindex            : 156, 160      -> 164
#   numbonecontrollers, ...index   : 164, 168      -> 172
#   numhitboxsets, hitboxsetindex  : 172, 176      -> 180
#   numlocalanim, localanimindex   : 180, 184      -> 188
#   numlocalseq, localseqindex     : 188, 192      -> 196
#   activitylistversion, eventsindexed : 196, 200  -> 204
#   numtextures, textureindex      : 204, 208      -> 212
#   numcdtextures, cdtextureindex  : 212, 216      -> 220
#   numskinref, numskinfamilies, skinindex : 220, 224, 228
OFF_NUMTEXTURES = 204
OFF_TEXTUREINDEX = 208
OFF_NUMCDTEXTURES = 212
OFF_CDTEXTUREINDEX = 216
OFF_NUMSKINREF = 220
OFF_NUMSKINFAMILIES = 224
OFF_SKININDEX = 228

SUPPORTED_VERSIONS = range(44, 50)  # 44..49 inclusive


@dataclass
class MDLInfo:
    path: Path
    version: int
    internal_name: str
    materials: list[str] = field(default_factory=list)     # e.g. "models/player/example/body"
    cdmaterials: list[str] = field(default_factory=list)    # e.g. "models/player/example/"
    warnings: list[str] = field(default_factory=list)


def _read_i32(buf: bytes, offset: int) -> int:
    if offset + 4 > len(buf):
        raise MDLParseError(f"Unexpected end of file reading int32 at offset {offset}")
    return struct.unpack_from("<i", buf, offset)[0]


def _read_cstring(buf: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(buf):
        raise MDLParseError(f"String offset {offset} out of range")
    end = buf.find(b"\x00", offset)
    if end == -1:
        end = len(buf)
    raw = buf[offset:end]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def parse_mdl(path: Path) -> MDLInfo:
    """Parse a .mdl file and return the materials it references.

    Raises MDLParseError on anything that looks malformed or on an
    unsupported version.
    """
    buf = path.read_bytes()

    if len(buf) < OFF_SKININDEX + 4:
        raise MDLParseError("File is too small to be a valid MDL")

    magic = buf[OFF_ID:OFF_ID + 4]
    if magic != b"IDST":
        raise MDLParseError(
            f"Not a Source MDL file (expected 'IDST' magic, got {magic!r})"
        )

    version = _read_i32(buf, OFF_VERSION)
    if version not in SUPPORTED_VERSIONS:
        raise MDLParseError(
            f"Unsupported MDL version {version} "
            f"(this parser supports v{SUPPORTED_VERSIONS.start}-{SUPPORTED_VERSIONS.stop - 1})"
        )

    name = _read_cstring(buf, OFF_NAME)
    warnings: list[str] = []

    # --- cdmaterials (search directories) ---
    numcdtextures = _read_i32(buf, OFF_NUMCDTEXTURES)
    cdtextureindex = _read_i32(buf, OFF_CDTEXTUREINDEX)
    cdmaterials: list[str] = []
    for i in range(numcdtextures):
        entry_off = cdtextureindex + i * 4
        try:
            str_off = _read_i32(buf, entry_off)
            s = _read_cstring(buf, str_off)
        except MDLParseError as e:
            warnings.append(f"Could not read cdmaterials entry {i}: {e}")
            continue
        s = s.replace("\\", "/").strip("/")
        cdmaterials.append(s + "/" if s else "")

    if not cdmaterials:
        cdmaterials = [""]  # fall back to materials/ root only

    # --- texture (material) names ---
    numtextures = _read_i32(buf, OFF_NUMTEXTURES)
    textureindex = _read_i32(buf, OFF_TEXTUREINDEX)
    materials: list[str] = []
    for i in range(numtextures):
        struct_off = textureindex + i * MSTUDIOTEXTURE_SIZE
        try:
            sznameindex = _read_i32(buf, struct_off)
            tex_name = _read_cstring(buf, struct_off + sznameindex)
        except MDLParseError as e:
            warnings.append(f"Could not read texture entry {i}: {e}")
            continue
        tex_name = tex_name.replace("\\", "/").strip("/")
        if tex_name:
            materials.append(tex_name)

    if numtextures > 0 and not materials:
        warnings.append(
            "Header reported textures but none could be read -- "
            "this MDL may use a layout this parser doesn't support."
        )

    return MDLInfo(
        path=path,
        version=version,
        internal_name=name,
        materials=materials,
        cdmaterials=cdmaterials,
        warnings=warnings,
    )
