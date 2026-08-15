"""
Server Setup for Discord: a local UI over the community-ops blueprint.

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
import secrets
import socket
import sys
import threading
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

app = FastAPI(title="Server Setup for Discord", docs_url=None, redoc_url=None)

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


@app.get("/api/health")
def health(request: Request):
    """The page polls this so it can tell "the program stopped" apart from
    "something went wrong", which the browser reports identically as the
    unhelpful "Failed to fetch"."""
    sid = request.cookies.get("cops_session")
    return {"ok": True, "connected": bool(sid and sid in SESSIONS)}


# --------------------------------------------------------------------------
# Blueprints
# --------------------------------------------------------------------------

@app.get("/api/blueprints")
def list_blueprints():
    out = []
    for p in sorted(BLUEPRINTS.glob("*.yaml")):
        try:
            bp = core.load(p)
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


@app.get("/api/manual")
def manual(request: Request, game: str = "the game", mod_channel: str = "mod-log"):
    app_id = None
    sid = request.cookies.get("cops_session")
    if sid and sid in SESSIONS:
        app_id = SESSIONS[sid]["bot"].get("id")
    return core.manual_steps(app_id, game=game, mod_channel=mod_channel)


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
    if report["errors"]:
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

    def work():
        try:
            client = core.Client(session["token"], dry_run=dry, log=log)
            prov = core.Provisioner(client, guild_id, bp, log=log)
            problems = prov.run(server_name=server_name, icon=icon, icon_name=icon_name,
                                delete_channels=del_channels, delete_roles=del_roles)
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

    if port_busy(PORT):
        print(f"\n  Something is already using port {PORT}.")
        print(f"  If the setup page is already open, use it: {url}")
        print("  Otherwise close the other program, or start this one with a")
        print(f"  different port:   set PORT=8771 && python app.py\n")
        raise SystemExit(1)

    banner = (
        f"\n  Server Setup for Discord\n"
        f"  {url}\n\n"
        "  KEEP THIS WINDOW OPEN while you use the page.\n"
        "  Closing it stops the setup page, and the page will say it cannot\n"
        "  reach the setup program.\n\n"
        "  Your bot token stays in this window's memory. It is never written\n"
        "  to disk and never sent back to the browser. Closing this forgets it.\n")
    print(banner, flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    except KeyboardInterrupt:
        pass
    print("\n  Stopped.")
