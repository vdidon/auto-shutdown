"""Generate the executable's icon, with no external dependency.

Produces `assets/auto-shutdown.ico`: a disc bearing the universal power
symbol. The resulting file is versioned, so building the executable does not
need this tool.

The ICO format is written by hand: an `ICONDIR` header, one `ICONDIRENTRY` per
size, then for each image a `BITMAPINFOHEADER` of double height followed by
the BGRA pixels stored bottom-up and an AND mask left at zero — the alpha
channel already carries the transparency.

Usage:
    uv run python tools/make_ico.py
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

SIZES = (16, 32, 48, 256)

#: The ICO format encodes each dimension in a single byte; the value 0 there
#: conventionally means 256 pixels.
ICO_DIMENSION_LIMIT = 256
OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "auto-shutdown.ico"

#: Dark slate for the disc, off-white for the symbol. This pair stays legible
#: on both a light and a dark taskbar.
DISC_COLOR = (46, 60, 74)
GLYPH_COLOR = (245, 247, 250)

#: Half-opening of the ring's top gap, in radians.
GAP_HALF_ANGLE = math.radians(34)

#: Width of the anti-aliased edge, in pixels. It must not grow with the image:
#: edges blend over one pixel at any size, otherwise large sizes look blurred.
FEATHER = 1.0


def _coverage(distance: float, radius: float, feather: float) -> float:
    """Fraction of a pixel covered by a disc of radius `radius`."""
    return max(0.0, min(1.0, (radius - distance) / feather + 0.5))


def _glyph_alpha(x: float, y: float, size: int) -> float:
    """Opacity of the power symbol at the given point.

    The coordinate system is visual: `y` grows downwards, the origin is the
    top-left corner.
    """
    centre = (size - 1) / 2.0
    dx = x - centre
    dy = y - centre
    ring_radius = size * 0.26
    thickness = max(1.6, size * 0.105)
    feather = FEATHER

    # Ring, minus the top gap through which the bar passes.
    distance = math.hypot(dx, dy)
    ring = _coverage(abs(distance - ring_radius), thickness / 2.0, feather)
    if dy < 0 and abs(math.atan2(dx, -dy)) < GAP_HALF_ANGLE:
        ring = 0.0

    # Vertical bar, from the top of the ring towards the centre.
    bar_top = centre - size * 0.36
    bar_bottom = centre - size * 0.06
    horizontal = _coverage(abs(dx), thickness / 2.0, feather)
    if y < bar_top:
        vertical = _coverage(bar_top - y, 0.0, feather)
    elif y > bar_bottom:
        vertical = _coverage(y - bar_bottom, 0.0, feather)
    else:
        vertical = 1.0
    bar = horizontal * vertical

    return max(ring, bar)


def _render(size: int) -> bytes:
    """Render a BGRA image stored bottom-up."""
    centre = (size - 1) / 2.0
    disc_radius = size / 2.0 - max(0.5, size / 32.0)
    feather = FEATHER
    pixels = bytearray(size * size * 4)

    for row in range(size):
        y = size - 1 - row  # rows are stored bottom-up
        for x in range(size):
            disc = _coverage(math.hypot(x - centre, y - centre), disc_radius, feather)
            if disc <= 0.0:
                continue
            glyph = _glyph_alpha(x, y, size)

            # The symbol is composited over the disc, and the result is then
            # limited by the disc coverage: the glyph never overflows.
            red = DISC_COLOR[0] + (GLYPH_COLOR[0] - DISC_COLOR[0]) * glyph
            green = DISC_COLOR[1] + (GLYPH_COLOR[1] - DISC_COLOR[1]) * glyph
            blue = DISC_COLOR[2] + (GLYPH_COLOR[2] - DISC_COLOR[2]) * glyph

            offset = (row * size + x) * 4
            pixels[offset] = round(blue * disc)
            pixels[offset + 1] = round(green * disc)
            pixels[offset + 2] = round(red * disc)
            pixels[offset + 3] = round(255 * disc)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,  # biSize
        size,  # biWidth
        size * 2,  # biHeight: colour plane then AND mask
        1,  # biPlanes
        32,  # biBitCount
        0,  # biCompression
        size * size * 4,  # biSizeImage
        0,
        0,
        0,
        0,
    )
    mask_row = ((size + 31) // 32) * 4  # mask rows aligned to 4 bytes
    return header + bytes(pixels) + bytes(mask_row * size)


def build_ico(sizes: tuple[int, ...] = SIZES) -> bytes:
    images = [_render(size) for size in sizes]
    offset = 6 + 16 * len(images)

    directory = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for size, image in zip(sizes, images, strict=True):
        directory += struct.pack(
            "<BBBBHHII",
            size if size < ICO_DIMENSION_LIMIT else 0,
            size if size < ICO_DIMENSION_LIMIT else 0,
            0,  # palette unused
            0,
            1,  # planes
            32,  # bits per pixel
            len(image),
            offset,
        )
        offset += len(image)

    return bytes(directory) + b"".join(images)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = build_ico()
    OUTPUT.write_bytes(data)
    print(f"{OUTPUT} — {len(data) / 1024:.0f} KiB, sizes {', '.join(map(str, SIZES))}")


if __name__ == "__main__":
    main()
