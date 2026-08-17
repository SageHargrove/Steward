"""Real screenshots of the setup page, for the README.

    python tools/screenshots.py

Taken with Chrome headless against the page served on a spare port, so what
lands in the README is what the program looks like today. Drawn mockups go
stale silently; these go stale the moment somebody looks at them again.

`solo=1` in the query string hides every other step, which is why the
per-feature shots are tight rather than the whole page nine times.
"""
import os, pathlib, shutil, subprocess, sys, threading, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
PORT = 8806
BASE = f"http://127.0.0.1:{PORT}"
CHROME = next(
    (c for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ) if os.path.exists(c)), "")

SHOTS = [
    ("overview",  "",                          1180, 1000),
    ("01-bot",    "?open=s1&solo=1",           1180, 1180),
    ("02-choose", "?open=s4&solo=1",           1180, 1250),
    ("03-build",  "?open=s5&solo=1",           1180,  520),
    ("04-content","?open=s6&solo=1",           1180,  760),
    ("05-ledger", "?open=s7&solo=1",           1180,  560),
    ("06-calendar","?open=s8&solo=1",          1180, 1250),
    ("07-check",  "?open=s9b&solo=1",          1180,  520),
    ("08-byhand", "?open=s9&solo=1",           1180, 1150),
]


def serve():
    sys.path.insert(0, str(ROOT / "ui"))
    sys.path.insert(0, str(ROOT / "provision"))
    os.environ["PORT"] = str(PORT)
    import app, uvicorn
    uvicorn.run(app.app, host="127.0.0.1", port=PORT, log_level="error")


def wait():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def shoot(name, query, w, h):
    dest = OUT / f"{name}.png"
    profile = pathlib.Path(os.environ["TEMP"]) / f"chrome-shot-{name}"
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", f"--user-data-dir={profile}",
           f"--window-size={w},{h}", f"--screenshot={dest}",
           "--virtual-time-budget=4000", BASE + query]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    shutil.rmtree(profile, ignore_errors=True)
    if dest.exists():
        kb = dest.stat().st_size // 1024
        print(f"  {name:10} {w}x{h}  {kb} KB")
        return True
    print(f"  {name:10} FAILED: {(r.stderr or '')[-300:]}")
    return False


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=serve, daemon=True).start()
    if not wait():
        sys.exit("  the page never came up")
    print(f"  serving on {PORT}\n")
    ok = sum(shoot(*s) for s in SHOTS)
    print(f"\n  {ok}/{len(SHOTS)} taken into {OUT}")
