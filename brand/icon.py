"""Windows icons, cut from the same mark as the Discord avatar.

An .ico is several images in one file and Windows picks by context: 256 for
the large-icon view, 32 for the taskbar, 16 for the title bar and the Start
Menu list. Each one is rendered at its own size rather than letting Windows
scale a single big image down, because the whole point of this mark is that it
was drawn to survive being small.

Not circle-cropped. That crop is Discord's, and Windows draws icons square.
"""
from PIL import Image
import pathlib

import keystones as K
import final as F

OUT = pathlib.Path(__file__).parent
SIZES = [256, 128, 64, 48, 40, 32, 24, 20, 16]


def frames(palette: str):
    ground, ink = F.PALETTES[palette]
    return [F.avatar(ground, ink, s) for s in SIZES]


def write(palette: str, name: str):
    imgs = frames(palette)
    # Pillow writes the largest image and stores the rest as additional frames.
    imgs[0].save(OUT / name, format="ICO",
                 sizes=[(s, s) for s in SIZES], append_images=imgs[1:])
    return OUT / name


def contact():
    """The icon at the sizes Windows actually uses, on both chrome colours."""
    pad, gap = 20, 18
    row = sum(SIZES[2:]) + gap * len(SIZES[2:])
    im = Image.new("RGB", (pad * 2 + row, pad * 3 + 64 * 2), (32, 32, 32))
    for band, bg in enumerate(((32, 32, 32), (243, 243, 243))):
        top = pad + band * (64 + pad)
        im.paste(Image.new("RGB", (im.width, 64 + 12), bg), (0, top - 6))
        x = pad
        for s in SIZES[2:]:
            ground, ink = F.PALETTES["limestone"]
            im.paste(F.avatar(ground, ink, s), (x, top + (64 - s) // 2))
            x += s + gap
    return im


if __name__ == "__main__":
    print("wrote", write("limestone", "steward.ico").name)
    print("wrote", write("slate", "steward-slate.ico").name)
    contact().save(OUT / "icon-contact-sheet.png")
    print("wrote icon-contact-sheet.png")
