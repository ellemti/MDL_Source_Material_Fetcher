"""
tests/test_pipeline.py

Regression tests for the core parsing/resolution pipeline. Uses a
byte-accurate synthetic .mdl (built to match Valve's real studiohdr_t
layout) plus a fake on-disk content root, so these run without
needing any real game files.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from core.mdl_parser import parse_mdl
from core.packager import write_package, zip_package
from core.resolver import resolve_model
from core.vmt_parser import parse_vmt


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


def build_fake_mdl(material_name: str = "body", cdmaterials=("models/player/example/", "")) -> bytes:
    """Builds a minimal but byte-accurate MDL v48 file: real studiohdr_t
    field offsets, one texture entry, and the given cdmaterials search dirs.
    """
    buf = bytearray()
    buf += b"IDST"                              # id            0
    buf += _i32(48)                             # version       4
    buf += _i32(0)                              # checksum      8
    buf += b"test_model".ljust(64, b"\x00")      # name          12
    buf += _i32(0)                              # length        76 (patched later)
    buf += b"\x00" * (12 * 6)                    # 6 Vectors     80 -> 152
    buf += _i32(0)                              # flags         152
    buf += _i32(0) + _i32(0)                    # bones         156
    buf += _i32(0) + _i32(0)                    # bonecontrollers 164
    buf += _i32(0) + _i32(0)                    # hitboxsets    172
    buf += _i32(0) + _i32(0)                    # localanim     180
    buf += _i32(0) + _i32(0)                    # localseq      188
    buf += _i32(0) + _i32(0)                    # activitylistversion/eventsindexed 196
    textureindex_field_off = len(buf) + 4
    buf += _i32(1) + _i32(0)                    # numtextures=1, textureindex (patched) 204
    cdtextureindex_field_off = len(buf) + 4
    buf += _i32(len(cdmaterials)) + _i32(0)      # numcdtextures, cdtextureindex (patched) 212
    buf += _i32(0) + _i32(0) + _i32(0)          # numskinref/numskinfamilies/skinindex 220
    assert len(buf) == 232

    cdtextureindex_value = len(buf)
    buf += _i32(0) * len(cdmaterials)            # placeholder string-offset array

    tex_struct_start = len(buf)
    buf += _i32(0)                              # sznameindex placeholder
    buf += _i32(0) * 15                          # flags/used/unused1/material/clientmaterial/unused[10]
    assert len(buf) - tex_struct_start == 64

    cd_str_offsets = []
    for cd in cdmaterials:
        cd_str_offsets.append(len(buf))
        buf += cd.encode("utf-8") + b"\x00"

    tex_name_off = len(buf)
    buf += material_name.encode("utf-8") + b"\x00"

    for i, off in enumerate(cd_str_offsets):
        struct.pack_into("<i", buf, cdtextureindex_value + i * 4, off)
    struct.pack_into("<i", buf, cdtextureindex_field_off, cdtextureindex_value)
    struct.pack_into("<i", buf, textureindex_field_off, tex_struct_start)
    struct.pack_into("<i", buf, tex_struct_start, tex_name_off - tex_struct_start)
    struct.pack_into("<i", buf, 76, len(buf))

    return bytes(buf)


@pytest.fixture
def fake_mdl_path(tmp_path: Path) -> Path:
    p = tmp_path / "fake.mdl"
    p.write_bytes(build_fake_mdl())
    return p


def test_mdl_parser_reads_real_header_layout(fake_mdl_path: Path):
    info = parse_mdl(fake_mdl_path)
    assert info.version == 48
    assert info.materials == ["body"]
    assert info.cdmaterials == ["models/player/example/", ""]
    assert not info.warnings


def test_vmt_parser_extracts_multiple_texture_params():
    vmt = """
    VertexLitGeneric
    {
        "$basetexture" "models/player/example/body"
        "$bumpmap" "models/player/example/body_normal"
        "$envmap" "env_cubemap"
    }
    """
    info = parse_vmt(vmt)
    assert info.shader == "VertexLitGeneric"
    assert "models/player/example/body" in info.textures
    assert "models/player/example/body_normal" in info.textures
    assert "env_cubemap" not in info.textures  # special keyword, not a real texture path


def test_vmt_parser_follows_patch_include():
    vmt = """
    patch
    {
        include "materials/models/player/example/body_ref.vmt"
        insert { "$color" "[1 1 1]" }
    }
    """
    info = parse_vmt(vmt)
    assert info.is_patch
    assert info.include_path == "models/player/example/body_ref"


def test_resolve_and_package_end_to_end(tmp_path: Path, fake_mdl_path: Path):
    root = tmp_path / "fakegame"
    mat_dir = root / "materials/models/player/example"
    mat_dir.mkdir(parents=True)
    (mat_dir / "body.vmt").write_text(
        'VertexLitGeneric { "$basetexture" "models/player/example/body" }'
    )
    (mat_dir / "body.vtf").write_bytes(b"FAKEVTF")

    mdl = parse_mdl(fake_mdl_path)
    result = resolve_model(mdl, [root])

    assert len(result.found) == 2  # body.vmt + body.vtf
    assert not result.missing

    out_dir = tmp_path / "out"
    written = write_package(result.found, out_dir)
    zip_path = zip_package(out_dir, tmp_path / "package.zip", written)

    assert zip_path.exists()
    assert len(written) == 2


def test_resolve_reports_missing_material(tmp_path: Path, fake_mdl_path: Path):
    root = tmp_path / "emptygame"
    root.mkdir()
    mdl = parse_mdl(fake_mdl_path)
    result = resolve_model(mdl, [root])
    assert not result.found
    assert result.missing == ["materials/models/player/example/body.vmt"]


def test_updater_version_parsing():
    from core.updater import _parse_version
    assert _parse_version("v1.2.3") == (1, 2, 3)
    assert _parse_version("0.1.0") == (0, 1, 0)
    assert _parse_version("v2.0") < _parse_version("v2.0.1")
    assert _parse_version("v0.1.0") == _parse_version("0.1.0")


def test_pipeline_resolves_multiple_models_concurrently(tmp_path: Path):
    from core.pipeline import run_pipeline

    root = tmp_path / "fakegame"
    mat_dir = root / "materials/models/player/example"
    mat_dir.mkdir(parents=True)
    (mat_dir / "body.vmt").write_text(
        'VertexLitGeneric { "$basetexture" "models/player/example/body" }'
    )
    (mat_dir / "body.vtf").write_bytes(b"FAKEVTF")

    mdl_paths = []
    for name in ("a.mdl", "b.mdl", "c.mdl"):
        p = tmp_path / name
        p.write_bytes(build_fake_mdl())
        mdl_paths.append(p)

    seen_indices = []
    result = run_pipeline(
        mdl_paths, [root], do_package=False, output_dir=None,
        model_done_cb=lambda i, report: seen_indices.append(i),
    )

    assert len(result.model_reports) == 3
    assert sorted(seen_indices) == [0, 1, 2]
    for report in result.model_reports:
        assert report.error is None
        assert report.found_count == 2  # body.vmt + body.vtf, per model
    # combined_found is deduped by absolute source path, so 2 files total
    # even though all 3 models reference the same material.
    assert len(result.combined_found) == 2


def test_pipeline_one_bad_model_does_not_abort_the_batch(tmp_path: Path, fake_mdl_path: Path):
    from core.pipeline import run_pipeline

    root = tmp_path / "fakegame"
    mat_dir = root / "materials/models/player/example"
    mat_dir.mkdir(parents=True)
    (mat_dir / "body.vmt").write_text(
        'VertexLitGeneric { "$basetexture" "models/player/example/body" }'
    )
    (mat_dir / "body.vtf").write_bytes(b"FAKEVTF")

    bad_mdl = tmp_path / "corrupt.mdl"
    bad_mdl.write_bytes(b"NOTAMDLFILE")

    result = run_pipeline([fake_mdl_path, bad_mdl], [root], do_package=False, output_dir=None)

    reports_by_name = {r.path.name: r for r in result.model_reports}
    assert reports_by_name["fake.mdl"].error is None
    assert reports_by_name["fake.mdl"].found_count == 2
    assert reports_by_name["corrupt.mdl"].error is not None


def test_pipeline_packages_when_requested(tmp_path: Path, fake_mdl_path: Path):
    from core.pipeline import run_pipeline

    root = tmp_path / "fakegame"
    mat_dir = root / "materials/models/player/example"
    mat_dir.mkdir(parents=True)
    (mat_dir / "body.vmt").write_text(
        'VertexLitGeneric { "$basetexture" "models/player/example/body" }'
    )
    (mat_dir / "body.vtf").write_bytes(b"FAKEVTF")

    out_dir = tmp_path / "out"
    result = run_pipeline([fake_mdl_path], [root], do_package=True, output_dir=out_dir)

    assert result.zip_path is not None
    assert result.zip_path.exists()
    assert result.written_count == 2
