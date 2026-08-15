"""Moderation logging.

What this deliberately does not do: quote deleted messages. Reading message
content is a privileged intent Steward does not request, and the promise made
to members in the welcome post is that the bot records who posted where and
when, never what was said. Keeping that promise costs one feature and buys
every other one an honest answer.

What is left is the part that actually matters when something goes wrong: who
banned whom, who changed which role, who timed somebody out, and when a
channel appeared or vanished. Discord's audit log carries all of that without
touching a single message body.
"""

from __future__ import annotations

import discord

# Muted greys and reds so a wall of these stays readable, with the destructive
# ones standing out rather than everything shouting at once.
COLOURS = {
    "ban": 0xF23F42,
    "unban": 0x23A55A,
    "kick": 0xE8912D,
    "timeout": 0xF0B232,
    "timeout_over": 0x5E8C7B,
    "roles": 0x5865F2,
    "nickname": 0x949BA4,
    "message": 0x80848E,
    "channel": 0x8B5FBF,
    "role": 0x8B5FBF,
}


def entry(kind: str, title: str, lines: list[str], who=None) -> discord.Embed:
    e = discord.Embed(title=title, colour=COLOURS.get(kind, 0x80848E),
                      description="\n".join(l for l in lines if l))
    if who is not None:
        e.set_author(name=str(who), icon_url=who.display_avatar.url)
        e.set_footer(text=f"user id {who.id}")
    return e


async def actor_for(guild: discord.Guild, action: discord.AuditLogAction,
                    target_id: int | None = None):
    """Who did it, from the audit log.

    Discord's own events say what happened but not who caused it, so without
    this a ban log reads "someone was banned" and helps nobody. Requires View
    Audit Log; returns None rather than failing if that is missing.
    """
    try:
        async for record in guild.audit_logs(limit=6, action=action):
            if target_id is None or getattr(record.target, "id", None) == target_id:
                return record
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


def describe_roles(before: discord.Member, after: discord.Member):
    gained = [r for r in after.roles if r not in before.roles]
    lost = [r for r in before.roles if r not in after.roles]
    return gained, lost
