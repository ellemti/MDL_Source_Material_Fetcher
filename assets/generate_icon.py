"""
Generates the app icon and README banner, based on the
"missing-texture checkerboard" concept: the magenta/black checker
pattern is Source Engine's iconic placeholder for a missing texture
-- a fitting mark for a tool whose whole job is finding those files.

  assets/icon.png / icon.ico   -- small app icon (checkerboard only,
                                   simplified so it still reads at 16px)
  assets/banner.png             -- wide banner for the README header /
                                   GitHub social preview, with the full
                                   "MDL / VTF / VMT / ZIP -> ?" concept

Run this if you ever want to regenerate/tweak them:
    python assets/generate_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent
BG = (30, 31, 36)          # matches DARK_STYLE background
MAGENTA = (255, 0, 255)    # Source Engine's missing-texture checker
BLACK_SQ = (20, 20, 22)
GOLD = (196, 142, 39)      # matches the sketch's arrow color
TEXT = (230, 230, 230)
MUTED = (154, 157, 168)


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def draw_checkerboard(draw: ImageDraw.ImageDraw, cx: int, cy: int, half: int):
    """2x2 magenta/black missing-texture checker, centered at (cx, cy)."""
    r = int(half * 0.28)
    quads = [
        (cx - half, cy - half, cx, cy, BLACK_SQ),
        (cx, cy - half, cx + half, cy, MAGENTA),
        (cx - half, cy, cx, cy + half, MAGENTA),
        (cx, cy, cx + half, cy + half, BLACK_SQ),
    ]
    for x0, y0, x1, y1, color in quads:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=color)


import math


def draw_fan_artwork(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, checker_half: float):
    """The checkerboard + 5 converging labeled arrows, sized relative to `size`.
    Shared by the icon and the banner so both stay visually consistent.
    """
    draw_checkerboard(draw, cx, cy, checker_half)

    arrows = [
        # (label, angle_deg, length_frac_of_size, color)
        ("MDL", 205, 0.34, GOLD),
        ("VTF", 165, 0.37, GOLD),
        ("VMT", 130, 0.36, GOLD),
        ("ZIP", 55, 0.34, GOLD),
        ("?", 15, 0.33, MUTED),
    ]
    font_label = _font(max(7, int(size * 0.062)))
    font_q = _font(max(9, int(size * 0.095)))
    line_width = max(2, round(size * 0.024))
    head_len = size * 0.065

    for label, angle, length_frac, color in arrows:
        rad = math.radians(angle)
        length = size * length_frac
        tip_x = cx + math.cos(rad) * (checker_half + size * 0.02)
        tip_y = cy - math.sin(rad) * (checker_half + size * 0.02)
        tail_x = cx + math.cos(rad) * length
        tail_y = cy - math.sin(rad) * length

        draw.line([tail_x, tail_y, tip_x, tip_y], fill=color, width=line_width)
        left_a = rad + math.radians(150)
        right_a = rad - math.radians(150)
        p1 = (tip_x + math.cos(left_a) * head_len, tip_y - math.sin(left_a) * head_len)
        p2 = (tip_x + math.cos(right_a) * head_len, tip_y - math.sin(right_a) * head_len)
        draw.polygon([(tip_x, tip_y), p1, p2], fill=color)

        label_x = tail_x + math.cos(rad) * size * 0.058
        label_y = tail_y - math.sin(rad) * size * 0.058
        font = font_q if label == "?" else font_label
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((label_x - tw / 2 - bbox[0], label_y - th / 2 - bbox[1]), label, fill=TEXT, font=font)


def build_icon(size: int) -> Image.Image:
    """The full logo (checkerboard + arrows + labels), fit into a square
    icon canvas. Rendered once at high resolution and scaled down for
    smaller icon sizes -- at 16-32px the arrow labels will blur into
    illegible flecks, which is expected for a detailed mark shrunk that
    far; the shapes and color pattern still read fine.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = size * 0.18
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG)
    draw_fan_artwork(draw, size * 0.50, size * 0.50, size, checker_half=size * 0.13)
    return img


def build_banner(width: int = 1280, height: int = 720) -> Image.Image:
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    cx, cy = width // 2 + 60, 320
    half = 85
    draw_checkerboard(draw, cx, cy, half)

    # Arrows converging on the checkerboard, matching the sketch's
    # fan-out layout, each labeled with the file type it represents.
    arrows = [
        # (label, angle_deg from checkerboard, length, color)
        ("MDL", 205, 240, GOLD),
        ("VTF", 165, 280, GOLD),
        ("VMT", 130, 270, GOLD),
        ("ZIP", 55, 260, GOLD),
        ("?", 15, 240, MUTED),
    ]
    font_label = _font(28)
    font_q = _font(42)

    for label, angle, length, color in arrows:
        rad = math.radians(angle)
        tip_x = cx + math.cos(rad) * (half + 10)
        tip_y = cy - math.sin(rad) * (half + 10)
        tail_x = cx + math.cos(rad) * length
        tail_y = cy - math.sin(rad) * length

        draw.line([tail_x, tail_y, tip_x, tip_y], fill=color, width=9)
        head_len = 30
        left_a = rad + math.radians(150)
        right_a = rad - math.radians(150)
        p1 = (tip_x + math.cos(left_a) * head_len, tip_y - math.sin(left_a) * head_len)
        p2 = (tip_x + math.cos(right_a) * head_len, tip_y - math.sin(right_a) * head_len)
        draw.polygon([(tip_x, tip_y), p1, p2], fill=color)

        label_x = tail_x + math.cos(rad) * 34
        label_y = tail_y - math.sin(rad) * 34
        font = font_q if label == "?" else font_label
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((label_x - tw / 2 - bbox[0], label_y - th / 2 - bbox[1]), label, fill=TEXT, font=font)

    # Title block, left-aligned, with clear separation from the artwork above
    title_font = _font(56)
    sub_font = _font(23, bold=False)
    draw.text((70, height - 190), "SOURCE MATERIAL FETCHER", fill=TEXT, font=title_font)
    draw.text((70, height - 128), "Finds and packages your model's missing textures", fill=MUTED, font=sub_font)

    return img


def main():
    # Render at a high base resolution for a crisp downscale, then let
    # Pillow generate every smaller ICO size from it (see note above --
    # Pillow only keeps sizes <= the source image, so the source must be
    # at least as large as the biggest size we want).
    icon_source = build_icon(512)
    icon_source.resize((256, 256), Image.LANCZOS).save(OUT_DIR / "icon.png")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    icon_source.save(OUT_DIR / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes])

    banner = build_banner()
    banner.save(OUT_DIR / "banner.png")

    print(f"Wrote {OUT_DIR / 'icon.png'}, {OUT_DIR / 'icon.ico'}, {OUT_DIR / 'banner.png'}")


if __name__ == "__main__":
    main()
