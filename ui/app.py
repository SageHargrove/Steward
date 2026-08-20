"""
Steward: set up and run a Discord community server.

    python app.py            then open http://127.0.0.1:8770

Binds to localhost only and holds the bot token in server memory for the life
of the process. The token is never written to disk and never sent back to the
browser.

This is the local shape of the tool. A hosted version would swap the
token-paste step for a Discord OAuth "Add to Server" flow and everything below
`core` would stay as it is, which is why the provisioning logic lives in
../provision/core.py rather than here.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "provision"))
import core  # noqa: E402

HERE = Path(__file__).resolve().parent
BLUEPRINTS = HERE.parent / "blueprint"
PORT = int(os.environ.get("PORT", "8770"))
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

app = FastAPI(title="Steward", docs_url=None, redoc_url=None)

# session id -> {"token": str, "bot": dict}. Process memory only.
SESSIONS: dict[str, dict] = {}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """This process holds a bot token, so a page on another origin must not be
    able to drive it. Browsers omit Origin on same-origin GETs, so absence is
    only tolerated for safe methods."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD"):
        if origin is not None and origin not in ORIGINS:
            return Response("Cross-origin request refused", status_code=403)
    return await call_next(request)


def session_of(request: Request) -> dict:
    sid = request.cookies.get("cops_session")
    if not sid or sid not in SESSIONS:
        raise HTTPException(401, "Not connected. Paste your bot token first.")
    return SESSIONS[sid]


# --------------------------------------------------------------------------
# Static
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


WATCHED = [Path(__file__), Path(core.__file__), HERE / "static" / "index.html"]
LOADED_AT = {p: p.stat().st_mtime for p in WATCHED if p.exists()}


def stale_files() -> list[str]:
    """Files that changed on disk after this process imported them.

    Python does not reload modules, so editing core.py and refreshing the page
    silently keeps serving the old behaviour. That has caused real confusion,
    so the page asks about it and says to restart.
    """
    out = []
    for p, was in LOADED_AT.items():
        try:
            if p.stat().st_mtime > was + 1:
                out.append(p.name)
        except OSError:
            pass
    return out


@app.get("/api/health")
def health(request: Request):
    """The page polls this so it can tell "the program stopped" apart from
    "something went wrong", which the browser reports identically as the
    unhelpful "Failed to fetch"."""
    sid = request.cookies.get("cops_session")
    return {"ok": True, "connected": bool(sid and sid in SESSIONS),
            "stale": stale_files()}


# --------------------------------------------------------------------------
# Blueprints
# --------------------------------------------------------------------------

def looks_like_a_blueprint(bp: dict) -> bool:
    """A server blueprint declares roles or categories.

    The blueprint folder also holds the content calendar and its overrides,
    which are YAML but describe posts, not a server. Listing those put a second
    entry in the picker that sorted first alphabetically, so the page opened
    with it selected and an empty panel, and the only way out was to pick the
    real one and then pick back.
    """
    return bool(bp.get("categories") or bp.get("roles"))


@app.get("/api/blueprints")
def list_blueprints():
    out = []
    for p in sorted(BLUEPRINTS.glob("*.yaml")):
        try:
            bp = core.load(p)
            if not looks_like_a_blueprint(bp):
                continue
            out.append({"file": p.name,
                        "name": bp.get("meta", {}).get("name", p.stem)})
        except Exception as e:
            out.append({"file": p.name, "name": p.stem, "error": str(e)[:200]})
    return out


def _load_named(file: str) -> dict:
    # Filename comes from the browser, so keep it inside the blueprint folder.
    path = (BLUEPRINTS / Path(file).name).resolve()
    if not path.is_file() or path.parent != BLUEPRINTS.resolve():
        raise HTTPException(404, "No such blueprint")
    return core.load(path)


@app.get("/api/blueprint/{file}")
def get_blueprint(file: str):
    """Everything selectable, in render order, plus a first validation pass."""
    bp = _load_named(file)
    return {"inventory": core.inventory(bp),
            "preview": core.validate(core.customize(bp, None))}


@app.post("/api/preview")
def preview(payload: dict = Body(...)):
    """Called on every toggle. No token, no network, no writes."""
    bp = _load_named(payload.get("file", ""))
    customized = core.customize(bp, payload.get("selection") or {})
    report = core.validate(customized)
    report["plan"] = [
        {"category": cat["name"],
         "channels": [{"name": c["name"], "type": c.get("type", "text")}
                      for c in cat.get("channels", [])]}
        for cat in customized.get("categories", [])
    ]
    report["roles_planned"] = [r["name"] for r in customized.get("roles", [])]
    return report


# --------------------------------------------------------------------------
# Connect
# --------------------------------------------------------------------------

@app.post("/api/connect")
def connect(response: Response, payload: dict = Body(...)):
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "Paste a bot token.")
    try:
        who = core.identify(token)
    except core.Failed as e:
        msg = str(e)
        if "401" in msg:
            raise HTTPException(400, "Discord rejected that token. Copy it again from the "
                                     "Bot tab. Make sure it is the token and not the "
                                     "Application ID or the Client Secret, and that you "
                                     "got the whole thing.")
        if "403" in msg:
            raise HTTPException(400, "Discord refused that token. If you reset it since "
                                     "copying, the old one stopped working. Reset it once "
                                     "more and use the new value.")
        raise HTTPException(400, f"Discord returned an error: {msg[:200]}")
    except Exception as e:                                   # noqa: BLE001
        # Network-level failures (no internet, DNS, proxy, TLS) arrive here as
        # raw requests exceptions rather than core.Failed.
        raise HTTPException(400, "Could not reach Discord at all. Check your internet "
                                 f"connection. ({type(e).__name__})")

    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"token": token, "bot": who}
    response.set_cookie("cops_session", sid, httponly=True, samesite="lax", max_age=8 * 3600)
    # Deliberately no token in the response body.
    return {"bot": {k: who[k] for k in ("id", "username", "avatar")},
            "guilds": who["guilds"],
            "invite_url": core.invite_url(who["id"])}


@app.get("/api/guilds")
def guilds(request: Request):
    """Re-read the guild list after the user authorises the bot, so they never
    have to hunt for a server id in Developer Mode."""
    session = session_of(request)
    try:
        who = core.identify(session["token"])
    except core.Failed as e:
        raise HTTPException(400, f"Could not reach Discord: {str(e)[:200]}")
    session["bot"] = who
    return {"guilds": who["guilds"]}


@app.get("/api/existing")
def existing(request: Request, guild_id: str):
    """What is already in the server, so leftovers from Discord's default
    template can be seen and removed rather than sitting there confusing you."""
    session = session_of(request)
    try:
        return core.read_guild(session["token"], guild_id)
    except core.Failed as e:
        raise HTTPException(400, f"Could not read that server: {str(e)[:200]}")


@app.post("/api/disconnect")
def disconnect(request: Request, response: Response):
    sid = request.cookies.get("cops_session")
    SESSIONS.pop(sid, None)
    response.delete_cookie("cops_session")
    return {"ok": True}


def _content_path(rel: str) -> Path:
    """Resolve a content file, refusing anything outside the blueprint folder."""
    path = (BLUEPRINTS / rel).resolve()
    root = BLUEPRINTS.resolve()
    if root not in path.parents or path.suffix.lower() != ".md":
        raise HTTPException(400, "That is not a content file.")
    return path


@app.get("/api/content")
def list_content(file: str):
    """Every piece of text this blueprint posts, so it can be edited here
    rather than by finding files on disk."""
    bp = _load_named(file)
    out = []
    for cat in bp.get("categories", []):
        for ch in cat.get("channels", []):
            for rel, kind, title in (
                    (ch.get("content_file"), "pinned message", None),
                    ((ch.get("forum_post") or {}).get("content_file"), "forum post",
                     (ch.get("forum_post") or {}).get("title"))):
                if not rel:
                    continue
                try:
                    text = _content_path(rel).read_text(encoding="utf-8")
                except (OSError, HTTPException):
                    continue
                out.append({"channel": ch["name"], "path": rel, "kind": kind,
                            "title": title, "text": text})
    return out


@app.post("/api/content")
def save_content(payload: dict = Body(...)):
    path = _content_path(payload.get("path", ""))
    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(400, "Nothing to save.")
    path.write_text(text, encoding="utf-8")
    # Report what it will look like before it is sent anywhere.
    blocks = core.split_content(text)
    return {"ok": True, "sections": len(blocks),
            "sizes": [len(b) for b in blocks]}


@app.get("/api/manual")
def manual(request: Request, file: str = "", variables: str = ""):
    """Read from the blueprint on every call, so editing the checklist or the
    rules file shows up without restarting this program."""
    app_id = None
    sid = request.cookies.get("cops_session")
    if sid and sid in SESSIONS:
        app_id = SESSIONS[sid]["bot"].get("id")
    try:
        bp = _load_named(file) if file else {}
    except HTTPException:
        bp = {}
    if bp and variables:
        try:
            bp = {**bp, "variables": {**bp.get("variables", {}),
                                      **json.loads(variables)}}
        except ValueError:
            pass
    return core.manual_steps(app_id, bp)


# --------------------------------------------------------------------------
# The ledger, started and watched from here
#
# A browser cannot launch a program, but this process can, so the buttons on
# the page post here and the work happens locally. The ledger is started
# detached with its output going to a file: detached so closing this window
# does not stop it recording, and to a file so the page can still show what it
# said, including the two startup failures people actually hit.
# --------------------------------------------------------------------------

STEWARD = HERE.parent / "steward"
LEDGER_LOG = STEWARD / "data" / "ledger.log"
STALE_AFTER = 90            # seconds without a pulse before it counts as gone


def ledger_db():
    """Read the ledger's own database without importing discord.py."""
    import sqlite3
    env = {}
    envfile = STEWARD / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    rel = env.get("STEWARD_DB", "data/steward.sqlite3")
    path = (STEWARD / rel).resolve()
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def ledger_meta() -> dict:
    con = ledger_db()
    if con is None:
        return {}
    try:
        rows = con.execute("SELECT key, value FROM meta").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except Exception:                                        # noqa: BLE001
        return {}
    finally:
        con.close()


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@app.get("/api/ledger/status")
def ledger_status():
    meta = ledger_meta()
    seen = int(meta.get("ledger_seen_at", 0) or 0)
    pid = int(meta.get("ledger_pid", 0) or 0)
    age = int(time.time()) - seen if seen else None
    alive = bool(seen and age is not None and age < STALE_AFTER and pid_alive(pid))

    tail = ""
    if LEDGER_LOG.exists():
        try:
            tail = "\n".join(
                LEDGER_LOG.read_text(encoding="utf-8", errors="replace")
                .splitlines()[-40:])
        except OSError:
            pass

    return {
        "configured": (STEWARD / ".env").exists(),
        "running": alive,
        "state": meta.get("ledger_state", "never started"),
        "seconds_since_seen": age,
        "pid": pid,
        "log": tail,
    }


@app.post("/api/ledger/start")
def ledger_start():
    status = ledger_status()
    if status["running"]:
        raise HTTPException(400, "It is already running.")
    if not (STEWARD / ".env").exists():
        raise HTTPException(400, "No steward/.env yet. Add the bot token first.")

    LEDGER_LOG.parent.mkdir(parents=True, exist_ok=True)
    # Detached and in its own process group, so closing the setup page leaves
    # the ledger recording. Windows and POSIX spell that differently, and
    # without the POSIX half the bot dies with the page that started it.
    creation, extra = 0, {}
    if os.name == "nt":
        creation = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                   getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        extra["start_new_session"] = True
    try:
        with open(LEDGER_LOG, "w", encoding="utf-8") as out:
            subprocess.Popen([sys.executable, "-u", "bot.py"], cwd=str(STEWARD),
                             stdout=out, stderr=subprocess.STDOUT,
                             creationflags=creation, close_fds=True, **extra)
    except OSError as e:
        raise HTTPException(400, f"Could not start it: {e}")
    return {"ok": True}


@app.post("/api/ledger/stop")
def ledger_stop():
    meta = ledger_meta()
    pid = int(meta.get("ledger_pid", 0) or 0)
    if not pid or not pid_alive(pid):
        raise HTTPException(400, "It is not running.")
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True)
        else:
            os.kill(pid, 15)
    except OSError as e:
        raise HTTPException(400, f"Could not stop it: {e}")
    return {"ok": True}


@app.post("/api/ledger/restart")
def ledger_restart():
    """Stop and start in one click.

    Every change to the bot's own code needs this, and doing it as two clicks
    meant watching the dot go red and remembering to press the other button.
    """
    if not (STEWARD / ".env").exists():
        raise HTTPException(400, "No steward/.env yet. Add the bot token first.")
    meta = ledger_meta()
    pid = int(meta.get("ledger_pid", 0) or 0)
    if pid and pid_alive(pid):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True)
            else:
                os.kill(pid, 15)
        except OSError as e:
            raise HTTPException(400, f"Could not stop it: {e}")
        # SQLite in WAL mode needs the old process to let go before the new one
        # opens the same file, and taskkill returns before the handle closes.
        for _ in range(40):
            if not pid_alive(pid):
                break
            time.sleep(0.1)
    return ledger_start()


@app.get("/api/update/check")
def update_check():
    """Talks to the network, so it is never called on page load. The page asks
    when it is opened by a click and otherwise leaves it alone."""
    import updates
    return updates.check()


@app.get("/api/version")
def version_info():
    import updates
    return {"version": updates.version(), "git": updates.is_git_checkout(),
            "repo": updates.remote_slug()}


@app.post("/api/update/apply")
def update_apply(payload: dict = Body(default={})):
    import updates
    result = updates.apply(discard_local=bool(payload.get("discard_local")))
    return result


@app.post("/api/restart")
def restart_self():
    """Restart the setup program itself.

    Python does not reload modules, so any change to app.py or core.py needs a
    new process. Doing that by hand means finding the console window, closing
    it, and finding the .bat again. The replacement is launched first and waits
    for this one to release the port, so the browser can just poll until the
    page answers again.
    """
    env = dict(os.environ)
    env["PORT"] = str(PORT)
    env["COPS_WAIT_FOR_PORT"] = "1"
    creation, extra = 0, {}
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    else:
        # The replacement has to outlive this process, which is about to exit.
        extra["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, "app.py"], cwd=str(HERE), env=env,
                         creationflags=creation, close_fds=True, **extra)
    except OSError as e:
        raise HTTPException(400, f"Could not start the replacement: {e}")

    def bow_out():
        # Long enough for this response to reach the browser. The replacement
        # is already up and waiting on the port.
        time.sleep(0.7)
        os._exit(0)

    threading.Thread(target=bow_out, daemon=True).start()
    return {"ok": True, "port": PORT}


@app.post("/api/ledger/install")
def ledger_install():
    """Install the ledger's dependencies, so nobody has to find a terminal."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(STEWARD / "requirements.txt")],
            capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(400, f"Could not install: {e}")
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
    return {"ok": proc.returncode == 0, "log": "\n".join(tail)}


def charts_available() -> bool:
    """Whether the interpreter running the bot can draw the digest chart.

    Asked of a subprocess rather than by importing matplotlib here: importing
    it into the web server costs a second and some memory to answer a question
    about a different process.
    """
    try:
        r = subprocess.run([sys.executable, "-c", "import matplotlib"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@app.get("/api/charts")
def charts_status():
    return {"installed": charts_available()}


@app.post("/api/charts/install")
def charts_install():
    """Add matplotlib on request.

    It is not in the download because it brings numpy, PIL and fontTools with
    it: 115 MB for one image a week, when the digest already falls back to the
    same numbers and a text sparkline. Anyone who wants the picture can have it
    in a minute without everyone else paying for the download.
    """
    req = STEWARD / "requirements-charts.txt"
    if not req.exists():
        raise HTTPException(400, f"No {req.name} beside the bot.")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(req)],
            capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(400, f"Could not install: {e}")
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
    return {"ok": proc.returncode == 0, "installed": charts_available(),
            "log": "\n".join(tail)}


# --------------------------------------------------------------------------
# The content calendar
# --------------------------------------------------------------------------

CALENDAR_DIR = HERE.parent / "blueprint" / "calendars"
LEGACY_CALENDAR = HERE.parent / "blueprint" / "content-calendar.yaml"


def calendar_templates() -> list[dict]:
    """Every calendar you could be running, newest layout first."""
    import yaml
    out = []
    for f in sorted(CALENDAR_DIR.glob("*.yaml")):
        if f.name.endswith(".local.yaml"):
            continue
        try:
            meta = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("meta") or {}
        except Exception:                                    # noqa: BLE001
            meta = {}
        out.append({"id": f.stem, "name": meta.get("name", f.stem)})
    return out


def active_calendar() -> Path:
    """Which one is in use. Same rules the bot follows, so the page cannot
    show one calendar while the bot runs another."""
    named = read_env().get("CALENDAR") or read_env().get("STEWARD_CALENDAR")
    if named:
        direct = Path(named)
        if direct.is_file():
            return direct
        guess = CALENDAR_DIR / f"{Path(named).stem}.yaml"
        if guess.exists():
            return guess
    if LEGACY_CALENDAR.exists():
        return LEGACY_CALENDAR
    general = CALENDAR_DIR / "general.yaml"
    if general.exists():
        return general
    rest = [f for f in sorted(CALENDAR_DIR.glob("*.yaml"))
            if not f.name.endswith(".local.yaml")]
    return rest[0] if rest else general


def read_env() -> dict:
    out = {}
    envfile = STEWARD / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_env(key: str, value: str | None):
    """Set or clear one key, leaving every other line exactly as it was. The
    token lives in this file, so it is never rewritten wholesale."""
    envfile = STEWARD / ".env"
    if not envfile.exists():
        raise HTTPException(400, "No steward/.env yet. Add the bot token first.")
    lines = envfile.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key and not line.strip().startswith("#"):
            if value:
                out.append(f"{key}={value}")
            done = True
            continue
        out.append(line)
    if value and not done:
        out.append(f"{key}={value}")
    envfile.write_text("\n".join(out) + "\n", encoding="utf-8")


@app.get("/api/calendar")
def calendar_view(days: int = 120):
    sys.path.insert(0, str(STEWARD))
    import calendar_engine
    from datetime import date

    if not active_calendar().exists():
        return {"present": False}

    bp = core.load(BLUEPRINTS / "default.yaml") if (BLUEPRINTS / "default.yaml").exists() \
        else {}
    variables = {k: (v if v is not None else "")
                 for k, v in (bp.get("variables") or {}).items()}
    anchor = read_env().get("LAUNCH_DATE") or None
    try:
        cal = calendar_engine.load(active_calendar(), variables, anchor_override=anchor)
    except Exception as e:                                   # noqa: BLE001
        return {"present": True, "error": str(e)}

    channels = [c["name"] for cat in (bp.get("categories") or [])
                for c in (cat.get("channels") or [])]
    roles = [r["name"] for r in (bp.get("roles") or [])]
    report = cal.validate(channels=channels, roles=roles)

    today = date.today()
    upcoming = cal.upcoming(today, max(1, min(days, 400)))
    return {
        "present": True,
        "name": cal.name,
        "anchor": report["anchor"],
        "override": bool(anchor),
        "t_minus": cal.t_minus(today),
        "counts": {"posts": report["posts"], "recurring": report["recurring"]},
        "errors": report["errors"],
        "warnings": report["warnings"],
        "upcoming": [{
            "date": o.date.isoformat(),
            "t": cal.t_minus(o.date),
            "id": o.id,
            "kind": o.post.get("kind", "post"),
            "channel": o.post.get("channel"),
            "title": o.post.get("title") or o.id,
            "mention": o.post.get("mention"),
            "event": bool(o.post.get("event")),
            "recurring": o.recurring,
        } for o in upcoming[:60]],
    }


VARIABLES_FILE = BLUEPRINTS / "variables.local.yaml"

HEADER_VARIABLES = """# What you filled in on the setup page.
#
# Kept out of the blueprint on purpose: that file is what an update replaces
# and what you would reuse on the next project, and the name of this game is
# not part of it. Safe to edit or delete by hand.

"""


@app.get("/api/variables")
def variables_get():
    import yaml
    saved = {}
    if VARIABLES_FILE.exists():
        saved = yaml.safe_load(VARIABLES_FILE.read_text(encoding="utf-8")) or {}
    bp = core.load(BLUEPRINTS / "default.yaml") if (BLUEPRINTS / "default.yaml").exists() else {}
    return {"declared": core.declared_variables(bp), "saved": saved,
            "file": VARIABLES_FILE.name}


@app.post("/api/variables")
def variables_save(payload: dict = Body(...)):
    """Remember what somebody typed, so the bot uses it too.

    The page kept these in the browser only, so the name filled in here was
    applied to the server and then forgotten. Every scheduled post the bot
    wrote afterwards still said the blueprint's placeholder.
    """
    values = payload.get("variables") or {}
    if not isinstance(values, dict):
        raise HTTPException(400, "Expected an object of variables.")
    clean = {str(k): ("" if v is None else str(v)) for k, v in values.items()
             if re.fullmatch(r"[a-zA-Z_][\w]*", str(k))}
    clean = {k: v for k, v in clean.items() if v != ""}
    if not clean:
        VARIABLES_FILE.unlink(missing_ok=True)
        return {"ok": True, "saved": {}}

    header = HEADER_VARIABLES
    VARIABLES_FILE.write_text(header + dump_yaml(clean), encoding="utf-8")
    return {"ok": True, "saved": clean,
            "note": "The bot uses these too, from its next restart."}


@app.get("/api/audit")
def audit(request: Request):
    """Compare the live server against what the tool expects of it.

    Everything else in this page describes what it is about to do. This is the
    only thing that reads back what is actually there, which is the only
    honest answer to "am I finished?".
    """
    sys.path.insert(0, str(STEWARD))
    import calendar_engine

    session = session_of(request)
    guild_id = (request.query_params.get("guild") or "").strip()
    if not guild_id:
        raise HTTPException(400, "Pick a server first.")
    try:
        live = core.read_guild(session["token"], guild_id)
    except core.Failed as e:
        raise HTTPException(400, f"Could not read the server: {str(e)[:200]}")

    chans = {c["name"] for c in live["channels"]}
    forums = {c["name"] for c in live["channels"] if c["type"] == "forum"}
    roles = {r["name"] for r in live["roles"]}

    env = read_env()
    problems, notes, good = [], [], []

    # -- the calendar has somewhere to post ------------------------------
    cal_file = active_calendar()
    if cal_file.exists():
        bp = core.load(BLUEPRINTS / "default.yaml") if (BLUEPRINTS / "default.yaml").exists() else {}
        variables = {k: (v or "") for k, v in (bp.get("variables") or {}).items()}
        cal = calendar_engine.load(cal_file, variables,
                                   anchor_override=env.get("LAUNCH_DATE"))
        missing = {}
        for post in cal.posts + cal.recurring:
            ch = post.get("channel")
            if ch and ch not in chans:
                missing.setdefault(ch, []).append(post.get("id"))
        for ch, ids in sorted(missing.items()):
            problems.append({
                "what": f"#{ch} does not exist, and {len(ids)} scheduled post(s) "
                        f"aim at it",
                "fix": f"Either make a channel called {ch}, or open those posts "
                       f"in the list below and point them somewhere else. "
                       f"({', '.join(ids[:4])})"})
        if not missing and (cal.posts or cal.recurring):
            good.append(f"All {len(cal.posts) + len(cal.recurring)} scheduled "
                        f"posts have a channel that exists")

        for post in cal.posts + cal.recurring:
            m = post.get("mention")
            if m and m != "everyone" and m not in roles:
                problems.append({
                    "what": f"'{post.get('id')}' pings @{m}, which is not a role here",
                    "fix": f"Make a role called {m}, or clear the Pings box on "
                           f"that post."})
        if not cal.anchor:
            problems.append({
                "what": "No launch day is set, so nothing dated T-minus will "
                        "ever post",
                "fix": "Put a date in the Launch day box above."})
        else:
            good.append(f"Launch day is {cal.anchor.isoformat()}")

    # -- the bot's own channels ------------------------------------------
    for key, default, why in (
            ("REPORT_CHANNEL", "steward-reports",
             "the weekly digest, and where scheduled posts wait for approval"),
            ("MOD_CHANNEL", "mod-log", "the moderation log"),
            ("BUG_FORUM", "bug-reports", "where /playtest-report files bugs")):
        name = env.get(key, default)
        if name not in chans:
            problems.append({
                "what": f"#{name} does not exist, and it is where {why} goes",
                "fix": f"Make it, or set {key} in steward\\.env to a channel "
                       f"you do have."})
        elif key == "BUG_FORUM" and name not in forums:
            problems.append({
                "what": f"#{name} exists but is not a forum channel, so "
                        f"/playtest-report cannot file into it",
                "fix": "Forum channels need Community mode on. Rebuild it in "
                       "step 5, or point BUG_FORUM at a forum you have."})
        else:
            good.append(f"#{name} exists")

    playtest_role = env.get("PLAYTEST_ROLE", "Ping Me For Playtests")
    if playtest_role not in roles:
        problems.append({
            "what": f"There is no @{playtest_role} role, so /playtest-join "
                    f"cannot give anyone one",
            "fix": "Make the role, or set PLAYTEST_ROLE in steward\\.env."})
    else:
        good.append(f"@{playtest_role} exists")

    # -- drift from the blueprint ----------------------------------------
    if (BLUEPRINTS / "default.yaml").exists():
        bp = core.load(BLUEPRINTS / "default.yaml")
        want = {c["name"] for cat in (bp.get("categories") or [])
                for c in (cat.get("channels") or [])}
        gone = sorted(want - chans)
        if gone:
            notes.append({
                "what": f"{len(gone)} channel(s) in the blueprint are not in "
                        f"this server: {', '.join(gone[:8])}",
                "fix": "Not a problem if you renamed or removed them on "
                       "purpose. It only means the blueprint and the server "
                       "have drifted, so a rebuild would put them back."})

    # -- levels ------------------------------------------------------------
    levels = (core.load(BLUEPRINTS / "default.yaml").get("levels") or {}) \
        if (BLUEPRINTS / "default.yaml").exists() else {}
    if levels.get("enabled", True):
        want = [r["role"] for r in (levels.get("rewards") or [])]
        gone = [r for r in want if r not in roles]
        if gone:
            problems.append({
                "what": f"Level rewards point at role(s) that do not exist: "
                        f"{', '.join(gone)}",
                "fix": "Make them, or change the level rewards in step 4. "
                       "Members will hit those levels and get nothing."})
        elif want:
            good.append(f"All {len(want)} level reward roles exist")

    return {"ok": not problems, "problems": problems, "notes": notes,
            "good": good, "channels": len(chans), "roles": len(roles)}


@app.get("/api/calendar/templates")
def calendar_templates_api(blueprint: str = ""):
    """`blueprint` names the file selected in step 4, so the page can say when
    the chosen server shape and the chosen calendar do not go together. A
    Roblox server on the Steam calendar is a mistake nobody would make on
    purpose."""
    suggested = None
    if blueprint:
        path = (BLUEPRINTS / Path(blueprint).name)
        if path.is_file() and path.parent == BLUEPRINTS.resolve():
            try:
                suggested = (core.load(path).get("meta") or {}).get("calendar")
            except Exception:                                # noqa: BLE001
                suggested = None
    return {"active": active_calendar().stem,
            "templates": calendar_templates(),
            "suggested": suggested}


@app.post("/api/calendar/template")
def calendar_set_template(payload: dict = Body(...)):
    """Switch which calendar is in use.

    Nothing is copied or overwritten: the setting names one of the shipped
    templates and each keeps its own edits, so switching to Roblox and back
    leaves the Steam calendar exactly as you left it.
    """
    want = (payload.get("id") or "").strip()
    known = {t["id"] for t in calendar_templates()}
    if want not in known:
        raise HTTPException(400, f"No calendar called {want!r}. "
                                 f"There is: {', '.join(sorted(known))}.")
    write_env("CALENDAR", want)
    write_env("STEWARD_CALENDAR", None)         # the older name, if it is there
    return {"ok": True, "active": want,
            "note": "Steward picks this up on restart, or with /calendar-reload."}


@app.get("/api/calendar/posts")
def calendar_posts(blueprint: str = ""):
    """Every post, as written, so the page can put it in a textarea.

    Deliberately unsubstituted: `{{game}}` has to survive a round trip through
    the editor, or saving any post would freeze this deployment's game name
    into a file whose whole purpose is being reusable.
    """
    sys.path.insert(0, str(STEWARD))
    import calendar_engine
    import yaml

    if not active_calendar().exists():
        return {"present": False, "posts": []}
    with open(active_calendar(), encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}
    local_file = calendar_engine.overrides_path(active_calendar())
    local = {}
    if local_file.exists():
        with open(local_file, encoding="utf-8") as fh:
            local = yaml.safe_load(fh) or {}
    def rows(d, key):
        return d.get(key) or (d.get("beats") if key == "posts" else None) or []

    local_rows = rows(local, "posts") + rows(local, "recurring")
    edited = {b.get("id") for b in local_rows if b.get("id")}
    hidden = {b.get("id") for b in local_rows if b.get("enabled") is False}
    shipped = {b.get("id") for b in rows(spec, "posts") + rows(spec, "recurring")}

    suggested = None
    if blueprint:
        bpath = BLUEPRINTS / Path(blueprint).name
        if bpath.is_file() and bpath.parent == BLUEPRINTS.resolve():
            try:
                suggested = (core.load(bpath).get("meta") or {}).get("calendar")
            except Exception:                                # noqa: BLE001
                suggested = None

    merged = calendar_engine.merge(spec, local)
    anchor = read_env().get("LAUNCH_DATE") or None
    cal = calendar_engine.Calendar(
        {**merged, "meta": {**(merged.get("meta") or {}),
                            **({"anchor": anchor} if anchor else {})}})
    from datetime import date, timedelta
    today = date.today()

    def next_run(bid):
        """When this next goes out, so the list can be sorted by it and each
        row can say it. Without this the page needs a second list."""
        for occ in cal.occurrences(today, today + timedelta(days=800)):
            if occ.id == bid:
                return occ.date
        return None

    out = []
    for which in ("posts", "recurring"):
        for b in merged.get(which, []):
            nxt = next_run(b.get("id"))
            out.append({
                "id": b.get("id"), "list": which,
                "kind": b.get("kind", "post"),
                "title": b.get("title", ""), "body": b.get("body", ""),
                "channel": b.get("channel", ""), "when": b.get("when", ""),
                "every": b.get("every", ""), "mention": b.get("mention", ""),
                "event": bool(b.get("event")),
                "next": nxt.isoformat() if nxt else None,
                "t": cal.t_minus(nxt) if nxt else None,
                "edited": b.get("id") in edited,
                "shipped": b.get("id") in shipped,
            })
    for bid in sorted(hidden):
        out.append({"id": bid, "list": "posts", "hidden": True, "edited": True,
                    "shipped": bid in shipped, "title": "", "body": "",
                    "channel": "", "when": "", "every": "", "mention": "",
                    "kind": "post", "next": None, "t": None, "event": False})

    # Soonest first, with anything dormant after it.
    out.sort(key=lambda b: (b["next"] is None, b["next"] or "", b["id"]))
    return {"present": True, "posts": out,
            "template": active_calendar().stem,
            "suggested": suggested,
            "templates": calendar_templates(),
            "anchor": cal.anchor.isoformat() if cal.anchor else None,
            "t_today": cal.t_minus(today),
            "overrides_file": local_file.name,
            "has_overrides": local_file.exists()}


EDITABLE = ("kind", "title", "body", "channel", "when", "every", "mention")


def dump_yaml(data: dict) -> str:
    """Write it the way a person would.

    safe_dump turns a multi-line body into a quoted scalar wrapped at the
    margin, which round-trips correctly and is horrible to read if anybody
    opens the file. Anything with a newline in it gets a block scalar instead.
    """
    import yaml

    class Dumper(yaml.SafeDumper):
        pass

    def block(dumper, value):
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    Dumper.add_representer(str, block)
    return yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=88)


@app.post("/api/calendar/post")
def calendar_save_post(payload: dict = Body(...)):
    """Save one post's edits into content-calendar.local.yaml.

    Never into the shipped file. Rewriting that would destroy its comments,
    and an update replaces it, so edits written there would be lost every
    time somebody updated.
    """
    sys.path.insert(0, str(STEWARD))
    import calendar_engine
    import yaml

    bid = (payload.get("id") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,48}", bid):
        raise HTTPException(400, "An id must be lowercase letters, numbers and "
                                 "hyphens, like 'devlog-monday'.")

    which = "recurring" if payload.get("list") == "recurring" else "posts"
    local_file = calendar_engine.overrides_path(active_calendar())
    local = {}
    if local_file.exists():
        with open(local_file, encoding="utf-8") as fh:
            local = yaml.safe_load(fh) or {}
    local.setdefault("posts", [])
    local.setdefault("recurring", [])
    if local.pop("beats", None):        # written before the rename
        local["posts"] = local["posts"] + local.get("beats", [])

    entry = {"id": bid}
    if payload.get("hidden"):
        entry["enabled"] = False
    else:
        for k in EDITABLE:
            v = payload.get(k)
            if v not in (None, ""):
                entry[k] = v
        if not entry.get("body"):
            raise HTTPException(400, "A post needs something to post.")
        if not entry.get("channel"):
            raise HTTPException(400, "A post needs a channel to post in.")

    rows = [b for b in local[which] if b.get("id") != bid]
    other = "recurring" if which == "posts" else "posts"
    local[other] = [b for b in local[other] if b.get("id") != bid]
    rows.append(entry)
    local[which] = rows

    local_file.write_text(HEADER_LOCAL + dump_yaml(local), encoding="utf-8")
    return {"ok": True, "file": local_file.name}


@app.post("/api/calendar/post/reset")
def calendar_reset_post(payload: dict = Body(...)):
    """Drop an edit and go back to what shipped."""
    sys.path.insert(0, str(STEWARD))
    import calendar_engine
    import yaml

    bid = (payload.get("id") or "").strip()
    local_file = calendar_engine.overrides_path(active_calendar())
    if not local_file.exists():
        return {"ok": True}
    with open(local_file, encoding="utf-8") as fh:
        local = yaml.safe_load(fh) or {}
    for key in ("posts", "beats", "recurring"):
        if key in local:
            local[key] = [b for b in (local.get(key) or []) if b.get("id") != bid]
    if not any(local.get(k) for k in ("posts", "beats", "recurring")):
        local_file.unlink()
        return {"ok": True, "removed_file": True}
    local_file.write_text(HEADER_LOCAL + dump_yaml(local), encoding="utf-8")
    return {"ok": True}


HEADER_LOCAL = """# Your edits to the content calendar.
#
# Written by the setup page. Safe to edit by hand, and safe to delete: doing
# either just puts the shipped calendar back.
#
# Kept apart from content-calendar.yaml on purpose. That file is the one an
# update replaces and the one you would redeploy to the next project, so
# anything written into it would be lost the next time you updated. Posts
# here are matched by id and override the shipped ones field by field.
#
#   enabled: false   hides a shipped post without deleting it
#   a new id         adds a post of your own

"""


@app.post("/api/calendar/anchor")
def calendar_anchor(payload: dict = Body(...)):
    """Set the launch date without editing the calendar file, so the file stays
    the reusable artifact and the date stays this deployment's business."""
    value = (payload.get("date") or "").strip()
    if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(400, "Use a date like 2027-03-01.")
    write_env("LAUNCH_DATE", value or None)
    return {"ok": True, "anchor": value or None,
            "note": "Steward picks this up on restart, or with /calendar-reload."}


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------

def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/apply")
def apply(request: Request, payload: dict = Body(...)):
    session = session_of(request)
    guild_id = str(payload.get("guild_id") or "")
    if not guild_id:
        raise HTTPException(400, "Pick a server first.")

    bp = core.customize(_load_named(payload.get("file", "")), payload.get("selection") or {})
    report = core.validate(bp)
    content_errors = [e for e in report["errors"] if "content file" in e or "characters" in e]
    if payload.get("content_only"):
        # Republishing text only needs the text to be sendable. Blocking on an
        # unrelated structural error would make a typo unfixable.
        if content_errors:
            raise HTTPException(400, "; ".join(content_errors[:3]))
    elif report["errors"]:
        raise HTTPException(400, "Fix the errors before applying: "
                                 + "; ".join(report["errors"][:3]))

    dry = bool(payload.get("dry_run"))
    server_name = (payload.get("server_name") or "").strip() or None

    icon = None
    icon_name = "icon.png"
    if payload.get("icon"):
        raw = payload["icon"]
        if "," in raw:                       # data:image/png;base64,....
            header, raw = raw.split(",", 1)
            if "jpeg" in header or "jpg" in header:
                icon_name = "icon.jpg"
        try:
            icon = base64.b64decode(raw)
        except Exception:
            raise HTTPException(400, "Could not read that icon file.")

    q: queue.Queue = queue.Queue()

    def log(line=""):
        q.put(("log", str(line)))

    dele = payload.get("delete") or {}
    del_channels = [str(x) for x in dele.get("channels", [])]
    del_roles = [str(x) for x in dele.get("roles", [])]

    content_only = bool(payload.get("content_only"))

    def work():
        try:
            client = core.Client(session["token"], dry_run=dry, log=log)
            prov = core.Provisioner(client, guild_id, bp, log=log)
            if content_only:
                problems = prov.run_content_only(BLUEPRINTS)
            else:
                problems = prov.run(server_name=server_name, icon=icon,
                                    icon_name=icon_name,
                                    delete_channels=del_channels,
                                    delete_roles=del_roles,
                                    content_dir=BLUEPRINTS)
            q.put(("done", {"problems": problems, "dry_run": dry}))
        except core.Failed as e:
            q.put(("failed", str(e)[:1200]))
        except Exception as e:                       # noqa: BLE001
            q.put(("failed", f"{type(e).__name__}: {e}"[:1200]))
        finally:
            q.put((None, None))

    threading.Thread(target=work, daemon=True).start()

    def stream():
        yield _sse("log", f"{'Dry run' if dry else 'Applying'}: "
                          f"{bp.get('meta', {}).get('name', 'blueprint')} "
                          f"-> guild {guild_id}")
        while True:
            kind, data = q.get()
            if kind is None:
                break
            yield _sse(kind, data)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    import uvicorn

    url = f"http://127.0.0.1:{PORT}"

    # Launched by the Restart button: the old process still holds the port for
    # a moment, so wait for it rather than refusing to start.
    if os.environ.get("COPS_WAIT_FOR_PORT"):
        print("  Waiting for the previous window to let go of the port...")
        for _ in range(80):
            if not port_busy(PORT):
                break
            time.sleep(0.25)

    if port_busy(PORT):
        print(f"\n  Something is already using port {PORT}.")
        print(f"  If the setup page is already open, use it: {url}")
        print("  Otherwise close the other program, or start this one with a")
        print("  different port:   set PORT=8771 && python app.py\n")
        raise SystemExit(1)

    banner = (
        f"\n  Steward\n"
        f"  {url}\n\n"
        "  KEEP THIS WINDOW OPEN while you use the page.\n"
        "  Closing it stops the setup page, and the page will say it cannot\n"
        "  reach the setup program.\n\n"
        "  Your bot token stays in this window's memory. It is never written\n"
        "  to disk and never sent back to the browser. Closing this forgets it.\n")
    print(banner, flush=True)
    # On a restart the browser tab is already open and polling, so opening a
    # second one would be the only visible result of pressing the button.
    if not os.environ.get("COPS_WAIT_FOR_PORT"):
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    except KeyboardInterrupt:
        pass
    print("\n  Stopped.")
