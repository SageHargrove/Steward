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
INVITE_PERMS_LEDGER = 2147568640      # view, send, history, embed, slash commands


class Failed(Exception):
    pass


# --------------------------------------------------------------------------
# Load, template, customize
# --------------------------------------------------------------------------

def load(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def declared_variables(bp: dict) -> dict:
    """The `variables:` block, which is what the UI turns into form fields."""
    return dict(bp.get("variables", {}))


_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def substitute(bp: dict, values: dict) -> dict:
    """Replace {{name}} placeholders throughout every string in the blueprint.

    This is what makes a blueprint redeployable rather than a config file.
    `{{game}}` survives a move to the next project; "Giltgrave" does not.
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

    if not bp.get("roles"):
        warnings.append("No roles selected")
    if not channels:
        errors.append("No channels selected, so there is nothing to build")

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
            "User-Agent": "CommunityOpsProvisioner (https://giltgrave.example, 1.0)",
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

    def _warn(self, msg):
        self.problems.append(msg)
        self.log(f"  ! {msg}")

    # -- roles ------------------------------------------------------------

    def sync_roles(self):
        self.log("\nRoles")
        existing = {r["name"]: r for r in self.c.get(f"/guilds/{self.gid}/roles")}
        self.roles["everyone"] = self.gid   # @everyone's role id is the guild id

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
        """Blueprint lists roles highest-first. Discord positions are
        lowest-first, and nothing can sit above the bot's own managed role,
        so a failure here is expected and harmless."""
        if self.dry:
            self.log("\n  [dry run] would reorder roles")
            return
        names = [r["name"] for r in self.bp.get("roles", [])]
        payload = [{"id": self.roles[n], "position": len(names) - i}
                   for i, n in enumerate(names) if n in self.roles]
        if not payload:
            return
        try:
            self.c.patch(f"/guilds/{self.gid}/roles", payload)
            self.log("\n  role order applied")
        except Failed:
            self.log("\n  role order not applied, drag them by hand in Server Settings")

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

    def _channel_body(self, spec, parent_id=None, position=None):
        ctype = spec.get("type", "text")
        body = {
            "name": spec["name"],
            "type": CHANNEL_TYPES[ctype],
            "permission_overwrites": self._overwrites(spec.get("overwrites")),
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

        self.c.patch(f"/guilds/{self.gid}", body)
        self.log("  on. Verification: verified email. Media filter: all members")

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
        for cid in channel_ids or []:
            if str(cid) in mine:
                self._warn(f"refused to delete channel {cid}: this run just created it")
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
                self._warn(f"refused to delete role {rid}: this run just created it")
                continue
            try:
                self.c.request("DELETE", f"/guilds/{self.gid}/roles/{rid}")
                self.log(f"  - role {rid}")
            except Failed as e:
                self._warn(f"could not delete role {rid}: {str(e)[:120]}")

    # -- run --------------------------------------------------------------

    def run(self, server_name=None, icon=None, icon_name="icon.png",
            delete_channels=None, delete_roles=None):
        self.set_identity(server_name, icon, icon_name)
        self.sync_roles()
        self.sync_channels(gated=False)
        self.enable_community()
        self.sync_channels(gated=True)
        self.sync_automod()
        self.sync_onboarding()
        self.sync_role_positions()
        self.delete_extras(delete_channels, delete_roles)
        return self.problems


# --------------------------------------------------------------------------
# The steps no API can do
# --------------------------------------------------------------------------

def manual_steps(app_id: str | None = None, game: str = "the game",
                 mod_channel: str = "mod-log") -> list[dict]:
    """Everything the provisioner cannot do, with the exact clicks.

    Bot installation is a permission flow requiring a human with Manage Server
    to press Authorize, so every server-blueprint product ever built has a
    manual bot step. The honest move is to make each one as short as possible
    rather than pretend otherwise.

    No invite URLs for third-party bots: their OAuth links are keyed to client
    ids that are not ours to guess, and a wrong invite link would send someone's
    server to the wrong application. Discord's own App Directory is reachable
    from the server dropdown and is the safe route.
    """
    rules = (
        f"1. Be decent to each other. Disagreement is fine, contempt is not.\n"
        f"2. No slurs, harassment, or sexual content. The filter catches some of "
        f"it and a human catches the rest.\n"
        f"3. No advertising or invite links outside #looking-for-guild.\n"
        f"4. Playtest builds are unreleased. Do not post screenshots, footage, or "
        f"files from them outside #playtest-lounge until a build is public.\n"
        f"5. Bugs go in #bug-reports with a build number and repro steps. A bug "
        f"reported in #general is a bug that gets lost."
    )

    steps = [
        {
            "kind": "setting", "title": "Rules Screening",
            "why": "Shows your rules to every new member and makes them agree before "
                   "they can post. There is no API for it.",
            "where": ["Click your server name at the top left",
                      "Server Settings",
                      "Safety Setup",
                      "Rules Screening",
                      "Paste the rules below, one per box. 16 maximum."],
            "copy_label": "Copy the draft rules",
            "copy": rules,
        },
        {
            "kind": "setting", "title": "Server Guide",
            "why": "The panel new members see first. Worth five minutes; it is the "
                   "difference between someone posting and someone lurking.",
            "where": ["Server name at the top left", "Server Settings", "Onboarding",
                      "Server Guide tab",
                      "Add #start-here, #announcements and #bug-reports as resource "
                      "pages, one line of description each"],
        },
        {
            "kind": "setting", "title": "Raid Protection",
            "why": "Detects join spikes and makes new joiners solve a CAPTCHA for an "
                   "hour. Turn it on now, not after your first raid.",
            "where": ["Server name at the top left", "Server Settings", "Safety Setup",
                      "Turn on Raid Protection"],
        },
        {
            "kind": "setting", "title": "Make yourself Dev",
            "why": "The Dev role was created but Discord will not assign roles to you "
                   "automatically. Nothing shows you as staff until you do this.",
            "where": ["Server name at the top left", "Server Settings", "Members",
                      "Find yourself", "Press the + next to your name", "Pick Dev"],
        },
        {
            "kind": "bot", "title": "Wick",
            "why": "Security. Anti-nuke, CAPTCHA verification, and a join gate that "
                   "filters brand-new and avatarless accounts.",
            "where": ["Click your server name at the top left", "App Directory",
                      "Search for Wick", "Add to Server, pick your server, Authorize"],
            "after": "Set its join gate to reject accounts under 7 days old, and point "
                     f"its logging at #{mod_channel}.",
        },
        {
            "kind": "bot", "title": "Sapphire",
            "why": "Moderation, reaction roles and logging. Genuinely free, and it "
                   "covers what MEE6 charges for.",
            "where": ["Server name at the top left", "App Directory",
                      "Search for Sapphire", "Add to Server, pick your server, Authorize"],
            "after": f"Point its logging at #{mod_channel}. Skip its join-role feature, "
                     "the new-member questions already handle roles.",
        },
        {
            "kind": "bot", "title": "Statbot", "optional": True,
            "why": "Charts and member counters. Its free tier only keeps 30 days of "
                   "history, which is exactly why the ledger exists alongside it.",
            "where": ["Server name at the top left", "App Directory",
                      "Search for Statbot", "Add to Server, pick your server, Authorize"],
        },
        {
            "kind": "bot", "title": "Steamy", "optional": True,
            "why": "Posts new Steam reviews and weekly rating digests into Discord. "
                   f"Install it the day {game} has a Steam page, not before.",
            "where": ["Server name at the top left", "App Directory",
                      "Search for Steamy", "Add to Server, pick your server, Authorize"],
        },
    ]

    if app_id:
        steps.append({
            "kind": "bot", "title": "Trim your own bot's permissions", "optional": True,
            "why": "Your bot still has Administrator from the setup run. It only needs "
                   "to read channels and post reports from here on.",
            "where": ["Open the link below", "Pick the same server", "Authorize"],
            "url": invite_url(app_id, INVITE_PERMS_LEDGER),
            "after": "Re-running this setup tool afterwards will fail until you give it "
                     "Administrator again. That is deliberate.",
        })
    return steps
