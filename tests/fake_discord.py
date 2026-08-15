"""A stand-in for Discord's REST API.

Everything here exists so the provisioner can be exercised end to end without
touching a real server. It records every call it receives, so tests can assert
on ordering (which matters: forum channels cannot be created before Community
mode is on) as well as on the final state.

It is deliberately permissive. It is not a Discord validator, it is a way to
watch what we send.
"""

from __future__ import annotations

import itertools
import json

# Discord channel type numbers, mirrored here so a typo in core.py does not
# silently agree with a matching typo in the tests.
CATEGORY, TEXT, VOICE, ANNOUNCEMENT, FORUM = 4, 0, 2, 5, 15
GATED_TYPES = {ANNOUNCEMENT, FORUM, 13}


class FakeDiscord:
    def __init__(self, guild_id="5", channels=None, roles=None):
        self.guild_id = guild_id
        self.ids = itertools.count(900000000000000000)
        self.channels = list(channels or [])
        self.roles = list(roles or [{"id": guild_id, "name": "@everyone", "managed": False}])
        self.automod = []
        self.guild = {"id": guild_id, "features": [], "name": "Test Server",
                      "owner_id": "77"}
        self.onboarding = None
        self.messages = {}       # channel id -> [{id, content, author}]
        self.threads = []        # forum starter posts
        self.invites = {}        # channel id -> [invite]
        self.welcome_screen = None
        self.bot_role_position = 50   # where this bot's own role sits
        self.calls = []          # (method, path, body)
        self.deleted = []
        self.fail_on = {}        # (method, path_substring) -> status to raise

    # -- helpers for assertions ------------------------------------------

    def paths(self, method=None):
        return [p for m, p, _ in self.calls if method in (None, m)]

    def index_of(self, method, path, where=None):
        """First index of a matching call, or -1."""
        for i, (m, p, b) in enumerate(self.calls):
            if m == method and p == path and (where is None or where(b)):
                return i
        return -1

    def created_channels(self, ctype=None):
        return [b for m, p, b in self.calls
                if m == "POST" and p.endswith("/channels")
                and (ctype is None or b.get("type") == ctype)]

    def channel_named(self, name):
        return next((c for c in self.channels if c["name"] == name), None)

    def role_named(self, name):
        return next((r for r in self.roles if r["name"] == name), None)

    # -- the transport ---------------------------------------------------

    def session(self):
        outer = self

        class Session:
            def __init__(self):
                self.headers = {}

            def request(self, method, url, data=None):
                path = url.split("/api/v10")[1]
                body = json.loads(data) if data else None
                return outer._handle(method, path, body)

        return Session

    def _handle(self, method, path, body):
        self.calls.append((method, path, body))

        for (m, frag), status in self.fail_on.items():
            if m == method and frag in path:
                return _Resp(status, {"message": "forced failure", "code": 50035})

        if method == "GET":
            payload = self._get(path)
            if isinstance(payload, dict) and payload.get("code") == 50035:
                return _Resp(400, payload)
            return _Resp(200, payload)
        if method == "POST":
            return _Resp(200, self._post(path, body))
        if method in ("PATCH", "PUT"):
            return _Resp(200, self._write(method, path, body))
        if method == "DELETE":
            self.deleted.append(path)
            return _Resp(204, None)
        return _Resp(200, {})

    def _get(self, path):
        if path.endswith("/members/@me"):
            # Real Discord rejects this for bot tokens: @me only resolves for an
            # OAuth2 bearer token with guilds.members.read. Refusing it here is
            # what makes the ordering test honest.
            return {"message": "Invalid Form Body", "code": 50035,
                    "errors": {"user_id": {"_errors": [{"code": "NUMBER_TYPE_COERCE"}]}}}
        if "/members/" in path:
            uid = path.rsplit("/", 1)[1]
            return {"user": {"id": uid}, "roles": ["bot-role"]}
        if path == "/users/@me":
            return {"id": "4242", "username": "Steward", "avatar": None}
        if path == "/users/@me/guilds":
            return [{"id": self.guild_id, "name": "Test Server", "icon": None,
                     "owner": True, "permissions": 8}]
        if path.endswith("/roles"):
            out = []
            for i, r in enumerate(self.roles):
                out.append({**r, "position": r.get("position", i)})
            out.append({"id": "bot-role", "name": "Steward", "managed": True,
                        "position": self.bot_role_position})
            return out
        if path.endswith("/invites"):
            return self.invites.get(path.split("/")[2], [])
        if path.endswith("/threads/active"):
            return {"threads": self.threads}
        if "/messages" in path:
            cid = path.split("/")[2]
            return list(reversed(self.messages.get(cid, [])))    # newest first
        if path.endswith("/channels"):
            return self.channels
        if "auto-moderation" in path:
            return self.automod
        return self.guild

    def _post(self, path, body):
        obj = {**body, "id": str(next(self.ids))}
        if path.endswith("/invites"):
            cid = path.split("/")[2]
            inv = {"code": "testinvite", "max_age": body.get("max_age"),
                   "max_uses": body.get("max_uses")}
            self.invites.setdefault(cid, []).append(inv)
            return inv
        if path.endswith("/threads"):
            cid = path.split("/")[2]
            obj = {"id": str(next(self.ids)), "name": body["name"], "parent_id": cid}
            self.threads.append(obj)
            return obj
        if path.endswith("/messages"):
            cid = path.split("/")[2]
            obj["author"] = {"id": "4242"}
            self.messages.setdefault(cid, []).append(obj)
            return obj
        if path.endswith("/channels"):
            # Refuse gated types before Community mode, exactly as Discord does.
            if obj.get("type") in GATED_TYPES and "COMMUNITY" not in self.guild["features"]:
                return {"message": "Cannot create in a non-community guild", "code": 50035}
            self.channels.append(obj)
        elif path.endswith("/roles"):
            self.roles.append(obj)
        elif "auto-moderation" in path:
            self.automod.append(obj)
        return obj

    def _write(self, method, path, body):
        if path == f"/guilds/{self.guild_id}":
            if body and "features" in body:
                self.guild["features"] = body["features"]
            self.guild.update({k: v for k, v in (body or {}).items() if k != "features"})
        elif "onboarding" in path:
            self.onboarding = body
        elif path.endswith("/welcome-screen"):
            self.welcome_screen = body
        elif "/messages/" in path:
            cid, mid = path.split("/")[2], path.split("/")[4]
            for m in self.messages.get(cid, []):
                if m["id"] == mid:
                    m.update(body or {})
        elif path.startswith("/channels/"):
            cid = path.split("/")[2]
            for c in self.channels:
                if c["id"] == cid:
                    c.update(body or {})
        return {}


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.content = b"{}" if payload is not None else b""
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


def install(core, fake):
    """Point core's HTTP layer at the fake for the duration of a test."""
    core.requests.Session = fake.session()
    return fake
