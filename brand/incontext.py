"""The candidates in a fake member list, which is the test that matters.

Judging an avatar on its own says whether it is a good drawing. It does not
say whether you can find it, and finding it is the whole job: Steward sits in
a column of thirty other circles, most of which are dark and saturated because
that is what bot and player avatars look like.
"""
from PIL import Image, ImageDraw, ImageFont
import pathlib

import keystones as K
import final as F

OUT = pathlib.Path(__file__).parent
FONTS = OUT / "fonts"

LIST_BG = (43, 45, 49)          # Discord member list
CHAT_BG = (49, 51, 56)          # Discord message area
NAME = (148, 155, 164)

CANDIDATES = ["limestone", "oxblood", "brass", "slate"]

# What it is actually sitting next to. Discord's own defaults plus the sort of
# thing people and bots pick, weighted dark because most of them are.
NEIGHBOURS = [(88, 101, 242), (35, 165, 89), (237, 66, 69), (60, 63, 70),
              (235, 69, 158), (46, 51, 58), (242, 156, 56), (74, 79, 88),
              (32, 34, 39), (110, 118, 129)]


def blob(size, colour):
    im = Image.new("RGB", (size * 4, size * 4), colour)
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    return im.resize((size, size), Image.LANCZOS), m.resize((size, size), Image.LANCZOS)


def member_list(name, w=210, rows=11, slot=5, av=32):
    ground, ink = F.PALETTES[name]
    steward = F.avatar(ground, ink, 256)
    rowh, pad = 42, 14
    im = Image.new("RGB", (w, pad * 2 + rows * rowh), LIST_BG)
    d = ImageDraw.Draw(im)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    for r in range(rows):
        y = pad + r * rowh
        if r == slot:
            t, m = K.circle(steward, av)
            im.paste(t, (pad, y), m)
            d.text((pad + av + 12, y + 9), "Steward", font=small, fill=(219, 222, 225))
        else:
            t, m = blob(av, NEIGHBOURS[r % len(NEIGHBOURS)])
            im.paste(t, (pad, y), m)
            # A grey bar rather than a fake name, so nothing competes for the eye.
            d.rounded_rectangle([pad + av + 12, y + 12, pad + av + 12 + 62 + (r * 13) % 40,
                                 y + 21], radius=4, fill=(60, 63, 70))
    return im


def message_row(name, w=470, av=40):
    """The other place it lives: beside something it just said."""
    ground, ink = F.PALETTES[name]
    im = Image.new("RGB", (w, 96), CHAT_BG)
    d = ImageDraw.Draw(im)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 13)
    t, m = K.circle(F.avatar(ground, ink, 256), av)
    im.paste(t, (16, 16), m)
    d.text((16 + av + 14, 17), "Steward", font=small, fill=(242, 243, 245))
    d.rounded_rectangle([16 + av + 14, 40, w - 40, 50], radius=4, fill=(63, 66, 73))
    d.rounded_rectangle([16 + av + 14, 58, w - 150, 68], radius=4, fill=(63, 66, 73))
    return im


def sheet():
    pad, gap, lab = 20, 18, 24
    lists = [member_list(c) for c in CANDIDATES]
    rows = [message_row(c) for c in CANDIDATES]
    lw, lh = lists[0].size
    mw, mh = rows[0].size
    W = pad * 2 + len(CANDIDATES) * lw + (len(CANDIDATES) - 1) * gap
    H = pad + lab + lh + 34 + len(CANDIDATES) * (mh + gap) + pad
    sh = Image.new("RGB", (W, H), (17, 18, 21))
    d = ImageDraw.Draw(sh)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    for i, c in enumerate(CANDIDATES):
        x = pad + i * (lw + gap)
        d.text((x, pad), c, font=small, fill=(180, 184, 190))
        sh.paste(lists[i], (x, pad + lab))
    y = pad + lab + lh + 34
    for i, c in enumerate(CANDIDATES):
        d.text((pad, y - 15), c, font=small, fill=(180, 184, 190))
        sh.paste(rows[i], (pad, y))
        y += mh + gap
    return sh


if __name__ == "__main__":
    sheet().save(OUT / "in-context-sheet.png")
    print("wrote in-context-sheet.png")
