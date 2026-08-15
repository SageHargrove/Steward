"""Pull a handful of OFL faces with actual character from Google Fonts."""
import pathlib, urllib.request, urllib.parse

OUT = pathlib.Path(r"C:\CommunityOps\brand\fonts")
OUT.mkdir(exist_ok=True)
BASE = "https://raw.githubusercontent.com/google/fonts/main/"

FONTS = {
    "marcellus":      "ofl/marcellus/Marcellus-Regular.ttf",
    "dmserif":        "ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf",
    "youngserif":     "ofl/youngserif/YoungSerif-Regular.ttf",
    "instrument":     "ofl/instrumentserif/InstrumentSerif-Regular.ttf",
    "fraunces":       "ofl/fraunces/Fraunces[SOFT,WONK,opsz,wght].ttf",
    "playfair":       "ofl/playfairdisplay/PlayfairDisplay[wght].ttf",
    "bodoni":         "ofl/bodonimoda/BodoniModa[opsz,wght].ttf",
    "spectral":       "ofl/spectral/Spectral-SemiBold.ttf",
    "spacegrotesk":   "ofl/spacegrotesk/SpaceGrotesk[wght].ttf",
    "archivo":        "ofl/archivo/Archivo[wdth,wght].ttf",
    "eb":             "ofl/ebgaramond/EBGaramond[wght].ttf",
    "newsreader":     "ofl/newsreader/Newsreader[opsz,wght].ttf",
}

for name, path in FONTS.items():
    dest = OUT / f"{name}.ttf"
    if dest.exists():
        print("  have", name)
        continue
    url = BASE + urllib.parse.quote(path)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            dest.write_bytes(r.read())
        print("  got ", name, dest.stat().st_size // 1024, "kb")
    except Exception as e:
        print("  MISS", name, e)
