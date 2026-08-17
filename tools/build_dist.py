"""Assemble a folder that runs Steward on a machine with no Python.

    python tools/build_dist.py            build into dist/Steward
    python tools/build_dist.py --zip      and zip it
    python tools/build_dist.py --clean    throw the previous build away first

The problem this solves: everything here is Python, and a Discord server owner
is not necessarily a Python user. Telling somebody to install Python and tick
"Add to PATH" before they can use a tool loses most of them at that sentence.

The fix is python.org's own **embeddable package**: a zip of the interpreter
that unpacks into a folder, is not registered with Windows, does not touch
PATH, and cannot conflict with a Python already installed. About 11 MB, and
roughly 60 MB once the dependencies are in it.

Two things about the embeddable build catch people out, and both are handled
below. It ships with no pip, so pip has to be bootstrapped in. And it ignores
site-packages unless the `._pth` file that comes with it is edited to say
otherwise, which is why an install that looks like it worked then fails on the
first import.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT / "provision"))
import updates                                             # noqa: E402

PY_VERSION = "3.11.9"
PY_URL = (f"https://www.python.org/ftp/python/{PY_VERSION}/"
          f"python-{PY_VERSION}-embed-amd64.zip")
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"

# What a user needs. Not the tests, not the brand scripts, not the fonts, and
# above all not steward/.env or steward/data.
COPY_TREES = [
    ("ui", ["__pycache__", "SETUP-UI.bat"]),
    ("provision", ["__pycache__"]),
    # The local override file is this machine's, not something to ship.
    ("blueprint", ["__pycache__", "content-calendar.local.yaml"]),
    ("docs", []),
    # The Start Menu shortcuts come along, so the zip can give somebody a
    # normal-looking install without an .exe and the SmartScreen panel that
    # comes with one.
    ("install", ["dist", "setup.iss"]),
]
COPY_FILES = ["README.md", "SETUP.md", "LICENSE", "VERSION", "INSTALL.bat"]
STEWARD_FILES = ["*.py", "requirements*.txt", ".env.example"]


def say(msg):
    print(f"  {msg}", flush=True)


def fetch(url: str) -> bytes:
    say(f"downloading {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=180) as r:
        return r.read()


def build_python(target: Path):
    """Unpack the embeddable interpreter and give it pip and site-packages."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(fetch(PY_URL))) as z:
        z.extractall(target)

    # The embeddable build ships a python3xx._pth listing what is importable,
    # and it deliberately leaves site-packages out. Every dependency installed
    # into this interpreter is invisible until `import site` is uncommented,
    # and the failure looks like a broken install rather than a missing line.
    for pth in target.glob("python*._pth"):
        text = pth.read_text(encoding="utf-8")
        if "#import site" in text:
            pth.write_text(text.replace("#import site", "import site"),
                           encoding="utf-8")
            say(f"enabled site-packages in {pth.name}")
        if "Lib\\site-packages" not in text:
            pth.write_text(pth.read_text(encoding="utf-8").rstrip()
                           + "\nLib\\site-packages\n", encoding="utf-8")

    exe = target / "python.exe"
    (target / "get-pip.py").write_bytes(fetch(GET_PIP))
    say("bootstrapping pip")
    r = subprocess.run([str(exe), str(target / "get-pip.py"), "--no-warn-script-location"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit(f"  pip would not install:\n{r.stdout[-1500:]}{r.stderr[-1500:]}")
    (target / "get-pip.py").unlink(missing_ok=True)
    return exe


def install_requirements(exe: Path):
    # requirements-charts.txt is deliberately not here. matplotlib drags in
    # numpy, PIL and fontTools, which is 115 MB of the download for one image a
    # week, and the digest already falls back to a text sparkline without it.
    # The page offers a button to add it afterwards.
    reqs = [ROOT / "ui" / "requirements.txt", ROOT / "steward" / "requirements.txt"]
    for req in reqs:
        if not req.exists():
            continue
        say(f"installing {req.parent.name}/requirements.txt")
        r = subprocess.run([str(exe), "-m", "pip", "install", "--no-warn-script-location",
                            "-q", "-r", str(req)],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise SystemExit(f"  failed:\n{r.stdout[-1500:]}{r.stderr[-1500:]}")


def copy_app(app: Path):
    for name, skip in COPY_TREES:
        src = ROOT / name
        if not src.exists():
            continue
        shutil.copytree(src, app / name,
                        ignore=shutil.ignore_patterns(*skip) if skip else None)
    for name in COPY_FILES:
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, app / name)

    # The bot, file by file. A blanket copy of steward/ would take .env, which
    # holds a live token, and data/, which holds members' activity and any
    # playtest keys. Neither may ever be inside something handed to a stranger.
    out = app / "steward"
    out.mkdir(parents=True, exist_ok=True)
    for pattern in STEWARD_FILES:
        for f in (ROOT / "steward").glob(pattern):
            if f.is_file() and "__pycache__" not in f.parts:
                shutil.copy2(f, out / f.name)

    (app / "brand").mkdir(exist_ok=True)
    for f in ("steward.ico", "steward-avatar.png", "steward-banner.png"):
        if (ROOT / "brand" / f).exists():
            shutil.copy2(ROOT / "brand" / f, app / "brand" / f)


LAUNCHER = r"""@echo off
setlocal
title Steward
cd /d "%~dp0"

REM Uses the Python that shipped in this folder. Nothing is installed, nothing
REM is added to PATH, and a Python already on this machine is left alone.
set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  echo.
  echo   This copy of Steward is missing its python folder, so it cannot run.
  echo   Download it again and make sure the whole folder is extracted, not
  echo   just this file.
  echo.
  pause
  exit /b 1
)

echo.
echo   Steward
echo   =======
echo.
echo   Keep this window open while you use the page in your browser.
echo   Your bot token lives in this window's memory and nowhere else, so
echo   closing it forgets the token. Nothing already built is affected.
echo.

"%PY%" ui\app.py

echo.
echo   Steward has stopped. You can close this window.
pause
"""


def main():
    ap = argparse.ArgumentParser(description="Build a no-Python-required folder.")
    ap.add_argument("--zip", action="store_true", help="also produce a .zip")
    ap.add_argument("--clean", action="store_true", help="delete any previous build")
    args = ap.parse_args()

    version = updates.version()
    app = DIST / "Steward"
    if args.clean and DIST.exists():
        shutil.rmtree(DIST)
    if app.exists():
        raise SystemExit(f"  {app} already exists. Pass --clean to replace it.")

    print(f"\n  Building Steward {version} with Python {PY_VERSION} inside it\n")
    app.mkdir(parents=True)
    exe = build_python(app / "python")
    install_requirements(exe)
    copy_app(app)
    (app / "Steward.bat").write_text(LAUNCHER, encoding="utf-8")

    # In a checkout the shortcuts point at START.bat, which finds a system
    # Python. In a download that Python may not exist, so they have to point at
    # the launcher that uses the bundled one.
    for rel in ("INSTALL.bat", "install/Install.ps1"):
        f = app / rel
        if f.exists():
            f.write_text(f.read_text(encoding="utf-8").replace("START.bat", "Steward.bat"),
                         encoding="utf-8")

    # START-LEDGER.bat expects a system Python too, and the ledger is started
    # from the page anyway.
    ps1 = app / "install" / "Install.ps1"
    if ps1.exists():
        text = ps1.read_text(encoding="utf-8")
        cut = text.find("New-Shortcut -Path (Join-Path $Dest 'Steward ledger only.lnk')")
        end = text.find("New-Shortcut -Path (Join-Path $Dest 'Remove these shortcuts.lnk')")
        if 0 < cut < end:
            ps1.write_text(text[:cut] + text[end:], encoding="utf-8")

    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    say(f"built {app}  ({size / 1_048_576:.0f} MB)")

    if args.zip:
        out = DIST / f"Steward-{version}-windows"
        say("zipping")
        shutil.make_archive(str(out), "zip", root_dir=DIST, base_dir="Steward")
        say(f"{out}.zip  ({Path(str(out) + '.zip').stat().st_size / 1_048_576:.0f} MB)")

    print("\n  Test it by double-clicking Steward.bat in that folder.\n")


if __name__ == "__main__":
    main()
