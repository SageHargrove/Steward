"""
Blueprint core: load, template, customize, validate, apply.

The CLI (provision.py) and the UI (../ui/app.py) both import this. Nothing in
here prints to stdout on its own; everything routes through an injected `log`
callable so the UI can stream progress to a browser and the CLI can pass
`print`. That indirection is also what a hosted version would need, so it is
worth having now rather than retrofitting.
"""

from __future__ import annotations

import base64
import copy
import json
import mimetypes
import re
import time
from pathlib import Path

import requests
import yaml

API = "https://discord.com/api/v10"


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

PERMISSIONS = {
    "CREATE_INSTANT_INVITE": 1 << 0,
    "KICK_MEMBERS": 1 << 1,
    "BAN_MEMBERS": 1 << 2,
    "ADMINISTRATOR": 1 << 3,
    "MANAGE_CHANNELS": 1 << 4,
    "MANAGE_GUILD": 1 << 5,
    "ADD_REACTIONS": 1 << 6,
    "VIEW_AUDIT_LOG": 1 << 7,
    "PRIORITY_SPEAKER": 1 << 8,
    "STREAM": 1 << 9,
    "VIEW_CHANNEL": 1 << 10,
    "SEND_MESSAGES": 1 << 11,
    "SEND_TTS_MESSAGES": 1 << 12,
    "MANAGE_MESSAGES": 1 << 13,
    "EMBED_LINKS": 1 << 14,
    "ATTACH_FILES": 1 << 15,
    "READ_MESSAGE_HISTORY": 1 << 16,
    "MENTION_EVERYONE": 1 << 17,
    "USE_EXTERNAL_EMOJIS": 1 << 18,
    "VIEW_GUILD_INSIGHTS": 1 << 19,
    "CONNECT": 1 << 20,
    "SPEAK": 1 << 21,
    "MUTE_MEMBERS": 1 << 22,
    "DEAFEN_MEMBERS": 1 << 23,
    "MOVE_MEMBERS": 1 << 24,
    "USE_VAD": 1 << 25,
    "CHANGE_NICKNAME": 1 << 26,
    "MANAGE_NICKNAMES": 1 << 27,
    "MANAGE_ROLES": 1 << 28,
    "MANAGE_WEBHOOKS": 1 << 29,
    "MANAGE_GUILD_EXPRESSIONS": 1 << 30,
    "USE_APPLICATION_COMMANDS": 1 << 31,
    "REQUEST_TO_SPEAK": 1 << 32,
    "MANAGE_EVENTS": 1 << 33,
    "MANAGE_THREADS": 1 << 34,
    "CREATE_PUBLIC_THREADS": 1 << 35,
    "CREATE_PRIVATE_THREADS": 1 << 36,
    "USE_EXTERNAL_STICKERS": 1 << 37,
    "SEND_MESSAGES_IN_THREADS": 1 << 38,
    "USE_EMBEDDED_ACTIVITIES": 1 << 39,
    "MODERATE_MEMBERS": 1 << 40,
    "USE_SOUNDBOARD": 1 << 42,
    "USE_EXTERNAL_SOUNDS": 1 << 45,
    "SEND_VOICE_MESSAGES": 1 << 46,
    "SEND_POLLS": 1 << 49,
}

CHANNEL_TYPES = {
    "text": 0, "voice": 2, "category": 4,
    "announcement": 5, "stage": 13, "forum": 15, "media": 16,
}

# Channel types Discord refuses to create before Community mode is on.
COMMUNITY_GATED = {"announcement", "forum", "stage"}

AUTOMOD_TRIGGERS = {"keyword": 1, "spam": 3, "keyword_preset": 4,
                    "mention_spam": 5, "member_profile": 6}
AUTOMOD_EVENTS = {"message_send": 1, "member_update": 2}
AUTOMOD_PRESETS = {"profanity": 1, "sexual_content": 2, "slurs": 3}
AUTOMOD_LIMITS = {"keyword": 6, "spam": 1, "keyword_preset": 1,
                  "mention_spam": 1, "member_profile": 1}
PROMPT_TYPES = {"multiple_choice": 0, "dropdown": 1}

# Sensible permission preset for a channel someone adds by hand in the UI,
# by channel type. These names must exist in the blueprint's overwrite_presets.
DEFAULT_OVERWRITES = {
    "text": "open",
    "voice": "voice_open",
    "forum": "forum_open",
    "announcement": "readonly_reactable",
    "stage": "voice_open",
    "media": "forum_open",
}

# Permission integers for the invite URLs the UI shows.
INVITE_PERMS_PROVISION = 8            # Administrator, needed for the first run
INVITE_PERMS_LEDGER = 2416004096      # view, send, history, embed, slash commands,
                                      # plus MANAGE_ROLES so Steward can remove the
                                      # ephemeral attribution roles after recording them


# Enhanced role styles: a two-colour gradient, or the animated holographic
# sheen. Unlocked by three server boosts and then usable on any number of
# roles. Discord fixes the holographic colours, so it is a look you switch on
# rather than one you design; a gradient is the customisable option.
# If the perk lapses, Discord silently reverts those roles to their primary
# colour, which is why every role here keeps a plain `color` as well.
HOLOGRAPHIC = {"primary_color": 11127295,      # #A9C9FF
               "secondary_color": 16759788,    # #FFBBEC
               "tertiary_color": 16761760}     # #FFC3A0
ENHANCED_ROLE_COLORS = "ENHANCED_ROLE_COLORS"


def role_colors(spec: dict) -> dict | None:
    """The `colors` object for a role, or None if it just wants a flat colour."""
    style = spec.get("colors")
    if not style:
        return None
    if style.get("holographic"):
        return dict(HOLOGRAPHIC)
    primary = style.get("primary", spec.get("color", 0))
    secondary = style.get("secondary")
    if secondary is None:
        return None                             # one colour is not a gradient
    return {"primary_color": int(primary), "secondary_color": int(secondary)}


class Failed(Exception):
    pass


# --------------------------------------------------------------------------
# Load, template, customize
# --------------------------------------------------------------------------

def load(path: str | Path) -> dict:
    path = Path(path)
    bp = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Remembered so content_file entries resolve relative to the blueprint,
    # wherever the tool is invoked from.
    bp["_base_dir"] = str(path.parent.resolve())
    return bp


def declared_variables(bp: dict) -> dict:
    """The `variables:` block, which is what the UI turns into form fields."""
    return dict(bp.get("variables", {}))


_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def substitute(bp: dict, values: dict) -> dict:
    """Replace {{name}} placeholders throughout every string in the blueprint.

    This is what makes a blueprint redeployable rather than a config file.
    `{{game}}` survives a move to the next project; a name typed in does not.
    """
    merged = {**declared_variables(bp), **(values or {})}

    def walk(node):
        if isinstance(node, str):
            return _VAR.sub(lambda m: str(merged.get(m.group(1), m.group(0))), node)
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    out = walk(copy.deepcopy(bp))
    out["variables"] = merged
    return out


# A line containing only this starts a new message. Deliberately NOT an HTML
# comment: the marker used to be one, and any editor note that mentioned it
# closed its own comment early and leaked the rest of the note into the
# channel. A marker that cannot appear inside a comment cannot do that.
SPLIT_MARKER = "%%SPLIT%%"


def substitute_text(text: str, values: dict) -> str:
    return _VAR.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


def split_content(text: str) -> list[str]:
    """Turn a markdown file into the messages to post.

    HTML comments anywhere in the file are editor notes and never reach the
    channel, so a content file can explain how to edit itself.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # A variable left blank leaves an empty line behind. Collapse those, so an
    # unfilled tagline reads as "no tagline" rather than as a gap in the post.
    text = re.sub(r"[ \t]*\n[ \t]*(?:\n[ \t]*)+", "\n\n", text)
    parts = [p.strip("\n") for p in re.split(rf"^{re.escape(SPLIT_MARKER)}\s*$",
                                             text, flags=re.M)]
    return [p.strip() for p in parts if p.strip()]


# Discord's embed limits. A description holds far more than a plain message,
# which is what stops a long document turning into a wall of separate posts.
EMBED_DESC_LIMIT = 4096
EMBED_TITLE_LIMIT = 256
EMBED_TOTAL_PER_MESSAGE = 6000
EMBEDS_PER_MESSAGE = 10


def as_embed(block: str, color: int) -> dict:
    """One block becomes one embed. A leading markdown heading becomes its
    title, so the file stays readable as markdown."""
    title = None
    body = block
    first, _, rest = block.partition("\n")
    if first.startswith("#"):
        title = first.lstrip("#").strip()[:EMBED_TITLE_LIMIT]
        body = rest.strip()
    embed = {"description": body[:EMBED_DESC_LIMIT]}
    if title:
        embed["title"] = title
    if color:
        embed["color"] = color
    return embed


def pack_messages(blocks: list[str], color: int | None) -> list[dict]:
    """Group blocks into as few Discord messages as the limits allow.

    Without embeds each block is its own message and a long document reads as
    a stack of disconnected posts. With them, several sections fit in one.
    """
    if not color:
        return [{"content": b, "allowed_mentions": {"parse": []}} for b in blocks]

    messages, current, used = [], [], 0
    for block in blocks:
        embed = as_embed(block, color)
        size = len(embed.get("title", "")) + len(embed["description"])
        if current and (used + size > EMBED_TOTAL_PER_MESSAGE
                        or len(current) >= EMBEDS_PER_MESSAGE):
            messages.append({"embeds": current, "allowed_mentions": {"parse": []}})
            current, used = [], 0
        current.append(embed)
        used += size
    if current:
        messages.append({"embeds": current, "allowed_mentions": {"parse": []}})
    return messages


# System channel flags, for the notices Discord posts on its own.
SYSTEM_CHANNEL_FLAGS = {
    "suppress_join_notifications": 1 << 0,
    "suppress_boost_notifications": 1 << 1,
    "suppress_setup_tips": 1 << 2,
    "suppress_join_stickers": 1 << 3,
    "suppress_subscription_notifications": 1 << 4,
    "suppress_subscription_replies": 1 << 5,
}


def inventory(bp: dict) -> dict:
    """Everything selectable, in the shape the UI renders. Read-only."""
    cats = []
    for cat in bp.get("categories", []):
        cats.append({
            "name": cat["name"],
            "channels": [{
                "name": ch["name"],
                "type": ch.get("type", "text"),
                "topic": (ch.get("topic") or "").strip(),
                "required": bool(ch.get("required")),
                "required_when": ch.get("required_when", ""),
                "required_reason": ch.get("required_reason", ""),
                "tags": [t["name"] for t in ch.get("tags", [])],
                "default": bool(ch.get("default")),
                "added": bool(ch.get("added")),
            } for ch in cat.get("channels", [])],
        })
    return {
        "meta": bp.get("meta", {}),
        "variables": declared_variables(bp),
        "categories": cats,
        "roles": [{
            "name": r["name"],
            "required": bool(r.get("required")),
            "required_reason": r.get("required_reason", ""),
            "color": r.get("color", 0),
            "note": r.get("note", ""),
            "ephemeral": bool(r.get("ephemeral")),
            "colors": r.get("colors") or {},
        } for r in bp.get("roles", [])],
        "automod": [{
            "name": a["name"],
            "trigger": a["trigger"],
            "note": a.get("note", ""),
        } for a in bp.get("automod", [])],
        "prompts": [{
            "title": p["title"],
            "options": [o["title"] for o in p.get("options", [])],
            "note": p.get("note", ""),
        } for p in bp.get("onboarding_prompts", [])],
        "onboarding_defaults": bp.get("onboarding_defaults", []),
        "levels": {
            **{k: v for k, v in (bp.get("levels") or {}).items() if k != "rewards"},
            # role name -> the level that unlocks it, which is how the UI wants
            # to show it: on the role itself rather than in a separate list.
            "rewards": {r["role"]: r["level"]
                        for r in (bp.get("levels") or {}).get("rewards", [])},
        },
    }


def customize(bp: dict, selection: dict | None) -> dict:
    """Apply a UI selection: variables, keep-lists, and renames.

    Keep-lists use the blueprint's ORIGINAL names. Renames are applied last so
    that a selection stays stable even after the user renames something.
    Anything required:true survives regardless of what the selection says,
    because dropping it breaks Community mode.

    Dangling references left behind by a removal are cleaned automatically:
    an overwrite naming a dropped role, an onboarding default naming a dropped
    channel, an AutoMod alert pointing at a dropped channel. Those are
    mechanical consequences, not user errors, so they should not surface as
    validation failures.
    """
    sel = selection or {}
    # Substitution happens at the very END, not here. The UI is handed the raw
    # blueprint, so its keep-lists hold raw names like "What brings you to
    # {{game}}?". Substituting first renamed things out from under those lists
    # and silently dropped them. Every keep-list, rename key and default below
    # therefore matches against the blueprint's own untouched names.
    bp = copy.deepcopy(bp)

    # -- level settings, which the UI edits alongside the roles they reward
    lv = sel.get("levels")
    if lv:
        levels = dict(bp.get("levels") or {})
        for key in ("enabled", "noun", "cooldown_seconds", "voice_xp_per_minute",
                    "announce", "announce_only_rewards", "no_xp_channels",
                    "max_level"):
            if key in lv:
                levels[key] = lv[key]
        if "xp_per_message" in lv:
            pair = lv["xp_per_message"]
            levels["xp_per_message"] = [int(pair[0]), int(pair[1])]
        if "curve" in lv and isinstance(lv["curve"], dict):
            levels["curve"] = {k: int(v) for k, v in lv["curve"].items()
                               if k in ("base", "linear", "quadratic")}
        if "rewards" in lv:
            # Sent as {role: level}; stored as a list so the order is the
            # order they unlock in.
            levels["rewards"] = [
                {"level": int(level), "role": role}
                for role, level in sorted((lv["rewards"] or {}).items(),
                                          key=lambda kv: int(kv[1]))
                if str(level).strip() != ""]
        bp["levels"] = levels

    # Whole features the user can switch off, as opposed to individual items.
    feats = sel.get("features") or {}
    if feats.get("onboarding") is False:
        bp["onboarding_defaults"] = []
        bp["onboarding_prompts"] = []
    if feats.get("community") is False:
        bp.setdefault("guild", {})["community"] = False
        # Forum and announcement channels cannot exist without Community mode,
        # so drop them rather than letting the run fail channel by channel.
        for cat in bp.get("categories", []):
            cat["channels"] = [ch for ch in cat.get("channels", [])
                               if ch.get("type", "text") not in COMMUNITY_GATED]
        bp["categories"] = [c for c in bp.get("categories", []) if c.get("channels")]

    def keep_set(key, all_names, required_names=frozenset()):
        chosen = sel.get(key)
        if chosen is None:
            return set(all_names)
        return set(chosen) | set(required_names)

    # -- roles
    all_roles = [r["name"] for r in bp.get("roles", [])]
    req_roles = {r["name"] for r in bp.get("roles", [])
                 if r.get("required") and (r.get("required_when") != "community"
                                           or bp.get("guild", {}).get("community"))}
    roles_keep = keep_set("roles", all_roles, req_roles)
    bp["roles"] = [r for r in bp.get("roles", []) if r["name"] in roles_keep]

    # -- channels. "required" can be conditional: #server-updates is only
    # unavoidable while Community mode is on, and forcing it into a
    # non-community server would create a channel Discord never posts to.
    community_on = bool(bp.get("guild", {}).get("community"))

    def still_required(item):
        if not item.get("required"):
            return False
        when = item.get("required_when")
        return community_on if when == "community" else True

    all_chans, req_chans = [], set()
    for cat in bp.get("categories", []):
        for ch in cat.get("channels", []):
            all_chans.append(ch["name"])
            if still_required(ch):
                req_chans.add(ch["name"])
    chans_keep = keep_set("channels", all_chans, req_chans)

    cats = []
    for cat in bp.get("categories", []):
        kept = [ch for ch in cat.get("channels", []) if ch["name"] in chans_keep]
        if kept:
            cat = {**cat, "channels": kept}
            cats.append(cat)
    bp["categories"] = cats

    # -- automod and prompts
    am_keep = keep_set("automod", [a["name"] for a in bp.get("automod", [])])
    bp["automod"] = [a for a in bp.get("automod", []) if a["name"] in am_keep]

    pr_keep = keep_set("prompts", [p["title"] for p in bp.get("onboarding_prompts", [])])
    bp["onboarding_prompts"] = [
        p for p in bp.get("onboarding_prompts", []) if p["title"] in pr_keep]

    # -- clean references to things that were dropped
    for pname, entries in list(bp.get("overwrite_presets", {}).items()):
        bp["overwrite_presets"][pname] = [
            e for e in entries if e["role"] == "everyone" or e["role"] in roles_keep]

    bp["onboarding_defaults"] = [
        c for c in bp.get("onboarding_defaults", []) if c in chans_keep]

    if bp.get("levels", {}).get("rewards"):
        # Roles added by hand are appended further down, so they are not in
        # roles_keep yet. Keep their rewards rather than pruning them here.
        added_names = {(r.get("name") or "").strip()
                       for r in (sel.get("additions") or {}).get("roles", [])}
        bp["levels"]["rewards"] = [
            r for r in bp["levels"]["rewards"]
            if r["role"] in roles_keep or r["role"] in added_names]

    for p in bp.get("onboarding_prompts", []):
        for o in p.get("options", []):
            o["roles"] = [r for r in o.get("roles", []) if r in roles_keep]
            o["channels"] = [c for c in o.get("channels", []) if c in chans_keep]
        # Discord rejects any option granting neither a role nor a channel
        # (ROLE_OR_CHANNEL_REQUIRED). Pruning can produce exactly that, so an
        # option left with nothing has to go rather than survive as a survey
        # answer. A prompt whose options all go with it goes too.
        p["options"] = [o for o in p.get("options", [])
                        if o.get("title") and (o.get("roles") or o.get("channels"))]
    bp["onboarding_prompts"] = [p for p in bp["onboarding_prompts"] if p.get("options")]

    for a in bp.get("automod", []):
        a["actions"] = [
            act for act in a.get("actions", [])
            if "alert" not in act or act["alert"] in chans_keep]
        a["exempt_roles"] = [r for r in a.get("exempt_roles", []) if r in roles_keep]
        a["exempt_channels"] = [c for c in a.get("exempt_channels", []) if c in chans_keep]

    g = bp.setdefault("guild", {})
    for key in ("rules_channel", "public_updates_channel", "safety_alerts_channel"):
        if g.get(key) and g[key] not in chans_keep:
            g[key] = None

    # -- which channels new members are shown, if the UI overrode it
    if sel.get("defaults") is not None:
        bp["onboarding_defaults"] = [c for c in sel["defaults"] if c in chans_keep]

    # -- renames, updating every reference site.
    # Accepts either {"channels": {...}, "roles": {...}} or a bare channel map.
    raw = sel.get("renames") or {}
    if raw and not any(k in ("channels", "roles") for k in raw):
        raw = {"channels": raw}

    def clean(m):
        return {k: v.strip() for k, v in (m or {}).items()
                if v and v.strip() and v.strip() != k}

    ch_renames = clean(raw.get("channels"))
    role_renames = clean(raw.get("roles"))

    if ch_renames:
        def rn(name):
            return ch_renames.get(name, name)

        for cat in bp.get("categories", []):
            for ch in cat.get("channels", []):
                ch["name"] = rn(ch["name"])
        bp["onboarding_defaults"] = [rn(c) for c in bp.get("onboarding_defaults", [])]
        for p in bp.get("onboarding_prompts", []):
            for o in p.get("options", []):
                o["channels"] = [rn(c) for c in o.get("channels", [])]
        for a in bp.get("automod", []):
            for act in a.get("actions", []):
                if "alert" in act:
                    act["alert"] = rn(act["alert"])
            a["exempt_channels"] = [rn(c) for c in a.get("exempt_channels", [])]
        for key in ("rules_channel", "public_updates_channel", "safety_alerts_channel"):
            if g.get(key):
                g[key] = rn(g[key])

    if role_renames:
        def rr(name):
            return role_renames.get(name, name)

        for r in bp.get("roles", []):
            r["name"] = rr(r["name"])
        for entries in bp.get("overwrite_presets", {}).values():
            for e in entries:
                if e["role"] != "everyone":
                    e["role"] = rr(e["role"])
        for p in bp.get("onboarding_prompts", []):
            for o in p.get("options", []):
                o["roles"] = [rr(x) for x in o.get("roles", [])]
        for a in bp.get("automod", []):
            a["exempt_roles"] = [rr(x) for x in a.get("exempt_roles", [])]
        # A threshold belongs to the role, not to its name. Without this,
        # renaming a tier silently stopped it ever being granted.
        for reward in bp.get("levels", {}).get("rewards", []):
            reward["role"] = rr(reward["role"])

    # -- recolouring, which the UI offers on every role rather than only on
    # ones somebody added by hand
    for name, style in (sel.get("colors") or {}).items():
        for r in bp.get("roles", []):
            if r["name"] != name:
                continue
            if "color" in style:
                r["color"] = int(style["color"])
            if style.get("holographic"):
                r["colors"] = {"holographic": True}
            elif style.get("secondary"):
                r["colors"] = {"primary": int(style.get("primary", r.get("color", 0))),
                               "secondary": int(style["secondary"])}
            elif "secondary" in style:      # explicitly cleared
                r.pop("colors", None)

    # -- fill in {{placeholders}}, now that every selection has been matched
    # against the raw names it was built from
    bp = substitute(bp, sel.get("variables"))

    # -- user-added items, appended last so their names stay exactly as typed
    add = sel.get("additions") or {}

    for spec in add.get("roles", []):
        name = (spec.get("name") or "").strip()
        if not name or any(r["name"] == name for r in bp.get("roles", [])):
            continue
        bp.setdefault("roles", []).append({
            "name": name,
            "color": int(spec.get("color", 0)),
            "hoist": bool(spec.get("hoist", False)),
            "mentionable": True,
            # No permissions by design. A hand-added role is a label; giving it
            # powers is a decision better made in Discord's own role editor,
            # where you can see what each permission actually does.
            "permissions": [],
            "added": True,
        })

    by_cat = {c["name"]: c for c in bp.get("categories", [])}
    for spec in add.get("channels", []):
        name = (spec.get("name") or "").strip()
        ctype = spec.get("type", "text")
        if not name or ctype not in CHANNEL_TYPES or ctype == "category":
            continue
        existing = {ch["name"] for c in bp.get("categories", []) for ch in c["channels"]}
        if name in existing:
            continue
        if ctype in COMMUNITY_GATED and not bp.get("guild", {}).get("community"):
            continue
        cat_name = spec.get("category")
        cat = by_cat.get(cat_name)
        if cat is None:
            cat = {"name": cat_name or "MORE", "channels": []}
            by_cat[cat["name"]] = cat
            bp.setdefault("categories", []).append(cat)
        cat["channels"].append({
            "name": name,
            "type": ctype,
            "overwrites": spec.get("overwrites") or DEFAULT_OVERWRITES.get(ctype, "open"),
            "topic": (spec.get("topic") or "").strip(),
            "added": True,
        })
        if spec.get("default"):
            bp.setdefault("onboarding_defaults", []).append(name)

    return bp


# --------------------------------------------------------------------------
# Validate
# --------------------------------------------------------------------------

def validate(bp: dict) -> dict:
    """Offline checks. No token, no network.

    Returns {"errors": [...], "warnings": [...], "summary": {...}}. Errors are
    things Discord will reject; warnings are things that will apply cleanly but
    probably are not what you meant. The UI calls this on every toggle, so it
    must stay cheap and must never raise.
    """
    errors: list[str] = []
    warnings: list[str] = []

    roles = {r["name"] for r in bp.get("roles", [])} | {"everyone"}
    for r in bp.get("roles", []):
        for p in r.get("permissions", []):
            if p not in PERMISSIONS:
                errors.append(f"Role '{r['name']}': unknown permission {p}")

    presets = bp.get("overwrite_presets", {})
    for pname, entries in presets.items():
        for e in entries:
            if e["role"] not in roles:
                errors.append(f"Preset '{pname}' references missing role {e['role']}")
            for key in ("allow", "deny"):
                for p in e.get(key, []):
                    if p not in PERMISSIONS:
                        errors.append(f"Preset '{pname}': unknown permission {p}")

    channels: dict[str, dict] = {}
    for cat in bp.get("categories", []):
        for ch in cat.get("channels", []):
            if ch["name"] in channels:
                errors.append(f"Two channels are both named '{ch['name']}'")
            channels[ch["name"]] = ch
            ctype = ch.get("type", "text")
            if ctype not in CHANNEL_TYPES:
                errors.append(f"Channel '{ch['name']}': unknown type {ctype}")
            if ch.get("overwrites") and ch["overwrites"] not in presets:
                errors.append(f"Channel '{ch['name']}': unknown preset {ch['overwrites']}")
            if len(ch.get("tags", [])) > 20:
                errors.append(
                    f"Channel '{ch['name']}': {len(ch['tags'])} forum tags, Discord allows 20")
            if not re.fullmatch(r"[^\s]{1,100}", ch["name"]) and ctype != "voice":
                warnings.append(
                    f"Channel '{ch['name']}' has whitespace in its name. Discord will "
                    f"convert it to dashes")

    # Community mode's own prerequisites.
    g = bp.get("guild", {})
    community = bool(g.get("community"))
    if community:
        for key, label in (("rules_channel", "rules"),
                           ("public_updates_channel", "mod-only updates")):
            if not g.get(key):
                errors.append(
                    f"Community mode needs a {label} channel, and the one it pointed at "
                    f"was removed. Keep it, or turn Community mode off")
            elif g[key] not in channels:
                errors.append(f"Community mode's {label} channel '{g[key]}' does not exist")

    base = bp.get("_base_dir")
    for name, ch in channels.items():
        rel = ch.get("content_file")
        if not rel or base is None:
            continue
        path = Path(base) / rel
        if not path.is_file():
            errors.append(f"Channel '{name}': no content file at {rel}")
            continue
        try:
            blocks = split_content(substitute_text(
                path.read_text(encoding="utf-8"), bp.get("variables", {})))
        except OSError as e:
            errors.append(f"Channel '{name}': cannot read {rel} ({e})")
            continue
        if not blocks:
            warnings.append(f"Channel '{name}': {rel} is empty, so nothing will be posted")
        color = ch.get("color", bp.get("meta", {}).get("accent_color"))
        limit = EMBED_DESC_LIMIT if color else 2000
        for i, block in enumerate(blocks, 1):
            if len(block) > limit:
                errors.append(
                    f"Channel '{name}': section {i} of {rel} is {len(block)} characters "
                    f"and Discord's limit is {limit}. Add a {SPLIT_MARKER} line before it")

    gated = [c for c, s in channels.items() if s.get("type") in COMMUNITY_GATED]
    if gated and not community:
        errors.append(
            f"{len(gated)} forum/announcement channels are selected but Community mode "
            f"is off. Discord will not create them")

    # Onboarding's two hard constraints, the usual cause of a rejected PUT.
    defaults = bp.get("onboarding_defaults", [])
    prompts = bp.get("onboarding_prompts", [])
    for d in defaults:
        if d not in channels:
            errors.append(f"Onboarding default channel '{d}' does not exist")

    def is_open(name):
        ch = channels.get(name, {})
        for e in presets.get(ch.get("overwrites"), []):
            if e["role"] == "everyone":
                allow, deny = set(e.get("allow", [])), set(e.get("deny", []))
                return ({"VIEW_CHANNEL", "SEND_MESSAGES"} <= allow
                        and not ({"VIEW_CHANNEL", "SEND_MESSAGES"} & deny))
        return False

    open_count = sum(1 for d in defaults if is_open(d))
    onboarding_on = bool(defaults or prompts)
    if onboarding_on:
        if len(defaults) < 7:
            errors.append(
                f"Onboarding needs at least 7 default channels and you have "
                f"{len(defaults)}. Add {7 - len(defaults)} more, or turn onboarding off")
        if open_count < 5:
            errors.append(
                f"Onboarding needs at least 5 default channels where everyone can both "
                f"view and post, and you have {open_count}")

    for p in prompts:
        if p.get("type", "multiple_choice") not in PROMPT_TYPES:
            errors.append(f"Prompt '{p['title']}': unknown type {p.get('type')}")
        if len(p.get("options", [])) > 50:
            errors.append(f"Prompt '{p['title']}': more than 50 options")
        if not p.get("options"):
            errors.append(f"Question '{p['title']}' has no answers left")
        for o in p.get("options", []):
            for r in o.get("roles", []):
                if r not in roles:
                    errors.append(f"Prompt option '{o['title']}' grants missing role {r}")
            for c in o.get("channels", []):
                if c not in channels:
                    errors.append(f"Prompt option '{o['title']}' shows missing channel {c}")
            # Discord's ROLE_OR_CHANNEL_REQUIRED. Every answer must hand out a
            # role or reveal a channel; a pure survey answer is refused.
            if not o.get("roles") and not o.get("channels"):
                errors.append(
                    f"Answer '{o['title']}' in '{p['title']}' gives neither a role nor a "
                    f"channel. Discord refuses those. Give it a role, or remove the answer")

    counts: dict[str, int] = {}
    for r in bp.get("automod", []):
        t = r.get("trigger")
        if t not in AUTOMOD_TRIGGERS:
            errors.append(f"AutoMod '{r['name']}': unknown trigger {t}")
            continue
        counts[t] = counts.get(t, 0) + 1
        if r.get("presets") and t != "keyword_preset":
            errors.append(
                f"AutoMod '{r['name']}': presets exist only on the keyword_preset "
                f"trigger, not {t}. Use keyword_filter or regex_patterns")
        for p in r.get("presets", []):
            if p not in AUTOMOD_PRESETS:
                errors.append(f"AutoMod '{r['name']}': unknown preset {p}")
        if t in ("keyword", "member_profile") and not (
                r.get("keyword_filter") or r.get("regex_patterns")):
            errors.append(f"AutoMod '{r['name']}': nothing to match on")
        if len(r.get("regex_patterns", [])) > 10:
            errors.append(f"AutoMod '{r['name']}': more than 10 regex patterns")
        for pat in r.get("regex_patterns", []):
            if len(pat) > 260:
                errors.append(f"AutoMod '{r['name']}': a regex exceeds 260 characters")
        has_alert = any("alert" in a for a in r.get("actions", []))
        for a in r.get("actions", []):
            if "timeout" in a and t not in ("keyword", "mention_spam"):
                errors.append(
                    f"AutoMod '{r['name']}': timeout works only on keyword and "
                    f"mention_spam rules, not {t}")
            if "alert" in a and a["alert"] not in channels:
                errors.append(f"AutoMod '{r['name']}': alert channel '{a['alert']}' missing")
        if not r.get("actions"):
            errors.append(f"AutoMod '{r['name']}': no actions, so it would do nothing")
        elif not has_alert and t != "member_profile":
            # member_profile rules act by blocking the profile itself and do
            # not support an alert action, so silence is expected there.
            warnings.append(
                f"AutoMod '{r['name']}' has no alert channel, so you will not see when "
                f"it fires")
    for t, n in counts.items():
        if n > AUTOMOD_LIMITS.get(t, 99):
            errors.append(
                f"AutoMod: {n} {t} rules selected, Discord allows {AUTOMOD_LIMITS[t]}")

    styled = [r["name"] for r in bp.get("roles", []) if r.get("colors")]
    if styled:
        warnings.append(
            f"{len(styled)} role(s) use a fade or the animated style, which needs the "
            f"server to have 3 boosts. Without them those roles use their plain colour "
            f"and everything else is unaffected")

    if not bp.get("roles"):
        warnings.append("No roles selected")
    if not channels:
        errors.append("No channels selected, so there is nothing to build")

    # A blank variable is legal and the text around it is simply left out, but
    # it is nearly always something nobody got round to filling in.
    for name, value in (bp.get("variables") or {}).items():
        if isinstance(value, str) and not value.strip():
            warnings.append(
                f"'{name}' is empty, so the line it belongs to is left out of the "
                f"posted text. Fill it in above if you want it")

    unresolved = set()
    def scan(node):
        if isinstance(node, str):
            unresolved.update(_VAR.findall(node))
        elif isinstance(node, list):
            for x in node:
                scan(x)
        elif isinstance(node, dict):
            for v in node.values():
                scan(v)
    scan({k: v for k, v in bp.items() if k != "variables"})
    for name in sorted(unresolved):
        warnings.append(f"Placeholder {{{{{name}}}}} was never filled in")

    return {
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "styled_roles": sum(1 for r in bp.get("roles", []) if r.get("colors")),
            "roles": len(bp.get("roles", [])),
            "channels": len(channels),
            "categories": len(bp.get("categories", [])),
            "automod": len(bp.get("automod", [])),
            "prompts": len(prompts),
            "defaults": len(defaults),
            "defaults_open": open_count,
            "community": community,
        },
    }


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Client:
    def __init__(self, token: str, dry_run: bool = False, log=print):
        self.dry_run = dry_run
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bot {token}",
            "User-Agent": "CommunityOpsProvisioner (https://github.com/, 1.0)",
            "Content-Type": "application/json",
        })

    def request(self, method: str, path: str, payload=None, *, mutating=True):
        if self.dry_run and mutating:
            self.log(f"    [dry run] {method} {path}")
            if payload is not None:
                preview = json.dumps(payload, ensure_ascii=False)
                self.log(f"              {preview[:300]}{'...' if len(preview) > 300 else ''}")
            return {}

        for attempt in range(6):
            resp = self.session.request(
                method, API + path,
                data=json.dumps(payload) if payload is not None else None)

            if resp.status_code == 429:
                wait = float(resp.json().get("retry_after", 1.0)) + 0.25
                self.log(f"    rate limited, waiting {wait:.1f}s")
                time.sleep(wait)
                continue
            if resp.status_code in (500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise Failed(f"{method} {path} -> {resp.status_code}\n{resp.text}")
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()

        raise Failed(f"{method} {path} gave up after retries")

    def get(self, path):
        return self.request("GET", path, mutating=False)

    def post(self, path, payload):
        return self.request("POST", path, payload)

    def patch(self, path, payload):
        return self.request("PATCH", path, payload)

    def put(self, path, payload):
        return self.request("PUT", path, payload)


def invite_url(app_id: str, permissions: int = INVITE_PERMS_PROVISION) -> str:
    """The authorize link for adding this bot to a server.

    A bot user's id is its application id, so once someone has pasted a token
    we can build this for them. That removes the worst step of the old flow,
    which was asking a non-technical user to assemble an OAuth URL by hand.
    """
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}"
            f"&scope=bot+applications.commands&permissions={permissions}")


def identify(token: str) -> dict:
    """Who is this token, and which guilds can it see? Used by the UI's
    connect step so the user picks a server from a list instead of hunting
    for an id in Developer Mode."""
    c = Client(token, log=lambda *_: None)
    me = c.get("/users/@me")
    guilds = c.get("/users/@me/guilds")
    return {
        "id": me.get("id"),
        "username": me.get("username"),
        "avatar": me.get("avatar"),
        "guilds": [{
            "id": g["id"],
            "name": g["name"],
            "icon": g.get("icon"),
            "owner": g.get("owner", False),
            # 0x8 Administrator, 0x20 Manage Guild
            "can_manage": bool(int(g.get("permissions", 0)) & 0x28),
        } for g in guilds],
    }


def read_guild(token: str, guild_id: str) -> dict:
    """What is in the server right now, so the UI can show leftovers.

    A freshly made Discord server arrives with a "Text Channels" category, a
    "Voice Channels" category and a General voice channel. The provisioner
    adopts anything whose name matches the blueprint and ignores the rest, so
    without this the leftovers just sit there looking like a mistake.
    """
    c = Client(token, log=lambda *_: None)
    chans = c.get(f"/guilds/{guild_id}/channels")
    roles = c.get(f"/guilds/{guild_id}/roles")
    by_id = {ch["id"]: ch for ch in chans}
    rev = {v: k for k, v in CHANNEL_TYPES.items()}
    return {
        "channels": [{
            "id": ch["id"],
            "name": ch["name"],
            "type": rev.get(ch["type"], str(ch["type"])),
            "parent": by_id.get(ch.get("parent_id"), {}).get("name", ""),
        } for ch in chans],
        "roles": [{
            "id": r["id"],
            "name": r["name"],
            # @everyone shares the guild id and can never be deleted. Managed
            # roles belong to bots and integrations; deleting one is either
            # refused or breaks that bot.
            "deletable": not r.get("managed") and r["id"] != str(guild_id)
                         and r["name"] != "@everyone",
        } for r in roles],
    }


def perms_to_int(names) -> int:
    total = 0
    for name in names or []:
        if name not in PERMISSIONS:
            raise Failed(f"unknown permission {name!r}")
        total |= PERMISSIONS[name]
    return total


def emoji_field(value):
    if not value:
        return None
    return {"id": None, "name": value}


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------

class Provisioner:
    def __init__(self, client: Client, guild_id: str, blueprint: dict, log=print):
        self.c = client
        self.gid = str(guild_id)
        self.bp = blueprint
        self.log = log
        self.roles: dict[str, str] = {}
        self.channels: dict[str, str] = {}
        self.dry = client.dry_run
        self.problems: list[str] = []
        self.invite_url_made: str | None = None

    def _warn(self, msg):
        self.problems.append(msg)
        self.log(f"  ! {msg}")

    # -- roles ------------------------------------------------------------

    def sync_roles(self):
        self.log("\nRoles")
        existing = {r["name"]: r for r in self.c.get(f"/guilds/{self.gid}/roles")}
        self.roles["everyone"] = self.gid   # @everyone's role id is the guild id

        try:
            features = set(self.c.get(f"/guilds/{self.gid}").get("features", []))
        except Failed:
            features = set()
        fancy = ENHANCED_ROLE_COLORS in features
        wanted = [r["name"] for r in self.bp.get("roles", []) if role_colors(r)]
        if wanted and not fancy:
            self.log(f"  gradients skipped: {len(wanted)} role(s) ask for one, and this "
                     f"server has not unlocked them")
            self.log("      Three server boosts turns them on. Until then those roles")
            self.log("      use their plain colour, which is what Discord falls back to")
            self.log("      anyway if the boosts ever lapse.")

        for spec in self.bp.get("roles", []):
            name = spec["name"]
            body = {
                "name": name,
                "permissions": str(perms_to_int(spec.get("permissions"))),
                "hoist": bool(spec.get("hoist", False)),
                "mentionable": bool(spec.get("mentionable", False)),
                # Discord treats colour 0 as "no colour", which is what the
                # interest roles want, so pass it straight through.
                "color": int(spec.get("color", 0)),
            }
            style = role_colors(spec) if fancy else None
            if style:
                body["colors"] = style
            try:
                if name in existing:
                    rid = existing[name]["id"]
                    self.c.patch(f"/guilds/{self.gid}/roles/{rid}", body)
                    self.log(f"  = {name}")
                else:
                    created = self.c.post(f"/guilds/{self.gid}/roles", body)
                    rid = created.get("id", f"<new:{name}>")
                    self.log(f"  + {name}")
                self.roles[name] = rid
            except Failed as e:
                # Discord will not let a bot grant a permission it does not
                # itself hold, so a role carrying ADMINISTRATOR needs an
                # ADMINISTRATOR bot. This is what reliably trips a first run.
                if name in existing:
                    self.roles[name] = existing[name]["id"]
                    self._warn(f"{name}: could not update, keeping the existing role")
                else:
                    self._warn(f"{name}: NOT CREATED. {str(e)[:160]}")
                    self.log("      Re-invite the bot with Administrator, then re-run.")

    def sync_role_positions(self):
        """Put the roles in the blueprint's order, highest first.

        Discord numbers positions from the bottom, and a bot cannot move any
        role above its own. Asking for a position above it rejects the ENTIRE
        batch, which is why naively numbering from the top left everything
        where it started. So find the bot's own role and pack everything into
        the space underneath it.
        """
        if self.dry:
            self.log("\n  [dry run] would reorder roles")
            return

        names = [r["name"] for r in self.bp.get("roles", []) if r["name"] in self.roles]
        if not names:
            return

        try:
            live = {r["id"]: r for r in self.c.get(f"/guilds/{self.gid}/roles")}
        except Failed as e:
            self._warn(f"could not read role positions: {str(e)[:120]}")
            return

        # "@me" only resolves for an OAuth2 bearer token with
        # guilds.members.read; with a bot token Discord rejects it as an
        # invalid user id. Ask who we are first, then look ourselves up.
        mine: list[int] = []
        uid = None
        try:
            uid = self.c.get("/users/@me")["id"]
            member = self.c.get(f"/guilds/{self.gid}/members/{uid}")
            mine = [live[rid]["position"] for rid in member.get("roles", []) if rid in live]
        except Failed:
            # Fall back to the integration role Discord creates for the bot,
            # which carries our application id in its tags.
            mine = [r["position"] for r in live.values()
                    if (r.get("tags") or {}).get("bot_id") == uid]

        if not mine:
            self.log("\n  role order skipped: could not work out this bot's own position")
            return

        # A bot may manage any role below its HIGHEST one, so that is the
        # ceiling. Using the lowest would refuse orderings that are legal.
        ceiling = max(mine) - 1

        if ceiling < len(names):
            self.log(
                f"\n  role order skipped: only {max(ceiling, 0)} slots sit below this "
                f"bot's own role but {len(names)} roles need ordering.")
            self.log("      Server Settings, Roles, drag the bot's role to the top,")
            self.log("      then run this again and the order sorts itself out.")
            return

        payload = [{"id": self.roles[n], "position": ceiling - i}
                   for i, n in enumerate(names)]
        try:
            self.c.patch(f"/guilds/{self.gid}/roles", payload)
            self.log(f"\n  role order applied, {names[0]} at the top")
        except Failed as e:
            self._warn(f"role order not applied: {str(e)[:140]}")
            self.log("      Drag the bot's role above the others and re-run.")

    # -- channels ---------------------------------------------------------

    def _overwrites(self, preset_name):
        if not preset_name:
            return []
        presets = self.bp.get("overwrite_presets", {})
        if preset_name not in presets:
            raise Failed(f"unknown overwrite preset {preset_name!r}")
        out = []
        for entry in presets[preset_name]:
            role = entry["role"]
            if role not in self.roles:
                # validate() proved the role was declared, so reaching here
                # means creation failed above. Skip the overwrite rather than
                # abandoning the whole channel.
                continue
            out.append({
                "id": self.roles[role], "type": 0,
                "allow": str(perms_to_int(entry.get("allow"))),
                "deny": str(perms_to_int(entry.get("deny"))),
            })
        return out

    def _self_id(self):
        """This bot's own user id, fetched once."""
        if getattr(self, "_me", None) is None:
            try:
                self._me = self.c.get("/users/@me")["id"]
            except Failed:
                self._me = ""
        return self._me

    def _channel_body(self, spec, parent_id=None, position=None):
        ctype = spec.get("type", "text")
        overwrites = self._overwrites(spec.get("overwrites"))

        # A private channel hides itself by denying @everyone, and the bot is
        # part of @everyone. Administrator papers over that during setup, but
        # the moment its permissions are trimmed it loses the very channel it
        # reports into. Give it an explicit way in.
        hides = any(o["id"] == self.gid
                    and int(o["deny"]) & PERMISSIONS["VIEW_CHANNEL"]
                    for o in overwrites)
        if hides and ctype != "voice":
            me = self._self_id()
            if me:
                overwrites.append({
                    "id": me, "type": 1,          # 1 = a member, not a role
                    "allow": str(perms_to_int([
                        "VIEW_CHANNEL", "SEND_MESSAGES", "READ_MESSAGE_HISTORY",
                        "EMBED_LINKS", "MANAGE_MESSAGES"])),
                    "deny": "0",
                })

        body = {
            "name": spec["name"],
            "type": CHANNEL_TYPES[ctype],
            "permission_overwrites": overwrites,
        }
        if parent_id:
            body["parent_id"] = parent_id
        if position is not None:
            body["position"] = position
        if spec.get("topic") and ctype != "voice":
            body["topic"] = spec["topic"].strip()[:1000]
        if spec.get("nsfw"):
            body["nsfw"] = True
        if ctype in ("forum", "media"):
            tags = []
            for t in spec.get("tags", []):
                tag = {"name": t["name"], "moderated": bool(t.get("moderated", False))}
                if t.get("emoji"):
                    tag["emoji_name"] = t["emoji"]
                    tag["emoji_id"] = None
                tags.append(tag)
            if tags:
                body["available_tags"] = tags
            if spec.get("default_reaction_emoji"):
                body["default_reaction_emoji"] = {
                    "emoji_id": None, "emoji_name": spec["default_reaction_emoji"]}
            for key in ("default_sort_order", "default_forum_layout"):
                if key in spec:
                    body[key] = spec[key]
        if "default_auto_archive_duration" in spec:
            body["default_auto_archive_duration"] = spec["default_auto_archive_duration"]
        return body

    def _upsert(self, spec, existing, parent_id=None, position=None, indent="  "):
        name = spec["name"]
        body = self._channel_body(spec, parent_id, position)
        if name in existing:
            cid = existing[name]["id"]
            patch = {k: v for k, v in body.items() if k != "type"}   # type is immutable
            self.c.patch(f"/channels/{cid}", patch)
            self.log(f"{indent}= {name}")
        else:
            created = self.c.post(f"/guilds/{self.gid}/channels", body)
            cid = created.get("id", f"<new:{name}>")
            self.log(f"{indent}+ {name} ({spec.get('type', 'text')})")
        self.channels[name] = cid
        return cid

    def sync_channels(self, gated: bool):
        """gated=False does categories and plain text/voice channels.
        gated=True does forum and announcement channels, which Discord will
        not create until Community mode is on."""
        self.log("\nForum and announcement channels" if gated else "\nChannels")
        existing = {c["name"]: c for c in self.c.get(f"/guilds/{self.gid}/channels")}

        for ci, cat in enumerate(self.bp.get("categories", [])):
            if not gated:
                parent = self._upsert({"name": cat["name"], "type": "category"},
                                      existing, position=ci)
            else:
                parent = self.channels.get(cat["name"]) or existing.get(
                    cat["name"], {}).get("id")

            for i, ch in enumerate(cat.get("channels", [])):
                if (ch.get("type", "text") in COMMUNITY_GATED) != gated:
                    if not gated and ch["name"] in existing:
                        self.channels[ch["name"]] = existing[ch["name"]]["id"]
                    continue
                try:
                    self._upsert(ch, existing, parent_id=parent, position=i, indent="    ")
                except Failed as e:
                    self._warn(f"channel {ch['name']}: {str(e)[:160]}")

    # -- community mode ---------------------------------------------------

    def enable_community(self):
        g = self.bp.get("guild", {})
        if not g.get("community"):
            self.log("\nCommunity mode: off (blueprint does not ask for it)")
            return
        self.log("\nCommunity mode")

        guild = self.c.get(f"/guilds/{self.gid}")
        features = set(guild.get("features", [])) if guild else set()
        features.add("COMMUNITY")
        # RAID_ALERTS_DISABLED is the off switch, so removing it turns join-raid
        # alerts on. One of only four features Discord lets a bot change.
        if self.bp.get("guild", {}).get("raid_alerts", True):
            features.discard("RAID_ALERTS_DISABLED")

        rules = self.channels.get(g.get("rules_channel"))
        updates = self.channels.get(g.get("public_updates_channel"))
        if not self.dry and (not rules or not updates):
            raise Failed(
                "Community mode needs both a rules channel and a mod-only updates "
                "channel to exist first")

        body = {
            "features": sorted(features),
            "rules_channel_id": rules,
            "public_updates_channel_id": updates,
            "verification_level": g.get("verification_level", 1),
            "explicit_content_filter": g.get("explicit_content_filter", 2),
        }
        if "default_message_notifications" in g:
            body["default_message_notifications"] = g["default_message_notifications"]
        if g.get("safety_alerts_channel") and self.channels.get(g["safety_alerts_channel"]):
            body["safety_alerts_channel_id"] = self.channels[g["safety_alerts_channel"]]

        # Where Discord posts its own notices, and which of them to silence.
        # Left unset, Discord picks a channel itself and adds setup-tip spam.
        if g.get("system_channel") and self.channels.get(g["system_channel"]):
            body["system_channel_id"] = self.channels[g["system_channel"]]
        if g.get("system_channel_flags"):
            flags = 0
            for name in g["system_channel_flags"]:
                if name not in SYSTEM_CHANNEL_FLAGS:
                    self._warn(f"unknown system channel flag {name}")
                    continue
                flags |= SYSTEM_CHANNEL_FLAGS[name]
            body["system_channel_flags"] = flags
        if g.get("afk_channel") and self.channels.get(g["afk_channel"]):
            body["afk_channel_id"] = self.channels[g["afk_channel"]]
        if g.get("afk_timeout"):
            body["afk_timeout"] = int(g["afk_timeout"])
        if "boost_progress_bar" in g:
            body["premium_progress_bar_enabled"] = bool(g["boost_progress_bar"])

        self.c.patch(f"/guilds/{self.gid}", body)
        self.log("  on. Verification: verified email. Media filter: all members")
        if self.bp.get("guild", {}).get("raid_alerts", True):
            self.log("  join-raid alerts on")
        if body.get("system_channel_id"):
            self.log(f"  join messages go to #{g['system_channel']}, setup tips silenced")

    # -- automod ----------------------------------------------------------

    def _automod_body(self, spec):
        trigger = AUTOMOD_TRIGGERS[spec["trigger"]]
        meta = {}
        if spec["trigger"] in ("keyword", "member_profile"):
            for key in ("keyword_filter", "regex_patterns", "allow_list"):
                if spec.get(key):
                    meta[key] = spec[key]
        if spec.get("presets") and spec["trigger"] == "keyword_preset":
            meta["presets"] = [AUTOMOD_PRESETS[p] for p in spec["presets"]]
            meta.setdefault("allow_list", spec.get("allow_list", []))
        if spec["trigger"] == "mention_spam":
            meta["mention_total_limit"] = spec.get("mention_total_limit", 6)
            meta["mention_raid_protection_enabled"] = bool(
                spec.get("mention_raid_protection", True))

        actions = []
        for action in spec.get("actions", []):
            if "block" in action:
                actions.append({"type": 1,
                                "metadata": {"custom_message": action["block"][:150]}})
            elif "alert" in action:
                cid = self.channels.get(action["alert"])
                if cid:
                    actions.append({"type": 2, "metadata": {"channel_id": cid}})
            elif "timeout" in action:
                actions.append({"type": 3,
                                "metadata": {"duration_seconds": int(action["timeout"])}})
            elif "block_member_interaction" in action:
                actions.append({"type": 4, "metadata": {}})

        body = {
            "name": spec["name"],
            "event_type": AUTOMOD_EVENTS[spec.get("event", "message_send")],
            "trigger_type": trigger,
            "actions": actions,
            "enabled": True,
            "exempt_roles": [self.roles[r] for r in spec.get("exempt_roles", [])
                             if r in self.roles],
            "exempt_channels": [self.channels[c] for c in spec.get("exempt_channels", [])
                                if c in self.channels],
        }
        if meta:
            body["trigger_metadata"] = meta
        return body

    def sync_automod(self):
        rules = self.bp.get("automod", [])
        if not rules:
            return
        self.log("\nAutoMod")
        try:
            existing = {r["name"]: r for r in
                        self.c.get(f"/guilds/{self.gid}/auto-moderation/rules")}
        except Failed:
            existing = {}

        for spec in rules:
            try:
                body = self._automod_body(spec)
                if spec["name"] in existing:
                    rid = existing[spec["name"]]["id"]
                    self.c.patch(f"/guilds/{self.gid}/auto-moderation/rules/{rid}", body)
                    self.log(f"  = {spec['name']}")
                else:
                    self.c.post(f"/guilds/{self.gid}/auto-moderation/rules", body)
                    self.log(f"  + {spec['name']}")
            except Failed as e:
                # One bad rule should not abort the run.
                self._warn(f"{spec['name']}: {str(e)[:200]}")

    # -- onboarding -------------------------------------------------------

    def sync_onboarding(self):
        prompts_spec = self.bp.get("onboarding_prompts", [])
        defaults = self.bp.get("onboarding_defaults", [])
        if not prompts_spec and not defaults:
            return
        self.log("\nOnboarding")

        default_ids = []
        for name in defaults:
            cid = self.channels.get(name)
            if cid:
                default_ids.append(cid)
            else:
                self._warn(f"default channel {name} not found, skipped")

        prompts, counter = [], 1
        for p in prompts_spec:
            options = []
            for o in p.get("options", []):
                counter += 1
                opt = {
                    "id": str(counter),
                    "title": o["title"],
                    "role_ids": [self.roles[r] for r in o.get("roles", []) if r in self.roles],
                    "channel_ids": [self.channels[c] for c in o.get("channels", [])
                                    if c in self.channels],
                }
                if o.get("description"):
                    opt["description"] = o["description"]
                if o.get("emoji"):
                    opt["emoji"] = emoji_field(o["emoji"])
                options.append(opt)
            counter += 1
            # New prompts and options still need an id. Discord accepts
            # arbitrary numeric placeholders and assigns real snowflakes.
            prompts.append({
                "id": str(counter),
                "type": PROMPT_TYPES[p.get("type", "multiple_choice")],
                "title": p["title"],
                "options": options,
                "single_select": bool(p.get("single_select", False)),
                "required": bool(p.get("required", True)),
                "in_onboarding": True,
            })

        try:
            self.c.put(f"/guilds/{self.gid}/onboarding", {
                "enabled": True,
                "mode": 0,   # count only default channels toward the minimums
                "default_channel_ids": default_ids,
                "prompts": prompts,
            })
            self.log(f"  {len(prompts)} prompts, {len(default_ids)} default channels")
        except Failed as e:
            msg = str(e)
            # Say what Discord actually objected to. The old message guessed
            # "not enough default channels" every time, which sent people
            # looking at the wrong thing.
            if "ROLE_OR_CHANNEL_REQUIRED" in msg:
                self._warn("onboarding rejected: one or more answers grant neither a "
                           "role nor a channel, which Discord refuses.")
                self.log("      Everything else was applied. Re-run once the questions")
                self.log("      are fixed and only the questions will change.")
            elif "default_channel_ids" in msg or "DEFAULT_CHANNEL" in msg:
                self._warn("onboarding rejected: not enough starting channels. Discord "
                           "needs 7 or more, at least 5 letting everyone view and post.")
            else:
                self._warn(f"onboarding rejected: {msg[:300]}")

    # -- guild identity ---------------------------------------------------

    def set_identity(self, name: str | None = None, icon: bytes | None = None,
                     icon_name: str = "icon.png"):
        body = {}
        if name:
            body["name"] = name
        if icon:
            mime = mimetypes.guess_type(icon_name)[0] or "image/png"
            body["icon"] = f"data:{mime};base64,{base64.b64encode(icon).decode()}"
        if not body:
            return
        self.log("\nServer identity")
        try:
            self.c.patch(f"/guilds/{self.gid}", body)
            self.log(f"  {'name and icon' if icon and name else 'name' if name else 'icon'} set")
        except Failed as e:
            self._warn(f"could not set server name/icon: {str(e)[:160]}")

    def adopt_existing_channels(self):
        """Fill in channel ids from the live server without building anything.

        Lets the text be republished on its own, so fixing a wording mistake
        does not mean re-running the whole setup.
        """
        try:
            for ch in self.c.get(f"/guilds/{self.gid}/channels"):
                self.channels.setdefault(ch["name"], ch["id"])
            for r in self.c.get(f"/guilds/{self.gid}/roles"):
                self.roles.setdefault(r["name"], r["id"])
        except Failed as e:
            raise Failed(f"could not read the server: {str(e)[:160]}")

    def run_content_only(self, content_dir):
        """Republish the posted text and nothing else."""
        self.adopt_existing_channels()
        self.sync_content(Path(content_dir))
        self.sync_forum_posts(Path(content_dir))
        return self.problems

    # -- channel content --------------------------------------------------

    def sync_content(self, base_dir: Path):
        """Post the pinned welcome and rules text into their channels.

        Re-running edits the messages already there rather than posting again,
        so the rules can be corrected by editing a markdown file and running
        this once more. Anything the bot previously posted and that the file no
        longer contains is deleted, so the channel ends up matching the file
        exactly.
        """
        jobs = [(ch, ch.get("content_file")) for cat in self.bp.get("categories", [])
                for ch in cat.get("channels", []) if ch.get("content_file")]
        if not jobs:
            return
        self.log("\nChannel content")

        try:
            me = self.c.get("/users/@me")["id"]
        except Failed as e:
            self._warn(f"could not identify the bot, skipping content: {str(e)[:120]}")
            return

        for ch, rel in jobs:
            cid = self.channels.get(ch["name"])
            if not cid:
                continue
            path = (base_dir / rel).resolve()
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as e:
                self._warn(f"{ch['name']}: cannot read {rel} ({e})")
                continue

            blocks = split_content(substitute_text(raw, self.bp.get("variables", {})))
            color = ch.get("color", self.bp.get("meta", {}).get("accent_color"))
            if isinstance(color, str):
                color = int(color, 16)
            limit = EMBED_DESC_LIMIT if color else 2000
            too_long = [i for i, b in enumerate(blocks) if len(b) > limit]
            if too_long:
                self._warn(
                    f"{ch['name']}: section {too_long[0] + 1} of {rel} is over Discord's "
                    f"{limit}-character limit. Add a {SPLIT_MARKER} line before it.")
                continue

            payloads = pack_messages(blocks, color)

            if self.dry:
                self.log(f"  = #{ch['name']}: {len(blocks)} section(s) from {rel} "
                         f"in {len(payloads)} message(s)")
                continue

            try:
                existing = self.c.get(f"/channels/{cid}/messages?limit=100")
            except Failed:
                existing = []
            mine = [m for m in reversed(existing) if m.get("author", {}).get("id") == me]

            posted = []
            for i, payload in enumerate(payloads):
                try:
                    if i < len(mine):
                        # Sending both keys clears whichever the message is not
                        # using, so switching between plain text and embeds
                        # does not leave the old form behind.
                        body = {"content": payload.get("content", ""),
                                "embeds": payload.get("embeds", []),
                                "allowed_mentions": {"parse": []}}
                        self.c.patch(f"/channels/{cid}/messages/{mine[i]['id']}", body)
                        posted.append(mine[i]["id"])
                    else:
                        msg = self.c.post(f"/channels/{cid}/messages", payload)
                        posted.append(msg.get("id"))
                except Failed as e:
                    self._warn(f"{ch['name']}: could not write message {i + 1}: {str(e)[:120]}")

            for surplus in mine[len(payloads):]:
                try:
                    self.c.request("DELETE", f"/channels/{cid}/messages/{surplus['id']}")
                except Failed:
                    pass

            if ch.get("pin") and posted and posted[0]:
                try:
                    self.c.put(f"/channels/{cid}/pins/{posted[0]}", None)
                except Failed:
                    pass                      # already pinned, or no permission

            verb = "updated" if mine else "posted"
            shape = "embed" if color else "message"
            self.log(f"  {verb} {len(payloads)} {shape}(s) in #{ch['name']} "
                     f"({len(blocks)} section(s))")

    def sync_forum_posts(self, base_dir: Path):
        """Open the pinned starter post in each forum.

        A forum with no posts in it reads as broken, and the first person to
        use it has no example to copy. These are the posts that set the format
        everyone else follows, which is the whole reason bug reports arrive
        usable or not.
        """
        jobs = [(ch, ch["forum_post"]) for cat in self.bp.get("categories", [])
                for ch in cat.get("channels", [])
                if ch.get("forum_post") and ch.get("type") == "forum"]
        if not jobs:
            return
        self.log("\nForum starter posts")

        try:
            active = self.c.get(f"/guilds/{self.gid}/threads/active").get("threads", [])
        except Failed:
            active = []

        for ch, spec in jobs:
            cid = self.channels.get(ch["name"])
            if not cid:
                continue
            title = substitute_text(spec.get("title", "Start here"),
                                    self.bp.get("variables", {}))[:100]
            try:
                raw = (base_dir / spec["content_file"]).read_text(encoding="utf-8")
            except OSError as e:
                self._warn(f"{ch['name']}: cannot read {spec.get('content_file')} ({e})")
                continue

            blocks = split_content(substitute_text(raw, self.bp.get("variables", {})))
            body = "\n\n".join(blocks)[:2000]        # a starter post is one message

            if self.dry:
                self.log(f"  = #{ch['name']}: post \"{title}\"")
                continue

            existing = next((t for t in active
                             if t.get("parent_id") == cid and t.get("name") == title), None)
            if existing:
                # A forum post's opening message shares the thread's id, so it
                # can be rewritten in place. Without this, fixing a typo in a
                # starter post would mean deleting the thread by hand.
                try:
                    self.c.patch(f"/channels/{existing['id']}/messages/{existing['id']}",
                                 {"content": body, "allowed_mentions": {"parse": []}})
                    self.log(f"  = #{ch['name']}: updated \"{title}\"")
                except Failed as e:
                    self._warn(f"{ch['name']}: could not update \"{title}\": {str(e)[:120]}")
                continue

            payload = {"name": title,
                       "message": {"content": body, "allowed_mentions": {"parse": []}}}
            tag = spec.get("tag")
            if tag:
                by_name = {t["name"]: t.get("id") for t in ch.get("available_tags", [])}
                if by_name.get(tag):
                    payload["applied_tags"] = [by_name[tag]]
            try:
                thread = self.c.post(f"/channels/{cid}/threads", payload)
                self.log(f"  + #{ch['name']}: \"{title}\"")
                if spec.get("pin") and thread.get("id"):
                    # Forum posts pin via a thread flag, not the pins endpoint.
                    try:
                        self.c.patch(f"/channels/{thread['id']}", {"flags": 1 << 1})
                    except Failed:
                        pass
            except Failed as e:
                self._warn(f"{ch['name']}: could not create the starter post: {str(e)[:140]}")

    # -- welcome screen ---------------------------------------------------

    def sync_welcome_screen(self):
        """The panel Discord shows on the invite. Separate from onboarding,
        and one of the things people usually set by hand because they do not
        know it has an endpoint."""
        spec = self.bp.get("welcome_screen")
        if not spec or not self.bp.get("guild", {}).get("community"):
            return
        channels = []
        for entry in spec.get("channels", [])[:5]:      # Discord allows five
            cid = self.channels.get(entry.get("channel"))
            if not cid:
                continue
            item = {"channel_id": cid, "description": entry.get("description", "")[:50]}
            if entry.get("emoji"):
                item["emoji_name"] = entry["emoji"]
            channels.append(item)

        body = {"enabled": True,
                "description": (spec.get("description") or "")[:140],
                "welcome_channels": channels}
        try:
            self.c.patch(f"/guilds/{self.gid}/welcome-screen", body)
            self.log(f"\nWelcome screen\n  on, {len(channels)} channel(s) highlighted")
        except Failed as e:
            self._warn(f"welcome screen not set: {str(e)[:140]}")

    def sync_invite(self):
        """Make a permanent invite, or reuse the one already made.

        Discord's default invite expires after seven days, which is how a
        server ends up with a dead link on its store page and no idea why
        nobody arrives.
        """
        spec = self.bp.get("invite")
        if not spec:
            return
        cid = self.channels.get(spec.get("channel"))
        if not cid:
            return

        if self.dry:
            self.log("\nInvite\n  [dry run] would create a permanent invite")
            return

        try:
            for inv in self.c.get(f"/channels/{cid}/invites"):
                if inv.get("max_age") == 0 and inv.get("max_uses") == 0:
                    self.invite_url_made = f"https://discord.gg/{inv['code']}"
                    self.log(f"\nInvite\n  already had one: {self.invite_url_made}")
                    return
        except Failed:
            pass

        try:
            inv = self.c.post(f"/channels/{cid}/invites",
                              {"max_age": 0, "max_uses": 0, "unique": False})
            self.invite_url_made = f"https://discord.gg/{inv['code']}"
            self.log(f"\nInvite\n  {self.invite_url_made}  (never expires)")
        except Failed as e:
            self._warn(f"could not create an invite: {str(e)[:140]}")

    def grant_owner_role(self):
        """Give the server owner the roles that mark them as running the place.

        Discord assigns roles to nobody automatically, so without this the
        person who owns the server shows up in the default colour with no
        badge, which reliably reads as the setup having failed.
        """
        wanted = self.bp.get("guild", {}).get("owner_roles")
        if not wanted:
            single = self.bp.get("guild", {}).get("owner_role")
            wanted = [single] if single else []
        if not wanted or self.dry:
            return

        try:
            owner = self.c.get(f"/guilds/{self.gid}").get("owner_id")
        except Failed as e:
            self._warn(f"could not find the server owner: {str(e)[:120]}")
            return
        if not owner:
            return

        given = []
        for name in wanted:
            rid = self.roles.get(name)
            if not rid:
                continue
            try:
                self.c.put(f"/guilds/{self.gid}/members/{owner}/roles/{rid}", None)
                given.append(name)
            except Failed as e:
                # Usually the bot's own role sitting below the one it is trying
                # to hand out, which Discord will not allow.
                self._warn(f"could not give the owner the {name} role: {str(e)[:110]}")
        if given:
            self.log(f"\nOwner\n  gave {', '.join(given)} to the server owner")

    # -- deletions --------------------------------------------------------

    def delete_extras(self, channel_ids, role_ids):
        """Remove things the user explicitly ticked. Runs last, so nothing
        created above can depend on them. Deleting a channel deletes its
        messages, so this only ever acts on an explicit list."""
        if not channel_ids and not role_ids:
            return
        self.log("\nRemoving what you asked to remove")

        # Never delete something this run just made, whatever the browser sent.
        mine = set(self.channels.values()) | set(self.roles.values())
        by_id = {v: k for k, v in self.channels.items()}
        by_id.update({v: k for k, v in self.roles.items()})

        for cid in channel_ids or []:
            if str(cid) in mine:
                name = by_id.get(str(cid), cid)
                self._warn(
                    f"kept #{name}: it was marked for deletion but this run also "
                    f"builds it, so deleting it would undo the work above")
                continue
            try:
                self.c.request("DELETE", f"/channels/{cid}")
                self.log(f"  - channel {cid}")
            except Failed as e:
                self._warn(f"could not delete channel {cid}: {str(e)[:120]}")

        for rid in role_ids or []:
            if str(rid) == self.gid:
                self._warn("refused to delete @everyone")
                continue
            if str(rid) in mine:
                name = by_id.get(str(rid), rid)
                self._warn(
                    f"kept the {name} role: it was marked for deletion but this run "
                    f"also builds it, so deleting it would undo the work above")
                continue
            try:
                self.c.request("DELETE", f"/guilds/{self.gid}/roles/{rid}")
                self.log(f"  - role {rid}")
            except Failed as e:
                self._warn(f"could not delete role {rid}: {str(e)[:120]}")

    # -- run --------------------------------------------------------------

    def run(self, server_name=None, icon=None, icon_name="icon.png",
            delete_channels=None, delete_roles=None, content_dir=None):
        self.set_identity(server_name, icon, icon_name)
        self.sync_roles()
        self.sync_channels(gated=False)
        self.enable_community()
        self.sync_channels(gated=True)
        self.sync_automod()
        self.sync_onboarding()
        self.sync_welcome_screen()
        if content_dir:
            self.sync_content(Path(content_dir))
            self.sync_forum_posts(Path(content_dir))
        self.sync_role_positions()
        self.grant_owner_role()
        self.sync_invite()
        self.delete_extras(delete_channels, delete_roles)
        return self.problems


# --------------------------------------------------------------------------
# The steps no API can do
# --------------------------------------------------------------------------

def load_screening_rules(base_dir, rel: str) -> str:
    """The short rules, as one pasteable block.

    Kept in a file rather than in this function so that fixing a typo does not
    mean editing Python and restarting the setup page.
    """
    if not base_dir or not rel:
        return ""
    path = Path(base_dir) / rel
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    text = re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.S)
    return text.strip()


def manual_steps(app_id: str | None = None, bp: dict | None = None) -> list[dict]:
    """The steps with no endpoint behind them, with the exact clicks.

    The list lives in the blueprint under `manual_steps:` so it can be edited
    without touching code, and so a blueprint for a different community can
    carry its own. Everything here is read fresh on each call; nothing is
    baked in at import.

    No invite URLs for third-party bots: their OAuth links are keyed to client
    ids that are not ours to guess, and a wrong link would send someone's
    server to the wrong application. Discord's App Directory is the safe route.
    """
    bp = bp or {}
    variables = bp.get("variables", {})
    base = bp.get("_base_dir")

    steps = []
    for raw in bp.get("manual_steps", []):
        step = {
            "kind": raw.get("kind", "setting"),
            "title": substitute_text(raw.get("title", ""), variables),
            "why": substitute_text(raw.get("why", ""), variables),
            "where": [substitute_text(w, variables) for w in raw.get("where", [])],
        }
        if raw.get("after"):
            step["after"] = substitute_text(raw["after"], variables)
        if raw.get("optional"):
            step["optional"] = True
        if raw.get("copy_file"):
            body = load_screening_rules(base, raw["copy_file"])
            if body:
                step["copy"] = substitute_text(body, variables)
                step["copy_label"] = raw.get("copy_label", "Copy")
        steps.append(step)

    if app_id:
        steps.append({
            "kind": "bot", "title": "Trim your own bot's permissions", "optional": True,
            "why": "Your bot still has Administrator from the setup run. From here it "
                   "only needs to read channels, post reports, and remove the temporary "
                   "attribution roles.",
            "where": ["Open the link below", "Pick the same server", "Authorize"],
            "url": invite_url(app_id, INVITE_PERMS_LEDGER),
            "after": "Running this setup tool again will fail until you give it "
                     "Administrator back. That is deliberate.",
        })
    return steps
