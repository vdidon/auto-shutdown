"""Génère l'icône de l'exécutable, sans dépendance externe.

Produit `assets/auto-shutdown.ico` : un disque portant le symbole universel de
mise en marche. Le fichier résultant est versionné, si bien que la construction
de l'exécutable n'a pas besoin de cet outil.

Le format ICO est écrit à la main : un en-tête `ICONDIR`, une entrée
`ICONDIRENTRY` par taille, puis pour chaque image un `BITMAPINFOHEADER` de
hauteur double suivi des pixels BGRA rangés du bas vers le haut et d'un masque
AND laissé à zéro — la couche alpha porte déjà la transparence.

Usage :
    uv run python tools/make_ico.py
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

SIZES = (16, 32, 48, 256)

#: Le format ICO code chaque dimension sur un seul octet ; la valeur 0 y désigne
#: conventionnellement 256 pixels.
ICO_DIMENSION_LIMIT = 256
OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "auto-shutdown.ico"

#: Ardoise sombre pour le disque, blanc cassé pour le symbole. Ce couple reste
#: lisible aussi bien sur une barre des tâches claire que sombre.
DISC_COLOR = (46, 60, 74)
GLYPH_COLOR = (245, 247, 250)

#: Demi-ouverture de l'échancrure supérieure de l'anneau, en radians.
GAP_HALF_ANGLE = math.radians(34)


def _coverage(distance: float, radius: float, feather: float) -> float:
    """Fraction d'un pixel couverte par un disque de rayon `radius`."""
    return max(0.0, min(1.0, (radius - distance) / feather + 0.5))


def _glyph_alpha(x: float, y: float, size: int) -> float:
    """Opacité du symbole de mise en marche au point donné.

    Le repère est visuel : `y` croît vers le bas, l'origine est le coin
    supérieur gauche.
    """
    centre = (size - 1) / 2.0
    dx = x - centre
    dy = y - centre
    ring_radius = size * 0.26
    thickness = max(1.6, size * 0.105)
    feather = max(0.8, size / 32.0)

    # Anneau, moins l'échancrure du haut par laquelle passe la barre.
    distance = math.hypot(dx, dy)
    ring = _coverage(abs(distance - ring_radius), thickness / 2.0, feather)
    if dy < 0 and abs(math.atan2(dx, -dy)) < GAP_HALF_ANGLE:
        ring = 0.0

    # Barre verticale, du sommet de l'anneau vers le centre.
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
    """Rend une image BGRA rangée du bas vers le haut."""
    centre = (size - 1) / 2.0
    disc_radius = size / 2.0 - max(0.5, size / 32.0)
    feather = max(0.8, size / 24.0)
    pixels = bytearray(size * size * 4)

    for row in range(size):
        y = size - 1 - row  # les lignes sont stockées du bas vers le haut
        for x in range(size):
            disc = _coverage(math.hypot(x - centre, y - centre), disc_radius, feather)
            if disc <= 0.0:
                continue
            glyph = _glyph_alpha(x, y, size)

            # Le symbole est composé par-dessus le disque, le tout étant ensuite
            # limité par la couverture du disque : le glyphe ne déborde jamais.
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
        size * 2,  # biHeight : plan couleur puis masque AND
        1,  # biPlanes
        32,  # biBitCount
        0,  # biCompression
        size * size * 4,  # biSizeImage
        0,
        0,
        0,
        0,
    )
    mask_row = ((size + 31) // 32) * 4  # lignes du masque alignées sur 4 octets
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
            0,  # palette non utilisée
            0,
            1,  # plans
            32,  # bits par pixel
            len(image),
            offset,
        )
        offset += len(image)

    return bytes(directory) + b"".join(images)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = build_ico()
    OUTPUT.write_bytes(data)
    print(f"{OUTPUT} — {len(data) / 1024:.0f} Kio, tailles {', '.join(map(str, SIZES))}")


if __name__ == "__main__":
    main()
