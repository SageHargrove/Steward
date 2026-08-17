"""The calendar engine: what to post, and when, relative to a launch.

Dates are written as offsets from T-0 rather than as calendar dates. That is
the whole reason this is a product rather than a config file. `T-42` redeploys
to any launch; `2026-09-14` describes exactly one.

Nothing here talks to Discord. It answers two questions, both pure: what does
the schedule look like between these dates, and what became due. The bot does
the posting, and it dedupes against the ledger rather than against a
last-checked timestamp, so a bot that was switched off for a fortnight
catches up exactly once per post instead of either replaying or skipping.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]

_OFFSET = re.compile(r"^\s*T\s*([+-])\s*(\d+)\s*$", re.I)
_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][\w]*)\s*\}\}")


class BadDate(ValueError):
    pass


def parse_when(when, anchor: date | None) -> date:
    """`T-180`, `T+14`, `T-0`, or a plain `2026-09-14`.

    An absolute date is allowed and sometimes right: Next Fest registration
    closes when Valve says it closes, not when your launch happens to be.
    """
    if isinstance(when, date):
        return when
    text = str(when)
    m = _ISO.match(text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _OFFSET.match(text)
    if m:
        if anchor is None:
            raise BadDate(f"{text!r} is relative to the launch date, which is not set")
        days = int(m.group(2))
        return anchor + timedelta(days=days if m.group(1) == "+" else -days)
    raise BadDate(f"cannot read {text!r} as a date. Use T-90, T+7, or 2026-09-14")


def substitute(text, values: dict) -> str:
    """The same {{placeholder}} filling the blueprint uses, so one calendar
    serves any game without editing the prose."""
    if not isinstance(text, str):
        return text
    return _VAR.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


class Occurrence:
    """One post on one day."""

    def __init__(self, post: dict, when: date, recurring=False):
        self.post, self.date, self.recurring = post, when, recurring
        self.id = post.get("id", "")

    @property
    def key(self) -> str:
        return f"{self.id}@{self.date.isoformat()}"

    def __repr__(self):
        return f"<Occurrence {self.key}>"


class Calendar:
    def __init__(self, spec: dict | None = None, variables: dict | None = None):
        spec = spec or {}
        meta = spec.get("meta") or {}
        self.name = meta.get("name", "Content calendar")
        self.timezone = meta.get("timezone", "UTC")
        self.tz, self.tz_problem = self._zone(self.timezone)
        self.post_hour = int(meta.get("post_hour", 17))
        self.anchor = self._anchor(meta.get("anchor"))
        self.variables = variables or {}
        # `posts:` is the name now. `beats:` was content-marketing jargon and
        # is still read, so a calendar written before the rename still loads.
        self.posts = list(spec.get("posts") or spec.get("beats") or [])
        self.recurring = list(spec.get("recurring") or [])

    @staticmethod
    def _zone(name: str):
        """The timezone posts are timed against.

        Windows does not ship the IANA database, so `ZoneInfo("Europe/London")`
        raises there unless the `tzdata` package is installed. It is in
        requirements.txt for that reason, and this still falls back to UTC with
        an explanation rather than refusing to load the calendar: a bot that
        will not start because of a timezone is worse than one an hour out.
        """
        if not name or name.upper() == "UTC":
            return timezone.utc, None
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name), None
        except Exception as e:                               # noqa: BLE001
            return timezone.utc, (
                f"timezone {name!r} could not be loaded ({type(e).__name__}), so "
                f"posts are timed against UTC. Install the 'tzdata' package, or "
                f"set meta.timezone to UTC to silence this.")

    def now(self) -> datetime:
        """The current time where the calendar says it lives, so post_hour
        means the hour a person would recognise."""
        return datetime.now(self.tz)

    @staticmethod
    def _anchor(value) -> date | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        m = _ISO.match(str(value))
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

    @property
    def configured(self) -> bool:
        """A calendar with posts but no launch date does nothing, on purpose.
        Firing relative posts against a guessed anchor is worse than silence."""
        return bool(self.anchor) or not any(
            _OFFSET.match(str(b.get("when", ""))) for b in self.posts)

    def t_minus(self, when: date) -> int | None:
        return (when - self.anchor).days if self.anchor else None

    # -- laying it out ----------------------------------------------------

    def occurrences(self, start: date, end: date) -> list[Occurrence]:
        """Everything scheduled in [start, end], in date order."""
        out: list[Occurrence] = []
        for post in self.posts:
            try:
                when = parse_when(post.get("when"), self.anchor)
            except BadDate:
                continue                    # validate() reports it; do not fire it
            if start <= when <= end:
                out.append(Occurrence(self.fill(post), when))
        for post in self.recurring:
            out.extend(self._recur(post, start, end))
        return sorted(out, key=lambda o: (o.date, o.id))

    def _recur(self, post: dict, start: date, end: date) -> list[Occurrence]:
        every = str(post.get("every", "")).strip().lower()
        try:
            lo = parse_when(post["from"], self.anchor) if post.get("from") else None
            hi = parse_when(post["until"], self.anchor) if post.get("until") else None
        except BadDate:
            return []
        lo, hi = max(start, lo or start), min(end, hi or end)
        if lo > hi:
            return []

        out = []
        if every == "daily":
            days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        elif every in WEEKDAYS:
            target = WEEKDAYS.index(every)
            first = lo + timedelta(days=(target - lo.weekday()) % 7)
            days = []
            while first <= hi:
                days.append(first)
                first += timedelta(days=7 * int(post.get("weeks", 1) or 1))
        else:
            return []                       # validate() explains why
        filled = self.fill(post)
        return [Occurrence(filled, d, recurring=True) for d in days] + out

    def due(self, today: date, lookback: int = 7) -> list[Occurrence]:
        """What should have gone out by now.

        The window exists so that installing the bot in November does not fire
        every post since September at once. Anything older than the window is
        treated as missed rather than late, which is almost always what a human
        would have wanted.
        """
        return self.occurrences(today - timedelta(days=lookback), today)

    def upcoming(self, today: date, days: int = 60) -> list[Occurrence]:
        return self.occurrences(today + timedelta(days=1), today + timedelta(days=days))

    def find(self, post_id: str, when: date) -> Occurrence | None:
        """One named post, dated to whatever day you ask for. This is how a
        post gets tested without waiting months for its real date."""
        for post in self.posts:
            if post.get("id") == post_id:
                return Occurrence(self.fill(post), when)
        for post in self.recurring:
            if post.get("id") == post_id:
                return Occurrence(self.fill(post), when, recurring=True)
        return None

    def ids(self) -> list[str]:
        return [b.get("id", "") for b in self.posts + self.recurring if b.get("id")]

    def fill(self, post: dict) -> dict:
        out = {}
        for k, v in post.items():
            if isinstance(v, str):
                out[k] = substitute(v, self.variables)
            elif isinstance(v, dict):
                out[k] = {kk: substitute(vv, self.variables) for kk, vv in v.items()}
            else:
                out[k] = v
        return out

    # -- checking ---------------------------------------------------------

    def validate(self, channels: list[str] | None = None,
                 roles: list[str] | None = None) -> dict:
        errors, warnings = [], []
        seen = set()
        every_post = [(b, False) for b in self.posts] + [(b, True) for b in self.recurring]

        if self.tz_problem:
            warnings.append(self.tz_problem)

        if not self.anchor and any(_OFFSET.match(str(b.get("when", "")))
                                   for b in self.posts):
            warnings.append(
                "No launch date set, so every T-minus post is dormant. Set "
                "meta.anchor, or LAUNCH_DATE in the environment.")

        for post, is_recurring in every_post:
            bid = post.get("id")
            if not bid:
                errors.append(f"a post has no id: {str(post)[:60]}")
                continue
            if bid in seen:
                errors.append(f"two posts share the id {bid!r}. Ids are how a "
                              f"posted post is remembered, so they must be unique")
            seen.add(bid)

            if is_recurring:
                every = str(post.get("every", "")).strip().lower()
                if every not in WEEKDAYS and every != "daily":
                    errors.append(f"{bid}: 'every: {post.get('every')}' is not a "
                                  f"weekday or 'daily'")
            else:
                try:
                    parse_when(post.get("when"), self.anchor or date(2000, 1, 1))
                except BadDate as e:
                    errors.append(f"{bid}: {e}")

            kind = post.get("kind", "post")
            if kind not in ("post", "reminder"):
                errors.append(f"{bid}: kind is {kind!r}, which is neither 'post' "
                              f"nor 'reminder'")

            if not post.get("body"):
                errors.append(f"{bid}: has nothing to post")
            if not post.get("channel"):
                errors.append(f"{bid}: has no channel to post in")
            elif channels is not None and post["channel"] not in channels:
                warnings.append(f"{bid}: posts to #{post['channel']}, which is not "
                                f"in the blueprint. It will be skipped if the "
                                f"channel does not exist")

            mention = post.get("mention")
            if mention and mention != "everyone" and roles is not None \
                    and mention not in roles:
                warnings.append(f"{bid}: mentions @{mention}, which is not a role "
                                f"in the blueprint")
            if mention == "everyone":
                warnings.append(f"{bid}: uses @everyone. Discord will deliver that "
                                f"to every member, so make sure the post earns it")

            ev = post.get("event")
            if ev and not ev.get("name"):
                errors.append(f"{bid}: has an event with no name")

        return {"errors": errors, "warnings": warnings,
                "posts": len(self.posts), "recurring": len(self.recurring),
                "anchor": self.anchor.isoformat() if self.anchor else None}


def overrides_path(path) -> Path:
    """Where a person's own edits live: `content-calendar.local.yaml`."""
    p = Path(path)
    return p.with_name(p.stem + ".local" + p.suffix)


def merge(spec: dict, local: dict) -> dict:
    """Lay somebody's edits over the shipped calendar.

    Edits go in a separate file rather than being written back into the
    original, for three reasons that all bite otherwise. Rewriting the shipped
    file would destroy its comments, which are most of what makes it readable.
    An update replaces that file, so edits written into it would be lost every
    time. And keeping them apart means the shipped calendar stays a clean thing
    to redeploy to the next project, which is the whole point of it.

    Posts are matched by id. Any field can be overridden, `enabled: false`
    hides a shipped post without deleting it, and an id that is not in the
    original is simply added.
    """
    def rows(d, key):
        return d.get(key) or (d.get("beats") if key == "posts" else None) or []

    out = {"meta": {**(spec.get("meta") or {}), **(local.get("meta") or {})}}
    for key in ("posts", "recurring"):
        base = {b.get("id"): dict(b) for b in rows(spec, key) if b.get("id")}
        order = [b.get("id") for b in rows(spec, key) if b.get("id")]
        for edit in rows(local, key):
            bid = edit.get("id")
            if not bid:
                continue
            if bid in base:
                base[bid].update(edit)
            else:
                base[bid] = dict(edit)
                order.append(bid)
        out[key] = [base[i] for i in order
                    if base[i].get("enabled", True) is not False]
    return out


def load(path, variables: dict | None = None, anchor_override=None) -> Calendar:
    import yaml
    with open(path, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}

    local_file = overrides_path(path)
    if local_file.exists():
        try:
            with open(local_file, encoding="utf-8") as fh:
                spec = merge(spec, yaml.safe_load(fh) or {})
        except Exception:                                    # noqa: BLE001
            pass                        # a broken overrides file must not stop the bot

    if anchor_override:
        spec.setdefault("meta", {})["anchor"] = anchor_override
    return Calendar(spec, variables)
