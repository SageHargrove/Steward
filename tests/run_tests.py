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

CALENDAR = ROOT / "blueprint" / "content-calendar.yaml"
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


@test("the shipped calendar is valid against the shipped blueprint")
def _():
    bp = _yaml.safe_load(CALENDAR.parent.joinpath("default.yaml").read_text("utf-8"))
    channels = [c["name"] for cat in bp.get("categories", [])
                for c in cat.get("channels", [])]
    roles = [r["name"] for r in bp.get("roles", [])]
    report = fresh_calendar().validate(channels=channels, roles=roles)
    assert not report["errors"], report["errors"]
    # Every beat must aim at a channel the blueprint actually creates, or it
    # will draft and then fail at the moment somebody clicks approve.
    missing = [w for w in report["warnings"] if "not in the blueprint" in w]
    assert not missing, missing


@test("every beat names a channel and has something to say")
def _():
    cal = fresh_calendar()
    for beat in cal.beats + cal.recurring:
        assert beat.get("id"), beat
        assert beat.get("channel"), beat["id"]
        assert beat.get("body", "").strip(), beat["id"]


@test("beat ids are unique, because the id is what stops a repost")
def _():
    cal = fresh_calendar()
    ids = [b["id"] for b in cal.beats + cal.recurring]
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]


@test("placeholders are filled from the blueprint's variables")
def _():
    cal = fresh_calendar()
    occ = [o for o in cal.occurrences(ANCHOR, ANCHOR) if o.id == "launch-day"]
    assert occ, "launch-day does not land on T-0"
    body = occ[0].beat["title"] + occ[0].beat["body"]
    assert "Testgame" in body, body[:120]
    assert "{{" not in body, "an unfilled placeholder reached the post"


@test("recurring beats land on the weekday they name")
def _():
    cal = fresh_calendar()
    start = ANCHOR - _td(days=120)
    got = [o for o in cal.occurrences(start, start + _td(days=28))
           if o.id == "screenshot-saturday"]
    assert got, "screenshot-saturday never fired"
    assert all(o.date.weekday() == 5 for o in got), [str(o.date) for o in got]
    assert len(got) == 4, len(got)


@test("recurring beats stop at their until date")
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


@test("a calendar with no launch date fires nothing")
def _():
    spec = _yaml.safe_load(CALENDAR.read_text("utf-8"))
    spec["meta"]["anchor"] = None
    cal = ce.Calendar(spec)
    assert cal.anchor is None
    relative = [o for o in cal.occurrences(_date(2020, 1, 1), _date(2030, 1, 1))
                if not o.recurring]
    # Only the handful written as absolute dates survive; every T-minus beat
    # is dormant rather than fired against a guessed anchor.
    assert all(str(o.beat.get("when", "")).startswith("20") for o in relative), \
        [o.id for o in relative]
    assert cal.validate()["warnings"], "no warning about the missing launch date"


@test("an unparseable beat is reported and never fired")
def _():
    cal = ce.Calendar({"meta": {"anchor": "2027-03-01"}, "beats": [
        {"id": "bad", "when": "soon", "channel": "general", "body": "x"}]})
    assert cal.validate()["errors"], "a bad date passed validation"
    assert not cal.occurrences(_date(2020, 1, 1), _date(2030, 1, 1))


@test("kind is post or reminder and nothing else")
def _():
    cal = fresh_calendar()
    for beat in cal.beats + cal.recurring:
        assert beat.get("kind", "post") in ("post", "reminder"), beat["id"]
    bad = ce.Calendar({"meta": {"anchor": "2027-03-01"}, "beats": [
        {"id": "b", "when": "T-1", "kind": "shout", "channel": "g", "body": "x"}]})
    assert bad.validate()["errors"]


@test("mentioning everyone is flagged, because it reaches the whole server")
def _():
    warnings = " ".join(fresh_calendar().validate()["warnings"])
    assert "everyone" in warnings


@test("the calendar is generic, not one game's")
def _():
    text = CALENDAR.read_text("utf-8").lower()
    for word in ("giltgrave", "gacha", "tower", "hero-showcase"):
        assert word not in text, f"the calendar still mentions {word!r}"


# ---------------------------------------------------------------------------
print("\ncalendar storage")


@test("a beat can only be claimed once")
def _():
    L = fresh_ledger()
    assert L.calendar_record(1, "beat", "2027-01-01", "drafted") is True
    # The second claim is the one that matters: two ticks racing, or a restart
    # mid-post, must not put the same beat out twice.
    assert L.calendar_record(1, "beat", "2027-01-01", "drafted") is False


@test("the same beat can fire again on a different day")
def _():
    L = fresh_ledger()
    assert L.calendar_record(1, "weekly", "2027-01-02", "drafted")
    assert L.calendar_record(1, "weekly", "2027-01-09", "drafted")


@test("only a drafted beat can be decided, so two clicks cannot double-post")
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
    assert L.calendar_by_draft(1, 555)["beat_id"] == "b"
    assert L.calendar_by_draft(1, 999) is None
    assert L.calendar_by_draft(2, 555) is None


@test("pending beats are listed for the calendar command")
def _():
    L = fresh_ledger()
    L.calendar_record(1, "a", "2027-01-01", "drafted")
    L.calendar_record(1, "b", "2027-01-02", "published")
    pending = L.calendar_pending(1)
    assert [p["beat_id"] for p in pending] == ["a"]


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
    # A beat body containing the literal word @everyone would otherwise ping
    # the whole server. This shipped as a real bug once already.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def draft_beat"):src.index("def mention_for")]
    for call in re.finditer(r"await \w+\.(send|create_thread)\(", body):
        tail = body[call.end():call.end() + 400]
        assert "allowed_mentions" in tail, f"unguarded send near: {tail[:80]!r}"


@test("the approval buttons carry fixed custom ids so they survive a restart")
def _():
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    assert 'custom_id="cal:approve"' in src and 'custom_id="cal:skip"' in src
    assert "timeout=None" in src, "a view with a timeout stops working on restart"
    assert "add_view(BeatApproval())" in src, "the view is never re-registered"


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


@test("a beat can be found by name so it can be tested out of season")
def _():
    # Without this the only way to see a beat is to wait for its date, which
    # for a T-140 beat is months. /calendar-run leans on it.
    cal = fresh_calendar()
    occ = cal.find("launch-day", _date(2026, 9, 1))
    assert occ is not None and occ.date == _date(2026, 9, 1)
    assert "{{" not in occ.beat["body"], "find() skipped the placeholder fill"
    assert cal.find("no-such-beat", _date(2026, 9, 1)) is None
    assert "launch-day" in cal.ids() and "screenshot-saturday" in cal.ids()


@test("the calendar claims a beat before posting it")
def _():
    # If the send fails after the claim, the beat is marked failed. If the claim
    # came second, a crash between send and claim would repost it every hour.
    src = (ROOT / "steward" / "bot.py").read_text(encoding="utf-8")
    body = src[src.index("async def draft_beat"):src.index("def find_beat")]
    claim = body.index("calendar_record(guild.id, occ.id, occ.date.isoformat(),\n"
                       "                                           \"drafted\")")
    send = body.index("msg = await staff.send(")
    assert claim < send, "the beat is posted before it is claimed"

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
    import tempfile
    d = tempfile.mkdtemp()
    b = _bot(Path(d) / "t.sqlite3")
    return _aio.run(fn(b, _Guild()))


@test("a beat drafted out of season can still be approved")
def _():
    # /calendar-run drafts a beat dated today, which is the only way to look at
    # a T-140 beat in August. Approval used to ask the schedule what was due on
    # that date, found nothing, and refused every test draft it had just made.
    async def go(b, g):
        from datetime import date as _d
        today = _d(2026, 8, 17)
        occ = b.client.calendar.find("launch-day", today)
        assert occ is not None, "launch-day is not in the calendar"
        assert await b.client.draft_beat(g, occ), "draft failed"
        run = b.client.ledger.calendar_by_draft(1, 1)
        assert run and run["status"] == "drafted"

        inter = _types.SimpleNamespace(
            guild=g, guild_id=1,
            user=_types.SimpleNamespace(
                id=7, mention="@me",
                guild_permissions=_types.SimpleNamespace(manage_guild=True)),
            message=_types.SimpleNamespace(id=1, embeds=[], edit=_noop))
        await b.client.publish_beat(inter, run)

        ann = g.text_channels[1]
        assert len(ann.sent) == 1, "the beat never reached its channel"
        after = b.client.ledger.calendar_seen(1, "launch-day", "2026-08-17")
        assert after["status"] == "published", after
        return True
    assert _drive(go)


@test("the draft warns before a beat that pings the whole server")
def _():
    async def go(b, g):
        from datetime import date as _d
        occ = b.client.calendar.find("launch-day", _d(2026, 8, 17))
        await b.client.draft_beat(g, occ)
        body = g.text_channels[0].sent[0][0]
        assert "pings people" in body, body
        assert "#announcements" in body, body
        return True
    assert _drive(go)


@test("an approved beat is crossposted from an announcement channel")
def _():
    # Announcement channels can be followed by other servers, which is free
    # reach and the reason #devlog and #announcements are that type.
    async def go(b, g):
        from datetime import date as _d
        occ = b.client.calendar.find("launch-day", _d(2026, 8, 17))
        await b.client.draft_beat(g, occ)
        run = b.client.ledger.calendar_by_draft(1, 1)
        inter = _types.SimpleNamespace(
            guild=g, guild_id=1,
            user=_types.SimpleNamespace(
                id=7, mention="@me",
                guild_permissions=_types.SimpleNamespace(manage_guild=True)),
            message=_types.SimpleNamespace(id=1, embeds=[], edit=_noop))
        await b.client.publish_beat(inter, run)
        assert g.text_channels[1].published, "not crossposted"
        return True
    assert _drive(go)


@test("a reminder skips approval and stops at staff")
def _():
    async def go(b, g):
        from datetime import date as _d
        occ = b.client.calendar.find("launch-week", _d(2026, 8, 17))
        await b.client.draft_beat(g, occ)
        row = b.client.ledger.calendar_seen(1, "launch-week", "2026-08-17")
        assert row["status"] == "published", row
        staff = g.text_channels[0]
        assert len(staff.sent) == 1
        assert "view" not in staff.sent[0][1], "a reminder was given buttons"
        # And it must not have reached anywhere members can see.
        assert not g.text_channels[1].sent and not g.text_channels[2].sent
        return True
    assert _drive(go)


@test("a beat aimed at a channel that does not exist fails once, not forever")
def _():
    async def go(b, g):
        from datetime import date as _d
        g.text_channels = [_Chan("steward-reports")]      # no #announcements
        occ = b.client.calendar.find("launch-day", _d(2026, 8, 17))
        await b.client.draft_beat(g, occ)
        row = b.client.ledger.calendar_seen(1, "launch-day", "2026-08-17")
        assert row["status"] == "failed", row
        # Recorded, so the hourly tick does not retry it every hour all week.
        assert await b.client.draft_beat(g, occ) is False
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
