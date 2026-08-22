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

BLUEPRINT = ROOT / "blueprint" / "default.yaml"

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
    assert s["channels"] == 20, s
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
    sel = {"variables": {"game": "Testgame"},
           "prompts": [p["title"] for p in inv["prompts"]],
           "channels": [c["name"] for cat in inv["categories"] for c in cat["channels"]],
           "roles": [r["name"] for r in inv["roles"]],
           "automod": [a["name"] for a in inv["automod"]],
           "defaults": inv["onboarding_defaults"]}
    out = core.customize(raw, sel)
    assert len(out["onboarding_prompts"]) == len(inv["prompts"]), \
        f"lost a prompt: {[p['title'] for p in out['onboarding_prompts']]}"
    assert out["onboarding_prompts"][0]["title"] == "What brings you to Testgame?"
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
        "channels": ["general", "screenshots", "strategy", "off-topic"],
        "defaults": ["general", "screenshots", "strategy", "off-topic"],
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

@test("catches community-only channel types with community off")
def _():
    """Forum, media, announcement and stage. Media was left out of the gated
    set once, and the only symptom was a channel that never appeared."""
    for kind in ("forum", "media", "announcement", "stage"):
        bp = load()
        bp["guild"]["community"] = False
        bp["categories"] = [{"name": "PLAY",
                             "channels": [{"name": "x", "type": kind}]}]
        errs = core.validate(bp)["errors"]
        assert any("need Community mode" in e for e in errs), (kind, errs)


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

@test("every channel a shipped blueprint asks for actually gets built")
def _():
    """The check that would have caught #lucky-pulls.

    It is a media channel, media was not in the set of types Discord refuses
    outside a Community server, so it was created in the pass that runs before
    Community mode is on. Discord said no, the run carried on, and the only
    trace was a channel that was not there. Every blueprint, every channel.
    """
    import glob
    from fake_discord import FakeDiscord, install as _install
    for path in sorted(glob.glob(str(ROOT / "blueprint" / "*.yaml"))):
        if path.endswith(".local.yaml"):
            continue
        bp = core.customize(core.load(path), None)
        fake = _install(core, FakeDiscord())
        client = core.Client("t", dry_run=False, log=lambda *_: None)
        core.Provisioner(client, fake.guild_id, bp,
                         log=lambda *_: None).run(content_dir=None)
        built = {c.get("name") for c in fake.channels}
        for cat in bp["categories"]:
            for ch in cat["channels"]:
                assert ch["name"] in built, (
                    f"{Path(path).name}: #{ch['name']} ({ch.get('type', 'text')}) "
                    f"was asked for and never created")


@test("the fake refuses the same channel types Discord refuses")
def _():
    """core decides which pass a channel is built in; the fake decides whether
    that was allowed. They were allowed to drift once and the result was a
    blind spot rather than a failure."""
    import fake_discord as fd
    numbers = {core.CHANNEL_TYPES[name] for name in core.COMMUNITY_GATED}
    assert numbers == fd.GATED_TYPES, (numbers, fd.GATED_TYPES)


@test("a refused create is a failure, not a silently skipped channel")
def _():
    """The fake used to hand a rejection back as a 200 with an error body, so
    the provisioner counted a refused channel as a created one."""
    from fake_discord import FakeDiscord, install as _install
    bp = core.customize(core.load(BLUEPRINT), None)
    bp["guild"]["community"] = False        # nothing gated may be created now
    bp["categories"] = [{"name": "PLAY",
                         "channels": [{"name": "wall", "type": "media"}]}]
    fake = _install(core, FakeDiscord())
    client = core.Client("t", dry_run=False, log=lambda *_: None)
    problems = core.Provisioner(client, fake.guild_id, bp,
                                log=lambda *_: None).run(content_dir=None)
    assert "wall" not in {c.get("name") for c in fake.channels}
    assert any("wall" in p for p in problems), \
        f"a channel Discord refused was not reported: {problems}"


@test("every ping role can be picked up by the person who wants it")
def _():
    """#pick-your-roles explained five ping roles and there was no way to take
    one. Four of the five appeared in no onboarding question at all, so the
    only route to them was a moderator granting them by hand.

    An onboarding question is the answer, and not only during the join flow:
    Discord keeps every question in the Channels & Roles tab afterwards, which
    makes it a self-serve panel that needs no bot.
    """
    import glob
    for path in sorted(glob.glob(str(ROOT / "blueprint" / "*.yaml"))):
        if path.endswith(".local.yaml"):
            continue
        bp = core.customize(core.load(path), None)
        granted = {r for p in bp.get("onboarding_prompts", [])
                   for o in p.get("options", []) for r in o.get("roles", [])}
        for role in bp.get("roles", []):
            if not role["name"].endswith("Alerts"):
                continue
            assert role["name"] in granted, (
                f"{Path(path).name}: @{role['name']} is a ping role nobody can "
                f"give themselves. Put it in an onboarding question")


@test("a question can be kept out of the join flow and left in Channels & Roles")
def _():
    """in_onboarding was hardcoded to True, so the flag every blueprint already
    carried did nothing. False is what makes a question a role picker and
    nothing else."""
    bp = load()
    bp["onboarding_prompts"] = [
        {"title": "in the flow", "options": [
            {"title": "a", "roles": ["Mod"]}, {"title": "b", "roles": ["Dev"]}]},
        {"title": "picker only", "in_onboarding": False, "options": [
            {"title": "a", "roles": ["Mod"]}, {"title": "b", "roles": ["Dev"]}]},
    ]
    fake, _ = run(bp)
    sent = next(b for m, p, b in fake.calls
                if m == "PUT" and p.endswith("/onboarding"))
    by_title = {p["title"]: p for p in sent["prompts"]}
    assert by_title["in the flow"]["in_onboarding"] is True
    assert by_title["picker only"]["in_onboarding"] is False


@test("a variant can add an answer without restating the question")
def _():
    """The gacha needed one more ping than the Roblox blueprint it extends.
    Without this it had to copy all three questions to change one of them, and
    a later edit upstream would not have reached the copy."""
    bp = core.customize(core.load(ROOT / "blueprint" / "roblox-gacha.yaml"), None)
    pings = next(p for p in bp["onboarding_prompts"]
                 if p["title"] == "Which pings do you want?")
    titles = [o["title"] for o in pings["options"]]
    assert titles == ["Codes", "Updates", "Events", "Giveaways", "Banners"], titles
    parent = core.customize(core.load(ROOT / "blueprint" / "roblox-game.yaml"), None)
    upstream = next(p for p in parent["onboarding_prompts"]
                    if p["title"] == "Which pings do you want?")
    assert len(upstream["options"]) == 4, "the append leaked into the parent"


@test("no pinned post sends people to a channel this server does not build")
def _():
    """A #mention of a channel that is not there is the first thing a new
    member notices, and the prose lives in a separate file from the blueprint
    so nothing else connects the two.

    Checked against the blueprint this checkout actually deploys, the one
    carrying meta.default. The shared welcome text is tailored to whichever
    project the checkout is for, so holding every blueprint to it would be
    holding them to somebody else's channel list.
    """
    import re as _re
    sys.path.insert(0, str(ROOT / "ui"))
    import app as webapp
    bp = core.customize(webapp.load_active(), None)
    if not bp.get("categories"):
        return
    built = {c["name"] for cat in bp["categories"] for c in cat["channels"]}
    for cat in bp["categories"]:
        for ch in cat["channels"]:
            rel = ch.get("content_file")
            if not rel:
                continue
            raw = (ROOT / "blueprint" / rel).read_text(encoding="utf-8")
            body = _re.sub(r"<!--.*?-->", "", raw, flags=_re.S)
            for name in _re.findall(r"#([a-z][a-z0-9-]{2,})", body):
                assert name in built, (
                    f"{rel}, pinned in #{ch['name']}, sends people to #{name}, "
                    f"which this blueprint does not build")


@test("no pinned post promises a panel this tool never posts")
def _():
    """#pick-your-roles had a pin describing a reaction-role panel that nothing
    here ever posted. The roles are picked in Discord's own Channels & Roles
    tab, and the prose has to say the thing that is true."""
    import glob
    for path in sorted(glob.glob(str(ROOT / "blueprint" / "content" / "*.md"))):
        body = Path(path).read_text(encoding="utf-8").split("-->")[-1]
        assert "reaction role" not in body.lower(),             f"{Path(path).name} promises a reaction-role panel"


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

@test("the shipped tiers work on a server with no boosts")
def _():
    # Fades and the animated style need three boosts. A default that quietly
    # depends on them would look broken on most servers.
    styled = [r["name"] for r in core.load(BLUEPRINT)["roles"] if r.get("colors")]
    assert not styled, f"the default asks for boost-only styles: {styled}"


@test("every tier has a colour of its own")
def _():
    tiers = {r["role"] for r in core.load(BLUEPRINT)["levels"]["rewards"]}
    colours = [r["color"] for r in core.load(BLUEPRINT)["roles"]
               if r["name"] in tiers]
    assert len(colours) == len(tiers), "a tier is missing from the roles list"
    assert len(set(colours)) == len(colours), "two tiers share a colour"


@test("a server without the perk still gets its roles")
def _():
    # Enhanced styles need three boosts. Sending them anyway would fail the
    # whole role, so they are dropped and the plain colour is used.
    fake = install(core, FakeDiscord())
    bp = load()
    fake, prov = run(bp, fake=fake)
    sent = [b for m, q, b in fake.calls if m == "POST" and q.endswith("/roles")]
    assert sent, "no roles created"
    assert not any("colors" in b for b in sent), (
        "gradients were sent to a server that has not unlocked them")
    assert any(b["name"] == "Tier 5" for b in sent), "the top tier was skipped"


@test("with the perk, a style set on a role is sent")
def _():
    fake = install(core, FakeDiscord())
    fake.guild["features"] = [core.ENHANCED_ROLE_COLORS]
    bp = load({"colors": {"Tier 5": {"holographic": True},
                          "Tier 4": {"color": 0x8B5CF6, "secondary": 0x3B82F6}}})
    fake, prov = run(bp, fake=fake)
    sent = {b["name"]: b for m, q, b in fake.calls
            if m == "POST" and q.endswith("/roles")}
    assert sent["Tier 5"]["colors"] == core.HOLOGRAPHIC, "holographic never sent"
    assert "secondary_color" in sent["Tier 4"]["colors"], "gradient never sent"
    assert "colors" not in sent["Dev"], "a plain role should not carry a style"


@test("the UI can recolour any role, not only ones it added")
def _():
    bp = load({"colors": {"Mod": {"color": 0xFF0000},
                          "Veteran": {"color": 0x00FF00, "secondary": 0x0000FF},
                          "Playtester": {"holographic": True}}})
    by = {r["name"]: r for r in bp["roles"]}
    assert by["Mod"]["color"] == 0xFF0000
    assert core.role_colors(by["Veteran"])["secondary_color"] == 0x0000FF
    assert core.role_colors(by["Playtester"]) == core.HOLOGRAPHIC


@test("roles are ordered below the bot's own role, not from the top")
def _():
    # Numbering from the top asks Discord to place a role above the bot, which
    # rejects the WHOLE batch and silently leaves every role where it was.
    fake = install(core, FakeDiscord())
    fake.bot_role_position = 30
    bp = load()
    fake, prov = run(bp, fake=fake)
    patch = next((b for m, p, b in fake.calls
                  if m == "PATCH" and p == "/guilds/5/roles"), None)
    assert patch, "role positions were never sent"
    positions = [e["position"] for e in patch]
    assert max(positions) < 30, f"asked for a slot at or above the bot: {max(positions)}"
    assert positions == sorted(positions, reverse=True), "order must be descending"
    assert len(set(positions)) == len(positions), "positions must be distinct"


@test("says what to do when there is no room below the bot")
def _():
    fake = install(core, FakeDiscord())
    fake.bot_role_position = 2          # almost at the bottom
    bp = load()
    fake, prov = run(bp, fake=fake)
    patch = next((b for m, p, b in fake.calls
                  if m == "PATCH" and p == "/guilds/5/roles"), None)
    assert patch is None, "should not attempt an ordering that cannot fit"


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
    assert any("general" in p for p in prov2.problems), \
        f"the warning should name the channel, got: {prov2.problems}"


@test("the delete queue drops anything no longer offered")
def _():
    # Marking a channel for deletion and then adding one with the same name
    # used to hide the row but leave the id queued, so a build asked to create
    # and delete the same thing. The page prunes the queue on every redraw.
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "const offered = {channels:" in html, "the prune step is missing"
    body = html[html.index("function renderExisting"):html.index("function toggleDelete")]
    assert body.index("SEL.delete[kind].filter") < body.index("if(!chans.length"), \
        "the queue must be pruned before the early return, or a cleared list never prunes"


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
print("\nchannel content")

@test("rules and welcome text fit Discord's message limit")
def _():
    bp = load()
    base = Path(bp["_base_dir"])
    # An embed description holds 4096; a plain message only 2000. Which limit
    # applies depends on whether an accent colour is set.
    limit = core.EMBED_DESC_LIMIT if bp.get("meta", {}).get("accent_color") else 2000
    found = 0
    for cat in bp["categories"]:
        for ch in cat["channels"]:
            if not ch.get("content_file"):
                continue
            found += 1
            blocks = core.split_content(core.substitute_text(
                (base / ch["content_file"]).read_text(encoding="utf-8"), bp["variables"]))
            assert blocks, f"{ch['content_file']} produced nothing"
            for i, b in enumerate(blocks, 1):
                assert len(b) <= limit, (
                    f"{ch['content_file']} section {i} is {len(b)} chars, limit {limit}")
    assert found >= 5, f"only {found} channels have content"


@test("editor notes at the top of a content file are not posted")
def _():
    out = core.split_content("<!--\n  a note to whoever edits this\n-->\n# Real title\nbody")
    assert out == ["# Real title\nbody"], out


@test("content files get variables filled in")
def _():
    bp = load({"variables": {"game": "One Trick"}})
    base = Path(bp["_base_dir"])
    ch = next(c for cat in bp["categories"] for c in cat["channels"]
              if c.get("content_file", "").endswith("rules.md"))
    text = core.substitute_text(
        (base / ch["content_file"]).read_text(encoding="utf-8"), bp["variables"])
    assert "One Trick" in text
    assert "{{game}}" not in text


@test("content is posted, pinned, and edited rather than duplicated on a re-run")
def _():
    bp = load()
    fake, _ = run(bp, content_dir=Path(bp["_base_dir"]))
    posts = [(p, b) for m, p, b in fake.calls
             if m == "POST" and p.endswith("/messages")]
    assert posts, "nothing was posted"
    pins = [p for m, p, _ in fake.calls if m == "PUT" and "/pins/" in p]
    assert pins, "the first message was never pinned"

    first_count = len(posts)
    fake.calls.clear()
    run(bp, fake=fake, content_dir=Path(bp["_base_dir"]))
    reposts = [p for m, p, b in fake.calls if m == "POST" and p.endswith("/messages")]
    edits = [p for m, p, b in fake.calls if m == "PATCH" and "/messages/" in p]
    assert not reposts, f"re-run posted {len(reposts)} duplicate message(s)"
    # Every pinned message is rewritten, and so is each forum starter post,
    # whose opening message shares its thread id.
    assert len(edits) >= first_count, f"expected at least {first_count} edits, got {len(edits)}"


@test("an oversized section is refused before anything is sent")
def _():
    bp = load()
    ch = next(c for cat in bp["categories"] for c in cat["channels"]
              if c.get("content_file"))
    big = Path(bp["_base_dir"]) / "content" / "_oversize_test.md"
    big.write_text("x" * (core.EMBED_DESC_LIMIT + 200), encoding="utf-8")
    try:
        ch["content_file"] = "content/_oversize_test.md"
        errs = core.validate(bp)["errors"]
        assert any("characters" in e and "limit" in e for e in errs), errs
    finally:
        big.unlink()


@test("editor notes never reach the channel")
def _():
    # The marker used to be an HTML comment, so a note that mentioned it closed
    # its own comment early and leaked the rest of the note into #rules.
    bp = load()
    base = Path(bp["_base_dir"])
    for f in sorted(base.glob("content/*.md")):
        blocks = core.split_content(f.read_text(encoding="utf-8"))
        joined = " ".join(blocks)
        assert "<!--" not in joined and "-->" not in joined, f"{f.name} leaks a comment"
        assert "STARTING POINT" not in joined, f"{f.name} leaks its editor note"
        assert core.SPLIT_MARKER not in joined, f"{f.name} leaks the split marker"
        if blocks:
            assert not blocks[0].startswith("starts a new"), (
                f"{f.name} starts mid-sentence, so a comment was cut short")


@test("posted content can never ping anyone")
def _():
    # The rules literally contain the word everyone, and the bot posts them
    # with Administrator. Without this, publishing the rules mass-pings.
    bp = load()
    fake, _ = run(bp, content_dir=Path(bp["_base_dir"]))
    writes = [b for m, p, b in fake.calls
              if m in ("POST", "PATCH") and "/messages" in p and b]
    assert writes, "nothing was written"
    for b in writes:
        assert b.get("allowed_mentions") == {"parse": []}, b
    threads = [b for m, p, b in fake.calls if m == "POST" and p.endswith("/threads")]
    for t in threads:
        assert t["message"].get("allowed_mentions") == {"parse": []}, t


@test("a long document is not split into a stack of posts")
def _():
    bp = load()
    base = Path(bp["_base_dir"])
    rules = next(c for cat in bp["categories"] for c in cat["channels"]
                 if c.get("content_file", "").endswith("rules.md"))
    blocks = core.split_content(core.substitute_text(
        (base / rules["content_file"]).read_text(encoding="utf-8"), bp["variables"]))
    color = bp["meta"]["accent_color"]
    msgs = core.pack_messages(blocks, color)
    assert len(msgs) == 1, f"the rules should be one message, got {len(msgs)}"
    for m in msgs:
        assert len(m["embeds"]) <= core.EMBEDS_PER_MESSAGE
        total = sum(len(e.get("title", "")) + len(e["description"]) for e in m["embeds"])
        assert total <= core.EMBED_TOTAL_PER_MESSAGE, total


@test("a markdown heading becomes the embed title")
def _():
    e = core.as_embed("# Server Rules" + chr(10) * 2 + "body text here", 0xC9A227)
    assert e["title"] == "Server Rules"
    assert e["description"] == "body text here"
    assert e["color"] == 0xC9A227
    plain = core.as_embed("no heading here", 0)
    assert "title" not in plain


@test("forum starter posts are created once, not on every run")
def _():
    bp = load()
    fake, _ = run(bp, content_dir=Path(bp["_base_dir"]))
    made = [b["name"] for m, p, b in fake.calls
            if m == "POST" and p.endswith("/threads")]
    assert len(made) == 2, made

    # the fake should now report them as active threads
    for m, p, b in fake.calls:
        if m == "POST" and p.endswith("/threads"):
            pass
    fake.calls.clear()
    run(bp, fake=fake, content_dir=Path(bp["_base_dir"]))
    again = [b["name"] for m, p, b in fake.calls
             if m == "POST" and p.endswith("/threads")]
    assert not again, f"re-run duplicated forum posts: {again}"


@test("reworded text updates in place instead of posting again")
def _():
    # Discord will not let a human edit a bot's message, so the only way to fix
    # a typo is for the bot to rewrite its own. Re-posting would leave the
    # mistake sitting above the correction forever.
    bp = load()
    base = Path(bp["_base_dir"])
    rules = base / "content" / "rules.md"
    backup = rules.read_text(encoding="utf-8")
    try:
        fake, _ = run(bp, content_dir=base)
        first = len([q for m, q, _ in fake.calls
                     if m == "POST" and q.endswith("/messages")])
        assert first, "nothing was posted the first time"

        # Append a marker rather than swapping a phrase, so rewording the
        # rules never breaks this test.
        marker = "Ledger regression marker, safe to delete."
        rules.write_text(backup.rstrip() + "\n\n" + marker + "\n", encoding="utf-8")
        fake.calls.clear()
        prov = core.Provisioner(core.Client("t", log=lambda *_: None),
                                fake.guild_id, load(), log=lambda *_: None)
        prov.run_content_only(base)

        posts = [q for m, q, _ in fake.calls if m == "POST" and q.endswith("/messages")]
        edits = [q for m, q, _ in fake.calls if m == "PATCH" and "/messages/" in q]
        assert not posts, f"republish created {len(posts)} duplicate message(s)"
        assert edits, "nothing was edited"
        import json as _j
        body = _j.dumps(fake.messages, ensure_ascii=False)
        assert marker in body, "the new wording never reached Discord"
    finally:
        rules.write_text(backup, encoding="utf-8")


@test("a forum starter post is rewritten, not duplicated")
def _():
    bp = load()
    base = Path(bp["_base_dir"])
    fake, _ = run(bp, content_dir=base)
    fake.calls.clear()
    prov = core.Provisioner(core.Client("t", log=lambda *_: None),
                            fake.guild_id, load(), log=lambda *_: None)
    prov.run_content_only(base)
    threads = [q for m, q, _ in fake.calls if m == "POST" and q.endswith("/threads")]
    assert not threads, "republish opened a second starter post"
    edits = [q for m, q, _ in fake.calls if m == "PATCH" and "/messages/" in q]
    assert any(q.split("/")[2] == q.split("/")[4] for q in edits), (
        "a forum starter message was never rewritten")


@test("content editing cannot reach outside the blueprint folder")
def _():
    try:
        sys.path.insert(0, str(ROOT / "ui"))
        import app as webapp
    except Exception:                                      # noqa: BLE001
        return                                             # ui deps missing
    for bad in ("../../secrets.md", "default.yaml", "content/../../core.py"):
        try:
            webapp._content_path(bad)
            raise AssertionError(f"accepted {bad!r}")
        except AssertionError:
            raise
        except Exception:
            pass
    assert webapp._content_path("content/rules.md").name == "rules.md"


@test("a permanent invite is created and reused")
def _():
    # Discord's default invite expires after 7 days, which is how a dead link
    # ends up on a store page.
    bp = load()
    fake, prov = run(bp)
    made = [b for m, q, b in fake.calls if m == "POST" and q.endswith("/invites")]
    assert made, "no invite was created"
    assert made[0]["max_age"] == 0 and made[0]["max_uses"] == 0, made[0]
    assert prov.invite_url_made and prov.invite_url_made.startswith("https://discord.gg/")

    fake.calls.clear()
    run(bp, fake=fake)
    again = [q for m, q, _ in fake.calls if m == "POST" and q.endswith("/invites")]
    assert not again, "a second invite was created on re-run"


@test("the server owner is given every role meant for them")
def _():
    bp = load()
    fake, prov = run(bp)
    byid = {v: k for k, v in prov.roles.items()}
    given = {byid.get(q.rsplit("/", 1)[1]) for m, q, _ in fake.calls
             if m == "PUT" and "/roles/" in q and "/members/" in q}
    wanted = set(bp["guild"]["owner_roles"])
    assert wanted <= given, f"owner missing {wanted - given}"


@test("level settings and thresholds are editable, not blueprint-only")
def _():
    # They were invisible from the setup page, so the only way to change a
    # threshold was to open the YAML.
    inv = core.inventory(core.load(BLUEPRINT))
    assert inv["levels"]["noun"], "the noun is not exposed to the UI"
    assert inv["levels"]["rewards"], "the thresholds are not exposed to the UI"
    bp = load({"levels": {"noun": "Rank",
                          "xp_per_message": [5, 9],
                          "rewards": {"Veteran": 12}}})
    assert bp["levels"]["noun"] == "Rank"
    assert bp["levels"]["xp_per_message"] == [5, 9]
    assert bp["levels"]["rewards"] == [{"level": 12, "role": "Veteran"}]


@test("a reward pointing at a removed role is dropped")
def _():
    keep = [r["name"] for r in core.load(BLUEPRINT)["roles"]
            if not r["name"].startswith("Tier ")]
    bp = load({"roles": keep})
    assert bp["levels"]["rewards"] == [], (
        "rewards still point at roles that will not exist")
    assert not core.validate(bp)["errors"]


@test("renaming a role carries its level threshold with it")
def _():
    # A threshold belongs to the role, not to its name. Without this, renaming
    # a tier silently stopped it ever being granted.
    star1 = "Tier 1"
    bp = load({"renames": {"roles": {star1: "Bronze"}}})
    rewards = {r["role"]: r["level"] for r in bp["levels"]["rewards"]}
    assert "Bronze" in rewards, f"threshold was stranded: {rewards}"
    assert star1 not in rewards
    assert not core.validate(bp)["errors"]


@test("a role you added can be a level reward")
def _():
    bp = load({"additions": {"roles": [{"name": "Regular", "color": 0x00FF00}]},
               "levels": {"rewards": {"Regular": 15}}})
    assert any(r["name"] == "Regular" for r in bp["roles"])
    assert {"level": 15, "role": "Regular"} in bp["levels"]["rewards"]
    assert not core.validate(bp)["errors"]


@test("a threshold on a role that exists nowhere is dropped")
def _():
    bp = load({"levels": {"rewards": {"Nonexistent": 5}}})
    assert bp["levels"]["rewards"] == [], bp["levels"]["rewards"]


@test("thresholds come back in unlock order")
def _():
    bp = load({"levels": {"rewards": {"Veteran": 30, "Playtester": 2,
                                      "Content Creator": 9}}})
    assert [r["role"] for r in bp["levels"]["rewards"]] == [
        "Playtester", "Content Creator", "Veteran"]


@test("any role can be a reward, not only the star tiers")
def _():
    bp = load({"levels": {"rewards": {"Veteran": 12}}})
    assert bp["levels"]["rewards"] == [{"level": 12, "role": "Veteran"}]
    assert not core.validate(bp)["errors"]


@test("join-raid alerts are left switched on")
def _():
    # RAID_ALERTS_DISABLED is the off switch, so it must be absent.
    bp = load()
    fake, _ = run(bp)
    call = next(b for m, q, b in fake.calls
                if m == "PATCH" and q == "/guilds/5" and b and "features" in b)
    assert "COMMUNITY" in call["features"]
    assert "RAID_ALERTS_DISABLED" not in call["features"],         "raid alerts were switched off"


@test("the welcome screen is set from the blueprint")
def _():
    bp = load()
    fake, _ = run(bp)
    call = next((b for m, p, b in fake.calls
                 if m == "PATCH" and p.endswith("/welcome-screen")), None)
    assert call, "welcome screen was never set"
    assert call["enabled"] is True
    assert 1 <= len(call["welcome_channels"]) <= 5, call["welcome_channels"]
    assert all(c["channel_id"] for c in call["welcome_channels"])


@test("join notices are pointed at a channel and setup tips silenced")
def _():
    bp = load()
    fake, _ = run(bp)
    call = next(b for m, p, b in fake.calls
                if m == "PATCH" and p == "/guilds/5" and b and "features" in b)
    assert call.get("system_channel_id"), "system channel was never set"
    flags = call.get("system_channel_flags", 0)
    assert flags & core.SYSTEM_CHANNEL_FLAGS["suppress_setup_tips"], \
        "Discord's setup-tip nagging was left on"
    assert not flags & core.SYSTEM_CHANNEL_FLAGS["suppress_join_notifications"], \
        "join messages should stay on; a small server feels alive when people arrive"


# ---------------------------------------------------------------------------
print("\nmanual steps")

@test("every step says where to click")
def _():
    steps = core.manual_steps("123", core.load(BLUEPRINT))
    assert len(steps) >= 8
    assert all(s.get("where") for s in steps), "a step with no click path is useless"
    assert all(s.get("why") for s in steps), "a step with no reason is an order"

@test("the screening rules come from a file, not from code")
def _():
    # Baked into a function, fixing a typo meant editing Python and restarting
    # the setup page, which silently served the old text for a while.
    bp = core.load(BLUEPRINT)
    step = next(s for s in core.manual_steps(None, bp) if s.get("copy"))
    entries = [e for e in step["copy"].split(chr(10) + chr(10)) if e.strip()]
    assert len(entries) == 16, f"Discord allows 16 rules, file has {len(entries)}"
    for e in entries:
        lines = e.strip().split(chr(10))
        assert len(lines) >= 2, f"rule needs a title and a description: {e!r}"
        assert len(lines[0]) <= 100, f"title too long: {lines[0]!r}"
    # and editing the file changes the output without touching code
    path = Path(bp["_base_dir"]) / "content" / "rules-screening.md"
    assert path.is_file(), path

@test("the checklist lives in the blueprint and is read fresh")
def _():
    bp = core.load(BLUEPRINT)
    assert bp.get("manual_steps"), "the checklist should be blueprint data"
    edited = {**bp, "manual_steps": [{"kind": "setting", "title": "Only step",
                                      "why": "because", "where": ["click"]}]}
    out = core.manual_steps(None, edited)
    assert [s["title"] for s in out] == ["Only step"], out

@test("checklist text gets variables filled in")
def _():
    bp = core.load(BLUEPRINT)
    bp = {**bp, "variables": {**bp.get("variables", {}), "game": "One Trick"}}
    text = " ".join(s["why"] + " ".join(s.get("where", []))
                    for s in core.manual_steps(None, bp))
    assert "{{game}}" not in text, "a placeholder reached the checklist"

@test("no invented invite URLs for third-party bots")
def _():
    # A wrong invite link sends someone's server to the wrong application.
    for s in core.manual_steps("123", core.load(BLUEPRINT)):
        if s.get("url"):
            assert "client_id=123" in s["url"], f"unexpected url: {s['url']}"

@test("nothing published to Discord uses an em dash")
def _():
    # A house style rule, and the content files are the one place text goes
    # out under someone else's name.
    bp = core.load(BLUEPRINT)
    base = Path(bp["_base_dir"])
    for f in sorted(base.glob("content/*.md")):
        body = " ".join(core.split_content(f.read_text(encoding="utf-8")))
        assert "—" not in body, f"{f.name} contains an em dash"

@test("the rules are generic enough to reuse")
def _():
    # The blueprint is a template. Rules naming one game's mechanics make it
    # someone else's editing job before they can use it.
    bp = core.load(BLUEPRINT)
    base = Path(bp["_base_dir"])
    for name in ("content/rules.md", "content/rules-screening.md"):
        body = (base / name).read_text(encoding="utf-8")
        posted = core.split_content(body)
        text = " ".join(posted).lower()
        for word in ("giltgrave", "gacha", "tower", "floor 40", "hero-showcase"):
            assert word not in text, f"{name} still mentions {word!r}"


# ---------------------------------------------------------------------------
print("\nledger")

sys.path.insert(0, str(ROOT / "steward"))
from ledger import Ledger                                # noqa: E402
import tempfile                                          # noqa: E402
import time as _time                                     # noqa: E402


def fresh_ledger():
    d = tempfile.mkdtemp()
    return Ledger(Path(d) / "test.sqlite3")


@test("records events and counts them")
def _():
    L = fresh_ledger()
    L.touch_member(1, 100, int(_time.time()))
    L.record(guild_id=1, user_id=100, channel_id=7, event_type="message")
    L.record(guild_id=1, user_id=100, channel_id=7, event_type="message")
    L.record(guild_id=1, user_id=100, channel_id=8, event_type="voice_join")
    c = L.counts(1)
    assert c["events"] == 3, c
    assert c["by_type"] == {"message": 2, "voice_join": 1}, c["by_type"]
    L.close()


@test("the join funnel is four honest numbers")
def _():
    L = fresh_ledger()
    now = int(_time.time())
    for uid in (1, 2, 3, 4):
        L.touch_member(1, uid, now - 3600)
    L.mark(1, 1, "onboarding_completed_at", now)
    L.mark(1, 2, "onboarding_completed_at", now)
    L.mark(1, 1, "first_message_at", now)
    L.mark(1, 4, "last_left_at", now, first_only=False)
    f = L.funnel(1, cohort_days=7)
    assert f == {"joined": 4, "onboarded": 2, "posted": 1, "left_server": 1}, f
    L.close()


@test("first_message_at keeps the earliest, not the latest")
def _():
    L = fresh_ledger()
    now = int(_time.time())
    L.touch_member(1, 100, now - 999)
    L.mark(1, 100, "first_message_at", now - 500)
    L.mark(1, 100, "first_message_at", now)          # later, must not overwrite
    row = L.db.execute("SELECT first_message_at FROM members WHERE user_id=100").fetchone()
    assert row["first_message_at"] == now - 500, row["first_message_at"]
    L.close()


@test("forget-me erases everything and stops future recording")
def _():
    L = fresh_ledger()
    L.touch_member(1, 100, int(_time.time()))
    L.record(guild_id=1, user_id=100, channel_id=7, event_type="message")
    removed = L.forget(100)
    assert removed["events"] == 1 and removed["members"] == 1, removed
    assert L.counts(1)["events"] == 0
    L.record(guild_id=1, user_id=100, channel_id=7, event_type="message")
    assert L.counts(1)["events"] == 0, "kept recording after forget-me"
    assert L.is_opted_out(100)
    L.close()


@test("an opted-out member is not re-added by touch_member")
def _():
    # A leave/rejoin must not quietly resurrect someone who opted out.
    L = fresh_ledger()
    L.forget(100)
    L.touch_member(1, 100, int(_time.time()))
    assert L.counts(1)["members"] == 0, "opted-out member was re-created"
    L.close()


@test("remember-me resumes recording without restoring anything")
def _():
    L = fresh_ledger()
    L.record(guild_id=1, user_id=100, channel_id=7, event_type="message")
    L.forget(100)
    assert L.unforget(100) is True
    assert L.unforget(100) is False, "second call should report nothing changed"
    L.record(guild_id=1, user_id=100, channel_id=7, event_type="message")
    assert L.counts(1)["events"] == 1, "old events should stay deleted"
    L.close()


@test("retention deletes old events but keeps the member funnel")
def _():
    L = fresh_ledger()
    now = int(_time.time())
    L.touch_member(1, 100, now - 400 * 86400)
    L.mark(1, 100, "first_message_at", now - 400 * 86400)
    L.record(guild_id=1, user_id=100, event_type="message", ts=now - 400 * 86400)
    L.record(guild_id=1, user_id=100, event_type="message", ts=now)
    removed = L.purge_older_than(365)
    assert removed == 1, removed
    assert L.counts(1)["events"] == 1
    assert L.counts(1)["members"] == 1, "member funnel rows must survive retention"
    L.close()


@test("survives being reopened, and remembers opt-outs")
def _():
    d = tempfile.mkdtemp()
    path = Path(d) / "reopen.sqlite3"
    L = Ledger(path)
    L.record(guild_id=1, user_id=100, event_type="message")
    L.forget(200)
    L.close()
    L2 = Ledger(path)
    assert L2.counts(1)["events"] == 1
    assert L2.is_opted_out(200), "opt-out did not survive a restart"
    L2.close()


@test("attribution is stored once and the first answer wins")
def _():
    L = fresh_ledger()
    L.touch_member(1, 100, int(_time.time()))
    assert L.set_attribution(1, 100, "Steam") is True
    assert L.set_attribution(1, 100, "Reddit") is False, "a rejoin must not overwrite"
    assert L.attribution_counts(1) == {"Steam": 1}, L.attribution_counts(1)
    L.close()


@test("attribution respects opt-out and survives retention")
def _():
    L = fresh_ledger()
    now = int(_time.time())
    L.touch_member(1, 100, now)
    L.set_attribution(1, 100, "Steam")
    L.touch_member(1, 200, now)
    L.forget(200)
    assert L.set_attribution(1, 200, "Reddit") is False, "opted-out member recorded anyway"
    L.record(guild_id=1, user_id=100, event_type="attribution", ts=now - 500 * 86400)
    L.purge_older_than(365)
    assert L.attribution_counts(1) == {"Steam": 1}, "attribution must outlive event retention"
    L.close()


@test("an older database gains the attribution column")
def _():
    import sqlite3
    d = tempfile.mkdtemp()
    path = Path(d) / "old.sqlite3"
    # a members table exactly as an earlier build wrote it, with no attribution
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE members (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            first_joined_at INTEGER NOT NULL, last_left_at INTEGER,
            onboarding_completed_at INTEGER, first_message_at INTEGER,
            last_seen_at INTEGER, PRIMARY KEY (guild_id, user_id));
        INSERT INTO members (guild_id, user_id, first_joined_at) VALUES (1, 100, 0);
    """)
    con.commit(); con.close()

    L = Ledger(path)                                  # must migrate, not crash
    assert L.set_attribution(1, 100, "Steam") is True
    assert L.attribution_counts(1) == {"Steam": 1}
    L.close()


@test("the blueprint's ephemeral roles map to readable answers")
def _():
    sys.path.insert(0, str(ROOT / "steward"))
    import importlib
    botmod = importlib.import_module("bot") if "bot" in sys.modules else None
    # Import bot only if discord.py is present; otherwise read the mapping the
    # same way it does, so this still checks the blueprint side.
    import yaml
    bp = yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))
    eph = {r["name"]: r["name"].split("Found via ", 1)[-1]
           for r in bp["roles"] if r.get("ephemeral")}
    assert len(eph) == 6, eph
    assert eph["Found via Steam"] == "Steam"
    assert eph["Found via a Creator"] == "a Creator"
    # every ephemeral role must actually be granted by an onboarding answer,
    # or it would never be handed out and never recorded
    granted = {r for p in bp["onboarding_prompts"] for o in p["options"]
               for r in o.get("roles", [])}
    assert set(eph) <= granted, set(eph) - granted


@test("stripping ephemeral roles needs Manage Roles in the ledger invite")
def _():
    sys.path.insert(0, str(ROOT / "provision"))
    assert core.INVITE_PERMS_LEDGER & (1 << 28), \
        "the ledger invite must include MANAGE_ROLES or the roles can never be removed"


@test("a brand new ledger does not post an empty first digest")
def _():
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "first run: digest clock started" in src, (
        "a fresh install would post a week of nothing")


@test("the ledger can be started and watched from the setup page")
def _():
    # A browser cannot launch a program; the local server does it. Detached, so
    # closing the page does not stop the recording.
    src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    for bit in ("/api/ledger/status", "/api/ledger/start", "/api/ledger/stop",
                "DETACHED_PROCESS"):
        assert bit in src, f"missing {bit}"
    assert "ledger_seen_at" in src, "no liveness check, so status would be a guess"


@test("two callers cannot both post a status message")
def _():
    # on_ready and the heartbeat's first tick arrive together. Without a lock
    # both looked, both found nothing, and both posted; a live server ended up
    # with two.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "status_lock" in src, "no lock, so the duplicate can happen again"
    assert "async with self.status_lock" in src
    assert "find_status_messages" in src, "it should look for all of them, not one"
    assert "extra.delete()" in src, "duplicates already posted are never cleaned up"


@test("startup failures explain themselves")
def _():
    # discord.py's own errors are written for library authors. The two a person
    # actually hits are a missing intent and a bad token, and both are fixed by
    # clicks rather than by reading a traceback.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "PrivilegedIntentsRequired" in src, "the missing-intent case is unhandled"
    assert "LoginFailure" in src, "a bad token still shows a traceback"
    assert "Save Changes" in src, "the step people miss is not called out"
    assert "Server Members Intent" in src


@test("the bot says out loud whether it is recording")
def _():
    # A bot that silently stops is worse than one that never started, because
    # you keep believing you have the data.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "async def update_status" in src
    assert "heartbeat" in src, "no periodic check-in, so a crash looks like silence"
    assert "async def close" in src, "a deliberate stop should say so"
    assert "running=False" in src, "the stopped state is never shown"


@test("private channels stay reachable after the bot is trimmed")
def _():
    # Staff channels hide themselves by denying @everyone, and the bot is part
    # of @everyone. Administrator hides that during setup; trimming exposes it.
    bp = load()
    fake, prov = run(bp)
    made = [b for m, q, b in fake.calls
            if m == "POST" and q.endswith("/channels")
            and b.get("name") == "steward-reports"]
    assert made, "the report channel was never created"
    ows = made[0]["permission_overwrites"]
    assert any(o.get("type") == 1 for o in ows), (
        "no member-level overwrite, so a trimmed bot cannot see its own channel")


@test("the bot asks for members but never message content")
def _():
    # Reading message content is a privileged intent needing annual
    # reapplication past 10k users, and the ledger does not need it.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "intents.members = True" in src
    assert "intents.message_content = False" in src, \
        "the ledger must never request MESSAGE_CONTENT"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
print("\nlevels")

sys.path.insert(0, str(ROOT / "steward"))
from levels import Curve, Levels                          # noqa: E402
import digest as digestmod                                # noqa: E402


@test("the curve rises and never stalls")
def _():
    c = Curve()
    totals = [c.total_for(n) for n in range(0, 30)]
    assert totals == sorted(totals), "levels must get more expensive, not less"
    assert all(b > a for a, b in zip(totals, totals[1:])), "a level costs nothing"
    for xp in (0, 99, 100, 254, 255, 10_000):
        lv = c.level_at(xp)
        assert c.total_for(lv) <= xp < c.total_for(lv + 1), (xp, lv)


@test("the cooldown is what stops level farming")
def _():
    L = fresh_ledger()
    lv = Levels(L, {"xp_per_message": [20, 20], "cooldown_seconds": 60})
    for _ in range(20):
        lv.award_message(1, 100)
    assert L.xp_of(1, 100)["xp"] == 20, "twenty messages in a row should pay once"
    L.close()


@test("crossing several levels at once collects every reward passed")
def _():
    # A long voice session can jump two or three levels, and skipping the tiers
    # in between would leave someone permanently missing a role.
    L = fresh_ledger()
    lv = Levels(L, {"voice_xp_per_minute": 50,
                    "rewards": [{"level": 1, "role": "A"}, {"level": 2, "role": "B"},
                                {"level": 3, "role": "C"}]})
    r = lv.award_voice(1, 100, 60 * 20)
    assert r["previous"] == 0 and r["level"] >= 3, r
    assert r["roles_passed"] == ["A", "B", "C"], r["roles_passed"]
    L.close()


@test("opting out earns nothing and clears any level")
def _():
    L = fresh_ledger()
    lv = Levels(L, {"xp_per_message": [50, 50], "cooldown_seconds": 0})
    for _ in range(10):
        lv.award_message(1, 100)
    assert L.xp_of(1, 100)["xp"] > 0
    L.forget(100)
    assert L.xp_of(1, 100)["xp"] == 0, "forget-me left them on the leaderboard"
    assert lv.award_message(1, 100) is None
    L.close()


@test("the leaderboard ranks by xp and numbers the positions")
def _():
    L = fresh_ledger()
    lv = Levels(L, {"cooldown_seconds": 0})
    for uid, amount in ((1, 500), (2, 900), (3, 100)):
        L.add_xp(1, uid, amount)
    board = lv.board(1)
    assert [r["user_id"] for r in board] == [2, 1, 3], board
    assert [r["position"] for r in board] == [1, 2, 3]
    assert lv.rank(1, 2)["rank"] == 1
    L.close()


@test("a level ceiling stops anyone going past it")
def _():
    L = fresh_ledger()
    lv = Levels(L, {"xp_per_message": [500, 500], "cooldown_seconds": 0,
                    "max_level": 5, "curve": {"base": 50, "linear": 0, "quadratic": 0}})
    for _ in range(60):
        lv.award_message(1, 100)
    r = lv.rank(1, 100)
    assert r["level"] == 5, f"went past the ceiling to {r['level']}"
    assert r["at_cap"] is True
    assert r["needed"] == 0, "there is no next level at the ceiling"
    L.close()


@test("no ceiling means no ceiling")
def _():
    L = fresh_ledger()
    lv = Levels(L, {"xp_per_message": [500, 500], "cooldown_seconds": 0,
                    "max_level": 0, "curve": {"base": 50, "linear": 0, "quadratic": 0}})
    for _ in range(60):
        lv.award_message(1, 100)
    assert lv.rank(1, 100)["level"] > 5
    L.close()


@test("the ceiling is editable and reaches the bot")
def _():
    bp = load({"levels": {"max_level": 999}})
    assert bp["levels"]["max_level"] == 999
    assert core.inventory(core.load(BLUEPRINT))["levels"].get("max_level") is not None, (
        "the UI cannot see the ceiling")


@test("the tiers climb and every one is reachable")
def _():
    rewards = core.load(BLUEPRINT)["levels"]["rewards"]
    levels = [r["level"] for r in rewards]
    assert levels == sorted(levels), f"tiers are out of order: {levels}"
    assert len(set(levels)) == len(levels), "two tiers unlock at the same level"
    cap = core.load(BLUEPRINT)["levels"].get("max_level", 0)
    if cap:
        assert max(levels) <= cap, "a tier sits above the ceiling"


@test("the page's level calculator matches the bot's curve")
def _():
    # The setup page recomputes the curve in JavaScript to show a live table.
    # If the two ever disagree, the table becomes confident and wrong.
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "function levelCost(n)" in html, "the page has no curve calculation"
    assert "return q * n * n + l * n + b;" in html, (
        "the page's formula no longer matches quadratic*n^2 + linear*n + base")

    # And the numbers it produces must be the ones the bot will award.
    bp = core.load(BLUEPRINT)
    c = Curve(**(bp["levels"].get("curve") or {}))
    q = (bp["levels"].get("curve") or {}).get("quadratic", 0)
    lin = (bp["levels"].get("curve") or {}).get("linear", 50)
    base = (bp["levels"].get("curve") or {}).get("base", 100)
    for level in (10, 40, 120):
        js_total = sum(q * n * n + lin * n + base for n in range(level))
        assert js_total == c.total_for(level), (
            f"level {level}: page says {js_total}, bot says {c.total_for(level)}")


@test("the tiers are reachable by a real person")
def _():
    # A chatty member earns roughly 600 XP a day once the cooldown applies. If
    # the top tier needs years, nobody ever sees it.
    bp = core.load(BLUEPRINT)
    rewards = bp["levels"]["rewards"]
    c = Curve(**(bp["levels"].get("curve") or {}))
    days = [c.total_for(r["level"]) / 600 for r in rewards]
    assert days[0] <= 7, f"first tier takes {days[0]:.0f} days, too slow to hook anyone"
    assert days[-1] <= 400, f"top tier takes {days[-1]:.0f} days, nobody gets there"
    assert days == sorted(days), "tiers are out of order"


# ---------------------------------------------------------------------------
print("\ndigest")

@test("a digest comes out of an empty server without falling over")
def _():
    L = fresh_ledger()
    out = digestmod.build(L, 1)
    assert out["week"]["this_week"]["joined"] == 0
    assert out["chart"] is None, "should not draw a chart with no data"
    L.close()


@test("no chart is drawn until there is enough to show")
def _():
    L = fresh_ledger()
    now = int(_time.time())
    for d in range(3):
        L.record(guild_id=1, user_id=1, event_type="message", ts=now - d * 86400)
    assert digestmod.build(L, 1)["chart"] is None, "three days is not a trend"
    L.close()


@test("cohort retention counts only posts made after that cohort joined")
def _():
    L = fresh_ledger()
    now = int(_time.time())
    joined = now - 14 * 86400
    L.touch_member(1, 100, joined)
    # a message from before they joined must not count as coming back
    L.record(guild_id=1, user_id=100, event_type="message", ts=joined - 86400)
    rows = {c["week"]: c for c in digestmod.cohort_retention(L, 1)}
    assert rows[2]["joined"] == 1 and rows[2]["retained"] == 0, rows[2]
    L.record(guild_id=1, user_id=100, event_type="message", ts=now - 86400)
    rows = {c["week"]: c for c in digestmod.cohort_retention(L, 1)}
    assert rows[2]["retained"] == 1, rows[2]
    L.close()


@test("week-on-week deltas read correctly at the edges")
def _():
    assert "first week" in digestmod.delta(3, 0)
    assert digestmod.delta(0, 0) == ""
    assert "+50%" in digestmod.delta(3, 2)
    assert "level with" in digestmod.delta(4, 4)


# ---------------------------------------------------------------------------
print("\nmoderation log")

@test("the mod log never asks to read message content")
def _():
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "intents.message_content = False" in src
    # and it says so where a moderator would otherwise wonder
    assert "Content is not recorded" in src


@test("it works out who did it, not just what happened")
def _():
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    for event in ("on_member_ban", "on_member_unban", "on_message_delete",
                  "on_guild_channel_delete"):
        assert f"async def {event}" in src, f"missing {event}"
    assert "actor_for" in src, "no audit-log lookup, so every entry says 'someone'"


@test("attribution roles are kept out of the role-change log")
def _():
    # They appear and vanish within a second, and would bury everything else.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "r.name not in self.ephemeral" in src


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
        assert "default.yaml" in w.get("/api/blueprints")[1]

    @test("refuses requests from another origin")
    def _():
        w = Web(BASE)
        code, _body = w.post("/api/preview", {"file": "default.yaml"},
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
        assert w.post("/api/apply", {"file": "default.yaml", "guild_id": "5"})[0] == 401

    @test("preview needs no token and reports errors")
    def _():
        w = Web(BASE)
        code, body = w.post("/api/preview",
                            {"file": "default.yaml", "selection": {"channels": ["general"]}})
        assert code == 200, body
        assert _json.loads(body)["errors"], "a one-channel server should fail onboarding rules"

    @test("apply refuses a selection that would not validate")
    def _():
        w = Web(BASE)
        w.post("/api/connect", {"token": "t"})
        code, _b = w.post("/api/apply", {"file": "default.yaml", "guild_id": "5",
                                         "selection": {"channels": ["general"]}})
        assert code == 400, code

    @test("apply streams progress and finishes")
    def _():
        fake = install(core, FakeDiscord())
        w = Web(BASE)
        w.post("/api/connect", {"token": "t"})
        code, body = w.post("/api/apply", {"file": "default.yaml", "guild_id": "5",
                                           "selection": {}, "dry_run": False})
        assert code == 200, body
        events = [_json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
        assert events, "no progress streamed"
        assert isinstance(events[-1], dict) and "problems" in events[-1], events[-1]
        assert fake.onboarding is not None, "onboarding never reached Discord"

    @test("health reports whether a session exists")
    def _():
        w = Web(BASE)
        h = _json.loads(w.get("/api/health")[1])
        assert h["ok"] is True and h["connected"] is False, h
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

@test("the page knows every channel type a blueprint uses")
def _():
    """The type dropdown listed four of the six. A media channel therefore
    rendered as "Text", which is the wrong answer to "what is this channel",
    and there was no way to make one from the page at all."""
    import glob, yaml as _y
    used = set()
    for path in sorted(glob.glob(str(ROOT / "blueprint" / "*.yaml"))):
        if path.endswith(".local.yaml"):
            continue
        raw = _y.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for cat in (raw.get("categories") or []):
            for ch in (cat.get("channels") or []):
                used.add(ch.get("type", "text"))
        for ch in ((raw.get("add") or {}).get("channels") or []):
            used.add(ch.get("type", "text"))
        for ch in ((raw.get("set") or {}).get("channels") or {}).values():
            if isinstance(ch, dict) and ch.get("type"):
                used.add(ch["type"])
    page = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    for kind in sorted(used):
        assert f"{kind}:" in page.split("const TYPE_PERMS")[1].split("};")[0], \
            f"{kind} channels exist in a blueprint but the page has no permissions for them"
        assert f"{kind}:" in page.split("const TYPE_NAMES")[1].split("};")[0], \
            f"{kind} channels exist in a blueprint but the page has no name for them"


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
print("\ncalendar")

import calendar_engine as ce                            # noqa: E402
from datetime import date as _date, timedelta as _td    # noqa: E402
import yaml as _yaml                                    # noqa: E402

CALENDAR_DIR = ROOT / "blueprint" / "calendars"
CALENDAR = CALENDAR_DIR / "steam-game.yaml"
TEMPLATES = sorted(f for f in CALENDAR_DIR.glob("*.yaml")
                   if not f.name.endswith(".local.yaml"))
ANCHOR = _date(2027, 3, 1)


def fresh_calendar():
    return ce.load(CALENDAR, {"game": "Testgame"})


@test("T-minus offsets resolve against the launch date")
def _():
    assert ce.parse_when("T-90", ANCHOR) == ANCHOR - _td(days=90)
    assert ce.parse_when("T+14", ANCHOR) == ANCHOR + _td(days=14)
    assert ce.parse_when("T-0", ANCHOR) == ANCHOR
    # An absolute date is allowed and sometimes necessary: Next Fest closes
    # when Valve says it does, not relative to your launch.
    assert ce.parse_when("2027-01-10", ANCHOR) == _date(2027, 1, 10)


@test("a relative date without a launch date is refused, not guessed")
def _():
    try:
        ce.parse_when("T-90", None)
        assert False, "T-90 resolved with no anchor"
    except ce.BadDate:
        pass


@test("nonsense dates are rejected rather than silently skipped")
def _():
    for bad in ("next tuesday", "T-", "2027-13-01x", ""):
        try:
            ce.parse_when(bad, ANCHOR)
            assert False, f"{bad!r} was accepted"
        except (ce.BadDate, ValueError):
            pass


@test("every calendar template is valid against the shipped blueprint")
def _():
    bp = _yaml.safe_load((ROOT / "blueprint" / "default.yaml").read_text("utf-8"))
    channels = [c["name"] for cat in bp.get("categories", [])
                for c in cat.get("channels", [])]
    roles = [r["name"] for r in bp.get("roles", [])]
    assert len(TEMPLATES) >= 4, f"only found {[t.name for t in TEMPLATES]}"
    for t in TEMPLATES:
        # What shipped, not what this machine has edited, and against the
        # blueprint the calendar is paired with rather than always the default.
        paired = ROOT / "blueprint" / f"{t.stem}.yaml"
        if paired.exists():
            other = core.load(paired)
            channels = [c["name"] for cat in other.get("categories", [])
                        for c in cat.get("channels", [])]
            roles = [r["name"] for r in other.get("roles", [])]
        report = ce.load(t, {"game": "Testgame"}, overrides=False).validate(
            channels=channels, roles=roles)
        assert not report["errors"], f"{t.name}: {report['errors']}"
        # Every post must aim at a channel the blueprint actually creates, or
        # it drafts and then fails the moment somebody clicks approve.
        missing = [w for w in report["warnings"] if "not in the blueprint" in w]
        assert not missing, f"{t.name}: {missing}"


@test("every post names a channel and has something to say")
def _():
    cal = fresh_calendar()
    for post in cal.posts + cal.recurring:
        assert post.get("id"), post
        assert post.get("channel"), post["id"]
        assert post.get("body", "").strip(), post["id"]


@test("post ids are unique, because the id is what stops a repost")
def _():
    cal = fresh_calendar()
    ids = [b["id"] for b in cal.posts + cal.recurring]
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]


@test("placeholders are filled from the blueprint's variables")
def _():
    cal = fresh_calendar()
    occ = [o for o in cal.occurrences(ANCHOR, ANCHOR) if o.id == "launch-day"]
    assert occ, "launch-day does not land on T-0"
    body = occ[0].post["title"] + occ[0].post["body"]
    assert "Testgame" in body, body[:120]
    assert "{{" not in body, "an unfilled placeholder reached the post"


@test("recurring posts land on the weekday they name")
def _():
    cal = fresh_calendar()
    start = ANCHOR - _td(days=120)
    got = [o for o in cal.occurrences(start, start + _td(days=28))
           if o.id == "screenshot-saturday"]
    assert got, "screenshot-saturday never fired"
    assert all(o.date.weekday() == 5 for o in got), [str(o.date) for o in got]
    assert len(got) == 4, len(got)


@test("recurring posts stop at their until date")
def _():
    cal = ce.Calendar({"meta": {"anchor": "2027-03-01"}, "recurring": [
        {"id": "x", "every": "monday", "channel": "general", "body": "hi",
         "from": "T-30", "until": "T-10"}]})
    got = cal.occurrences(_date(2027, 1, 1), _date(2027, 4, 1))
    assert got, "never fired"
    assert min(o.date for o in got) >= ANCHOR - _td(days=30)
    assert max(o.date for o in got) <= ANCHOR - _td(days=10)


@test("due() only looks back a week, so a late install does not dump months")
def _():
    cal = fresh_calendar()
    # Pretend the bot is switched on for the first time the day before launch.
    day = ANCHOR - _td(days=1)
    due = cal.due(day, lookback=7)
    assert all(o.date >= day - _td(days=7) for o in due), due
    # And the launch-day post, which is still in the future, is not among them.
    assert "launch-day" not in [o.id for o in due]


@test("the timezone setting actually changes when posts fire")
def _():
    # It was read from the file, documented as controlling the hour, and then
    # never used: every post fired on UTC hours whatever the file said. A
    # setting that lies is worse than no setting.
    utc = ce.Calendar({"meta": {"timezone": "UTC"}})
    chi = ce.Calendar({"meta": {"timezone": "America/Chicago"}})
    assert chi.tz_problem is None, chi.tz_problem
    assert utc.now().utcoffset() != chi.now().utcoffset(),         "the timezone made no difference to the clock"


@test("an unknown timezone warns and falls back rather than refusing to load")
def _():
    # A bot that will not start because of a timezone is worse than one an
    # hour out, and Windows ships no IANA database at all without tzdata.
    cal = ce.Calendar({"meta": {"timezone": "Not/AZone"}})
    assert cal.tz_problem and "UTC" in cal.tz_problem
    assert cal.now() is not None
    assert any("Not/AZone" in w for w in cal.validate()["warnings"])


@test("an edit overrides a shipped post without touching the shipped file")
def _():
    # Edits go in a separate file on purpose. Writing them back would destroy
    # the shipped calendar's comments, and an update replaces that file, so
    # anything written there would be lost on the next update.
    base = {"meta": {"anchor": "2027-03-01"},
            "posts": [{"id": "a", "when": "T-10", "channel": "general", "body": "shipped"}]}
    local = {"posts": [{"id": "a", "body": "mine", "title": "Mine"}]}
    out = ce.merge(base, local)
    assert out["posts"][0]["body"] == "mine"
    assert out["posts"][0]["title"] == "Mine"
    assert out["posts"][0]["when"] == "T-10", "an unedited field was lost"
    assert base["posts"][0]["body"] == "shipped", "merge mutated the original"


@test("no yaml file declares the same top-level key twice")
def _():
    """PyYAML keeps the last one silently.

    A variant grew a second `add:` block and the first one, holding every
    channel and role it added, was discarded without a word.
    """
    import yaml as _y

    class _Strict(_y.SafeLoader):
        pass

    def _no_dupes(loader, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise AssertionError(f"duplicate key {key!r}")
            seen.add(key)
        return _y.SafeLoader.construct_mapping(loader, node, deep)

    _Strict.add_constructor(_y.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)

    roots = [ROOT / "blueprint", ROOT / "blueprint" / "calendars"]
    for root in roots:
        for f in sorted(root.glob("*.yaml")):
            if f.name.endswith(".local.yaml"):
                continue
            try:
                _y.load(f.read_text(encoding="utf-8"), _Strict)
            except AssertionError as e:
                raise AssertionError(f"{f.name}: {e}")


@test("a channel type can be changed without removing the channel")
def _():
    # Turning #trading into a forum used to mean removing it and adding one of
    # the same name, which the page refused because the name was taken.
    bp = core.load(ROOT / "blueprint" / "roblox-game.yaml")
    out = core.customize(bp, {"types": {"trading": "forum"}})
    ch = next(c for cat in out["categories"] for c in cat["channels"]
              if c["name"] == "trading")
    assert ch["type"] == "forum", ch
    # A text preset denies thread creation, which is all a forum post is, so
    # the permissions have to follow the type.
    assert ch["overwrites"] == "forum_open", ch


@test("who can post is changeable per channel")
def _():
    bp = core.load(ROOT / "blueprint" / "roblox-game.yaml")
    out = core.customize(bp, {"perms": {"codes": "readonly_reactable"}})
    ch = next(c for cat in out["categories"] for c in cat["channels"]
              if c["name"] == "codes")
    assert ch["overwrites"] == "readonly_reactable", ch


@test("a removed channel does not keep hold of its name")
def _():
    # Remove-then-re-add is what people reach for when they cannot change a
    # type, and it was refused because the removed one still counted.
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    fn = html[html.index("function addChannel("):html.index("function addRole(")]
    assert "SEL.channels.includes" in fn,         "the taken-name check still counts removed channels"


@test("adding a by-hand step does not drop the inherited ones")
def _():
    # An unhandled key replaces outright, which silently lost Rules Screening
    # and Raid Protection from a variant that only wanted to add one step.
    base = core.load(ROOT / "blueprint" / "default.yaml").get("manual_steps") or []
    gacha = core.load(ROOT / "blueprint" / "roblox-gacha.yaml").get("manual_steps") or []
    assert len(gacha) > len(base), (len(base), len(gacha))
    titles = {m["title"] for m in gacha}
    for kept in ("Rules Screening", "Raid Protection and DM filtering"):
        assert kept in titles, f"{kept} was dropped"


@test("no channel is shown to new members twice")
def _():
    for f in sorted((ROOT / "blueprint").glob("*.yaml")):
        if f.name.endswith(".local.yaml"):
            continue
        defaults = core.load(f).get("onboarding_defaults") or []
        assert len(defaults) == len(set(defaults)),             f"{f.name}: {[d for d in defaults if defaults.count(d) > 1]}"




@test("there is a blueprint for each kind of project")
def _():
    # Only one shipped for a long time, so picking Roblox in step 8 still left
    # you building a Steam-shaped server in step 4.
    have = {f.stem for f in (ROOT / "blueprint").glob("*.yaml")
            if not f.name.endswith(".local.yaml")}
    for want in ("default", "steam-game", "roblox-game", "mod"):
        assert want in have, f"no {want} blueprint. Have: {sorted(have)}"


@test("every blueprint variant validates on its own")
def _():
    for f in sorted((ROOT / "blueprint").glob("*.yaml")):
        if f.name.endswith(".local.yaml"):
            continue
        bp = core.load(f)
        report = core.validate(core.customize(bp, None))
        assert not report["errors"], f"{f.name}: {report['errors']}"


@test("a variant states only its differences")
def _():
    # Copying the whole 900-line blueprint per platform means every later fix
    # has to be made four times.
    base = len((ROOT / "blueprint" / "default.yaml").read_text("utf-8").splitlines())
    for name in ("steam-game", "roblox-game", "mod"):
        f = ROOT / "blueprint" / f"{name}.yaml"
        assert "extends:" in f.read_text("utf-8"), f"{name} does not extend anything"
        assert len(f.read_text("utf-8").splitlines()) < base / 2,             f"{name} is not a variant, it is a copy"


@test("removing a role takes it out of onboarding too")
def _():
    # An option granting a role that no longer exists is refused by Discord as
    # ROLE_OR_CHANNEL_REQUIRED, and it takes the whole onboarding request down
    # with it rather than just that option.
    for f in sorted((ROOT / "blueprint").glob("*.yaml")):
        if f.name.endswith(".local.yaml"):
            continue
        bp = core.load(f)
        roles = {r["name"] for r in bp.get("roles", [])}
        channels = {c["name"] for cat in bp.get("categories", [])
                    for c in cat.get("channels", [])}
        for prompt in bp.get("onboarding_prompts", []):
            for option in prompt.get("options", []):
                missing = [r for r in option.get("roles", []) if r not in roles]
                assert not missing, f"{f.name}: '{option['title']}' grants {missing}"
                gone = [c for c in option.get("channels", []) if c not in channels]
                assert not gone, f"{f.name}: '{option['title']}' reveals {gone}"
                assert option.get("roles") or option.get("channels"),                     f"{f.name}: '{option['title']}' grants nothing"


@test("no attribution role is declared and never handed out")
def _():
    # They exist only because Discord refuses an answer that grants nothing.
    # One with no option behind it is clutter in the role list forever.
    for f in sorted((ROOT / "blueprint").glob("*.yaml")):
        if f.name.endswith(".local.yaml"):
            continue
        bp = core.load(f)
        ephemeral = {r["name"] for r in bp.get("roles", []) if r.get("ephemeral")}
        used = {g for p in bp.get("onboarding_prompts", [])
                for o in p.get("options", []) for g in o.get("roles", [])}
        assert not (ephemeral - used), f"{f.name}: unused {sorted(ephemeral - used)}"


@test("each variant names the calendar that goes with it")
def _():
    for name, cal in (("steam-game", "steam-game"), ("roblox-game", "roblox-game"),
                      ("mod", "mod")):
        bp = core.load(ROOT / "blueprint" / f"{name}.yaml")
        assert bp["meta"].get("calendar") == cal, bp["meta"]
        assert (ROOT / "blueprint" / "calendars" / f"{cal}.yaml").exists()
    # Default is the generic one and works with any calendar, so it must not
    # insist on one or it nags about perfectly good pairings.
    assert not core.load(ROOT / "blueprint" / "default.yaml")["meta"].get("calendar")


@test("the calendar is not offered as a server blueprint")
def _():
    # The blueprint folder also holds the content calendar, which is YAML but
    # describes posts, not a server. It sorted first in the picker, so the page
    # opened with it selected and an empty panel.
    sys.path.insert(0, str(ROOT / "ui"))
    import app as _app
    names = [b["file"] for b in _app.list_blueprints()]
    assert "content-calendar.yaml" not in names, names
    assert "default.yaml" in names, names
    assert not _app.looks_like_a_blueprint({"meta": {}, "posts": []})
    assert _app.looks_like_a_blueprint({"roles": [{"name": "x"}]})


@test("every screenshot the README points at exists")
def _():
    # A broken image in a README is the first thing a stranger sees. These are
    # regenerated by tools/screenshots.py, so it is easy to rename one and not
    # notice until somebody else does.
    import re as _re
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    imgs = _re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
    assert len(imgs) >= 8, f"only {len(imgs)} screenshots in the README"
    for rel in imgs:
        assert (ROOT / rel).exists(), f"README points at {rel}, which is missing"


@test("the screenshots are of the real page, not drawings")
def _():
    # The whole argument for them is that they go stale visibly. A hand-drawn
    # mockup goes stale silently.
    src = (ROOT / "tools" / "screenshots.py").read_text(encoding="utf-8")
    assert "--screenshot" in src and "headless" in src
    assert "uvicorn.run" in src, "the tool does not serve the real page"


@test("reading onboarding back tells a server that never had it from one with it off")
def _():
    """A server where onboarding was never configured and one where somebody
    switched it off look the same from Discord: no Channels & Roles entry, no
    message, nothing. Both mean nobody can pick a role, so both have to be
    reported rather than assumed fine."""
    from fake_discord import FakeDiscord, install as _install
    fake = _install(core, FakeDiscord())
    blank = core.read_onboarding("t", fake.guild_id)
    assert blank["readable"] and blank["enabled"] is False and not blank["prompts"]

    fake, _ = run(load())
    live = core.read_onboarding("t", fake.guild_id)
    assert live["enabled"] is True, "the build left onboarding switched off"
    assert live["prompts"], "no questions, so no role picker"
    granted = {r for p in live["prompts"] for r in p["roles"]}
    assert granted, "the questions hand out no roles at all"


@test("an unreadable onboarding is reported, not treated as healthy")
def _():
    from fake_discord import FakeDiscord, install as _install
    fake = _install(core, FakeDiscord())
    fake.fail_on[("GET", "/onboarding")] = 403
    out = core.read_onboarding("t", fake.guild_id)
    assert out["readable"] is False, "a refused read came back looking like an answer"


@test("the health check looks at whether anybody can pick a role")
def _():
    """The pin in #pick-your-roles told people to open Channels & Roles while
    Channels & Roles was not there. Discord gives no sign of that: the entry is
    simply absent. Nothing checked it, so nothing said so."""
    src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("def audit("):src.index("def calendar_templates_api")]
    assert "core.read_onboarding" in body, "the audit never reads onboarding back"
    assert "Channels & Roles" in body, "it never says where members would look"
    assert "Alerts" in body, "a ping role nobody can self-assign is not checked"


@test("a locked step says why it is locked")
def _():
    """Locked steps went grey and refused clicks with no explanation. Step 6
    reads as broken after a page restart, because the token is held in memory
    and a restart loses it, which nothing on the page said."""
    import re
    page = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    locked = re.findall(r'<section class="step locked" id="(\w+)"([^>]*)>', page)
    assert locked, "no locked steps found, so this check is watching nothing"
    for sid, attrs in locked:
        assert "data-locked=" in attrs, f"step {sid} locks with no reason given"
    assert "initLocks()" in page, "the reasons are never shown at load"


@test("the audit reads the server rather than describing it")
def _():
    # Every other panel says what it would write. This is the only one that
    # reads back, which is the only honest answer to "am I finished?".
    src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("def audit("):src.index("def calendar_templates_api")]
    assert "core.read_guild" in body, "the audit does not read the live server"
    assert "session_of(request)" in body, "the audit is not behind the token"
    # Every problem has to say how to fix it, or it is just a complaint.
    import re as _re
    for m in _re.finditer(r'problems\.append\(\{', body):
        chunk = body[m.start():m.start() + 700]
        assert '"fix"' in chunk, f"a problem with no fix: {chunk[:120]}"
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="s9b"' in html and "function runAudit" in html


@test("the page starts with every section folded")
def _():
    # Nine open sections is a wall of text. Nine headings is a table of
    # contents, and which ones you open is remembered after that.
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "localStorage.getItem(FOLD_KEY) === null" in html,         "there is no first-run default, so everything opens expanded"
    assert "first ? true : set.has(el.id)" in html


@test("a calendar written with the old 'beats:' key still loads")
def _():
    # The key was renamed to posts because "posts" is jargon. Anything already
    # written has to keep working, including override files.
    old = {"posts": [{"id": "a", "when": "T-1", "channel": "g", "body": "x"}]}
    assert len(ce.Calendar(old).posts) == 1
    out = ce.merge(old, {"posts": [{"id": "a", "body": "edited"}]})
    assert out["posts"][0]["body"] == "edited"


@test("a shipped post can be hidden without being deleted")
def _():
    base = {"posts": [{"id": "a", "when": "T-1", "channel": "g", "body": "x"},
                      {"id": "b", "when": "T-2", "channel": "g", "body": "y"}]}
    out = ce.merge(base, {"posts": [{"id": "a", "enabled": False}]})
    assert [b["id"] for b in out["posts"]] == ["b"]


@test("a post of your own is added at the end")
def _():
    base = {"posts": [{"id": "a", "when": "T-1", "channel": "g", "body": "x"}]}
    out = ce.merge(base, {"posts": [{"id": "mine", "when": "T-3",
                                     "channel": "g", "body": "z"}]})
    assert [b["id"] for b in out["posts"]] == ["a", "mine"]


@test("the bot finds its settings from any directory")
def _():
    # load_dotenv() searches the current directory, so running the bot from
    # anywhere but steward/ picked up no settings at all and quietly fell back
    # to every default, including the wrong calendar.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    calls = [l.strip() for l in src.splitlines()
             if l.startswith("load_dotenv(")]
    assert calls, "bot.py never loads its settings file"
    assert all("os.path.join(" in c for c in calls),         f"the env file is still searched for rather than named: {calls}"


@test("what you filled in is remembered where the bot can read it")
def _():
    # The page kept these in the browser only, so a game name typed in step 4
    # was applied to the server and then forgotten. Every scheduled post the
    # bot wrote afterwards still said the blueprint's placeholder, which is how
    # a launch announcement came out as "the game is out".
    import tempfile, shutil
    d = Path(tempfile.mkdtemp())
    shutil.copy(BLUEPRINT, d / "default.yaml")
    (d / "variables.local.yaml").write_text("game: Testgame" + chr(10),
                                           encoding="utf-8")
    bp = core.load(d / "default.yaml")
    assert core.declared_variables(bp)["game"] == "Testgame",         core.declared_variables(bp)
    # And with no local file the blueprint's own default still wins.
    (d / "variables.local.yaml").unlink()
    bp = core.load(d / "default.yaml")
    assert core.declared_variables(bp)["game"] != "Testgame"


@test("a capitalised placeholder gives a capitalised value")
def _():
    # {{game}} opening a title produced "the game is out", which reads as a
    # typo rather than a template.
    v = {"game": "the game"}
    assert core.substitute_text("{{Game}} is out", v) == "The game is out"
    assert core.substitute_text("about {{game}}", v) == "about the game"
    assert core.substitute_text("{{Nope}} stays", v) == "{{Nope}} stays"
    assert ce.substitute("{{Game}} is out", v) == "The game is out"


@test("no post title starts with a lowercase placeholder")
def _():
    import yaml as _y
    for t in TEMPLATES:
        spec = _y.safe_load(t.read_text("utf-8")) or {}
        rows = (spec.get("posts") or spec.get("beats") or []) + (spec.get("recurring") or [])
        for row in rows:
            title = row.get("title") or ""
            assert not title.startswith("{{game}}"),                 f"{t.name}: '{row.get('id')}' opens with the lowercase form"


@test("the page defines each function once")
def _():
    # A duplicated renderVars survived a splice and sat there as dead code.
    import re as _re
    html = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    names = _re.findall(r"^function (\w+)\(", html, _re.M)
    names += _re.findall(r"^async function (\w+)\(", html, _re.M)
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"defined more than once: {sorted(dupes)}"


@test("the overrides file survives an update")
def _():
    # It is this deployment's, like .env. An update that replaced it would
    # throw away every edit somebody had made in the page.
    # updates is imported further down the file, so reach it directly here.
    sys.path.insert(0, str(ROOT / "provision"))
    import updates
    assert "blueprint/content-calendar.local.yaml" in updates.KEEP_ON_UPDATE
    assert "blueprint/content-calendar.local.yaml" in updates.PROTECTED
    assert "content-calendar.local.yaml" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    build = (ROOT / "tools" / "build_dist.py").read_text(encoding="utf-8")
    assert "content-calendar.local.yaml" in build,         "the download would ship one machine's calendar edits"


@test("a broken overrides file does not stop the calendar loading")
def _():
    import tempfile
    d = Path(tempfile.mkdtemp())
    base = ("meta: {anchor: '2027-03-01'}" + chr(10) + "posts:" + chr(10)
            + "  - {id: a, when: T-1, channel: g, body: x}" + chr(10))
    (d / "c.yaml").write_text(base, encoding="utf-8")
    (d / "c.local.yaml").write_text("this: [is not" + chr(10) + "  valid yaml",
                                    encoding="utf-8")
    cal = ce.load(d / "c.yaml")
    assert len(cal.posts) == 1, "a broken edit file took the whole calendar down"


@test("a calendar with no launch date fires nothing")
def _():
    spec = _yaml.safe_load(CALENDAR.read_text("utf-8"))
    spec["meta"]["anchor"] = None
    cal = ce.Calendar(spec)
    assert cal.anchor is None
    relative = [o for o in cal.occurrences(_date(2020, 1, 1), _date(2030, 1, 1))
                if not o.recurring]
    # Only the handful written as absolute dates survive; every T-minus post
    # is dormant rather than fired against a guessed anchor.
    assert all(str(o.post.get("when", "")).startswith("20") for o in relative), \
        [o.id for o in relative]
    assert cal.validate()["warnings"], "no warning about the missing launch date"


@test("an unparseable post is reported and never fired")
def _():
    cal = ce.Calendar({"meta": {"anchor": "2027-03-01"}, "posts": [
        {"id": "bad", "when": "soon", "channel": "general", "body": "x"}]})
    assert cal.validate()["errors"], "a bad date passed validation"
    assert not cal.occurrences(_date(2020, 1, 1), _date(2030, 1, 1))


@test("kind is post or reminder and nothing else")
def _():
    cal = fresh_calendar()
    for post in cal.posts + cal.recurring:
        assert post.get("kind", "post") in ("post", "reminder"), post["id"]
    bad = ce.Calendar({"meta": {"anchor": "2027-03-01"}, "posts": [
        {"id": "b", "when": "T-1", "kind": "shout", "channel": "g", "body": "x"}]})
    assert bad.validate()["errors"]


@test("mentioning everyone is flagged, because it reaches the whole server")
def _():
    warnings = " ".join(fresh_calendar().validate()["warnings"])
    assert "everyone" in warnings


@test("a recurring post never fires before the date it is gated to")
def _():
    # "New things are live" going out four days before the game exists is the
    # sort of post that teaches people to ignore the channel.
    cal = ce.load(CALENDAR_DIR / "roblox-game.yaml", {"game": "X"},
                  anchor_override="2026-08-25", overrides=False)
    launch = _date(2026, 8, 25)
    early = [o for o in cal.occurrences(launch - _td(days=30), launch - _td(days=1))
             if o.id in ("update-day", "update-prep")]
    assert not early, [str(o) for o in early]
    later = [o for o in cal.occurrences(launch, launch + _td(days=21))
             if o.id == "update-day"]
    assert later, "update-day never fires after launch either"


@test("the roblox calendar is mostly rhythm, not a countdown")
def _():
    # A calendar full of one-offs written months ahead fires things you have
    # forgotten you wrote. On Roblox the weekly beat is the product.
    cal = ce.load(CALENDAR_DIR / "roblox-game.yaml", {"game": "X"}, overrides=False)
    assert len(cal.recurring) >= 4, len(cal.recurring)
    assert len(cal.posts) <= 8, f"{len(cal.posts)} one-offs is a countdown"
    # And most of the one-offs should be reminders to you rather than posts to
    # members, because nobody can write this week's update notes in advance.
    reminders = [p for p in cal.posts if p.get("kind") == "reminder"]
    assert len(reminders) >= len(cal.posts) / 2,         f"only {len(reminders)} of {len(cal.posts)} one-offs are reminders"


@test("loading can ignore this machine's edits")
def _():
    # Checking a shipped calendar against a blueprint has to read what shipped,
    # or the check passes or fails depending on whose laptop it runs on. That
    # exact leak broke the suite once.
    import tempfile, shutil, yaml as _y
    d = Path(tempfile.mkdtemp())
    cal = d / "c.yaml"
    shutil.copy(CALENDAR_DIR / "roblox-game.yaml", cal)
    ce.overrides_path(cal).write_text(
        _y.safe_dump({"posts": [{"id": "launch-day", "body": "LOCAL"}]}),
        encoding="utf-8")
    with_local = ce.load(cal, {"game": "X"})
    without = ce.load(cal, {"game": "X"}, overrides=False)
    a = with_local.find("launch-day", _date(2026, 8, 25))
    b = without.find("launch-day", _date(2026, 8, 25))
    assert a.post["body"] == "LOCAL"
    assert b.post["body"] != "LOCAL"
    shutil.rmtree(d, ignore_errors=True)




@test("no calendar names one particular game")
def _():
    for t in TEMPLATES:
        text = t.read_text("utf-8").lower()
        for word in ("giltgrave", "gacha", "tower", "hero-showcase"):
            assert word not in text, f"{t.name} still mentions {word!r}"


@test("there is a calendar for each kind of project")
def _():
    # Steam is not the only place a game lives, and the calendar for a Roblox
    # experience or a mod has almost nothing in common with a store launch.
    have = {t.stem for t in TEMPLATES}
    for want in ("general", "steam-game", "roblox-game", "mod"):
        assert want in have, f"no {want} calendar. Have: {sorted(have)}"


@test("a template names itself, so the picker is readable")
def _():
    for t in TEMPLATES:
        meta = _yaml.safe_load(t.read_text("utf-8")).get("meta") or {}
        assert meta.get("name"), f"{t.name} has no meta.name"
        assert meta["name"] != t.stem, f"{t.name} has no human name"


# ---------------------------------------------------------------------------
print("\ncalendar storage")


@test("a post can only be claimed once")
def _():
    L = fresh_ledger()
    assert L.calendar_record(1, "post", "2027-01-01", "drafted") is True
    # The second claim is the one that matters: two ticks racing, or a restart
    # mid-post, must not put the same post out twice.
    assert L.calendar_record(1, "post", "2027-01-01", "drafted") is False


@test("the same post can fire again on a different day")
def _():
    L = fresh_ledger()
    assert L.calendar_record(1, "weekly", "2027-01-02", "drafted")
    assert L.calendar_record(1, "weekly", "2027-01-09", "drafted")


@test("only a drafted post can be decided, so two clicks cannot double-post")
def _():
    L = fresh_ledger()
    L.calendar_record(1, "b", "2027-01-01", "drafted")
    assert L.calendar_decide(1, "b", "2027-01-01", "published", 99) is True
    assert L.calendar_decide(1, "b", "2027-01-01", "published", 98) is False
    row = L.calendar_seen(1, "b", "2027-01-01")
    assert row["status"] == "published" and row["decided_by"] == 99


@test("a draft is found by its message id")
def _():
    L = fresh_ledger()
    L.calendar_record(1, "b", "2027-01-01", "drafted", draft_id=555)
    assert L.calendar_by_draft(1, 555)["post_id"] == "b"
    assert L.calendar_by_draft(1, 999) is None
    assert L.calendar_by_draft(2, 555) is None


@test("pending posts are listed for the calendar command")
def _():
    L = fresh_ledger()
    L.calendar_record(1, "a", "2027-01-01", "drafted")
    L.calendar_record(1, "b", "2027-01-02", "published")
    pending = L.calendar_pending(1)
    assert [p["post_id"] for p in pending] == ["a"]


# ---------------------------------------------------------------------------
print("\nplaytest pipeline")


@test("signing up is idempotent and rejoining is distinguishable")
def _():
    L = fresh_ledger()
    assert L.playtest_signup(1, 7) is True
    assert L.playtest_signup(1, 7) is False
    L.playtest_leave(1, 7)
    assert len(L.playtest_roster(1)) == 0
    assert len(L.playtest_roster(1, active_only=False)) == 1
    L.playtest_signup(1, 7)
    assert len(L.playtest_roster(1)) == 1


@test("reporting counts as playing even without a formal signup")
def _():
    # Staff can hand somebody a key directly, without them ever running
    # /playtest-join. A plain UPDATE did nothing for those people, so the
    # signed-up-to-played conversion silently undercounted exactly the
    # hand-recruited testers you most want in the number.
    L = fresh_ledger()
    L.playtest_played(1, 42)
    roster = L.playtest_roster(1)
    assert len(roster) == 1 and roster[0]["user_id"] == 42
    assert roster[0]["played_at"]


@test("the first report is the one that counts, not the latest")
def _():
    L = fresh_ledger()
    L.playtest_signup(1, 42)
    L.playtest_played(1, 42)
    first = L.playtest_roster(1)[0]["played_at"]
    L.playtest_played(1, 42)
    assert L.playtest_roster(1)[0]["played_at"] == first


@test("an opted-out member is not resurrected by filing a report")
def _():
    L = fresh_ledger()
    L.forget(42)
    L.playtest_played(1, 42)
    assert L.playtest_roster(1, active_only=False) == []


@test("a key is issued to exactly one person")
def _():
    L = fresh_ledger()
    L.wave_open(1, "wave-1")
    L.add_keys(1, "wave-1", ["AAA", "BBB"])
    a = L.issue_key(1, "wave-1", 10, 99)
    b = L.issue_key(1, "wave-1", 11, 99)
    assert a["key"] != b["key"], "the same key went to two people"
    assert L.issue_key(1, "wave-1", 12, 99) is None, "issued a key that did not exist"


@test("asking twice returns the same key rather than burning another")
def _():
    L = fresh_ledger()
    L.wave_open(1, "w")
    L.add_keys(1, "w", ["AAA", "BBB"])
    first = L.issue_key(1, "w", 10, 99)
    again = L.issue_key(1, "w", 10, 99)
    assert again["key"] == first["key"]
    assert again["reissued"] is True
    assert L.waves(1)[0]["keys_issued"] == 1


@test("duplicate keys are ignored rather than stored twice")
def _():
    L = fresh_ledger()
    L.wave_open(1, "w")
    assert L.add_keys(1, "w", ["AAA", "BBB"]) == {"added": 2, "skipped": 0}
    assert L.add_keys(1, "w", ["BBB", "CCC"])["added"] == 1
    assert L.waves(1)[0]["keys_total"] == 3


@test("a revoked key does not count as issued")
def _():
    L = fresh_ledger()
    L.wave_open(1, "w")
    L.add_keys(1, "w", ["AAA"])
    L.issue_key(1, "w", 10, 99)
    assert L.waves(1)[0]["keys_issued"] == 1
    assert L.revoke_key(1, 10, "w") is True
    assert L.waves(1)[0]["keys_issued"] == 0


@test("forget-me scrubs the person off a key without freeing the key")
def _():
    # The key is spent whether or not the person is still in the ledger.
    # Deleting the row outright would put a live Steam key back in the pool.
    L = fresh_ledger()
    L.wave_open(1, "w")
    L.add_keys(1, "w", ["AAA"])
    L.issue_key(1, "w", 10, 99)
    L.playtest_signup(1, 10)
    L.forget(10)
    assert L.playtest_roster(1, active_only=False) == []
    assert L.issue_key(1, "w", 11, 99) is None, "a forgotten member's key was reissued"
    assert L.key_audit(1) == [], "an audit row still names a deleted member"


@test("opting out blocks a later signup from being recorded")
def _():
    L = fresh_ledger()
    L.forget(10)
    L.playtest_signup(1, 10)
    # The signup table is keyed on the member, so an opted-out member appearing
    # in it would be exactly the data they asked to have deleted.
    assert L.is_opted_out(10)


@test("a wave cannot be opened twice under the same name")
def _():
    L = fresh_ledger()
    assert L.wave_open(1, "w") is True
    assert L.wave_open(1, "w") is False
    assert L.wave_close(1, "w") is True
    assert L.wave_close(1, "w") is False


# ---------------------------------------------------------------------------
print("\ncalendar wiring")

import re                                               # noqa: E402


@test("the bot never opens an unsolicited DM")
def _():
    # Discord's Developer Policy prohibits unsolicited DMs outright, and there
    # is an undocumented quota that quarantines an app with no warning. The
    # only send() to a member is the playtest key, which they asked for.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    sends = re.findall(r"await (member|user)\.send\(", src)
    assert len(sends) <= 1, f"{len(sends)} direct messages in bot.py"


@test("every calendar post sets allowed_mentions explicitly")
def _():
    # A post body containing the literal word @everyone would otherwise ping
    # the whole server. This shipped as a real bug once already.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def draft_post"):src.index("def mention_for")]
    for call in re.finditer(r"await \w+\.(send|create_thread)\(", body):
        tail = body[call.end():call.end() + 400]
        assert "allowed_mentions" in tail, f"unguarded send near: {tail[:80]!r}"


@test("the approval buttons carry fixed custom ids so they survive a restart")
def _():
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert 'custom_id="cal:approve"' in src and 'custom_id="cal:skip"' in src
    assert "timeout=None" in src, "a view with a timeout stops working on restart"
    assert "add_view(PostApproval())" in src, "the view is never re-registered"


@test("bot.py imports and every command is registered")
def _():
    """The suite read bot.py as text until now, so a decorator discord.py
    rejects, or a parameter type it cannot turn into a slash-command option,
    would only surface the next time the bot was started. This builds the real
    command tree in a subprocess and reads back what is on it."""
    import os, subprocess, tempfile, json as _json
    probe = (
        "import sys, json\n"
        "sys.path.insert(0, r'{steward}')\n"
        "import bot\n"
        "print(json.dumps(sorted(c.name for c in bot.client.tree.get_commands())))"
    ).format(steward=ROOT / "steward")
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ)
        env["STEWARD_DB"] = str(Path(d) / "t.sqlite3")
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                           text=True, cwd=str(ROOT), env=env, timeout=180)
    assert r.returncode == 0, r.stderr[-1500:]
    names = _json.loads(r.stdout.strip().splitlines()[-1])
    for wanted in ("calendar", "calendar-run", "calendar-reload",
                   "playtest-join", "playtest-leave", "playtest-open",
                   "playtest-keys", "playtest-issue", "playtest-status",
                   "playtest-close", "playtest-report",
                   "rank", "leaderboard", "digest", "forget-me"):
        assert wanted in names, f"/{wanted} is not registered. Have: {names}"


@test("commands are registered per server, and not also globally")
def _():
    """A command registered both ways is listed twice in the picker.

    Global commands sit in Discord's cache for up to an hour, so a renamed
    option kept showing its old name. Per-guild commands appear at once. Doing
    both, which was the first fix, put every command in the list twice.
    """
    import asyncio as _aio2, types as _t2
    calls = []

    class _Tree:
        def __init__(self, on_discord):
            self.on_discord = list(on_discord)
            self._cmds = ["a", "b"]

        def copy_global_to(self, guild):
            calls.append(("copy", guild.name))

        async def sync(self, guild=None):
            calls.append(("sync", guild.name if guild else "GLOBAL"))
            if guild is None:
                self.on_discord = list(self._cmds)

        async def fetch_commands(self):
            return self.on_discord

        def get_commands(self):
            return list(self._cmds)

        def clear_commands(self, guild=None):
            self._cmds = []

        def add_command(self, c):
            self._cmds.append(c)

    import tempfile, os
    os.environ["STEWARD_DB"] = str(Path(tempfile.mkdtemp()) / "t.sqlite3")
    sys.path.insert(0, str(ROOT / "steward"))
    import bot as _b

    c = _b.client
    g1 = _t2.SimpleNamespace(name="One")
    g2 = _t2.SimpleNamespace(name="Two")
    was_tree, was_guilds = c.tree, type(c).guilds
    try:
        type(c).guilds = property(lambda self: [g1, g2])
        c.tree = _Tree(on_discord=["a-stale-global"])
        _aio2.run(c.sync_commands())

        assert ("sync", "One") in calls and ("sync", "Two") in calls, calls
        # The global clear has to come after the per-guild pushes, or the
        # servers get nothing.
        assert calls.index(("sync", "GLOBAL")) > calls.index(("sync", "Two")), calls
        assert c.tree.on_discord == [], "the global copies were left behind"
        assert c.tree.get_commands(),             "the in-memory tree was emptied, so a later join gets no commands"

        # Joining a server later still works, which is what the global sync
        # used to cover.
        calls.clear()
        c.tree = _Tree(on_discord=[])
        _aio2.run(c.on_guild_join(_t2.SimpleNamespace(name="New")))
        assert ("sync", "New") in calls, calls
    finally:
        c.tree = was_tree
        type(c).guilds = was_guilds


@test("the calendar-run option is called post")
def _():
    # It was called beat, which is the word this whole rename removed.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    block = src[src.index('name="calendar-run"'):src.index("async def calendar_run") + 200]
    assert "post=" in block, "the describe still names the old option"
    assert "post: str | None" in block, "the parameter is not called post"
    assert 'autocomplete("post")' in src


@test("every command touching interaction.guild is marked guild_only")
def _():
    # In a DM interaction.guild is None and the command dies on an attribute
    # error, which Discord shows the user as "the application did not respond".
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    parts = src.split("@client.tree.command(")
    for i, block in enumerate(parts[1:], 1):
        name = re.search(r'name="([\w-]+)"', block).group(1)
        body = block
        if not any(t in body for t in ("interaction.guild", "interaction.guild_id")):
            continue
        assert parts[i - 1].rstrip().endswith("@app_commands.guild_only()"), \
            f"/{name} reads interaction.guild but is not guild_only"


@test("a post can be found by name so it can be tested out of season")
def _():
    # Without this the only way to see a post is to wait for its date, which
    # for a T-140 post is months. /calendar-run leans on it.
    cal = fresh_calendar()
    occ = cal.find("launch-day", _date(2026, 9, 1))
    assert occ is not None and occ.date == _date(2026, 9, 1)
    assert "{{" not in occ.post["body"], "find() skipped the placeholder fill"
    assert cal.find("no-such-post", _date(2026, 9, 1)) is None
    assert "launch-day" in cal.ids() and "screenshot-saturday" in cal.ids()


@test("the calendar claims a post before posting it")
def _():
    # If the send fails after the claim, the post is marked failed. If the claim
    # came second, a crash between send and claim would repost it every hour.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def draft_post"):src.index("def find_post")]
    claim = body.index("calendar_record(guild.id, occ.id, occ.date.isoformat(),\n"
                       "                                           \"drafted\")")
    send = body.index("msg = await staff.send(")
    assert claim < send, "the post is posted before it is claimed"

# ---------------------------------------------------------------------------
print("\ncalendar, end to end")

import asyncio as _aio                                    # noqa: E402
import types as _types                                    # noqa: E402


class _Chan:
    """Just enough of a Discord channel to drive draft and publish."""

    def __init__(self, name, kind="text"):
        self.name, self.kind, self.sent = name, kind, []
        self.mention = f"#{name}"
        self.published = False

    def is_news(self):
        return self.kind == "news"

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        chan = self

        async def pub():
            chan.published = True

        async def edit(**k):
            chan.edited = k

        return _types.SimpleNamespace(
            id=len(self.sent), publish=pub, edit=edit,
            embeds=[kw["embed"]] if kw.get("embed") else [])


class _Guild:
    def __init__(self):
        self.id = 1
        self.text_channels = [_Chan("steward-reports"), _Chan("announcements", "news"),
                              _Chan("general")]
        self.forums, self.roles, self.voice_channels = [], [], []

    def get_channel(self, cid):
        return None

    async def fetch_scheduled_events(self):
        return []


async def _noop(**k):
    pass


def _bot(tmpdb):
    """Import bot.py against a throwaway database and hand back the client."""
    import os, importlib
    os.environ["STEWARD_DB"] = str(tmpdb)
    sys.path.insert(0, str(ROOT / "steward"))
    import bot as _b
    importlib.reload(_b)
    return _b


def _drive(fn):
    # mkdtemp rather than TemporaryDirectory: Windows will not delete a file
    # SQLite still has open, and the cleanup raises before the test can report.
    import os, tempfile
    d = tempfile.mkdtemp()
    # Pin the calendar. Without this the suite reads whatever steward/.env
    # happens to say, so switching template on a real machine broke tests that
    # have nothing to do with it.
    os.environ["CALENDAR"] = "steam-game"
    b = _bot(Path(d) / "t.sqlite3")
    return _aio.run(fn(b, _Guild()))


@test("an edit made while the bot runs reaches the next draft")
def _():
    """The calendar was read once at startup and never again.

    An edit made in the setup page therefore did not reach a running bot: the
    draft showed the old wording, approving it would have posted the old
    wording, and nothing anywhere said the two had diverged.

    Driven against a calendar in a temp folder, never the real one. An earlier
    version of this test wrote to and then deleted the actual overrides file,
    which destroyed somebody's edits.
    """
    import shutil, tempfile, time as _t, yaml as _y
    from datetime import date as _d

    d = Path(tempfile.mkdtemp())
    cal = d / "c.yaml"
    shutil.copy(CALENDAR, cal)
    local = ce.overrides_path(cal)

    loaded = [ce.load(cal, {"game": "x"})]
    stamp = [None]

    def mtimes():
        out = []
        for f in (cal, local):
            try:
                out.append(f.stat().st_mtime)
            except OSError:
                out.append(0.0)
        return tuple(out)

    def refresh():
        now = mtimes()
        if now == stamp[0]:
            return False
        loaded[0] = ce.load(cal, {"game": "x"})
        stamp[0] = now
        return True

    refresh()
    before = loaded[0].find("launch-day", _d(2026, 8, 17))
    assert before is not None

    _t.sleep(0.02)                      # mtime resolution
    local.write_text(_y.safe_dump(
        {"posts": [{"id": "launch-day", "body": "EDITED WHILE RUNNING"}]},
        sort_keys=False), encoding="utf-8")

    assert refresh(), "the change on disk went unnoticed"
    after = loaded[0].find("launch-day", _d(2026, 8, 17))
    assert after.post["body"] == "EDITED WHILE RUNNING", after.post["body"]
    shutil.rmtree(d, ignore_errors=True)


@test("the bot checks for a changed calendar everywhere it reads one")
def _():
    # Approving matters most: a draft can sit in a staff channel for hours, and
    # approving it must post what the calendar says now.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert "def refresh_calendar" in src
    body = src[src.index("def find_post"):src.index("async def close_draft")]
    assert "refresh_calendar()" in body, "approving a draft does not re-read"
    tick = src[src.index("async def calendar_tick"):src.index("@calendar_tick.before_loop")]
    assert "refresh_calendar()" in tick, "the hourly tick does not re-read"


@test("no test resolves overrides against the real calendar")
def _():
    # This suite deleted a real overrides file once and lost somebody's edits,
    # because it built the path from the bot's own CALENDAR and then unlinked
    # it. Temp copies only.
    #
    # The needles are assembled here rather than written out, or this check
    # matches its own source and fails forever.
    fn = "overrides_path"
    text = (ROOT / "tests" / "run_tests.py").read_text(encoding="utf-8")
    for arg in ("b.CALENDAR", "CALENDAR", "bot.CALENDAR"):
        needle = fn + "(" + arg + ")"
        assert needle not in text, f"a test would touch the real overrides: {needle}"


@test("naming a post re-drafts it even if it already went out today")
def _():
    # The per-day record exists to stop the hourly tick repeating itself. It
    # was also refusing a person who asked twice, which made it impossible to
    # look at an edit: "already handled today, try again tomorrow".
    L = fresh_ledger()
    assert L.calendar_record(1, "launch-day", "2026-08-17", "skipped")
    assert L.calendar_seen(1, "launch-day", "2026-08-17")
    assert L.calendar_forget(1, "launch-day", "2026-08-17") is True
    assert L.calendar_seen(1, "launch-day", "2026-08-17") is None
    assert L.calendar_record(1, "launch-day", "2026-08-17", "drafted")
    assert L.calendar_forget(1, "nothing-here", "2026-08-17") is False

    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def calendar_run"):src.index("@calendar_run.autocomplete")]
    assert "calendar_forget" in body, "/calendar-run still refuses a repeat"


@test("a database from before the rename still opens")
def _():
    # calendar_runs.beat_id became post_id. Anybody upgrading has rows under
    # the old name, and losing them would let every past post fire again.
    import sqlite3 as _sq, tempfile
    d = Path(tempfile.mkdtemp())
    db = d / "old.sqlite3"
    con = _sq.connect(db)
    con.executescript(
        "CREATE TABLE calendar_runs (guild_id INTEGER NOT NULL, "
        "beat_id TEXT NOT NULL, fire_date TEXT NOT NULL, status TEXT NOT NULL, "
        "draft_id INTEGER, published_id INTEGER, decided_by INTEGER, "
        "decided_at INTEGER, note TEXT, created_at INTEGER NOT NULL, "
        "PRIMARY KEY (guild_id, beat_id, fire_date)); "
        "INSERT INTO calendar_runs VALUES "
        "(1,'launch-day','2026-08-17','skipped',9,NULL,7,1,NULL,1);")
    con.commit()
    con.close()

    L = Ledger(db)
    cols = [r["name"] for r in L.db.execute("PRAGMA table_info(calendar_runs)")]
    assert "post_id" in cols and "beat_id" not in cols, cols
    row = L.calendar_seen(1, "launch-day", "2026-08-17")
    assert row and row["status"] == "skipped", "the old row was lost"


@test("nothing user-facing still says beat")
def _():
    # It is content-marketing jargon and it confused the one person using it.
    word = "b" + "eat"
    for rel in ("ui/static/index.html", "README.md", "SETUP.md",
                "steward/bot.py", "steward/calendar_engine.py", "ui/app.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if word not in low:
                continue
            # The YAML key is still read so old files keep working, and the
            # ordinary English verb is allowed.
            allowed = ('get("beats"', 'pop("beats"', '"beats", "recurring"',
                       "'beats:'", "`beats:`", "beats burning", "beats answering",
                       "beats most alternatives", "heartbeat",
                       "beat_id", "content-marketing jargon")
            if any(ok in line for ok in allowed):
                continue
            raise AssertionError(f"{rel}:{i} still says it: {line.strip()[:90]}")


@test("a post drafted out of season can still be approved")
def _():
    # /calendar-run drafts a post dated today, which is the only way to look at
    # a T-140 post in August. Approval used to ask the schedule what was due on
    # that date, found nothing, and refused every test draft it had just made.
    async def go(b, g):
        from datetime import date as _d
        today = _d(2026, 8, 17)
        occ = b.client.calendar.find("launch-day", today)
        assert occ is not None, "launch-day is not in the calendar"
        assert await b.client.draft_post(g, occ), "draft failed"
        run = b.client.ledger.calendar_by_draft(1, 1)
        assert run and run["status"] == "drafted"

        inter = _types.SimpleNamespace(
            guild=g, guild_id=1,
            user=_types.SimpleNamespace(
                id=7, mention="@me",
                guild_permissions=_types.SimpleNamespace(manage_guild=True)),
            message=_types.SimpleNamespace(id=1, embeds=[], edit=_noop))
        await b.client.publish_post(inter, run)

        ann = g.text_channels[1]
        assert len(ann.sent) == 1, "the post never reached its channel"
        after = b.client.ledger.calendar_seen(1, "launch-day", "2026-08-17")
        assert after["status"] == "published", after
        return True
    assert _drive(go)


@test("the draft warns before a post that pings the whole server")
def _():
    async def go(b, g):
        from datetime import date as _d
        occ = b.client.calendar.find("launch-day", _d(2026, 8, 17))
        await b.client.draft_post(g, occ)
        body = g.text_channels[0].sent[0][0]
        assert "pings people" in body, body
        assert "#announcements" in body, body
        return True
    assert _drive(go)


@test("an approved post is crossposted from an announcement channel")
def _():
    # Announcement channels can be followed by other servers, which is free
    # reach and the reason #devlog and #announcements are that type.
    async def go(b, g):
        from datetime import date as _d
        occ = b.client.calendar.find("launch-day", _d(2026, 8, 17))
        await b.client.draft_post(g, occ)
        run = b.client.ledger.calendar_by_draft(1, 1)
        inter = _types.SimpleNamespace(
            guild=g, guild_id=1,
            user=_types.SimpleNamespace(
                id=7, mention="@me",
                guild_permissions=_types.SimpleNamespace(manage_guild=True)),
            message=_types.SimpleNamespace(id=1, embeds=[], edit=_noop))
        await b.client.publish_post(inter, run)
        assert g.text_channels[1].published, "not crossposted"
        return True
    assert _drive(go)


@test("a reminder skips approval and stops at staff")
def _():
    async def go(b, g):
        from datetime import date as _d
        occ = b.client.calendar.find("launch-week", _d(2026, 8, 17))
        await b.client.draft_post(g, occ)
        row = b.client.ledger.calendar_seen(1, "launch-week", "2026-08-17")
        assert row["status"] == "published", row
        staff = g.text_channels[0]
        assert len(staff.sent) == 1
        assert "view" not in staff.sent[0][1], "a reminder was given buttons"
        # And it must not have reached anywhere members can see.
        assert not g.text_channels[1].sent and not g.text_channels[2].sent
        return True
    assert _drive(go)


@test("a post aimed at a channel that does not exist fails once, not forever")
def _():
    async def go(b, g):
        from datetime import date as _d
        g.text_channels = [_Chan("steward-reports")]      # no #announcements
        occ = b.client.calendar.find("launch-day", _d(2026, 8, 17))
        await b.client.draft_post(g, occ)
        row = b.client.ledger.calendar_seen(1, "launch-day", "2026-08-17")
        assert row["status"] == "failed", row
        # Recorded, so the hourly tick does not retry it every hour all week.
        assert await b.client.draft_post(g, occ) is False
        return True
    assert _drive(go)


# ---------------------------------------------------------------------------
print("\ndecay detection")

import decay                                             # noqa: E402

DAY = 86400


def seeded_ledger(plan, now=None):
    """plan: {channel_id: [messages on day -N, ..., messages yesterday]}.
    Day 0 in each list is the oldest."""
    import time as _t
    L = fresh_ledger()
    now = now or int(_t.time())
    span = max(len(v) for v in plan.values())
    for cid, counts in plan.items():
        for i, n in enumerate(counts):
            ts = now - (span - i) * DAY + 3600
            for k in range(n):
                L.record(guild_id=1, user_id=1000 + k, channel_id=cid,
                         event_type="message", ts=ts)
    return L, now


@test("the median ignores a single loud day")
def _():
    # A patch-notes day with forty messages would drag a mean up for a month,
    # and every ordinary week after it would then read as decay.
    assert decay.median([2, 2, 2, 2, 40]) == 2
    assert decay.median([]) == 0
    assert decay.median([1, 3]) == 2


@test("it refuses to report before there is enough history")
def _():
    # This is the whole reason the feature was built last. On a young server
    # the baseline is the launch spike and every channel looks like it is dying.
    L, now = seeded_ledger({10: [5] * 14})
    r = decay.analyse(L, 1, now=now)
    assert r["ready"] is False
    assert r["channels"] == []
    assert "history" in r["why"]
    assert r["need_days"] > r["have_days"]


@test("a channel that genuinely went quiet is reported")
def _():
    # 60 days at 10 a day, then a week at 1.
    L, now = seeded_ledger({10: [10] * 60 + [1] * 7})
    r = decay.analyse(L, 1, now=now)
    assert r["ready"], r["why"]
    quiet = [c for c in r["channels"] if c["verdict"] == "quiet"]
    assert len(quiet) == 1, r["channels"]
    assert quiet[0]["channel_id"] == 10
    assert quiet[0]["change_pct"] < -80, quiet[0]


@test("a quiet week everywhere is not reported as every channel decaying")
def _():
    # Christmas. Everything halves. Nothing has gone wrong with any one
    # channel, and a report that fires now is a report nobody trusts again.
    plan = {c: [10] * 60 + [5] * 7 for c in (10, 11, 12, 13)}
    L, now = seeded_ledger(plan)
    r = decay.analyse(L, 1, now=now)
    assert r["ready"]
    assert not [c for c in r["channels"] if c["verdict"] == "quiet"], r["channels"]
    assert r["server_change_pct"] < -40, r["server_change_pct"]


@test("a channel falling faster than the server still gets caught")
def _():
    # Same quiet week, but one channel fell much further than the rest.
    plan = {c: [10] * 60 + [5] * 7 for c in (10, 11, 12)}
    plan[13] = [10] * 60 + [0] * 7
    L, now = seeded_ledger(plan)
    r = decay.analyse(L, 1, now=now)
    quiet = [c for c in r["channels"] if c["verdict"] == "quiet"]
    assert [c["channel_id"] for c in quiet] == [13], r["channels"]


@test("a channel too quiet to have a trend is left alone")
def _():
    # One message a day can fall to zero because somebody took a holiday.
    L, now = seeded_ledger({10: [10] * 60 + [10] * 7,      # keeps the server flat
                            11: [1] * 60 + [0] * 7})
    r = decay.analyse(L, 1, now=now)
    assert 11 not in [c["channel_id"] for c in r["channels"]], r["channels"]


@test("silent days count as zero rather than as missing data")
def _():
    # Skipping days with no messages would make a channel that went silent look
    # like it has no data instead of no activity, which is the opposite reading.
    rates = decay._rates({"2020-01-02": 5}, 3, 1577923200)   # 2020-01-02 UTC
    assert len(rates) == 3
    assert rates.count(0.0) == 2, rates


@test("a channel that got busier is news too")
def _():
    L, now = seeded_ledger({10: [10] * 60 + [10] * 7,
                            11: [3] * 60 + [12] * 7})
    r = decay.analyse(L, 1, now=now)
    busy = [c for c in r["channels"] if c["verdict"] == "busy"]
    assert 11 in [c["channel_id"] for c in busy], r["channels"]


@test("the digest says why rather than dropping the heading")
def _():
    L, now = seeded_ledger({10: [5] * 10})
    r = decay.analyse(L, 1, now=now)
    assert decay.summarise(r) == [], "a report that is not ready produced lines"
    assert r["why"], "no explanation to show in its place"


@test("the blueprint carries the decay settings")
def _():
    import yaml as _y
    bp = _y.safe_load(BLUEPRINT.read_text(encoding="utf-8"))
    cfg = bp.get("decay")
    assert cfg, "the blueprint has no decay block"
    for key in ("recent_days", "baseline_days", "min_history_days",
                "min_baseline", "drop", "rise"):
        assert key in cfg, f"decay.{key} is missing"
    # The settings have to actually reach the code.
    L, now = seeded_ledger({10: [10] * 60 + [1] * 7})
    assert decay.analyse(L, 1, {"min_history_days": 999}, now=now)["ready"] is False
    assert decay.analyse(L, 1, cfg, now=now)["ready"] is True


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
print("\nswitches")

sys.path.insert(0, str(ROOT / "steward"))
import features as _feat                                 # noqa: E402


@test("a fresh install has everything switched on")
def _():
    """An absent key means on. Nothing should have to be written to .env for
    the tool to behave the way its own documentation describes it."""
    state = _feat.read({})
    assert set(state) == set(_feat.KEYS), state
    assert all(state.values()), state
    assert not _feat.off(state) and not _feat.commands_off(state)


@test("off is understood however it is spelled")
def _():
    for word in ("off", "OFF", "0", "false", "no", " off "):
        assert _feat.read({"FEATURE_LEVELS": word})["levels"] is False, word
    for word in ("on", "1", "true", "yes", ""):
        assert _feat.read({"FEATURE_LEVELS": word})["levels"] is True, word


@test("every switch names commands the bot actually has")
def _():
    """A renamed slash command would otherwise stop being switchable in
    silence: the switch would still be shown and would still turn nothing off.
    """
    import re
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    real = set(re.findall(r'tree\.command\(name="([^"]+)"', src))
    for f in _feat.CATALOG:
        for name in f["commands"]:
            assert name in real, f"{f['key']} claims /{name}, which does not exist"


@test("switching playtests off takes the channel, the roles and the question")
def _():
    """A part is more than its bot job. Leaving #playtest-lounge, two roles and
    an opt-in question on a server that will never run a playtest is how a
    blueprint turns into clutter nobody can explain."""
    bp = load({"features": {"playtest": False}})
    roles = {r["name"] for r in bp["roles"]}
    chans = {c["name"] for cat in bp["categories"] for c in cat["channels"]}
    assert "playtest-lounge" not in chans
    assert "Playtester" not in roles
    assert "Ping Me For Playtests" not in roles, "required, but only for playtests"
    assert not [p for p in bp["onboarding_prompts"] if "playtest" in p["title"].lower()]
    assert not core.validate(bp)["errors"], core.validate(bp)["errors"]


@test("switching levels off takes the tier roles and their rewards")
def _():
    bp = load({"features": {"levels": False}})
    roles = {r["name"] for r in bp["roles"]}
    assert not [r for r in roles if r.startswith("Tier ")], roles
    assert not (bp.get("levels") or {}).get("rewards")
    assert (bp.get("levels") or {}).get("enabled") is False, \
        "the audit would go looking for reward roles that were just dropped"
    assert not core.validate(bp)["errors"], core.validate(bp)["errors"]


@test("everything on is the blueprint untouched")
def _():
    on = load({"features": {k: True for k in _feat.KEYS}})
    plain = load()
    assert [r["name"] for r in on["roles"]] == [r["name"] for r in plain["roles"]]
    assert len(on["onboarding_prompts"]) == len(plain["onboarding_prompts"])


@test("the bot leaves out the commands of a switched-off part")
def _():
    """Answering "that is switched off" is worse than being absent: the command
    still fills the picker and a member cannot tell a choice from a fault."""
    import os, subprocess, tempfile, json as _json
    probe = (
        "import sys, json\n"
        "sys.path.insert(0, r'{steward}')\n"
        "import bot\n"
        "bot.client.hide_switched_off_commands()\n"
        "print(json.dumps(sorted(c.name for c in bot.client.tree.get_commands())))"
    ).format(steward=ROOT / "steward")
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ)
        env["STEWARD_DB"] = str(Path(d) / "t.sqlite3")
        env["FEATURE_PLAYTEST"] = "off"
        env["FEATURE_LEVELS"] = "off"
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                           text=True, cwd=str(ROOT), env=env, timeout=180)
    assert r.returncode == 0, r.stderr[-1500:]
    names = set(_json.loads(r.stdout.strip().splitlines()[-1]))
    for gone in ("rank", "leaderboard", "playtest-join", "playtest-report"):
        assert gone not in names, f"/{gone} survived being switched off"
    for kept in ("calendar", "digest", "forget-me", "my-data"):
        assert kept in names, f"/{kept} was taken out by an unrelated switch"


@test("a switched-off job is never started")
def _():
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert 'if FEATURES["digest"]:\n            self.weekly_digest.start()' in src
    assert 'if FEATURES["calendar"]:\n            self.calendar_tick.start()' in src
    assert "self.nightly_purge.start()" in src and "self.pulse.start()" in src, \
        "retention and the heartbeat are not optional"
    # The moderation log has no command and no channel of its own, so the only
    # thing that can switch it off is the write itself.
    assert 'if not FEATURES["modlog"]:' in src


@test("the ledger has no switch")
def _():
    """Every other part can be rebuilt from the server. Activity history cannot
    be backfilled from anything, so an off switch here would quietly destroy
    the one thing this tool exists to keep."""
    assert "ledger" not in _feat.KEYS
    page = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "The ledger itself has no switch" in page


@test("switching something off writes one line and touches nothing else")
def _():
    """The bot token is in this file. A rewrite that lost it, or that reordered
    it into a comment, would take the whole tool down."""
    import tempfile, shutil
    sys.path.insert(0, str(ROOT / "ui"))
    import app as webapp
    d = Path(tempfile.mkdtemp())
    (d / ".env").write_text(
        "# a comment\nDISCORD_TOKEN=secret.value\nCALENDAR=roblox-game\n",
        encoding="utf-8")
    was = webapp.STEWARD
    try:
        webapp.STEWARD = d
        webapp.write_env(_feat.env_name("levels"), "off")
        text = (d / ".env").read_text(encoding="utf-8")
        assert "DISCORD_TOKEN=secret.value" in text and "# a comment" in text
        assert "CALENDAR=roblox-game" in text
        assert webapp.read_env()["FEATURE_LEVELS"] == "off"
        assert _feat.read(webapp.read_env())["levels"] is False
        # Back on removes the line rather than leaving FEATURE_LEVELS=on to be
        # read as the only way to have levels.
        webapp.write_env(_feat.env_name("levels"), None)
        assert "FEATURE_LEVELS" not in (d / ".env").read_text(encoding="utf-8")
        assert _feat.read(webapp.read_env())["levels"] is True
    finally:
        webapp.STEWARD = was
        shutil.rmtree(d, ignore_errors=True)


@test("the switches survive an update")
def _():
    """They live in .env beside the token, which an update copies over rather
    than replacing. A switch that reset itself on every version bump would be
    worse than no switch."""
    sys.path.insert(0, str(ROOT / "provision"))
    import updates
    keep = set(updates.PROTECTED) | set(updates.KEEP_ON_UPDATE)
    assert any("steward/.env" in str(k).replace("\\", "/") for k in keep), keep


@test("the page offers every switch the bot reads")
def _():
    page = (ROOT / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "loadFeatures()" in page, "nothing fetches them"
    assert "api('/api/features'" in page
    assert "setFeature(" in page
    # The catalog is served rather than duplicated in the page, so a new switch
    # appears without anybody editing the HTML.
    assert "RUN.features.map" in page


@test("no switch leaves a question with a single answer")
def _():
    """Pruning an answer that granted a dropped role can leave a question whose
    only possible reply is "no thanks". Checked across every blueprint against
    every switch, because a variant replaces the questions wholesale and would
    not inherit a fix made to the default."""
    import glob
    for path in sorted(glob.glob(str(ROOT / "blueprint" / "*.yaml"))):
        if path.endswith(".local.yaml"):
            continue
        for key in _feat.KEYS + [None]:
            sel = {"features": {key: False}} if key else None
            bp = core.customize(core.load(path), sel)
            report = core.validate(bp)
            assert not report["errors"], (Path(path).name, key, report["errors"][:2])
            stuck = [w for w in report["warnings"] if "one answer" in w]
            assert not stuck, (Path(path).name, key, stuck)


@test("the switches are written down where somebody editing .env by hand looks")
def _():
    example = (ROOT / "steward" / ".env.example").read_text(encoding="utf-8")
    for key in _feat.KEYS:
        assert _feat.env_name(key) in example, f"{key} is not in .env.example"


print("\nversions and updates")

import updates                                          # noqa: E402


@test("version numbers compare in the right direction")
def _():
    assert updates.newer("0.2.1", "0.2.0")
    assert updates.newer("1.0.0", "0.9.9")
    assert updates.newer("v1.2.0", "1.1.9")
    assert not updates.newer("0.2.0", "0.2.0")
    assert not updates.newer("0.1.0", "0.2.0")
    # 10 is later than 9, which string comparison gets backwards.
    assert updates.newer("0.10.0", "0.9.0")


@test("an unreadable version sorts lowest instead of raising")
def _():
    # A bad tag upstream must not break the check on this machine.
    assert updates.parse("not-a-version") == (0, 0, 0)
    assert updates.parse("") == (0, 0, 0)
    assert not updates.newer("garbage", "0.0.1")


@test("VERSION is a single line, and it is the one that is read")
def _():
    raw = (ROOT / "VERSION").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d+\.\d+\.\d+\s*", raw), f"VERSION holds {raw!r}"
    # Reading the whole file would return a multi-line string that then gets
    # compared, displayed, and written into a git tag. This happened.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "VERSION"
        f.write_text("1.2.3\nsomebody's note\n", encoding="utf-8")
        was = updates.VERSION_FILE
        try:
            updates.VERSION_FILE = f
            assert updates.version() == "1.2.3", updates.version()
        finally:
            updates.VERSION_FILE = was


@test("an update never counts protected paths as overwritable")
def _():
    # These hold a live bot token and an activity history Discord cannot
    # rebuild. Neither may ever be listed as a file an update can replace.
    for p in ("steward/.env", "steward/data", "backups"):
        assert p in updates.PROTECTED, f"{p} is not protected"
    assert not any(d.startswith(("steward/.env", "steward/data", "backups"))
                   for d in updates.dirty_files())


@test("this checkout can see its own update channel")
def _():
    assert updates.is_git_checkout(), "the repo is not a git checkout"
    slug = updates.remote_slug()
    assert slug and "/" in slug, f"cannot read owner/repo from the remote: {slug}"


@test("the release tool refuses a version that is not newer")
def _():
    # Version numbers only go up. If one ever went down, the update check could
    # not tell which way forward was.
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "release.py"),
                        "0.0.1", "--dry-run"],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    assert r.returncode != 0, "release.py accepted an older version"
    assert "not newer" in (r.stdout + r.stderr)


@test("the release tool refuses a version that is not three numbers")
def _():
    import subprocess
    for bad in ("banana", "1.2", "v1.2.3.4.5"):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "release.py"),
                            bad, "--dry-run"],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        assert r.returncode != 0, f"release.py accepted {bad!r}"


@test("a downloaded copy updates without touching anyone's data")
def _():
    """The release path, driven end to end against a fake install.

    The archive deliberately contains a .env, a ledger and an interpreter. A
    naive extract-over-the-top would replace all three, which would hand the
    user somebody else's bot token, destroy an activity history Discord cannot
    rebuild, and try to overwrite the running interpreter.
    """
    import io, shutil, tempfile, zipfile, urllib.request
    home = Path(tempfile.mkdtemp(prefix="fakeinstall-"))
    (home / "ui").mkdir(parents=True)
    (home / "steward" / "data").mkdir(parents=True)
    (home / "python").mkdir()
    (home / "blueprint").mkdir()
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (home / "ui" / "app.py").write_text("# OLD\n", encoding="utf-8")
    (home / "blueprint" / "default.yaml").write_text("mine: edited\n", encoding="utf-8")
    (home / "steward" / ".env").write_text("DISCORD_TOKEN=theirs\n", encoding="utf-8")
    (home / "steward" / "data" / "l.sqlite3").write_text("LEDGER", encoding="utf-8")
    (home / "python" / "python.exe").write_text("INTERPRETER", encoding="utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Steward-0.4.0/VERSION", "0.4.0\n")
        z.writestr("Steward-0.4.0/ui/app.py", "# NEW\n")
        z.writestr("Steward-0.4.0/blueprint/default.yaml", "shipped: default\n")
        z.writestr("Steward-0.4.0/steward/.env", "DISCORD_TOKEN=NOT_THEIRS\n")
        z.writestr("Steward-0.4.0/steward/data/l.sqlite3", "SOMEBODY ELSES")
        z.writestr("Steward-0.4.0/python/python.exe", "DIFFERENT")

    class _Resp:
        def read(self): return buf.getvalue()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    saved = (updates.ROOT, updates.VERSION_FILE, updates.BACKUPS,
             updates.check_release, updates.is_git_checkout,
             urllib.request.urlopen)
    try:
        updates.ROOT = home
        updates.VERSION_FILE = home / "VERSION"
        updates.BACKUPS = home / "backups"
        updates.check_release = lambda slug: {
            "ok": True, "behind": 1, "latest": "0.4.0", "current": "0.1.0"}
        updates.is_git_checkout = lambda: False
        urllib.request.urlopen = lambda *a, **k: _Resp()
        res = updates.apply()
    finally:
        (updates.ROOT, updates.VERSION_FILE, updates.BACKUPS,
         updates.check_release, updates.is_git_checkout,
         urllib.request.urlopen) = saved

    try:
        assert res["ok"] and res["restart"], res
        assert (home / "ui" / "app.py").read_text().strip() == "# NEW", "code not updated"
        assert (home / "VERSION").read_text().strip() == "0.4.0"

        env = (home / "steward" / ".env").read_text()
        assert "theirs" in env, "the update overwrote the user's bot token"
        led = (home / "steward" / "data" / "l.sqlite3").read_text()
        assert led == "LEDGER", "the update destroyed the activity history"
        py = (home / "python" / "python.exe").read_text()
        assert py == "INTERPRETER", "the update replaced the running interpreter"

        # An edited blueprint is replaced, but only after being copied aside.
        assert (home / "blueprint" / "default.yaml").read_text().strip() \
            == "shipped: default"
        kept = list((home / "backups").rglob("default.yaml"))
        assert kept and kept[0].read_text().strip() == "mine: edited", \
            "the edited blueprint was replaced without a backup"
    finally:
        shutil.rmtree(home, ignore_errors=True)


@test("the paths an update must never replace are all listed")
def _():
    for p in ("steward/.env", "steward/data", "backups", "python"):
        assert p in updates.KEEP_ON_UPDATE, f"{p} is not protected from an update"


@test("the packaged build ships no secrets and no dev-only files")
def _():
    # Reads the build script rather than building, which takes minutes and
    # needs the network. What matters is that steward/ is copied file by file:
    # a blanket copytree would take .env and data/ with it.
    src = (ROOT / "tools" / "build_dist.py").read_text(encoding="utf-8")
    trees = re.search(r"COPY_TREES = \[(.*?)\]", src, re.S).group(1)
    for forbidden in ('"steward"', "'steward'", '"tests"', '"backups"'):
        assert forbidden not in trees,             f"build_dist copies {forbidden} wholesale, which would ship secrets"
    assert "STEWARD_FILES" in src and "*.py" in src
    # And the reason has to stay written down.
    assert ".env" in src and "data" in src


@test("the packaged build leaves matplotlib out")
def _():
    # It is 115 MB of a 70 MB product for one image a week, and the digest
    # already falls back to a text sparkline. The page installs it on request.
    src = (ROOT / "tools" / "build_dist.py").read_text(encoding="utf-8")
    assert "requirements-charts.txt is deliberately not here" in src
    assert (ROOT / "steward" / "requirements-charts.txt").exists()
    core = (ROOT / "steward" / "requirements.txt").read_text(encoding="utf-8")
    assert "matplotlib" not in core, "matplotlib is back in the core requirements"


@test("the embeddable interpreter gets site-packages switched on")
def _():
    # python3xx._pth leaves site-packages out by default, so every dependency
    # installed into the bundled interpreter is invisible and the failure looks
    # like a broken install rather than one commented-out line.
    src = (ROOT / "tools" / "build_dist.py").read_text(encoding="utf-8")
    assert "#import site" in src and "_pth" in src


@test("the installer version matches VERSION")
def _():
    # A .iss cannot read a file at compile time, so it carries its own copy and
    # the two drift. release.py bumps both; this catches a hand edit that did not.
    iss = (ROOT / "install" / "setup.iss").read_text(encoding="utf-8")
    declared = re.search(r'#define AppVersion\s+"([^"]+)"', iss).group(1)
    assert declared == updates.version(),         f"setup.iss says {declared}, VERSION says {updates.version()}"


@test("the release tool bumps both places")
def _():
    src = (ROOT / "tools" / "release.py").read_text(encoding="utf-8")
    assert "setup.iss" in src, "release.py does not touch the installer version"
    assert "AppVersion" in src


@test("backups are gitignored, or the next update sees them as edits")
def _():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "backups/" in ignored


# ---------------------------------------------------------------------------
print("\nlaunchers and shortcuts")


@test("every path the installer points at exists")
def _():
    # A shortcut to a file that moved fails silently months later, and the
    # failure looks like the program being broken rather than the shortcut.
    ps1 = (ROOT / "install" / "Install.ps1").read_text(encoding="utf-8")
    joins = re.findall(r"Join-Path \$Root '([^']+)'", ps1)
    assert joins, "the installer no longer resolves anything against $Root"
    for rel in joins:
        assert (ROOT / rel.replace("\\", "/")).exists(), \
            f"Install.ps1 points at {rel}, which does not exist"


@test("the launchers exist and run the file they claim to")
def _():
    for bat, must in (("START.bat", "app.py"),
                      ("INSTALL.bat", "install\\Install.ps1"),
                      ("install/Uninstall.bat", "install\\Uninstall.ps1"),
                      ("steward/START-LEDGER.bat", "bot.py")):
        p = ROOT / bat
        assert p.exists(), f"{bat} is missing"
        assert must in p.read_text(encoding="utf-8"), f"{bat} does not run {must}"


@test("the bot survives the page that started it, on either platform")
def _():
    # Detaching is spelled differently on Windows and POSIX. Without the POSIX
    # half the ledger dies with the setup page, which is the one thing it must
    # never do: Discord cannot hand back activity from a period when nothing
    # was listening.
    src = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("def ledger_start"):src.index("def ledger_stop")]
    assert "DETACHED_PROCESS" in body, "no Windows detach"
    assert "start_new_session" in body, "no POSIX detach"


@test("there is a launcher for both platforms")
def _():
    for name in ("START.bat", "start.sh"):
        p = ROOT / name
        assert p.exists(), f"{name} is missing"
        assert "app.py" in p.read_text(encoding="utf-8")


@test("the icon carries every size Windows asks for")
def _():
    # Windows picks a frame by context: 256 for the large-icon view, 32 for the
    # taskbar, 16 for the Start Menu list. A single big frame gets scaled by
    # Windows, which is exactly what this mark was drawn to avoid.
    ico = ROOT / "brand" / "steward.ico"
    assert ico.exists(), "brand/steward.ico is missing. Run python brand/icon.py"
    from PIL import Image
    sizes = {s[0] for s in Image.open(ico).info["sizes"]}
    for needed in (16, 32, 48, 256):
        assert needed in sizes, f"the icon has no {needed}px frame. Has: {sorted(sizes)}"


@test("installing clears shortcuts left by an older name")
def _():
    # The product was called Server Setup for Discord before it was called
    # Steward. Without this, upgrading leaves two Start Menu folders and the
    # only entry containing the new name is the secondary one, so searching
    # for the product finds the wrong thing. That happened.
    ps1 = (ROOT / "install" / "Install.ps1").read_text(encoding="utf-8")
    assert "$FormerNames" in ps1, "Install.ps1 does not clear old names"
    assert "Server Setup for Discord" in ps1
    un = (ROOT / "install" / "Uninstall.ps1").read_text(encoding="utf-8")
    assert "Server Setup for Discord" in un,         "Uninstall.ps1 would leave the old folder behind forever"


@test("the main shortcut is named exactly after the product")
def _():
    # Windows search ranks on the shortcut name. An entry called "Steward
    # ledger only" and no entry called "Steward" means typing the product name
    # surfaces the secondary tool.
    ps1 = (ROOT / "install" / "Install.ps1").read_text(encoding="utf-8")
    assert "'Steward.lnk'" in ps1, "there is no shortcut named exactly Steward"
    assert "ledger only" not in ps1, "the old confusing secondary name is back"


@test("the installer stays per-user, so it never needs administrator")
def _():
    ps1 = (ROOT / "install" / "Install.ps1").read_text(encoding="utf-8")
    # 'Programs' and 'Desktop' are the per-user folders. CommonPrograms and
    # CommonDesktopDirectory are the all-users ones and would prompt for admin.
    for forbidden in ("CommonPrograms", "CommonDesktopDirectory", "CommonStartMenu"):
        assert forbidden not in ps1, f"Install.ps1 writes to {forbidden}, which needs admin"
    assert "GetFolderPath('Programs')" in ps1


@test("the uninstaller never deletes the ledger")
def _():
    # The activity history cannot be rebuilt from Discord, and uninstalling
    # shortcuts is not consent to destroy it.
    text = (ROOT / "install" / "Uninstall.ps1").read_text(encoding="utf-8")
    removes = re.findall(r"Remove-Item[^\n]*", text)
    for line in removes:
        assert "data" not in line and "sqlite" not in line, \
            f"the uninstaller touches the ledger: {line}"
    iss = (ROOT / "install" / "setup.iss").read_text(encoding="utf-8")
    block = iss[iss.index("[UninstallDelete]"):iss.index("[Code]")]
    for line in block.splitlines():
        if line.strip().startswith("Type:"):
            assert "steward\\data" not in line and ".env" not in line, \
                f"the installer would delete data on uninstall: {line}"


@test("the installer packages no secrets")
def _():
    # steward/.env holds a live bot token and steward/data holds members'
    # activity. Either one inside a distributed installer is a breach.
    iss = (ROOT / "install" / "setup.iss").read_text(encoding="utf-8")
    block = iss[iss.index("[Files]"):iss.index("[Icons]")]
    for line in block.splitlines():
        if not line.strip().startswith("Source:"):
            continue
        src = re.search(r'Source: "([^"]+)"', line).group(1)
        assert not src.endswith("\\.env"), f"the installer ships {src}"
        assert "steward\\data" not in src, f"the installer ships {src}"
        # A bare steward\* would sweep up both of the above.
        assert src != "..\\steward\\*", "steward\\* would package .env and the ledger"


# ---------------------------------------------------------------------------
print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("\nfailures:")
    for name, why in FAIL:
        print(f"  {name}: {why.splitlines()[0] if why else ''}")
    sys.exit(1)
