"""Which parts of Steward are switched on, for this deployment.

Everything here is optional except the ledger. Somebody who already runs MEE6
does not want a second bot handing out XP, and somebody who posts their own
announcements does not want a calendar nagging them. Rather than making them
delete code or channels, each part has a switch.

The switches live in steward/.env alongside the token and the calendar choice,
because they are per deployment rather than per blueprint: the same blueprint
should be usable by a server that wants levels and a server that does not. .env
is gitignored and an update never overwrites it, so the choice survives.

Read by the bot at startup and by the setup page, which is why this module
imports nothing beyond the standard library.
"""

from __future__ import annotations

import os

# Order is the order the setup page shows them in.
CATALOG = [
    {
        "key": "levels",
        "name": "Levels and ranks",
        "blurb": "Members earn XP for taking part, and roles unlock at the levels "
                 "you set. Off means no XP is recorded at all, /rank and "
                 "/leaderboard disappear, and the Tier roles are left out of the "
                 "build. Switch it off if you already run MEE6, Arcane or Lurkr.",
        "commands": ["rank", "leaderboard"],
    },
    {
        "key": "calendar",
        "name": "The content calendar",
        "blurb": "When a scheduled post comes due, the bot drafts it into your "
                 "staff channel with Approve and Skip buttons. Off means nothing "
                 "is ever drafted and the calendar commands disappear. Nothing in "
                 "the calendar is deleted, so this is reversible.",
        "commands": ["calendar", "calendar-run", "calendar-reload"],
    },
    {
        "key": "digest",
        "name": "The weekly digest",
        "blurb": "Once a week the bot posts the numbers into your reports channel: "
                 "joins, people who posted, retention by cohort, and which channels "
                 "have fallen behind their own baseline. Off also removes /digest "
                 "and /decay.",
        "commands": ["digest", "decay"],
    },
    {
        "key": "modlog",
        "name": "The moderation log",
        "blurb": "Bans, kicks, timeouts, deleted messages and channel changes are "
                 "written to your mod-log channel, with who did it where Discord's "
                 "audit log says. Off writes nothing and leaves the channel alone.",
        "commands": [],
    },
    {
        "key": "playtest",
        "name": "Playtest waves and keys",
        "blurb": "Opt-in signups, handing out keys one per person with nothing "
                 "reused, and bug reports filed from Discord. Off removes the "
                 "playtest commands, the playtest channel and its two roles.",
        "commands": ["playtest-join", "playtest-leave", "playtest-open",
                     "playtest-keys", "playtest-issue", "playtest-status",
                     "playtest-close", "playtest-report"],
    },
]

KEYS = [f["key"] for f in CATALOG]

# Values that mean off. Anything else, including an unset key, means on: a
# fresh install should behave the way the documentation describes it.
OFF = {"0", "off", "false", "no", "none", "disabled"}


def env_name(key: str) -> str:
    return "FEATURE_" + key.upper()


def is_on(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() not in OFF


def read(env=None) -> dict:
    """The current switches. `env` is any mapping of .env-style keys, which is
    how the setup page reads a file it does not have loaded into its own
    process."""
    src = os.environ if env is None else env
    return {key: is_on(src.get(env_name(key))) for key in KEYS}


def off(state: dict) -> list:
    """The names of what is switched off, for a startup log line."""
    return [f["name"] for f in CATALOG if not state.get(f["key"], True)]


def commands_off(state: dict) -> set:
    """Slash commands that should not be registered at all. A command left
    registered but answering "that is switched off" is worse than absent: it
    shows up in the picker and looks broken."""
    gone = set()
    for f in CATALOG:
        if not state.get(f["key"], True):
            gone.update(f["commands"])
    return gone
