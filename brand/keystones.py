"""Variations on the keystone, to find out which one reads as an arch.

The first version was three trapezoids side by side, which is a shape but not
a thing. Real voussoirs radiate from the centre of the arch they belong to, so
these are built from that centre outward and the top and bottom edges follow
the curve rather than cutting straight across.

Same rule as before: drawn at 8x and downsampled, judged at 20 pixels.
"""
from PIL import Image, ImageDraw, ImageFont
import math, pathlib

OUT = pathlib.Path(__file__).parent
FONTS = OUT / "fonts"

N, S = 512, 8
GROUND = (34, 37, 43)
INK = (233, 226, 212)

CX, CY = 0.5, 0.94          # centre of the arch the stones belong to


def at(t, r):
    """A point on the arch: t is degrees from vertical, r the radius."""
    a = math.radians(t)
    return CX + r * math.sin(a), CY - r * math.cos(a)


def voussoir(t0, t1, r0, r1, steps=24):
    """One wedge of an arch, its inner and outer edges following the curve."""
    pts = [at(t0 + (t1 - t0) * i / steps, r1) for i in range(steps + 1)]
    pts += [at(t1 - (t1 - t0) * i / steps, r0) for i in range(steps + 1)]
    return pts


def fit(shapes, pad=0.15):
    """Centre the group and grow it to fill the frame, so every variant gets
    judged at the same visual weight rather than at whatever size it landed."""
    xs = [x for s in shapes for x, y in s]
    ys = [y for s in shapes for x, y in s]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = (1 - 2 * pad) / max(w, h)
    ox = 0.5 - (min(xs) + w / 2) * k
    oy = 0.5 - (min(ys) + h / 2) * k
    return [[(x * k + ox, y * k + oy) for x, y in s] for s in shapes]


# ------------------------------------------------------------------ variants

# A gap has to be about a pixel and a half at 20 wide or it closes up, which
# is 0.075 of the frame. Along an arc at radius 0.45 that is 0.075/0.45 radians,
# so the gaps between stones are nine degrees and not the two degrees a
# drawing at 512 makes look right.
GAP = 9


def stones(n, span, r0=.30, r1=.62, proud=0):
    """`n` stones filling `span` degrees, gapped so they stay separate at 20px.
    `proud` pushes the middle one further out, which is what a keystone does."""
    w = (span - GAP * (n - 1)) / n
    out = []
    for i in range(n):
        t0 = -span / 2 + i * (w + GAP)
        mid = n % 2 and i == n // 2
        out.append(voussoir(t0, t0 + w, r0, r1 + (proud if mid else 0)))
    return out


def base(shapes, drop=.06, thick=.11, over=.02):
    """The course the stones sit on. Cheap, and it is what stops the mark
    reading as a hand of cards."""
    xs = [x for s in shapes for x, y in s]
    y = max(yy for s in shapes for xx, yy in s)
    return shapes + [[(min(xs) - over, y + drop), (max(xs) + over, y + drop),
                      (max(xs) + over, y + drop + thick),
                      (min(xs) - over, y + drop + thick)]]


def piers(shapes, r0, r1, drop=.42):
    """The two legs the arch lands on. Without them the stones fan out and the
    mark reads as a crown; with them there is an opening underneath, which is
    the only thing that says arch rather than decoration."""
    return shapes + [
        [(CX + r0, CY), (CX + r1, CY), (CX + r1, CY + drop), (CX + r0, CY + drop)],
        [(CX - r1, CY), (CX - r0, CY), (CX - r0, CY + drop), (CX - r1, CY + drop)]]


# Wide and shallow reads as a fan. Narrow and deep reads as masonry.
def narrow3():      return stones(3, 52, r0=.24, r1=.72)
def narrow_crown(): return stones(3, 52, r0=.24, r1=.72, proud=.10)
def narrow_base():  return base(stones(3, 52, r0=.24, r1=.72))
def gate5():        return piers(stones(5, 156, r0=.36, r1=.62), .36, .62)
def gate5_crown():  return piers(stones(5, 156, r0=.36, r1=.62, proud=.09), .36, .62)


def gate3():
    """The mark. Three voussoirs carried down to two piers.

    The span is 176 rather than 150 so the outer stones come all the way round
    to horizontal and land on the piers, instead of stopping short and leaving
    them floating. The joint between stone and pier then reads as one more
    joint in the masonry rather than as a mistake."""
    return piers(stones(3, 176, r0=.36, r1=.62), .36, .62, drop=.40)


VARIANTS = [("narrow3", narrow3), ("narrow crown", narrow_crown),
            ("narrow+base", narrow_base), ("gate3", gate3),
            ("gate5", gate5), ("gate5 crown", gate5_crown)]


def render(fn, ground=GROUND, ink=INK, accent=None):
    im = Image.new("RGB", (N * S, N * S), ground)
    d = ImageDraw.Draw(im)
    shapes = fit(fn())
    mid = len(shapes) // 2
    for i, pts in enumerate(shapes):
        fill = accent if (accent and i == mid and len(shapes) % 2) else ink
        d.polygon([(x * N * S, y * N * S) for x, y in pts], fill=fill)
    return im.resize((N, N), Image.LANCZOS)


def circle(im, size):
    t = im.resize((size, size), Image.LANCZOS)
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    return t, m.resize((size, size), Image.LANCZOS)


def sheet():
    SIZES = [128, 96, 40, 20]
    pad, gap, labelw, rowh = 22, 26, 96, 162
    darkw = sum(SIZES) + gap * len(SIZES)
    lightx = pad + labelw + darkw + 40
    W = lightx + 96 + gap + 40 + pad
    H = pad * 2 + 46 + len(VARIANTS) * rowh
    sh = Image.new("RGB", (W, H), (17, 18, 21))
    d = ImageDraw.Draw(sh)
    small = ImageFont.truetype(str(FONTS / "spacegrotesk.ttf"), 12)
    d.rectangle([lightx - 14, pad + 24, W - pad + 6, H - pad], fill=(255, 255, 255))
    d.text((pad + labelw, pad + 6), "on Discord dark", font=small, fill=(120, 126, 136))
    d.text((lightx, pad + 6), "on light", font=small, fill=(120, 126, 136))
    x = pad + labelw
    for s in SIZES:
        d.text((x, pad + 24), f"{s}px", font=small, fill=(90, 95, 104))
        x += s + gap
    for i, (name, fn) in enumerate(VARIANTS):
        y = pad + 46 + i * rowh
        d.text((pad, y + 50), name, font=small, fill=(200, 196, 190))
        im, x = render(fn), pad + labelw
        for s in SIZES:
            t, m = circle(im, s)
            sh.paste(t, (x, y + (128 - s) // 2), m)
            x += s + gap
        inv, x = render(fn, ground=(247, 246, 244), ink=(38, 41, 48)), lightx
        for s in (96, 40):
            t, m = circle(inv, s)
            sh.paste(t, (x, y + (128 - s) // 2), m)
            x += s + gap
    return sh


if __name__ == "__main__":
    for name, fn in VARIANTS:
        render(fn).save(OUT / f"key-{name}.png")
    sheet().save(OUT / "keystones-sheet.png")
    print("wrote", len(VARIANTS), "keystone variants")
