#!/usr/bin/env python3
"""
Genere icon.ico depuis icone.jpg pour RUT Pipeline Windows.
Necessite Pillow (deja present via pdfplumber).
"""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageChops
except ImportError:
    raise SystemExit("Pillow requis : pip install pillow")

_HERE = Path(__file__).parent
_SRC  = _HERE / "icone.jpg"
_OUT  = _HERE / "icon.ico"


def remove_white_background(img: Image.Image, threshold: int = 240) -> Image.Image:
    """Remplace les pixels blancs/quasi-blancs par de la transparence."""
    rgba = img.convert("RGBA")
    r, g, b, _ = rgba.split()

    # Masque : 255 (opaque) si le canal est sous le seuil, 0 (transparent) sinon
    def below(x: int) -> int:
        return 0 if x >= threshold else 255

    mask_r = r.point(below)
    mask_g = g.point(below)
    mask_b = b.point(below)

    # Un pixel est opaque si AU MOINS un canal est coloré (pas blanc)
    alpha = ImageChops.lighter(ImageChops.lighter(mask_r, mask_g), mask_b)
    rgba.putalpha(alpha)
    return rgba


def make_icon(src: Path = _SRC, out: Path = _OUT) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Image source introuvable : {src}")

    img = remove_white_background(Image.open(src))

    sizes  = [256, 128, 64, 48, 32, 16]
    frames = [img.resize((s, s), Image.LANCZOS) for s in sizes]

    frames[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"OK  Icon generated: {out}")


if __name__ == "__main__":
    make_icon()
