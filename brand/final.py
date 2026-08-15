"""The chosen mark and wordmark, in colourways, then cut at delivery sizes.

Mark is `gate3` from keystones.py: an arched gateway of three voussoirs on two
piers. It won because the arch silhouette is still unmistakable at 20 pixels
while the two joints between the stones are still visible, which is the most
detail that survives at that size.

Wordmark is Newsreader at weight 600, SIL Open Font License, so it is clear
for commercial use and for embedding in a logo.
"""
from PIL import Image, ImageDraw, ImageFont
import pathlib

import keystones as K
import wordmarks as W

OUT = pathlib.Path(__file__).parent
FONTS = OUT / "fonts"
MARK = K.gate3
FACE = "newsreader"

# name -> (ground, ink). Violet is gone: it was doing nothing the greys were
# not, and every second dev tool is violet.
PALETTES = {
    "limestone":  ((232, 225, 211), (42, 46, 54)),
    "slate":      ((34, 37, 43), (233, 226, 212)),
    "brass":      ((26, 29, 35), (201, 162, 39)),
    "ink-brass":  ((201, 162, 39), (34, 31, 26)),
    "oxblood":    ((74, 35, 40), (237, 228, 212)),
    "moss":       ((46, 58, 50), (228, 222, 207)),
    "terracotta": ((181, 83, 60), (243, 231, 216)),
    "teal":       ((29, 58, 62), (228, 217, 195)),
}


def avatar(ground, ink, size=1024):
    """Rendered at the size asked for rather than scaled up from 512, because
    an upscale puts soft edges back into the one mark that needs hard ones."""
    old_n, old_s = K.N, K.S
    K.N, K.S = size, max(2, 4096 // size)
    try:
        return K.render(MARK, ground=ground, ink=ink)
    finally:
        K.N, K.S = old_n, old_s


def banner(ground, ink, mark=False):
    size, track, weight = W.FACES[FACE]
    S = W.S
    im = Image.new("RGB", (W.BW * S, W.BH * S), ground)
    d = ImageDraw.Draw(im)
    f = W.face(FACE, size * S, weight)
    # Discord lays the bot's own name across the lower left, so the word sits
    # high and the bottom third is left empty on purpose.
    W.tracked(d, "STEWARD", f, ink, W.BW * S / 2, W.BH * S * 0.42, track * S)
    out = im.resize((W.BW, W.BH), Image.LANCZOS)
    if mark:
        m = K.render(MARK, ground=ground, ink=ink).resize((120, 120), Image.LANCZOS)
        out.paste(m, (40, 60))
    return out


def sheet():
    """Every palette, with the avatar shown at the sizes it is really seen."""
    pad, gap, lab = 20, 14, 22
    rowh = W.BH + gap + lab
    W_ = pad * 2 + W.BW + gap + 96 + gap + 40 + gap + 20 + 40
    H = pad + len(PALETTES) * rowh
    sh = Image.new("RGB", (W_, H), (17, 18, 21))
    d = ImageDraw.Draw(sh)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    for i, (name, (ground, ink)) in enumerate(PALETTES.items()):
        y = pad + i * rowh
        d.text((pad, y), f"{name}   #{ground[0]:02X}{ground[1]:02X}{ground[2]:02X}"
                         f" / #{ink[0]:02X}{ink[1]:02X}{ink[2]:02X}",
               font=small, fill=(150, 155, 164))
        sh.paste(banner(ground, ink), (pad, y + lab))
        av, x = avatar(ground, ink, 512), pad + W.BW + gap
        for s in (96, 40, 20):
            t, m = K.circle(av, s)
            sh.paste(t, (x, y + lab + (W.BH - s) // 2), m)
            x += s + gap
    return sh


def contact(name):
    """The avatar at every size it is really seen, on both Discord themes."""
    ground, ink = PALETTES[name]
    av = avatar(ground, ink, 512)
    SIZES, pad, gap = [512, 96, 40, 20], 28, 30
    row = sum(SIZES) + gap * len(SIZES)
    im = Image.new("RGB", (pad * 2 + row, pad * 2 + 512 + 60 + 512 + 40),
                   (49, 51, 56))                       # Discord dark chrome
    d = ImageDraw.Draw(im)
    d.rectangle([0, pad + 512 + 60, im.width, im.height], fill=(255, 255, 255))
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 13)
    for band, top in ((0, pad), (1, pad + 512 + 60 + 20)):
        d.text((pad, top - 18), "#313338 (dark)" if not band else "#FFFFFF (light)",
               font=small, fill=(150, 155, 164) if not band else (120, 124, 132))
        x = pad
        for s in SIZES:
            t, m = K.circle(av, s)
            im.paste(t, (x, top + (512 - s) // 2), m)
            d.text((x, top + 512 // 2 + s // 2 + 8), f"{s}px", font=small,
                   fill=(120, 126, 136) if not band else (140, 144, 150))
            x += s + gap
    return im


if __name__ == "__main__":
    sheet().save(OUT / "colourways-sheet.png")
    for name, (ground, ink) in PALETTES.items():
        avatar(ground, ink, 512).save(OUT / f"cw-avatar-{name}.png")
        banner(ground, ink).save(OUT / f"cw-banner-{name}.png")

    # The two that ship. Limestone is the default; slate is there for anyone
    # who wants the avatar to sit back rather than stand out.
    for tag, pal in (("", "limestone"), ("-slate", "slate")):
        g, i = PALETTES[pal]
        avatar(g, i, 1024).save(OUT / f"steward-avatar{tag}.png")
        banner(g, i).save(OUT / f"steward-banner{tag}.png")
    contact("limestone").save(OUT / "steward-contact-sheet.png")
    print("wrote", len(PALETTES), "colourways + delivery files")
