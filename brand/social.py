"""The GitHub social preview card.

A different job from the Discord banner, and the difference is where it is
seen. The Discord banner sits on a profile somebody already chose to open.
This one is the thumbnail on a link pasted into a chat, and it is competing
with everything else in that channel. It has about a second.

GitHub crops to 1280x640 and shows it at maybe 500 wide in most previews, so
the rule is the same one the avatar taught: it has to work small. That means
the name, one line saying what it is, and nothing else. No screenshot, no
feature list, no three columns of icons.
"""
from PIL import Image, ImageDraw, ImageFont
import pathlib

import final as F
import keystones as K
import wordmarks as W

OUT = pathlib.Path(__file__).parent
FONTS = OUT / "fonts"
SW, SH = 1280, 640
S = 2


def card(title="STEWARD", line="", ground=None, ink=None, mark=True):
    ground = ground or F.PALETTES["limestone"][0]
    ink = ink or F.PALETTES["limestone"][1]
    im = Image.new("RGB", (SW * S, SH * S), ground)
    d = ImageDraw.Draw(im)

    # Stacked from a measured height and then centred, rather than positioned
    # by eye. Guessing leaves the block in the top half with dead space under
    # it, which is what the first version did.
    mark_h = int(180 * S) if mark else 0
    gap_1 = int(46 * S) if mark else 0
    title_h = int(96 * S)
    gap_2 = int(30 * S) if line else 0
    line_h = int(30 * S) if line else 0
    block = mark_h + gap_1 + title_h + gap_2 + line_h
    y = (SH * S - block) // 2

    if mark:
        m = F.avatar(ground, ink, mark_h)
        im.paste(m, (int(SW * S / 2 - mark_h / 2), y))
        y += mark_h + gap_1

    f = W.face("newsreader", int(104 * S), 600)
    W.tracked(d, title, f, ink, SW * S / 2, y + title_h / 2, 14 * S)
    y += title_h + gap_2

    if line:
        sub = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), int(25 * S))
        try:
            sub.set_variation_by_axes([400])
        except Exception:
            pass
        w = d.textlength(line, font=sub)
        # The ink at reduced contrast, so the line reads as secondary without
        # bringing in a third colour.
        soft = tuple(round(i * 0.62 + g * 0.38) for i, g in zip(ink, ground))
        d.text((SW * S / 2 - w / 2, y), line, font=sub, fill=soft)

    return im.resize((SW, SH), Image.LANCZOS)


LINE = "Set up and run a Discord community server from one file"

VARIANTS = {
    "social-limestone": dict(),
    "social-slate": dict(ground=F.PALETTES["slate"][0], ink=F.PALETTES["slate"][1]),
    "social-wordmark-only": dict(mark=False),
}


def sheet():
    """Shown at the width a link preview actually gets, which is the test."""
    pad, gap = 18, 16
    shots = [(n, card(line=LINE, **kw)) for n, kw in VARIANTS.items()]
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    w1, w2 = 640, 320
    H = pad + len(shots) * (w1 // 2 + gap + 20)
    sh = Image.new("RGB", (pad * 2 + w1 + gap + w2, H), (17, 18, 21))
    d = ImageDraw.Draw(sh)
    y = pad
    for name, im in shots:
        d.text((pad, y), f"{name}   (left: 640 wide, right: 320)", font=small,
               fill=(150, 155, 164))
        sh.paste(im.resize((w1, w1 // 2), Image.LANCZOS), (pad, y + 18))
        sh.paste(im.resize((w2, w2 // 2), Image.LANCZOS), (pad + w1 + gap, y + 18))
        y += w1 // 2 + gap + 20
    return sh


if __name__ == "__main__":
    for name, kw in VARIANTS.items():
        card(line=LINE, **kw).save(OUT / f"{name}.png")
    sheet().save(OUT / "social-sheet.png")
    print("wrote", len(VARIANTS), "social cards + social-sheet.png")
