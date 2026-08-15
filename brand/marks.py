"""Avatar directions for Steward, drawn to survive 20 pixels.

Everything is drawn on a 0..1 grid at 8x and downsampled, because the edges
are what died last time. No line art: every mark here is a filled shape or a
letterform, which is all that reads in a member list.
"""
from PIL import Image, ImageDraw, ImageFont
import pathlib

SP = pathlib.Path(__file__).parent
OUT = pathlib.Path(r"C:\CommunityOps\brand")
FONTS = OUT / "fonts"

N = 512
S = 8                       # supersample
GROUND = (34, 37, 43)       # slate, deliberately not violet
INK = (233, 226, 212)       # warm bone


def rect(d, x0, y0, x1, y1, fill):
    d.rectangle([x0 * N * S, y0 * N * S, x1 * N * S, y1 * N * S], fill=fill)


def poly(d, pts, fill):
    d.polygon([(x * N * S, y * N * S) for x, y in pts], fill=fill)


def bar(d, x0, y0, x1, y1, w, fill):
    d.line([(x0 * N * S, y0 * N * S), (x1 * N * S, y1 * N * S)],
           fill=fill, width=int(w * N * S))


# --------------------------------------------------------------- the marks

def tally(d, ink, ground):
    """Four strokes and the fifth laid across them. Steward counts things;
    this is the oldest mark for counting there is."""
    # A gap under 1.5px at 20 wide closes up, which is 0.075 of the width, so
    # the strokes and the gaps between them are both that and no thinner.
    for x in (0.20, 0.35, 0.50, 0.65):
        rect(d, x, 0.26, x + 0.075, 0.74, ink)
    bar(d, 0.155, 0.775, 0.815, 0.225, 0.075, ink)


def arch(d, ink, ground):
    """A gateway, held in the negative space of a solid block."""
    rect(d, 0.22, 0.20, 0.78, 0.80, ink)
    r, cy = 0.145, 0.455
    rect(d, 0.355, cy, 0.645, 0.805, ground)
    d.ellipse([(0.5 - r) * N * S, (cy - r) * N * S,
               (0.5 + r) * N * S, (cy + r) * N * S], fill=ground)


def column(d, ink, ground):
    """A steward keeps a house. This is the house reduced to one member."""
    rect(d, 0.24, 0.21, 0.76, 0.315, ink)
    rect(d, 0.415, 0.315, 0.585, 0.685, ink)
    rect(d, 0.22, 0.685, 0.78, 0.79, ink)


def keystone(d, ink, ground):
    """The stone that stops the arch falling down, with its neighbours."""
    poly(d, [(0.385, 0.24), (0.615, 0.24), (0.575, 0.76), (0.425, 0.76)], ink)
    poly(d, [(0.16, 0.24), (0.355, 0.24), (0.395, 0.76), (0.20, 0.76)], ink)
    poly(d, [(0.645, 0.24), (0.84, 0.24), (0.80, 0.76), (0.605, 0.76)], ink)


def sbar(d, ink, ground):
    """A letterform has to earn it. This one is cut through, the way a
    tally is cut through, so it is a mark before it is a letter."""
    f = ImageFont.truetype(str(FONTS / "dmserif.ttf"), int(0.86 * N * S))
    box = d.textbbox((0, 0), "S", font=f)
    d.text((N * S / 2 - (box[2] + box[0]) / 2,
            N * S / 2 - (box[3] + box[1]) / 2), "S", font=f, fill=ink)
    rect(d, 0.10, 0.455, 0.90, 0.545, ink)


def stack(d, ink, ground):
    """Three steps. The bot hands out levels; this is what that looks like
    when you take everything decorative off it."""
    rect(d, 0.16, 0.58, 0.40, 0.82, ink)
    rect(d, 0.42, 0.36, 0.66, 0.60, ink)
    rect(d, 0.68, 0.14, 0.92, 0.38, ink)


MARKS = [("tally", tally), ("arch", arch), ("column", column),
         ("keystone", keystone), ("s-cut", sbar), ("stack", stack)]


def render(fn, ground=GROUND, ink=INK):
    big = Image.new("RGB", (N * S, N * S), ground)
    fn(ImageDraw.Draw(big), ink, ground)
    return big.resize((N, N), Image.LANCZOS)


def circle(im, size):
    """As Discord shows it: cropped to a circle, at the size it is really seen."""
    t = im.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    return t, mask.resize((size, size), Image.LANCZOS)


def sheet():
    SIZES = [128, 96, 40, 20]
    pad, gap, labelw = 22, 26, 96
    rowh = 128 + 34
    darkw = sum(SIZES) + gap * len(SIZES)
    W = pad * 2 + labelw + darkw + 40 + 96 + gap + 40 + gap
    H = pad * 2 + 30 + len(MARKS) * rowh
    sh = Image.new("RGB", (W, H), (17, 18, 21))
    d = ImageDraw.Draw(sh)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    try:
        small.set_variation_by_axes([500])
    except Exception:
        pass

    lightx = pad + labelw + darkw + 40
    d.rectangle([lightx - 14, pad + 24, W - pad + 6, H - pad], fill=(255, 255, 255))
    d.text((pad + labelw, pad + 6), "on Discord dark", font=small, fill=(120, 126, 136))
    d.text((lightx, pad + 6), "on light", font=small, fill=(120, 126, 136))

    x = pad + labelw
    for s in SIZES:
        d.text((x, pad + 24 - 0), f"{s}px", font=small, fill=(90, 95, 104))
        x += s + gap

    for i, (name, fn) in enumerate(MARKS):
        y = pad + 46 + i * rowh
        d.text((pad, y + 50), name, font=small, fill=(200, 196, 190))
        im = render(fn)
        x = pad + labelw
        for s in SIZES:
            t, m = circle(im, s)
            sh.paste(t, (x, y + (128 - s) // 2), m)
            x += s + gap
        # same mark on a light page, ground and ink swapped
        x = lightx
        inv = render(fn, ground=(247, 246, 244), ink=(38, 41, 48))
        for s in (96, 40):
            t, m = circle(inv, s)
            sh.paste(t, (x, y + (128 - s) // 2), m)
            x += s + gap
    return sh


for name, fn in MARKS:
    render(fn).save(OUT / f"mark-{name}.png")
sheet().save(OUT / "marks-sheet.png")
print("wrote", len(MARKS), "marks + marks-sheet.png")
