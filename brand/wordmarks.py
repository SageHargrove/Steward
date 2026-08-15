"""STEWARD set in every OFL face worth considering, at real banner size.

The banner is 680x240 and Discord lays the bot's name over the lower left, so
the word sits high and centred. Letter-spacing is generous because a short
word set tight reads as a word and set loose reads as a mark.
"""
from PIL import Image, ImageDraw, ImageFont
import pathlib

OUT = pathlib.Path(r"C:\CommunityOps\brand")
FONTS = OUT / "fonts"
BW, BH = 680, 240
S = 4
GROUND = (34, 37, 43)
INK = (233, 226, 212)

# face -> (point size at 1x, tracking at 1x, weight to ask a variable font for)
FACES = {
    "cinzel":       (62, 14, 600),
    "marcellus":    (68, 14, None),
    "dmserif":      (70, 10, None),
    "youngserif":   (64, 10, None),
    "instrument":   (78, 12, None),
    "fraunces":     (66, 10, 600),
    "playfair":     (70, 12, 600),
    "spectral":     (62, 12, None),
    "spacegrotesk": (60, 18, 600),
    "archivo":      (58, 20, 700),
    "eb":           (70, 14, 600),
    "newsreader":   (68, 12, 600),
}


def face(name, size, weight):
    f = ImageFont.truetype(str(FONTS / f"{name}.ttf"), size)
    if weight:
        try:
            axes = f.get_variation_axes()
            vals = []
            for a in axes:
                tag = (a.get("name") or b"").decode() if isinstance(
                    a.get("name"), bytes) else str(a.get("name"))
                if "wght" in tag or "Weight" in tag:
                    vals.append(min(weight, a["maximum"]))
                elif "opsz" in tag or "Optical" in tag:
                    vals.append(a["maximum"])
                elif "WONK" in tag:
                    vals.append(a["maximum"])       # Fraunces' one odd axis
                elif "SOFT" in tag:
                    vals.append(a["minimum"])
                else:
                    vals.append(a["default"])
            f.set_variation_by_axes(vals)
        except Exception as e:
            print("   (no axes on", name, e, ")")
    return f


def tracked(d, text, f, fill, cx, cy, tracking):
    widths = [d.textlength(ch, font=f) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    box = d.textbbox((0, 0), text, font=f)
    x, y = cx - total / 2, cy - (box[3] + box[1]) / 2
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=f, fill=fill)
        x += w + tracking
    return total


def banner(name, ground=GROUND, ink=INK):
    size, track, weight = FACES[name]
    im = Image.new("RGB", (BW * S, BH * S), ground)
    d = ImageDraw.Draw(im)
    f = face(name, size * S, weight)
    # High, not centred: Discord's own name plate sits across the bottom.
    tracked(d, "STEWARD", f, ink, BW * S / 2, BH * S * 0.42, track * S)
    return im.resize((BW, BH), Image.LANCZOS)


def sheet():
    pad, gap, lab = 20, 12, 22
    rows = len(FACES)
    sh = Image.new("RGB", (pad * 2 + BW, pad + rows * (BH + gap + lab)),
                   (17, 18, 21))
    d = ImageDraw.Draw(sh)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    for i, name in enumerate(FACES):
        y = pad + i * (BH + gap + lab)
        d.text((pad, y), name, font=small, fill=(150, 155, 164))
        sh.paste(banner(name), (pad, y + lab))
    return sh


sheet().save(OUT / "wordmarks-sheet.png")
print("wrote", len(FACES), "wordmarks")
