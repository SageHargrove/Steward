"""Test suite. No dependencies beyond what the project already needs.

    python tests/run_tests.py

Every check here corresponds to something that either did break, or would
have broken silently against a real server. The onboarding ones in particular
exist because that failure reached a live guild before it was caught.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provision"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core                                          # noqa: E402
from fake_discord import FakeDiscord, install, CATEGORY, TEXT, VOICE, FORUM, ANNOUNCEMENT  # noqa: E402

BLUEPRINT = ROOT / "blueprint" / "giltgrave.yaml"

PASS, FAIL = [], []


def test(name):
    def deco(fn):
        try:
            fn()
            PASS.append(name)
            print(f"  ok    {name}")
        except AssertionError as e:
            FAIL.append((name, str(e) or "assertion failed"))
            print(f"  FAIL  {name}\n        {e}")
        except Exception:
            FAIL.append((name, traceback.format_exc(limit=3)))
            print(f"  ERROR {name}")
            print("        " + traceback.format_exc(limit=3).replace("\n", "\n        "))
        return fn
    return deco


def load(sel=None):
    return core.customize(core.load(BLUEPRINT), sel)


def run(bp, fake=None, **kw):
    fake = fake or install(core, FakeDiscord())
    client = core.Client("token", dry_run=kw.pop("dry_run", False), log=lambda *_: None)
    prov = core.Provisioner(client, fake.guild_id, bp, log=lambda *_: None)
    prov.run(**kw)
    return fake, prov


# ---------------------------------------------------------------------------
print("\nblueprint")

@test("ships valid")
def _():
    r = core.validate(load())
    assert not r["errors"], r["errors"]

@test("has the shape the docs claim")
def _():
    s = core.validate(load())["summary"]
    assert s["channels"] == 21, s
    assert s["categories"] == 7, s
    assert s["community"] is True
    assert s["defaults"] >= 7 and s["defaults_open"] >= 5, s

@test("every onboarding answer grants a role or a channel")
def _():
    # Discord answers ROLE_OR_CHANNEL_REQUIRED otherwise. This reached a live
    # server once; it must never regress.
    for p in load()["onboarding_prompts"]:
        for o in p["options"]:
            assert o.get("roles") or o.get("channels"), f"{p['title']} -> {o['title']}"


# ---------------------------------------------------------------------------
print("\ncustomize")

@test("variables substitute everywhere, including question titles")
def _():
    bp = load({"variables": {"game": "One Trick"}})
    assert bp["onboarding_prompts"][0]["title"] == "What brings you to One Trick?"
    topics = [c.get("topic", "") for cat in bp["categories"] for c in cat["channels"]]
    assert any("One Trick" in t for t in topics)
    assert not any("{{" in t for t in topics), "unsubstituted placeholder left"

@test("a selection built from raw names keeps items whose names hold placeholders")
def _():
    # The UI is handed the raw blueprint, so its keep-lists contain
    # "What brings you to {{game}}?". Substituting before filtering renamed
    # that prompt out from under the list and silently dropped it, which
    # reached a live server as "2 prompts" instead of 3.
    raw = core.load(BLUEPRINT)
    inv = core.inventory(raw)
    assert any("{{" in p["title"] for p in inv["prompts"]), \
        "this test is pointless unless a prompt title still has a placeholder"
    sel = {"variables": {"game": "Giltgrave"},
           "prompts": [p["title"] for p in inv["prompts"]],
           "channels": [c["name"] for cat in inv["categories"] for c in cat["channels"]],
           "roles": [r["name"] for r in inv["roles"]],
           "automod": [a["name"] for a in inv["automod"]],
           "defaults": inv["onboarding_defaults"]}
    out = core.customize(raw, sel)
    assert len(out["onboarding_prompts"]) == len(inv["prompts"]), \
        f"lost a prompt: {[p['title'] for p in out['onboarding_prompts']]}"
    assert out["onboarding_prompts"][0]["title"] == "What brings you to Giltgrave?"
    assert not core.validate(out)["errors"]

@test("unpicked channels are dropped, required ones survive")
def _():
    bp = load({"channels": ["general"]})
    names = [c["name"] for cat in bp["categories"] for c in cat["channels"]]
    assert "general" in names
    assert "off-topic" not in names
    assert "rules" in names and "server-updates" in names, names

@test("required-only-for-community becomes optional when community is off")
def _():
    bp = load({"channels": ["general"], "features": {"community": False, "onboarding": False}})
    names = [c["name"] for cat in bp["categories"] for c in cat["channels"]]
    assert names == ["general"], names

@test("dropping a role prunes it from overwrites, answers and exemptions")
def _():
    keep = [r["name"] for r in core.load(BLUEPRINT)["roles"] if r["name"] != "Mod"]
    bp = load({"roles": keep})
    for entries in bp["overwrite_presets"].values():
        assert all(e["role"] != "Mod" for e in entries)
    for a in bp["automod"]:
        assert "Mod" not in a.get("exempt_roles", [])
    for p in bp["onboarding_prompts"]:
        for o in p["options"]:
            assert "Mod" not in o.get("roles", [])

@test("pruning never leaves an answer granting nothing")
def _():
    # The exact bug: options used to survive with empty roles and be rejected.
    keep = [r["name"] for r in core.load(BLUEPRINT)["roles"]
            if not r["name"].startswith("Found via")]
    bp = load({"roles": keep})
    for p in bp["onboarding_prompts"]:
        for o in p["options"]:
            assert o.get("roles") or o.get("channels"), f"{p['title']} -> {o['title']}"
    assert not core.validate(bp)["errors"]

@test("renaming a channel retargets every reference")
def _():
    bp = load({"renames": {"channels": {"mod-log": "staff-log", "rules": "the-rules"}}})
    assert bp["guild"]["rules_channel"] == "the-rules"
    assert bp["guild"]["safety_alerts_channel"] == "staff-log"
    alerts = [a["alert"] for r in bp["automod"] for a in r["actions"] if "alert" in a]
    assert alerts and set(alerts) == {"staff-log"}, alerts

@test("renaming a role retargets every reference")
def _():
    bp = load({"renames": {"roles": {"Mod": "Warden"}}})
    assert any(r["name"] == "Warden" for r in bp["roles"])
    assert not any(r["name"] == "Mod" for r in bp["roles"])
    assert "Warden" in [e["role"] for e in bp["overwrite_presets"]["readonly"]]
    assert "Warden" in bp["automod"][1]["exempt_roles"]

@test("user-added channels and roles land where asked")
def _():
    bp = load({"additions": {
        "channels": [{"name": "chill", "type": "voice", "category": "VOICE"}],
        "roles": [{"name": "Artist", "color": 0x1ABC9C}]}})
    voice = [c["name"] for cat in bp["categories"] if cat["name"] == "VOICE"
             for c in cat["channels"]]
    assert "chill" in voice, voice
    artist = next(r for r in bp["roles"] if r["name"] == "Artist")
    assert artist["permissions"] == [], "a hand-added role must carry no permissions"

@test("a forum added while community is off is refused, not sent")
def _():
    bp = load({"features": {"community": False, "onboarding": False},
               "additions": {"channels": [{"name": "bugs", "type": "forum",
                                           "category": "PLAY"}]}})
    types = [c.get("type") for cat in bp["categories"] for c in cat["channels"]]
    assert "forum" not in types

@test("added channels can satisfy the onboarding minimum")
def _():
    bp = load({
        "channels": ["general", "screenshots", "hero-showcase", "off-topic"],
        "defaults": ["general", "screenshots", "hero-showcase", "off-topic"],
        "additions": {"channels": [
            {"name": f"chat-{i}", "type": "text", "category": "PLAY", "default": True}
            for i in range(2, 6)]}})
    r = core.validate(bp)
    assert not r["errors"], r["errors"]
    assert r["summary"]["defaults_open"] >= 5


# ---------------------------------------------------------------------------
print("\nvalidate")

@test("catches too few starting channels")
def _():
    errs = core.validate(load({"channels": ["general"]}))["errors"]
    assert any("7" in e for e in errs), errs

@test("catches an answer that grants nothing")
def _():
    bp = load()
    bp["onboarding_prompts"][0]["options"][0] = {"title": "Nothing", "roles": [], "channels": []}
    errs = core.validate(bp)["errors"]
    assert any("neither a role nor a channel" in e for e in errs), errs

@test("catches automod per-trigger limits")
def _():
    bp = load()
    spam = next(r for r in bp["automod"] if r["trigger"] == "spam")
    bp["automod"].append({**spam, "name": "Spam 2"})
    errs = core.validate(bp)["errors"]
    assert any("allows 1" in e for e in errs), errs

@test("catches presets on a trigger that has none")
def _():
    bp = load()
    bp["automod"][1]["presets"] = ["slurs"]
    errs = core.validate(bp)["errors"]
    assert any("keyword_preset" in e for e in errs), errs

@test("catches a timeout on a trigger that cannot time out")
def _():
    bp = load()
    bp["automod"][0]["actions"].append({"timeout": 60})
    errs = core.validate(bp)["errors"]
    assert any("timeout" in e for e in errs), errs

@test("catches forum channels with community off")
def _():
    bp = load()
    bp["guild"]["community"] = False
    errs = core.validate(bp)["errors"]
    assert any("Community mode is off" in e for e in errs), errs


# ---------------------------------------------------------------------------
print("\napply")

@test("phase order: plain channels, then community, then forums, then onboarding")
def _():
    fake, _ = run(load())
    community = fake.index_of("PATCH", "/guilds/5",
                              lambda b: b and "COMMUNITY" in (b.get("features") or []))
    posts = [(i, b) for i, (m, p, b) in enumerate(fake.calls)
             if m == "POST" and p.endswith("/channels")]
    plain = [i for i, b in posts if b.get("type") not in (5, 15, 13)]
    gated = [i for i, b in posts if b.get("type") in (5, 15, 13)]
    onboarding = fake.index_of("PUT", "/guilds/5/onboarding")
    assert community > 0, "community mode was never enabled"
    assert max(plain) < community, "plain channels must be created before community mode"
    assert min(gated) > community, "forum/announcement must come after community mode"
    assert onboarding > max(gated), "onboarding must come last"

@test("onboarding actually applies")
def _():
    fake, prov = run(load())
    assert fake.onboarding is not None, "onboarding was never sent"
    assert len(fake.onboarding["prompts"]) == 3
    assert len(fake.onboarding["default_channel_ids"]) >= 7
    assert not prov.problems, prov.problems

@test("second run updates in place and creates nothing")
def _():
    bp = load()
    fake, _ = run(bp)
    before = (len(fake.channels), len(fake.roles), len(fake.automod))
    fake.calls.clear()
    run(bp, fake=fake)
    after = (len(fake.channels), len(fake.roles), len(fake.automod))
    assert before == after, f"{before} -> {after}: duplicates created"
    assert not [p for m, p, _ in fake.calls if m == "POST" and "auto-moderation" not in p], \
        "second run should not POST"

@test("dry run sends no writes at all")
def _():
    fake, _ = run(load(), dry_run=True)
    writes = [(m, p) for m, p, _ in fake.calls if m in ("POST", "PATCH", "PUT", "DELETE")]
    assert not writes, writes

@test("a failing automod rule does not abort the run")
def _():
    fake = install(core, FakeDiscord())
    fake.fail_on[("POST", "auto-moderation")] = 400
    fake, prov = run(load(), fake=fake)
    assert prov.problems, "should have recorded the failures"
    assert fake.onboarding is not None, "run should have continued to onboarding"

@test("deletes only what was asked, and refuses its own work")
def _():
    fake = install(core, FakeDiscord(channels=[
        {"id": "10", "name": "Text Channels", "type": CATEGORY, "parent_id": None},
        {"id": "12", "name": "General", "type": VOICE, "parent_id": None}]))
    bp = load()
    fake, prov = run(bp, fake=fake, delete_channels=["10", "12"], delete_roles=["5"])
    assert "/channels/10" in fake.deleted and "/channels/12" in fake.deleted
    assert not any("roles/5" in d for d in fake.deleted), "@everyone must never be deleted"
    assert any("@everyone" in p for p in prov.problems)

@test("refuses to delete something this run just created")
def _():
    fake = install(core, FakeDiscord())
    bp = load()
    fake, prov = run(bp, fake=fake)
    made = fake.channel_named("general")["id"]
    fake2, prov2 = run(bp, fake=fake, delete_channels=[made])
    assert not any(made in d for d in fake2.deleted), "deleted a channel it had just made"


# ---------------------------------------------------------------------------
print("\nread_guild")

@test("marks @everyone and bot roles as undeletable")
def _():
    fake = install(core, FakeDiscord(roles=[
        {"id": "5", "name": "@everyone", "managed": False},
        {"id": "99", "name": "Steward", "managed": True},
        {"id": "77", "name": "Random", "managed": False}]))
    got = core.read_guild("token", "5")
    by = {r["name"]: r["deletable"] for r in got["roles"]}
    assert by["@everyone"] is False
    assert by["Steward"] is False, "managed (bot) roles must not be offered for deletion"
    assert by["Random"] is True

@test("reports channel types by name")
def _():
    fake = install(core, FakeDiscord(channels=[
        {"id": "1", "name": "Voice Channels", "type": CATEGORY, "parent_id": None},
        {"id": "2", "name": "General", "type": VOICE, "parent_id": "1"}]))
    got = core.read_guild("token", "5")
    kinds = {c["name"]: c["type"] for c in got["channels"]}
    assert kinds == {"Voice Channels": "category", "General": "voice"}, kinds


# ---------------------------------------------------------------------------
print("\nmanual steps")

@test("every step says where to click")
def _():
    steps = core.manual_steps("123", game="Giltgrave")
    assert len(steps) >= 8
    assert all(s.get("where") for s in steps), "a step with no click path is useless"
    assert any(s.get("copy") for s in steps), "the rules draft should be copyable"

@test("no invented invite URLs for third-party bots")
def _():
    # A wrong invite link sends someone's server to the wrong application.
    for s in core.manual_steps("123"):
        if s.get("url"):
            assert "client_id=123" in s["url"], f"unexpected url: {s['url']}"


# ---------------------------------------------------------------------------
print("\nweb layer")

# The real server on a spare port, driven over real HTTP. This needs no test
# client library, so it runs under whatever interpreter the app itself runs
# under, and it exercises the middleware and streaming for real.
import http.cookiejar                                    # noqa: E402
import json as _json                                     # noqa: E402
import socket                                            # noqa: E402
import threading                                         # noqa: E402
import urllib.error                                      # noqa: E402
import urllib.request                                    # noqa: E402

WEB = None


def _free_port():
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0))
        return s_.getsockname()[1]


def _start_server():
    """Boot ui/app.py in a thread. Returns (base_url, fake) or None."""
    try:
        import uvicorn
        sys.path.insert(0, str(ROOT / "ui"))
        import app as webapp
    except Exception as e:                               # noqa: BLE001
        print(f"  skipped ({type(e).__name__}: pip install -r ui/requirements.txt)")
        return None

    port = _free_port()
    webapp.ORIGINS = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    cfg = uvicorn.Config(webapp.app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()

    for _ in range(100):                                 # wait for the socket
        with socket.socket() as s_:
            if s_.connect_ex(("127.0.0.1", port)) == 0:
                break
        threading.Event().wait(0.05)
    else:
        print("  skipped (server never came up)")
        return None
    return f"http://127.0.0.1:{port}", webapp


class Web:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, origin=None):
        url = self.base + path
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if origin:
            req.add_header("Origin", origin)
        try:
            with self.opener.open(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body, origin=None):
        return self.call("POST", path, body, origin or self.base)


_started = _start_server()
if _started:
    BASE, WEBAPP = _started
    install(core, FakeDiscord())

    @test("serves the page and lists blueprints")
    def _():
        w = Web(BASE)
        assert w.get("/")[0] == 200
        assert "giltgrave.yaml" in w.get("/api/blueprints")[1]

    @test("refuses requests from another origin")
    def _():
        w = Web(BASE)
        code, _body = w.post("/api/preview", {"file": "giltgrave.yaml"},
                             origin="http://evil.test")
        assert code == 403, code

    @test("refuses to read a blueprint outside the blueprint folder")
    def _():
        w = Web(BASE)
        assert w.get("/api/blueprint/..%2f..%2fSETUP.md")[0] == 404

    @test("never returns the token it was given")
    def _():
        w = Web(BASE)
        code, body = w.post("/api/connect", {"token": "supersecret"})
        assert code == 200, body
        assert "supersecret" not in body

    @test("builds the invite link from the bot's own id")
    def _():
        w = Web(BASE)
        url = _json.loads(w.post("/api/connect", {"token": "t"})[1])["invite_url"]
        assert "client_id=4242" in url and "permissions=8" in url, url

    @test("guarded endpoints need a session")
    def _():
        w = Web(BASE)                                    # fresh jar, no cookie
        assert w.get("/api/guilds")[0] == 401
        assert w.post("/api/apply", {"file": "giltgrave.yaml", "guild_id": "5"})[0] == 401

    @test("preview needs no token and reports errors")
    def _():
        w = Web(BASE)
        code, body = w.post("/api/preview",
                            {"file": "giltgrave.yaml", "selection": {"channels": ["general"]}})
        assert code == 200, body
        assert _json.loads(body)["errors"], "a one-channel server should fail onboarding rules"

    @test("apply refuses a selection that would not validate")
    def _():
        w = Web(BASE)
        w.post("/api/connect", {"token": "t"})
        code, _b = w.post("/api/apply", {"file": "giltgrave.yaml", "guild_id": "5",
                                         "selection": {"channels": ["general"]}})
        assert code == 400, code

    @test("apply streams progress and finishes")
    def _():
        fake = install(core, FakeDiscord())
        w = Web(BASE)
        w.post("/api/connect", {"token": "t"})
        code, body = w.post("/api/apply", {"file": "giltgrave.yaml", "guild_id": "5",
                                           "selection": {}, "dry_run": False})
        assert code == 200, body
        events = [_json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
        assert events, "no progress streamed"
        assert isinstance(events[-1], dict) and "problems" in events[-1], events[-1]
        assert fake.onboarding is not None, "onboarding never reached Discord"

    @test("health reports whether a session exists")
    def _():
        w = Web(BASE)
        assert _json.loads(w.get("/api/health")[1]) == {"ok": True, "connected": False}
        w.post("/api/connect", {"token": "t"})
        assert _json.loads(w.get("/api/health")[1])["connected"] is True

    @test("reads what is already in the server")
    def _():
        install(core, FakeDiscord(channels=[
            {"id": "1", "name": "Voice Channels", "type": 4, "parent_id": None},
            {"id": "2", "name": "General", "type": 2, "parent_id": "1"}]))
        w = Web(BASE)
        w.post("/api/connect", {"token": "t"})
        code, body = w.get("/api/existing?guild_id=5")
        assert code == 200, body
        names = {c["name"] for c in _json.loads(body)["channels"]}
        assert {"Voice Channels", "General"} <= names, names


# ---------------------------------------------------------------------------
print("\npage")

@test("javascript parses and every inline handler exists")
def _():
    import re
    import subprocess
    import tempfile
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "check.js"
        f.write_text(js, encoding="utf-8")
        try:
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:400]
        except FileNotFoundError:
            pass                                     # node not installed, skip the parse
    called = set(re.findall(r'on(?:click|change|input|keydown)="[^"]*?(\w+)\(', html))
    defined = set(re.findall(r"function\s+(\w+)", js))
    missing = called - defined - {"if", "event"}
    assert not missing, f"handlers with no function: {sorted(missing)}"
    ids_used = set(re.findall(r"\$\('#(\w+)'\)", js))
    ids_have = set(re.findall(r'id="(\w+)"', html))
    assert not (ids_used - ids_have), f"missing elements: {sorted(ids_used - ids_have)}"


# ---------------------------------------------------------------------------
print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("\nfailures:")
    for name, why in FAIL:
        print(f"  {name}: {why.splitlines()[0] if why else ''}")
    sys.exit(1)
