"""Steward: the ledger, levels, the weekly digest and the moderation log.

One bot rather than four. A server that would otherwise install a leveling bot,
a stats bot and a logging bot ends up with three copies of its own activity in
three companies' databases, and this already has the data.

It does NOT request the MESSAGE_CONTENT intent, and that is a deliberate limit
rather than an oversight. on_message fires without it; only the content field
comes back empty. So the ledger records who posted where and when, levels come
from the fact of posting rather than what was posted, and the moderation log
reports that a message was deleted without quoting it. Less to protect, no
annual reapplication past 10,000 users, and an honest answer when a member asks
what is stored.

Run:
    python bot.py          (or START-LEDGER.bat, which installs what it needs)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import calendar_engine
import decay
import digest
import modlog
from ledger import Ledger
from levels import Levels

# Named explicitly rather than searched for. load_dotenv() looks in the
# current directory, so running the bot from anywhere but steward/ silently
# picked up no settings at all and fell back to every default.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TOKEN = os.environ.get("DISCORD_TOKEN")
DB_PATH = os.environ.get("STEWARD_DB", "data/steward.sqlite3")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "400"))
REPORT_CHANNEL = os.environ.get("REPORT_CHANNEL", "steward-reports")
MOD_CHANNEL = os.environ.get("MOD_CHANNEL", "mod-log")
def find_blueprint() -> str:
    """Where the blueprint is. Falls back to whatever is in the folder, so
    renaming or replacing it does not silently switch levels off."""
    named = os.environ.get("STEWARD_BLUEPRINT")
    if named and os.path.exists(named):
        return named
    for guess in ("../blueprint/default.yaml", "blueprint/default.yaml"):
        if os.path.exists(guess):
            return guess
    import glob
    found = sorted(glob.glob("../blueprint/*.yaml")) or sorted(glob.glob("blueprint/*.yaml"))
    return found[0] if found else (named or "../blueprint/default.yaml")


BLUEPRINT = find_blueprint()


def read_version() -> str:
    """The running version. Every bug report starts with an argument about
    which code somebody has, so the bot says so itself."""
    for guess in ("../VERSION", "VERSION"):
        try:
            lines = open(guess, encoding="utf-8").read().strip().splitlines()
            if lines:
                return lines[0].strip()
        except OSError:
            continue
    return "unknown"


VERSION = read_version()


CALENDAR_DIRS = ("../blueprint/calendars", "blueprint/calendars")


def calendar_dir() -> str:
    for guess in CALENDAR_DIRS:
        if os.path.isdir(guess):
            return guess
    return CALENDAR_DIRS[0]


def find_calendar() -> str:
    """Which calendar template is in use.

    `CALENDAR` names one of blueprint/calendars/*.yaml without the extension,
    because a Steam launch, a Roblox experience and a mod have almost nothing
    in common in what they post or when. A full path still works, and so does
    the old single-file layout.
    """
    named = os.environ.get("STEWARD_CALENDAR") or os.environ.get("CALENDAR")
    if named:
        if os.path.exists(named):
            return named
        guess = os.path.join(calendar_dir(), f"{named}.yaml")
        if os.path.exists(guess):
            return guess
        log.warning("no calendar called %r; falling back", named)

    for legacy in ("../blueprint/content-calendar.yaml", "blueprint/content-calendar.yaml"):
        if os.path.exists(legacy):
            return legacy

    default = os.path.join(calendar_dir(), "general.yaml")
    if os.path.exists(default):
        return default
    import glob
    found = sorted(glob.glob(os.path.join(calendar_dir(), "*.yaml")))
    found = [f for f in found if not f.endswith(".local.yaml")]
    return found[0] if found else default


CALENDAR = find_calendar()
# Overrides meta.anchor, so the launch date can move without editing the file
# that gets redeployed to the next project.
LAUNCH_DATE = os.environ.get("LAUNCH_DATE") or None
PLAYTEST_ROLE = os.environ.get("PLAYTEST_ROLE", "Ping Me For Playtests")
BUG_FORUM = os.environ.get("BUG_FORUM", "bug-reports")

# The status message identifies itself by its title, so restarts reuse the
# same message instead of stacking up.
STATUS_TITLE = "Ledger"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("steward")


def read_blueprint(path: str) -> dict:
    """The blueprint, so the bot and the server agree on names and rewards.

    Anything filled in on the setup page is laid over the top, from
    variables.local.yaml beside it. Without that the name typed into the page
    never reached the bot and every post said "the game".
    """
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            bp = yaml.safe_load(fh) or {}
        local = os.path.join(os.path.dirname(path) or ".", "variables.local.yaml")
        if os.path.exists(local):
            with open(local, encoding="utf-8") as fh:
                filled = yaml.safe_load(fh) or {}
            bp["variables"] = {**(bp.get("variables") or {}),
                               **{k: v for k, v in filled.items()
                                  if v not in (None, "")}}
        return bp
    except FileNotFoundError:
        log.warning("no blueprint at %s; levels and attribution roles are off", path)
    except Exception as e:                                   # noqa: BLE001
        log.warning("could not read %s (%s)", path, e)
    return {}


def ephemeral_roles(path: str) -> dict[str, str]:
    """Roles the blueprint marks `ephemeral: true`, mapped to the answer they
    stand for.

    Discord will not accept an onboarding answer that grants neither a role nor
    a channel, so "How did you find us?" has to hand out a role. These are the
    ones it hands out, and they are meant to be taken straight back off: the
    answer belongs in the ledger, not on somebody's profile.
    """
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            bp = yaml.safe_load(fh)
    except FileNotFoundError:
        log.warning("no blueprint at %s, so attribution roles will not be stripped", path)
        return {}
    except Exception as e:                                   # noqa: BLE001
        log.warning("could not read %s (%s); attribution roles will not be stripped",
                    path, e)
        return {}

    out = {}
    for r in bp.get("roles", []):
        if r.get("ephemeral"):
            name = r["name"]
            # "Found via a Creator" -> "a Creator"
            out[name] = name.split("Found via ", 1)[-1]
    return out


# GUILDS for structure, MEMBERS for joins and leaves and onboarding flags,
# VOICE_STATES for voice. MEMBERS is privileged: toggle it in the Developer
# Portal. Under 10,000 users that is a toggle, not an application.
intents = discord.Intents.none()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = False


def calendar_mtimes() -> tuple:
    """When the calendar and its overrides were last written, so a change can
    be noticed without watching the filesystem."""
    import calendar_engine
    out = []
    for f in (CALENDAR, str(calendar_engine.overrides_path(CALENDAR))):
        try:
            out.append(os.path.getmtime(f))
        except OSError:
            out.append(0.0)
    return tuple(out)


def load_calendar(path: str, blueprint: dict):
    """The content calendar, filled in with the blueprint's own variables so
    one calendar file serves any game without its prose being edited."""
    variables = {k: (v if v is not None else "")
                 for k, v in (blueprint.get("variables") or {}).items()}
    try:
        cal = calendar_engine.load(path, variables, anchor_override=LAUNCH_DATE)
    except FileNotFoundError:
        log.info("no content calendar at %s; the calendar engine is off", path)
        return calendar_engine.Calendar()
    except Exception as e:                                   # noqa: BLE001
        log.warning("could not read %s (%s); the calendar engine is off", path, e)
        return calendar_engine.Calendar()

    report = cal.validate()
    for problem in report["errors"]:
        log.warning("calendar: %s", problem)
    if report["errors"]:
        log.warning("calendar has errors and will not run until they are fixed")
        return calendar_engine.Calendar()
    if not cal.anchor:
        log.info("calendar loaded but no launch date is set, so nothing will fire. "
                 "Set meta.anchor in %s or LAUNCH_DATE in the environment.", path)
    else:
        log.info("calendar: %d posts and %d recurring, launch %s",
                 report["posts"], report["recurring"], report["anchor"])
    return cal


class PostApproval(discord.ui.View):
    """Approve or skip a drafted post.

    The custom ids are fixed rather than carrying the post in them, because a
    custom id caps at 100 characters and a post id is written by whoever edits
    the calendar. The message id is the key instead, and it is already stored.
    """

    def __init__(self):
        super().__init__(timeout=None)

    async def _decide(self, interaction: discord.Interaction, approve: bool):
        client = interaction.client
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Only someone who can manage the server can decide this.",
                ephemeral=True)
            return
        run = client.ledger.calendar_by_draft(interaction.guild.id,
                                              interaction.message.id)
        if not run or run["status"] != "drafted":
            await interaction.response.send_message(
                "That post has already been decided.", ephemeral=True)
            return

        await interaction.response.defer()
        if approve:
            await client.publish_post(interaction, run)
        else:
            client.ledger.calendar_decide(interaction.guild.id, run["post_id"],
                                          run["fire_date"], "skipped",
                                          interaction.user.id)
            await client.close_draft(interaction.message,
                                     f"Skipped by {interaction.user.mention}.",
                                     discord.Color.dark_grey())

    @discord.ui.button(label="Approve and post", custom_id="cal:approve",
                       style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button):
        await self._decide(interaction, True)

    @discord.ui.button(label="Skip", custom_id="cal:skip",
                       style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button):
        await self._decide(interaction, False)


class Steward(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.ledger = Ledger(DB_PATH)
        self.ephemeral = ephemeral_roles(BLUEPRINT)
        self.blueprint = read_blueprint(BLUEPRINT)
        self.levels = Levels(self.ledger, self.blueprint.get("levels") or {})
        self.calendar = load_calendar(CALENDAR, self.blueprint)
        self.calendar_stamp = calendar_mtimes()
        self.started_at = int(time.time())
        # user id -> when they joined voice, for paying out on leave
        self.voice_since: dict[int, int] = {}
        # Serialises status updates, which two callers reach at once on startup.
        self.status_lock = asyncio.Lock()

    async def absorb_attribution(self, member: discord.Member) -> bool:
        """Write down how someone said they found us, then take the role back
        off so it never shows on their profile.

        Returns whether anything was removed. Safe to call repeatedly.
        """
        held = [r for r in member.roles if r.name in self.ephemeral]
        if not held:
            return False

        for role in held:
            source = self.ephemeral[role.name]
            if self.ledger.set_attribution(member.guild.id, member.id, source):
                self.ledger.record(guild_id=member.guild.id, user_id=member.id,
                                   event_type="attribution", source=source)
        try:
            await member.remove_roles(*held, reason="attribution recorded by Steward")
            return True
        except discord.Forbidden:
            # Either the bot lacks Manage Roles, or its own role sits below
            # these. Either way the answer is already saved; say so once
            # rather than every time somebody joins.
            log.warning(
                "recorded attribution for %s but could not remove %s. Give the bot "
                "Manage Roles and drag its role above them, then run /sweep-roles.",
                member.id, ", ".join(r.name for r in held))
        except discord.HTTPException as e:
            log.warning("could not remove attribution roles from %s: %s", member.id, e)
        return False

    def refresh_calendar(self) -> bool:
        """Re-read the calendar if either file has changed on disk.

        The calendar was read once at startup and never again, so an edit made
        in the setup page did not reach a running bot. /calendar-reload fixed
        it, but needing to know that is the bug: the draft showed the old
        wording and would have posted the old wording, with nothing anywhere
        saying the two had diverged.
        """
        now = calendar_mtimes()
        if now == self.calendar_stamp:
            return False
        self.calendar = load_calendar(CALENDAR, self.blueprint)
        self.calendar_stamp = now
        log.info("calendar changed on disk, re-read it")
        return True

    async def setup_hook(self):
        # Deliberately not synced here. on_ready registers the commands with
        # each server directly, which is the only way a change appears at once
        # rather than whenever Discord's cache expires.
        # Registered before anything else so a draft posted last week still has
        # working buttons after a restart.
        self.add_view(PostApproval())
        self.nightly_purge.start()
        self.heartbeat.start()
        self.weekly_digest.start()
        self.calendar_tick.start()
        self.pulse.start()

    async def sync_commands(self, *guilds):
        """Register the commands with each server directly.

        A guild command appears the moment it is written. A global one can sit
        in Discord's cache for an hour, which is why a renamed option kept
        showing its old name and then refused the interaction as outdated.

        The catch, and the reason this is not simply both: a command registered
        globally *and* per guild is listed twice in the picker. So the global
        copies are removed once, and new servers are covered by on_guild_join
        instead.
        """
        for guild in (guilds or self.guilds):
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("%s: commands updated", guild.name)
            except discord.HTTPException as e:
                log.warning("%s: could not update commands: %s", guild.name, e)

        await self.drop_global_commands()

    async def drop_global_commands(self):
        """Remove the global registrations, which would otherwise show up
        alongside the per-guild ones and list every command twice.

        The in-memory tree is put back afterwards, because it is what
        copy_global_to reads when the bot joins a new server later.
        """
        try:
            if not await self.tree.fetch_commands():
                return
            saved = list(self.tree.get_commands())
            self.tree.clear_commands(guild=None)
            await self.tree.sync()                  # an empty set deletes them
            for command in saved:
                self.tree.add_command(command)
            log.info("removed %d duplicate global command(s)", len(saved))
        except discord.HTTPException as e:
            log.warning("could not remove the global commands: %s", e)

    async def on_guild_join(self, guild):
        """A new server needs the commands, and nothing is synced globally."""
        await self.sync_commands(guild)

    # -- backfill ---------------------------------------------------------

    async def on_ready(self):
        log.info("connected as %s (Steward v%s)", self.user, VERSION)
        await self.sync_commands()
        for guild in self.guilds:
            seeded = 0
            async for member in guild.fetch_members(limit=None):
                if member.bot or not member.joined_at:
                    continue
                self.ledger.touch_member(
                    guild.id, member.id, int(member.joined_at.timestamp()))
                if member.flags.completed_onboarding:
                    self.ledger.mark(guild.id, member.id, "onboarding_completed_at",
                                     int(member.joined_at.timestamp()))
                seeded += 1
            log.info("%s: seeded %d members", guild.name, seeded)

            # Anyone who answered while the bot was off is still wearing the
            # role. Record them and clean up, so being offline costs data but
            # never leaves clutter behind.
            if self.ephemeral:
                swept = 0
                for member in guild.members:
                    if not member.bot and await self.absorb_attribution(member):
                        swept += 1
                if swept:
                    log.info("%s: recorded and removed attribution roles from %d members",
                             guild.name, swept)

        counts = self.ledger.counts(self.guilds[0].id) if self.guilds else {}
        log.info("ledger: %s", counts)
        await self.update_status(running=True)
        log.info("status posted in #%s", REPORT_CHANNEL)

    # -- recording --------------------------------------------------------

    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        now = int(message.created_at.timestamp())
        self.ledger.record(
            guild_id=message.guild.id,
            user_id=message.author.id,
            channel_id=message.channel.id,
            event_type="message",
            ts=now,
            attachments=len(message.attachments) or None,
            thread=isinstance(message.channel, discord.Thread) or None,
        )
        self.ledger.mark(message.guild.id, message.author.id, "first_message_at", now)

        result = self.levels.award_message(
            message.guild.id, message.author.id, getattr(message.channel, "name", None))
        if result:
            await self.grant_level_roles(message.author, result["roles_passed"])
            await self.announce_level(message, message.author, result)

    async def on_thread_create(self, thread: discord.Thread):
        # Forum posts arrive here. Bug reports and suggestions are threads, so
        # without this the two channels that matter most look silent.
        if thread.guild is None or thread.owner_id is None:
            return
        parent = thread.parent
        self.ledger.record(
            guild_id=thread.guild.id,
            user_id=thread.owner_id,
            channel_id=thread.parent_id,
            event_type="thread_create",
            ts=int(thread.created_at.timestamp()) if thread.created_at else None,
            forum=isinstance(parent, discord.ForumChannel) or None,
            tags=[t.name for t in getattr(thread, "applied_tags", [])] or None,
        )

    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        now = int(time.time())
        self.ledger.touch_member(member.guild.id, member.id, now)
        self.ledger.record(
            guild_id=member.guild.id, user_id=member.id,
            event_type="join", ts=now,
            account_age_days=(datetime.now(timezone.utc) - member.created_at).days,
        )

    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        now = int(time.time())
        self.ledger.record(guild_id=member.guild.id, user_id=member.id,
                           event_type="leave", ts=now)
        self.ledger.mark(member.guild.id, member.id, "last_left_at", now, first_only=False)

        # Discord fires the same event for leaving and being kicked, so the
        # audit log is the only way to tell them apart.
        record = await modlog.actor_for(member.guild, discord.AuditLogAction.kick,
                                        member.id)
        if record and (now - int(record.created_at.timestamp())) < 10:
            await self.mod_log(member.guild, modlog.entry(
                "kick", "Member kicked",
                [f"**By:** {record.user}",
                 f"**Reason:** {record.reason}" if record.reason else None],
                who=member))

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # There is no onboarding-completed event. The member flag flipping is
        # the only signal, so watch for the transition.
        if after.bot:
            return
        if not before.flags.completed_onboarding and after.flags.completed_onboarding:
            now = int(time.time())
            self.ledger.record(guild_id=after.guild.id, user_id=after.id,
                               event_type="onboarding_complete", ts=now)
            self.ledger.mark(after.guild.id, after.id, "onboarding_completed_at", now)

        # The attribution answer arrives as a role appearing. Write it down and
        # take it straight back off; only compare when something actually
        # changed, since this event also fires for nicknames and avatars.
        roles_changed = {r.id for r in before.roles} != {r.id for r in after.roles}
        if self.ephemeral and roles_changed:
            await self.absorb_attribution(after)

        if roles_changed:
            gained, lost = modlog.describe_roles(before, after)
            # Ignore the attribution roles, which appear and vanish within a
            # second and would otherwise bury the log in noise.
            gained = [r for r in gained if r.name not in self.ephemeral]
            lost = [r for r in lost if r.name not in self.ephemeral]
            if gained or lost:
                record = await modlog.actor_for(
                    after.guild, discord.AuditLogAction.member_role_update, after.id)
                await self.mod_log(after.guild, modlog.entry(
                    "roles", "Roles changed",
                    ["**Added:** " + ", ".join(r.name for r in gained) if gained else None,
                     "**Removed:** " + ", ".join(r.name for r in lost) if lost else None,
                     f"**By:** {record.user}" if record else None],
                    who=after))

        if before.nick != after.nick:
            await self.mod_log(after.guild, modlog.entry(
                "nickname", "Nickname changed",
                [f"**From:** {before.nick or before.name}",
                 f"**To:** {after.nick or after.name}"], who=after))

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                record = await modlog.actor_for(
                    after.guild, discord.AuditLogAction.member_update, after.id)
                until = int(after.timed_out_until.timestamp())
                await self.mod_log(after.guild, modlog.entry(
                    "timeout", "Member timed out",
                    [f"**Until:** <t:{until}:f> (<t:{until}:R>)",
                     f"**By:** {record.user}" if record else None,
                     f"**Reason:** {record.reason}" if record and record.reason else None],
                    who=after))
            else:
                await self.mod_log(after.guild, modlog.entry(
                    "timeout_over", "Timeout lifted", [], who=after))

    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        gid = member.guild.id
        if before.channel is None and after.channel is not None:
            self.ledger.record(guild_id=gid, user_id=member.id,
                               channel_id=after.channel.id, event_type="voice_join")
            self.voice_since[member.id] = int(time.time())
        elif before.channel is not None and after.channel is None:
            self.ledger.record(guild_id=gid, user_id=member.id,
                               channel_id=before.channel.id, event_type="voice_leave")
            # Paid on the way out, so time in an empty channel with a muted mic
            # still counts but cannot be collected repeatedly.
            since = self.voice_since.pop(member.id, None)
            if since:
                result = self.levels.award_voice(gid, member.id, int(time.time()) - since)
                if result:
                    await self.grant_level_roles(member, result["roles_passed"])
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            self.ledger.record(guild_id=gid, user_id=member.id,
                               channel_id=after.channel.id, event_type="voice_move",
                               **{"from": before.channel.id})

    # -- moderation log ---------------------------------------------------

    async def mod_log(self, guild, embed):
        channel = discord.utils.get(guild.text_channels, name=MOD_CHANNEL)
        if channel is None:
            return
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            log.warning("cannot post in #%s; moderation logging is off", MOD_CHANNEL)
        except discord.HTTPException:
            pass

    async def on_member_ban(self, guild, user):
        record = await modlog.actor_for(guild, discord.AuditLogAction.ban, user.id)
        await self.mod_log(guild, modlog.entry(
            "ban", "Member banned",
            [f"**By:** {record.user}" if record else None,
             f"**Reason:** {record.reason}" if record and record.reason else None],
            who=user))

    async def on_member_unban(self, guild, user):
        record = await modlog.actor_for(guild, discord.AuditLogAction.unban, user.id)
        await self.mod_log(guild, modlog.entry(
            "unban", "Member unbanned",
            [f"**By:** {record.user}" if record else None], who=user))

    async def on_guild_channel_create(self, channel):
        record = await modlog.actor_for(channel.guild,
                                        discord.AuditLogAction.channel_create)
        await self.mod_log(channel.guild, modlog.entry(
            "channel", "Channel created",
            [f"**Channel:** #{channel.name}",
             f"**By:** {record.user}" if record else None]))

    async def on_guild_channel_delete(self, channel):
        record = await modlog.actor_for(channel.guild,
                                        discord.AuditLogAction.channel_delete)
        await self.mod_log(channel.guild, modlog.entry(
            "channel", "Channel deleted",
            [f"**Channel:** #{channel.name}",
             f"**By:** {record.user}" if record else None]))

    async def on_guild_role_delete(self, role):
        record = await modlog.actor_for(role.guild, discord.AuditLogAction.role_delete)
        await self.mod_log(role.guild, modlog.entry(
            "role", "Role deleted",
            [f"**Role:** {role.name}", f"**By:** {record.user}" if record else None]))

    async def on_message_delete(self, message):
        # Metadata only. The content is not read, so it cannot be quoted here,
        # which is the deliberate trade for never asking to read messages.
        if message.guild is None or message.author.bot:
            return
        record = await modlog.actor_for(message.guild,
                                        discord.AuditLogAction.message_delete,
                                        message.author.id)
        by = record.user if record else None
        await self.mod_log(message.guild, modlog.entry(
            "message", "Message deleted",
            [f"**In:** #{getattr(message.channel, 'name', 'unknown')}",
             f"**Deleted by:** {by}" if by and by.id != message.author.id
             else "**Deleted by:** the author",
             f"**Attachments:** {len(message.attachments)}" if message.attachments else None,
             "_Content is not recorded, by design._"],
            who=message.author))

    # -- levels -----------------------------------------------------------

    async def grant_level_roles(self, member, names):
        """Give the roles a level unlocked, and take back the tier below it.

        Tiers replace each other; holding ★1 through ★5 at once would be a
        member list full of noise.
        """
        if not names:
            return
        tiers = set(self.levels.rewards.values())
        add = [discord.utils.get(member.guild.roles, name=n) for n in names]
        add = [r for r in add if r and r not in member.roles]
        drop = [r for r in member.roles if r.name in tiers and r not in add]
        try:
            if add:
                await member.add_roles(*add, reason="level reward")
            if drop:
                await member.remove_roles(*drop, reason="replaced by a higher tier")
        except discord.Forbidden:
            log.warning("cannot manage level roles for %s. The bot needs Manage Roles "
                        "and its own role above them.", member.id)
        except discord.HTTPException as e:
            log.warning("could not update level roles: %s", e)

    async def announce_level(self, message, member, result):
        if self.levels.announce == "off":
            return
        if self.levels.only_announce_rewards and not result["roles_passed"]:
            return
        noun = self.levels.noun
        earned = result["roles_passed"]
        text = f"**{member.display_name}** reached {noun} {result['level']}"
        text += f" and unlocked **{earned[-1]}**." if earned else "."
        try:
            if self.levels.announce == "channel" and self.levels.announce_channel:
                ch = discord.utils.get(member.guild.text_channels,
                                       name=self.levels.announce_channel)
                if ch:
                    await ch.send(text, allowed_mentions=discord.AllowedMentions.none())
                    return
            if message is not None:
                # Replying in place rather than announcing to a channel: a
                # level-up firehose is the most irritating thing a bot does.
                await message.reply(text, mention_author=False,
                                    allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    # -- visible proof of life --------------------------------------------

    async def status_channel(self, guild):
        return discord.utils.get(guild.text_channels, name=REPORT_CHANNEL)

    async def find_status_messages(self, channel):
        """Every status message in the channel, newest first.

        Plural because there should be one and occasionally there are two: two
        callers can both look, both find nothing, and both post. The lock below
        prevents that happening again, and returning the whole list lets the
        next run tidy up any that already exist.
        """
        found = []
        try:
            async for m in channel.history(limit=50):
                if m.author.id == self.user.id and m.embeds:
                    if (m.embeds[0].title or "").startswith(STATUS_TITLE):
                        found.append(m)
        except discord.HTTPException:
            pass
        return found

    def status_embed(self, guild, running=True):
        c = self.ledger.counts(guild.id)
        now = int(time.time())
        e = discord.Embed(
            title=f"{STATUS_TITLE} {'recording' if running else 'stopped'}",
            colour=0x23A55A if running else 0xF23F42)
        if running:
            e.description = (
                f"Started <t:{self.started_at}:R>.\n"
                f"Last checked in <t:{now}:R>. If that stops moving, so has the bot.")
        else:
            e.description = (
                f"Stopped <t:{now}:R>. **Nothing is being recorded.**\n"
                "Discord cannot hand back activity from a period when nothing was "
                "listening, so anything that happens now is lost for good.\n"
                "Run START-LEDGER.bat to pick it back up.")
        e.add_field(name="Events recorded", value=f"{c['events']:,}")
        e.add_field(name="Members tracked", value=f"{c['members']:,}")
        if c["since"]:
            e.add_field(name="Recording since", value=f"<t:{c['since']}:D>")
        e.set_footer(text=f"v{VERSION} · Only who posted where and when. "
                          f"Never what was said.")
        return e

    async def update_status(self, running=True):
        # on_ready and the heartbeat's first tick land at almost the same
        # moment. Without this both look, both find nothing, and both post.
        async with self.status_lock:
            await self._update_status(running)

    async def _update_status(self, running=True):
        for guild in self.guilds:
            channel = await self.status_channel(guild)
            if channel is None:
                continue
            try:
                embed = self.status_embed(guild, running)
                found = await self.find_status_messages(channel)
                if found:
                    await found[0].edit(embed=embed)
                    # Tidy up any duplicates a previous version left behind.
                    for extra in found[1:]:
                        try:
                            await extra.delete()
                            log.info("removed a duplicate status message")
                        except discord.HTTPException:
                            pass
                else:
                    msg = await channel.send(embed=embed)
                    try:
                        await msg.pin(reason="Steward status")
                    except discord.HTTPException:
                        pass
            except discord.Forbidden:
                log.warning("cannot post in #%s. Give the bot access to it, or set "
                            "REPORT_CHANNEL to a channel it can see.", REPORT_CHANNEL)
            except discord.HTTPException as e:
                log.warning("could not update the status message: %s", e)

    def stamp(self, state: str):
        """Leave proof of life in the database itself.

        The setup page has no other way to tell a running ledger from a dead
        one: there is no port to poll and a process id goes stale the moment
        Windows reuses it. A timestamp that stops moving is unambiguous.
        """
        self.ledger.set_meta("ledger_state", state)
        self.ledger.set_meta("ledger_seen_at", int(time.time()))
        self.ledger.set_meta("ledger_pid", os.getpid())

    @tasks.loop(seconds=30)
    async def pulse(self):
        self.stamp("running")

    @pulse.before_loop
    async def _wait_pulse(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=10)
    async def heartbeat(self):
        # The timestamp going stale is the signal that the bot died, which a
        # message posted once at startup could never give you.
        await self.update_status(running=True)

    @heartbeat.before_loop
    async def _wait_heartbeat(self):
        await self.wait_until_ready()

    async def close(self):
        # Say so on the way out, so a deliberate stop does not look like a crash.
        try:
            self.stamp("stopped")
            await self.update_status(running=False)
        except Exception:                                    # noqa: BLE001
            pass
        await super().close()

    # -- weekly digest ----------------------------------------------------

    async def build_digest(self, guild):
        data = digest.build(self.ledger, guild.id)
        w, last = data["week"]["this_week"], data["week"]["last_week"]
        f = data["funnel"]
        joined = f["joined"] or 0
        pct = lambda n: f"{n / joined * 100:.0f}%" if joined else "n/a"

        e = discord.Embed(
            title="This week",
            colour=0xC9A227,
            description="\n".join([
                f"**{w['joined']}** joined{digest.delta(w['joined'], last['joined'])}",
                f"**{w['posted']}** people posted"
                f"{digest.delta(w['posted'], last['posted'])}",
                f"**{w['messages']:,}** messages"
                f"{digest.delta(w['messages'], last['messages'])}",
            ]))

        e.add_field(
            name="Of this week's arrivals",
            value=("\n".join([
                f"{f['onboarded']} finished the questions ({pct(f['onboarded'])})",
                f"{f['posted']} posted at least once ({pct(f['posted'])})",
                f"{f['left_server']} already left ({pct(f['left_server'])})"])
                if joined else "Nobody joined this week."), inline=False)

        kept = [c for c in data["cohorts"] if c["rate"] is not None]
        if kept:
            e.add_field(
                name="Did earlier arrivals come back",
                value="\n".join(
                    f"{c['week']} week{'s' if c['week'] != 1 else ''} ago: "
                    f"**{c['retained']}/{c['joined']}** ({c['rate'] * 100:.0f}%)"
                    for c in kept[-4:]), inline=False)

        if data["attribution"]:
            total = sum(data["attribution"].values())
            e.add_field(
                name="How they found you",
                value="\n".join(f"{k}: **{v}** ({v / total * 100:.0f}%)"
                                for k, v in data["attribution"].items()), inline=False)

        if data["chart"] is None:
            # Not enough shape to plot yet, so show it in text rather than
            # drawing a line through three points.
            e.add_field(
                name="Last 4 weeks",
                value="\n".join([
                    f"`joins    {digest.spark(data['series']['joins'])}`",
                    f"`posters  {digest.spark(data['series']['posters'])}`"]),
                inline=False)

        report = decay.analyse(self.ledger, guild.id,
                               self.blueprint.get("decay") or {})
        lines = decay.summarise(
            report, name_of=lambda cid: (
                guild.get_channel(cid).mention if guild.get_channel(cid)
                else "a deleted channel"))
        if lines:
            e.add_field(name="Channels against their own baseline",
                        value="\n".join(lines)[:1024], inline=False)
        elif not report["ready"]:
            # Say why rather than leaving a heading out with no explanation.
            e.add_field(name="Channels against their own baseline",
                        value=f"Not yet. {report['why']}", inline=False)

        e.set_footer(text=f"{data['counts']['events']:,} events recorded")
        return e, data["chart"]

    async def post_digest(self, guild):
        channel = discord.utils.get(guild.text_channels, name=REPORT_CHANNEL)
        if channel is None:
            return False
        embed, chart = await self.build_digest(guild)
        files = [discord.File(chart, filename="week.png")] if chart else []
        if chart:
            embed.set_image(url="attachment://week.png")
        try:
            await channel.send(embed=embed, files=files,
                               allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException as e:
            log.warning("could not post the digest: %s", e)
            return False

    @tasks.loop(hours=6)
    async def weekly_digest(self):
        # Checked against a stored timestamp rather than a weekday, so a
        # restart never double-posts and a bot that was off for a fortnight
        # still catches up exactly once.
        last = int(self.ledger.get_meta("last_digest_at", 0) or 0)
        if int(time.time()) - last < 7 * 86400:
            return

        # On a brand new ledger there is nothing to report yet, so start the
        # clock instead of posting an empty week. Use /digest to see one now.
        if not last and self.guilds:
            if self.ledger.counts(self.guilds[0].id)["events"] < 20:
                self.ledger.set_meta("last_digest_at", int(time.time()))
                log.info("first run: digest clock started, first report in a week")
                return
        for guild in self.guilds:
            if await self.post_digest(guild):
                log.info("weekly digest posted in %s", guild.name)
        self.ledger.set_meta("last_digest_at", int(time.time()))

    @weekly_digest.before_loop
    async def _wait_digest(self):
        await self.wait_until_ready()

    # -- the calendar -----------------------------------------------------

    def post_embed(self, post: dict, when, colour=None) -> discord.Embed:
        t = self.calendar.t_minus(when)
        stamp = when.isoformat() + (f"  (T{t:+d})" if t is not None else "")
        e = discord.Embed(
            title=post.get("title") or post.get("id"),
            description=post.get("body", "")[:4000],
            colour=colour or discord.Color.blurple())
        e.set_footer(text=f"{post.get('id')} · {stamp}")
        return e

    async def draft_post(self, guild, occ) -> bool:
        """Put a post in front of a human. Nothing reaches members from here."""
        post = occ.post
        staff = discord.utils.get(guild.text_channels, name=REPORT_CHANNEL)
        if staff is None:
            log.warning("calendar: no #%s to draft %s into", REPORT_CHANNEL, occ.id)
            return False

        target_name = post.get("channel")
        target = discord.utils.get(guild.text_channels, name=target_name) \
            or discord.utils.get(guild.forums, name=target_name)

        # Reminders are the post. They are for staff, they name a deadline or a
        # task, and holding one for approval would mean approving your own
        # to-do list.
        if post.get("kind") == "reminder":
            if not self.ledger.calendar_record(guild.id, occ.id, occ.date.isoformat(),
                                               "published"):
                return False
            e = self.post_embed(post, occ.date, discord.Color.dark_gold())
            e.title = f"Reminder: {e.title}"
            await staff.send(embed=e,
                             allowed_mentions=discord.AllowedMentions.none())
            log.info("calendar: reminder %s posted", occ.id)
            return True

        if target is None:
            self.ledger.calendar_record(
                guild.id, occ.id, occ.date.isoformat(), "failed",
                note=f"no channel #{target_name}")
            log.warning("calendar: %s wants #%s, which does not exist", occ.id,
                        target_name)
            return False

        e = self.post_embed(post, occ.date)
        mention = post.get("mention")
        lines = [f"Due today, for **#{target_name}**."]
        if mention:
            lines.append(f"It mentions **@{mention}**, so approving it pings people.")
        if post.get("event"):
            lines.append(f"It also creates the scheduled event "
                         f"**{post['event'].get('name')}**.")

        # Claim it before posting. If the send fails the row still exists and
        # the post is not retried forever against a channel that will not take it.
        if not self.ledger.calendar_record(guild.id, occ.id, occ.date.isoformat(),
                                           "drafted"):
            return False
        try:
            msg = await staff.send(
                content="\n".join(lines), embed=e, view=PostApproval(),
                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as ex:
            self.ledger.calendar_decide(guild.id, occ.id, occ.date.isoformat(),
                                        "failed", None, note=str(ex)[:200])
            log.warning("calendar: could not draft %s: %s", occ.id, ex)
            return False
        self.ledger.db.execute(
            "UPDATE calendar_runs SET draft_id = ? WHERE guild_id = ? "
            "AND post_id = ? AND fire_date = ?",
            (msg.id, guild.id, occ.id, occ.date.isoformat()))
        self.ledger.db.commit()
        log.info("calendar: drafted %s for #%s", occ.id, target_name)
        return True

    def find_post(self, post_id: str, fire_date: str):
        # Re-read first. Approving a draft has to post what the calendar says
        # now, and the draft in front of somebody may be hours old.
        """Re-read the post off the calendar at approval time rather than
        storing a copy, so fixing a typo in the file fixes the pending draft.

        Looked up by id, not by what happens to fall on that date. Asking the
        schedule what is due on the draft's date fails for anything drafted out
        of season with /calendar-run, which is the only way to look at a T-140
        post in August, so every test draft could be posted and never approved.
        """
        self.refresh_calendar()
        from datetime import date as _date
        y, m, d = (int(x) for x in fire_date.split("-"))
        return self.calendar.find(post_id, _date(y, m, d))

    async def close_draft(self, message, note: str, colour):
        """Retire an approval message so it cannot be clicked twice."""
        try:
            embed = message.embeds[0] if message.embeds else discord.Embed()
            embed.colour = colour
            await message.edit(content=note, embed=embed, view=None,
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    async def publish_post(self, interaction, run: dict):
        guild = interaction.guild
        occ = self.find_post(run["post_id"], run["fire_date"])
        if occ is None:
            self.ledger.calendar_decide(guild.id, run["post_id"], run["fire_date"],
                                        "failed", interaction.user.id,
                                        note="post is no longer in the calendar")
            await self.close_draft(interaction.message,
                                   "That post is no longer in the calendar file.",
                                   discord.Color.dark_red())
            return

        post = occ.post
        name = post.get("channel")
        channel = discord.utils.get(guild.text_channels, name=name) \
            or discord.utils.get(guild.forums, name=name)
        if channel is None:
            self.ledger.calendar_decide(guild.id, run["post_id"], run["fire_date"],
                                        "failed", interaction.user.id,
                                        note=f"no channel #{name}")
            await self.close_draft(interaction.message,
                                   f"There is no #{name} to post in.",
                                   discord.Color.dark_red())
            return

        content, allowed = self.mention_for(guild, post.get("mention"))
        body = post.get("body", "")
        title = post.get("title")

        try:
            if isinstance(channel, discord.ForumChannel):
                thread = await channel.create_thread(
                    name=(title or post.get("id"))[:100], content=body[:2000],
                    allowed_mentions=allowed)
                posted = thread.message
            else:
                text = "\n".join(x for x in (content, f"## {title}" if title else "",
                                             body) if x)
                posted = await channel.send(text[:2000], allowed_mentions=allowed)
                # Announcement channels can be followed by other servers, which
                # is free reach and the reason #devlog is one. Publishing is
                # capped at 10 an hour, so a failure here is not fatal.
                if channel.is_news():
                    try:
                        await posted.publish()
                    except discord.HTTPException as ex:
                        log.info("calendar: %s posted but not published: %s",
                                 occ.id, ex)
        except discord.HTTPException as ex:
            self.ledger.calendar_decide(guild.id, run["post_id"], run["fire_date"],
                                        "failed", interaction.user.id,
                                        note=str(ex)[:200])
            await self.close_draft(interaction.message,
                                   f"Discord refused it: {ex}", discord.Color.dark_red())
            return

        event_note = await self.make_event(guild, post, occ.date)
        self.ledger.calendar_decide(guild.id, run["post_id"], run["fire_date"],
                                    "published", interaction.user.id,
                                    published_id=posted.id)
        self.ledger.record(guild_id=guild.id, user_id=interaction.user.id,
                           event_type="calendar_published", post=occ.id)
        await self.close_draft(
            interaction.message,
            f"Posted in {channel.mention} by {interaction.user.mention}.{event_note}",
            discord.Color.green())
        log.info("calendar: %s published in #%s", occ.id, name)

    def mention_for(self, guild, mention):
        """A role ping, or nothing. Never a DM: Discord's Developer Policy
        prohibits unsolicited direct messages outright, so every proactive
        reach in this bot goes through a role somebody opted into."""
        if not mention:
            return "", discord.AllowedMentions.none()
        if mention == "everyone":
            return "@everyone", discord.AllowedMentions(everyone=True)
        role = discord.utils.get(guild.roles, name=mention)
        if role is None:
            log.warning("calendar: no @%s role, posting without the mention", mention)
            return "", discord.AllowedMentions.none()
        return role.mention, discord.AllowedMentions(roles=[role])

    async def make_event(self, guild, post: dict, when) -> str:
        spec = post.get("event")
        if not spec:
            return ""
        # Discord caps a server at 100 scheduled events. Worth checking rather
        # than letting the create fail with a bare 400.
        try:
            if len(await guild.fetch_scheduled_events()) >= 100:
                return " (no room for the event: this server is at Discord's 100 limit)"
        except discord.HTTPException:
            pass

        hh, mm = (spec.get("starts") or "18:00").split(":")[:2]
        start = datetime(when.year, when.month, when.day, int(hh), int(mm),
                         tzinfo=timezone.utc)
        if start < datetime.now(timezone.utc):
            start = datetime.now(timezone.utc) + timedelta(minutes=10)
        end = start + timedelta(minutes=int(spec.get("minutes", 60)))
        where = spec.get("location")
        voice = discord.utils.get(guild.voice_channels, name=where) if where else None
        try:
            if voice is not None:
                await guild.create_scheduled_event(
                    name=spec["name"][:100], start_time=start, end_time=end,
                    channel=voice, description=(spec.get("description") or "")[:1000])
            else:
                await guild.create_scheduled_event(
                    name=spec["name"][:100], start_time=start, end_time=end,
                    entity_type=discord.EntityType.external,
                    location=where or "Online",
                    description=(spec.get("description") or "")[:1000],
                    privacy_level=discord.PrivacyLevel.guild_only)
            return f" Scheduled event **{spec['name']}** created."
        except discord.HTTPException as ex:
            log.warning("calendar: could not create the event for %s: %s",
                        post.get("id"), ex)
            return f" The event could not be created: {ex}"

    @tasks.loop(hours=1)
    async def calendar_tick(self):
        self.refresh_calendar()
        if not self.calendar.anchor and not self.calendar.recurring:
            return
        # The calendar's own clock. post_hour: 17 should mean five in the
        # afternoon where the person who wrote it lives, not 17:00 UTC.
        now = self.calendar.now()
        if now.hour < self.calendar.post_hour:
            return
        today = now.date()
        for guild in self.guilds:
            for occ in self.calendar.due(today):
                if self.ledger.calendar_seen(guild.id, occ.id, occ.date.isoformat()):
                    continue
                try:
                    await self.draft_post(guild, occ)
                except Exception as e:                       # noqa: BLE001
                    log.warning("calendar: %s failed: %s", occ.id, e)

    @calendar_tick.before_loop
    async def _wait_calendar(self):
        await self.wait_until_ready()

    # -- retention --------------------------------------------------------

    @tasks.loop(hours=24)
    async def nightly_purge(self):
        removed = self.ledger.purge_older_than(RETENTION_DAYS)
        if removed:
            log.info("retention: removed %d events older than %d days",
                     removed, RETENTION_DAYS)

    @nightly_purge.before_loop
    async def _wait(self):
        await self.wait_until_ready()


client = Steward()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

@client.tree.command(name="my-data",
                     description="See exactly what this server's bot has recorded about you.")
async def my_data(interaction: discord.Interaction):
    s = client.ledger.summary_for(interaction.user.id)
    if s["opted_out"]:
        await interaction.response.send_message(
            "You have opted out. Nothing is being recorded about you. "
            "Use `/remember-me` if you change your mind.", ephemeral=True)
        return
    if not s["total"]:
        await interaction.response.send_message("Nothing recorded yet.", ephemeral=True)
        return

    lines = [
        "**What is stored about you**",
        "Message *metadata* only: which channel, and when. Not what you wrote.",
        "",
        f"Events: **{s['total']}**",
        f"First: <t:{s['first']}:D>   Most recent: <t:{s['last']}:R>",
        "",
        *[f"- {k}: {v}" for k, v in s["by_type"].items()],
        "",
        f"Retained for {RETENTION_DAYS} days, then deleted automatically.",
        "Use `/forget-me` to erase all of it now and stop future recording.",
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@client.tree.command(name="forget-me",
                     description="Erase everything recorded about you and stop future recording.")
@app_commands.describe(confirm="Type DELETE to confirm. This cannot be undone.")
async def forget_me(interaction: discord.Interaction, confirm: str):
    if confirm.strip().upper() != "DELETE":
        await interaction.response.send_message(
            "Not deleted. Run it again with `confirm: DELETE` if you meant to.",
            ephemeral=True)
        return
    removed = client.ledger.forget(interaction.user.id)
    await interaction.response.send_message(
        f"Deleted {removed['events']} events and your membership record. "
        "Nothing further will be recorded about you unless you run `/remember-me`.",
        ephemeral=True)
    log.info("forget-me honoured for %s", interaction.user.id)


@client.tree.command(name="remember-me",
                     description="Opt back in to activity recording.")
async def remember_me(interaction: discord.Interaction):
    changed = client.ledger.unforget(interaction.user.id)
    await interaction.response.send_message(
        "Recording resumed. Nothing previously deleted was restored."
        if changed else "You were not opted out.", ephemeral=True)
@app_commands.guild_only()
@client.tree.command(name="ledger-status",
                     description="Ledger health. Staff only.")
async def ledger_status(interaction: discord.Interaction):
    perms = interaction.user.guild_permissions if interaction.guild else None
    if not perms or not perms.manage_guild:
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    c = client.ledger.counts(interaction.guild_id)
    f = client.ledger.funnel(interaction.guild_id, cohort_days=7)
    joined = f["joined"] or 0
    pct = lambda n: f"{(n / joined * 100):.0f}%" if joined else "n/a"

    attribution = client.ledger.attribution_counts(interaction.guild_id)

    lines = [
        "**Ledger**",
        f"{c['events']} events since " + (f"<t:{c['since']}:D>" if c["since"] else "never"),
        f"{c['members']} members tracked, {c['opt_outs']} opted out, "
        f"{c['db_bytes'] / 1024:.0f} KB on disk",
        "",
        "**Last 7 days of joins**",
        f"joined: {joined}",
        f"completed onboarding: {f['onboarded']} ({pct(f['onboarded'])})",
        f"posted at least once: {f['posted']} ({pct(f['posted'])})",
        f"already left: {f['left_server']} ({pct(f['left_server'])})",
    ]
    if attribution:
        total = sum(attribution.values())
        lines += ["", "**How they found you** (all time)"]
        lines += [f"{k}: {v} ({v / total * 100:.0f}%)" for k, v in attribution.items()]
    lines += ["", *[f"- {k}: {v}" for k, v in c["by_type"].items()]]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)
@app_commands.guild_only()
@client.tree.command(name="rank", description="See your level and how far into the next one you are.")
@app_commands.describe(member="Whose rank to look up. Yours if left blank.")
async def rank(interaction: discord.Interaction, member: discord.Member | None = None):
    if not client.levels.enabled:
        await interaction.response.send_message("Levels are switched off here.",
                                                ephemeral=True)
        return
    who = member or interaction.user
    r = client.levels.rank(interaction.guild_id, who.id)
    noun = client.levels.noun

    if not r["xp"]:
        await interaction.response.send_message(
            f"{who.display_name} has not earned any {noun.lower()}s yet."
            if member else f"You have not earned any {noun.lower()}s yet. Post something.",
            ephemeral=True)
        return

    e = discord.Embed(title=f"{who.display_name}", colour=who.colour or discord.Colour.default())
    e.add_field(name=noun, value=str(r["level"]))
    e.add_field(name="Rank", value=f"#{r['rank']} of {r['total_ranked']}")
    e.add_field(name="Total XP", value=f"{r['xp']:,}")
    e.add_field(
        name=f"Progress to {noun} {r['level'] + 1}",
        value=f"`{client.levels.bar(r['into'], r['needed'])}`  "
              f"{r['into']:,} / {r['needed']:,}",
        inline=False)
    if r["voice_seconds"] >= 3600:
        e.add_field(name="In voice", value=f"{r['voice_seconds'] // 3600} hours",
                    inline=False)
    e.set_thumbnail(url=who.display_avatar.url)
    await interaction.response.send_message(embed=e)
@app_commands.guild_only()
@client.tree.command(name="leaderboard", description="The top of the server by level.")
@app_commands.describe(page="Which page, ten at a time.")
async def leaderboard(interaction: discord.Interaction, page: int = 1):
    if not client.levels.enabled:
        await interaction.response.send_message("Levels are switched off here.",
                                                ephemeral=True)
        return
    page = max(1, page)
    rows = client.levels.board(interaction.guild_id, limit=10, offset=(page - 1) * 10)
    if not rows:
        await interaction.response.send_message(
            "Nobody has earned anything yet." if page == 1 else "No such page.",
            ephemeral=True)
        return

    noun = client.levels.noun
    lines = []
    for row in rows:
        member = interaction.guild.get_member(row["user_id"])
        # Somebody who has left still holds their place; showing the raw id
        # would be worse than saying so.
        name = member.display_name if member else "(left the server)"
        lines.append(f"`{row['position']:>2}.` **{name}** — {noun} {row['level']} "
                     f"({row['xp']:,} XP)")

    total = client.ledger.ranked_count(interaction.guild_id)
    e = discord.Embed(title="Leaderboard", description="\n".join(lines),
                      colour=0xC9A227)
    e.set_footer(text=f"Page {page} of {max(1, (total + 9) // 10)}  ·  {total} ranked")
    await interaction.response.send_message(embed=e)
@app_commands.guild_only()
@client.tree.command(name="digest", description="Post this week's numbers now. Staff only.")
async def digest_now(interaction: discord.Interaction):
    perms = interaction.user.guild_permissions if interaction.guild else None
    if not perms or not perms.manage_guild:
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    ok = await client.post_digest(interaction.guild)
    await interaction.followup.send(
        f"Posted in #{REPORT_CHANNEL}." if ok
        else f"Could not post. Is there a #{REPORT_CHANNEL} the bot can write to?",
        ephemeral=True)
@app_commands.guild_only()
@client.tree.command(name="sweep-roles",
                     description="Record and remove any leftover attribution roles. Staff only.")
async def sweep_roles(interaction: discord.Interaction):
    perms = interaction.user.guild_permissions if interaction.guild else None
    if not perms or not perms.manage_guild:
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    if not client.ephemeral:
        await interaction.response.send_message(
            "No roles are marked ephemeral in the blueprint, so there is nothing to sweep.",
            ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    swept = 0
    for member in interaction.guild.members:
        if not member.bot and await client.absorb_attribution(member):
            swept += 1
    await interaction.followup.send(
        f"Recorded and cleaned up {swept} member(s)." if swept
        else "Nothing to clean up. Every answer is already recorded.", ephemeral=True)


# --------------------------------------------------------------------------
# The calendar
# --------------------------------------------------------------------------

def blueprint_channels(bp: dict) -> list[str]:
    """Every channel name the blueprint declares. They live one level down
    inside `categories`, not at the top."""
    return [c["name"] for cat in (bp.get("categories") or [])
            for c in (cat.get("channels") or []) if c.get("name")]


def staff_only(interaction) -> bool:
    perms = interaction.user.guild_permissions if interaction.guild else None
    return bool(perms and perms.manage_guild)


@app_commands.guild_only()
@client.tree.command(name="calendar",
                     description="What the content calendar has coming. Staff only.")
@app_commands.describe(days="How far ahead to look. Default 60.")
async def calendar_cmd(interaction: discord.Interaction, days: int = 60):
    client.refresh_calendar()
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    cal = client.calendar
    today = cal.now().date()
    if not cal.posts and not cal.recurring:
        await interaction.response.send_message(
            f"No content calendar loaded. Steward looked in `{CALENDAR}`.",
            ephemeral=True)
        return

    lines = [f"**{cal.name}**"]
    if cal.anchor:
        t = cal.t_minus(today)
        lines.append(f"Launch {cal.anchor.isoformat()}, which is T{t:+d} today.")
    else:
        lines.append("**No launch date set, so nothing will fire.** Set "
                     "`meta.anchor` in the calendar file, or `LAUNCH_DATE` in "
                     "steward\\.env.")

    pending = client.ledger.calendar_pending(interaction.guild_id)
    if pending:
        lines += ["", f"**Waiting on you: {len(pending)}**"]
        lines += [f"- `{p['post_id']}` drafted {p['fire_date']}" for p in pending[:8]]

    upcoming = cal.upcoming(today, max(1, min(days, 400)))
    lines += ["", f"**Next {len(upcoming)} in {days} days**"]
    if not upcoming:
        lines.append("Nothing scheduled in that window.")
    for occ in upcoming[:20]:
        t = cal.t_minus(occ.date)
        tag = "reminder" if occ.post.get("kind") == "reminder" else \
            f"#{occ.post.get('channel')}"
        stamp = f"T{t:+d}" if t is not None else occ.date.isoformat()
        lines.append(f"- `{occ.date.isoformat()}` ({stamp}) **{occ.id}** into {tag}")
    if len(upcoming) > 20:
        lines.append(f"...and {len(upcoming) - 20} more.")

    await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="calendar-run",
                     description="Draft a post right now instead of waiting. Staff only.")
@app_commands.describe(
    post="Which post to draft now. Leave blank to run everything due today.")
async def calendar_run(interaction: discord.Interaction, post: str | None = None):
    client.refresh_calendar()
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    today = client.calendar.now().date()

    if post:
        occ = client.calendar.find(post, today)
        if occ is None:
            ids = ", ".join(f"`{i}`" for i in client.calendar.ids()[:25])
            await interaction.followup.send(
                f"No post called `{post}`.\n\nThere is: {ids}", ephemeral=True)
            return
        # Naming a post is an explicit request for it, so any record of it
        # having gone out today is cleared first. The per-day memory exists to
        # stop the hourly tick repeating itself, not to stop a person asking
        # twice, and refusing the second ask made testing an edit impossible.
        seen = client.ledger.calendar_seen(interaction.guild_id, occ.id,
                                           today.isoformat())
        again = ""
        if seen:
            client.ledger.calendar_forget(interaction.guild_id, occ.id,
                                          today.isoformat())
            again = (f" It had already been {seen['status']} today; that record "
                     f"was cleared so you could look at it again.")
        ok = await client.draft_post(interaction.guild, occ)
        await interaction.followup.send(
            f"Drafted `{post}` into #{REPORT_CHANNEL}. Approve or skip it there."
            + again
            if ok else f"Could not draft `{post}`. Check the console for why.",
            ephemeral=True)
        return

    # The hourly tick refuses to run before post_hour, on purpose. This is the
    # override, because otherwise the only way to see any of this work is to
    # wait until late afternoon on a day something happens to be due.
    due = client.calendar.due(today)
    fresh = [o for o in due
             if not client.ledger.calendar_seen(interaction.guild_id, o.id,
                                                o.date.isoformat())]
    for occ in fresh:
        await client.draft_post(interaction.guild, occ)
    await interaction.followup.send(
        f"{len(due)} post(s) due in the last week, {len(fresh)} not yet handled. "
        f"Drafted those into #{REPORT_CHANNEL}."
        if fresh else
        f"{len(due)} post(s) due in the last week and all of them are already "
        f"handled. Use `/calendar` to see what is coming, or name a post to "
        f"draft one now for a look.", ephemeral=True)


@calendar_run.autocomplete("post")
async def _post_choices(interaction: discord.Interaction, current: str):
    out = [i for i in client.calendar.ids() if current.lower() in i.lower()]
    return [app_commands.Choice(name=i, value=i) for i in out[:25]]


@app_commands.guild_only()
@client.tree.command(name="calendar-reload",
                     description="Re-read the calendar file after editing it. Staff only.")
async def calendar_reload(interaction: discord.Interaction):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    client.calendar = load_calendar(CALENDAR, client.blueprint)
    report = client.calendar.validate(
        channels=blueprint_channels(client.blueprint),
        roles=[r["name"] for r in (client.blueprint.get("roles") or [])])
    lines = [f"Reloaded `{CALENDAR}`: {report['posts']} posts, "
             f"{report['recurring']} recurring."]
    for e in report["errors"][:6]:
        lines.append(f"ERROR  {e}")
    for w in report["warnings"][:6]:
        lines.append(f"warn   {w}")
    await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="decay",
                     description="Which channels are going quiet. Staff only.")
async def decay_cmd(interaction: discord.Interaction):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    report = decay.analyse(client.ledger, interaction.guild_id,
                           client.blueprint.get("decay") or {})
    if not report["ready"]:
        await interaction.followup.send(
            f"**Not enough history yet.**\n{report['why']}\n\n"
            f"There will be something here on "
            f"<t:{int(time.time()) + (report['need_days'] - report['have_days']) * 86400}:D>.",
            ephemeral=True)
        return

    lines = decay.summarise(
        report, name_of=lambda cid: (
            interaction.guild.get_channel(cid).mention
            if interaction.guild.get_channel(cid) else "a deleted channel"))
    w = report["window"]
    head = (f"Last **{w['recent_days']} days** against the **{w['baseline_days']} "
            f"days** before them, across {report['watched']} channel(s) busy "
            f"enough to measure.")
    await interaction.followup.send(
        head + "\n\n" + ("\n".join(lines) if lines else "Nothing has moved much."),
        ephemeral=True)


# --------------------------------------------------------------------------
# The playtest pipeline
# --------------------------------------------------------------------------

@app_commands.guild_only()
@client.tree.command(name="playtest-join",
                     description="Put your name down for playtests.")
async def playtest_join(interaction: discord.Interaction):
    role = discord.utils.get(interaction.guild.roles, name=PLAYTEST_ROLE)
    fresh = client.ledger.playtest_signup(interaction.guild_id, interaction.user.id)
    client.ledger.record(guild_id=interaction.guild_id, user_id=interaction.user.id,
                         event_type="playtest_signup")

    note = ""
    if role is not None:
        try:
            await interaction.user.add_roles(role, reason="playtest signup")
        except discord.Forbidden:
            note = (f"\n\nI could not give you **{PLAYTEST_ROLE}**; ask a "
                    f"moderator to move my role above it. You are still on the list.")
    else:
        note = (f"\n\nThere is no **{PLAYTEST_ROLE}** role in this server, so you "
                f"will not be pinged. You are on the list either way.")

    await interaction.response.send_message(
        ("You are on the playtest list." if fresh else "You are back on the list.")
        + f" Announcements go to **@{PLAYTEST_ROLE}**, never to your DMs. "
          f"Use `/playtest-leave` any time." + note, ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-leave",
                     description="Take your name off the playtest list.")
async def playtest_leave(interaction: discord.Interaction):
    client.ledger.playtest_leave(interaction.guild_id, interaction.user.id)
    role = discord.utils.get(interaction.guild.roles, name=PLAYTEST_ROLE)
    if role is not None and role in interaction.user.roles:
        try:
            await interaction.user.remove_roles(role, reason="playtest opt out")
        except discord.Forbidden:
            pass
    await interaction.response.send_message(
        "Taken off the list. Any key already issued to you still works; ask a "
        "moderator if you want it revoked.", ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-open",
                     description="Open a playtest wave. Staff only.")
@app_commands.describe(name="A short name for the wave, like 'wave-1'.",
                       cap="Most keys to hand out. 0 for no cap.")
async def playtest_open(interaction: discord.Interaction, name: str, cap: int = 0):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    if not client.ledger.wave_open(interaction.guild_id, name, max(0, cap)):
        await interaction.response.send_message(
            f"A wave called `{name}` already exists.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"Wave `{name}` is open. Add keys with `/playtest-keys`, then issue them "
        f"with `/playtest-issue`.\n\n"
        f"Worth knowing before you buy the keys: **Steam caps Release State "
        f"Override keys at 2,500 in total, ever.** Steam's native Playtest "
        f"feature has no practical ceiling, lives on your existing store page, "
        f"and does not cost you the wishlist, so use keys only for press and "
        f"people who need a build outside Steam.", ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-keys",
                     description="Add keys to a wave. Staff only.")
@app_commands.describe(wave="Which wave.",
                       keys="Keys, separated by spaces, commas or new lines.")
async def playtest_keys(interaction: discord.Interaction, wave: str, keys: str):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    if not any(w["name"] == wave for w in client.ledger.waves(interaction.guild_id)):
        await interaction.response.send_message(
            f"No wave called `{wave}`. Open it first with `/playtest-open`.",
            ephemeral=True)
        return

    parts = [k for k in re.split(r"[\s,;]+", keys) if k]
    result = client.ledger.add_keys(interaction.guild_id, wave, parts)
    total = sum(w["keys_total"] for w in client.ledger.waves(interaction.guild_id))
    lines = [f"Added {result['added']} key(s) to `{wave}`."
             + (f" {result['skipped']} were already there." if result["skipped"] else "")]
    if total > 2500:
        lines.append(f"\n**{total} keys stored, which is past Steam's 2,500 "
                     f"lifetime ceiling for override keys.** Check where these "
                     f"came from.")
    lines.append(f"\nThe keys are now in `{DB_PATH}`. That file is a secret: it "
                 f"holds live keys and member activity. Do not commit it and do "
                 f"not paste it anywhere, including into an AI assistant.")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-issue",
                     description="Send someone a key. Staff only.")
@app_commands.describe(wave="Which wave.", member="Who to give it to.")
async def playtest_issue(interaction: discord.Interaction, wave: str,
                         member: discord.Member):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    row = client.ledger.issue_key(interaction.guild_id, wave, member.id,
                                  interaction.user.id)
    if row is None:
        await interaction.followup.send(
            f"`{wave}` has no unissued keys left.", ephemeral=True)
        return

    # A DM here is solicited: they signed up, and this is the thing they signed
    # up for. Unsolicited DMs are what the Developer Policy prohibits, which is
    # why nothing else in this bot ever opens one.
    try:
        await member.send(
            f"Your key for the **{wave}** playtest in **{interaction.guild.name}**:\n"
            f"```\n{row['key']}\n```\n"
            f"Redeem it in Steam under Games, then Activate a Product on Steam. "
            f"Report anything broken with `/playtest-report` in the server.")
        sent = "sent by DM"
    except discord.Forbidden:
        client.ledger.return_key(interaction.guild_id, member.id, wave)
        await interaction.followup.send(
            f"{member.mention} has DMs closed, so the key was put back in the "
            f"pool rather than posted where everyone can see it. Ask them to "
            f"allow DMs from server members and try again.", ephemeral=True)
        return

    client.ledger.record(guild_id=interaction.guild_id, user_id=member.id,
                         event_type="playtest_key_issued", wave=wave)
    await client.mod_log(interaction.guild, discord.Embed(
        title="Playtest key issued",
        description=f"{member.mention} received a key for **{wave}**.",
        colour=discord.Color.blurple()).set_footer(
            text=f"issued by {interaction.user}"))
    await interaction.followup.send(
        f"Key {'reissued and ' if row.get('reissued') else ''}{sent} to "
        f"{member.mention}.", ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-status",
                     description="Waves, keys and signups. Staff only.")
async def playtest_status(interaction: discord.Interaction):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    waves = client.ledger.waves(interaction.guild_id)
    roster = client.ledger.playtest_roster(interaction.guild_id)
    played = sum(1 for r in roster if r["played_at"])

    lines = [f"**Signed up:** {len(roster)}",
             f"**Reported at least once:** {played}"
             + (f" ({played / len(roster) * 100:.0f}%)" if roster else "")]
    if not waves:
        lines.append("\nNo waves yet. `/playtest-open` starts one.")
    for w in waves:
        state = "closed" if w["closed_at"] else "open"
        left = w["keys_available"]
        lines.append(f"\n**{w['name']}** ({state}) - {w['keys_issued']} issued, "
                     f"{left} left"
                     + (f", cap {w['cap']}" if w["cap"] else ""))
    audit = client.ledger.key_audit(interaction.guild_id, limit=8)
    if audit:
        lines.append("\n**Most recent keys**")
        for a in audit:
            lines.append(f"- <@{a['issued_to']}> got `{a['wave']}` "
                         f"<t:{a['issued_at']}:R>"
                         + (" (revoked)" if a["revoked_at"] else ""))
    await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-close",
                     description="Close a wave. Staff only.")
async def playtest_close(interaction: discord.Interaction, wave: str):
    if not staff_only(interaction):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return
    ok = client.ledger.wave_close(interaction.guild_id, wave)
    await interaction.response.send_message(
        f"`{wave}` is closed." if ok else f"No open wave called `{wave}`.",
        ephemeral=True)


@app_commands.guild_only()
@client.tree.command(name="playtest-report",
                     description="File a bug from the playtest.")
@app_commands.describe(summary="One line: what went wrong.",
                       build="The build number or version you were on.",
                       steps="What you did just before it happened.")
async def playtest_report(interaction: discord.Interaction, summary: str,
                          build: str, steps: str):
    forum = discord.utils.get(interaction.guild.forums, name=BUG_FORUM)
    if forum is None:
        await interaction.response.send_message(
            f"There is no #{BUG_FORUM} forum channel in this server, so there is "
            f"nowhere to file this. Tell a moderator.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    body = (f"**Reported by** {interaction.user.mention}\n"
            f"**Build** {build}\n\n"
            f"**What happened**\n{summary}\n\n"
            f"**Steps**\n{steps}")
    try:
        thread = await forum.create_thread(
            name=summary[:100], content=body[:2000],
            allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        await interaction.followup.send(
            f"Discord refused the post: {e}", ephemeral=True)
        return

    client.ledger.playtest_played(interaction.guild_id, interaction.user.id)
    client.ledger.record(guild_id=interaction.guild_id, user_id=interaction.user.id,
                         event_type="playtest_report")
    await interaction.followup.send(
        f"Filed as {thread.thread.mention}. Add screenshots or a log to the "
        f"thread if you have them.", ephemeral=True)


def explain(title: str, lines: list[str]):
    """Discord's own errors are written for library authors. Anything a person
    has to act on gets rewritten here as the clicks that fix it."""
    width = 68
    print()
    print("  " + "=" * width)
    print("  " + title)
    print("  " + "=" * width)
    for line in lines:
        print("  " + line)
    print("  " + "=" * width)
    print()


if __name__ == "__main__":
    if not TOKEN:
        explain("No token in steward\\.env", [
            "",
            "Open steward\\.env and paste your bot token after DISCORD_TOKEN=",
            "",
            "If you no longer have it, get a new one:",
            "  1. https://discord.com/developers/applications",
            "  2. Your app, then Bot in the left menu",
            "  3. Reset Token, confirm, then Copy",
            "",
            "Resetting invalidates the old token, which is fine.",
        ])
        raise SystemExit(1)

    try:
        client.run(TOKEN, log_handler=None)

    except discord.PrivilegedIntentsRequired:
        explain("Discord refused: one switch is still off", [
            "",
            "The ledger needs the Server Members Intent to see who joins and",
            "leaves. It is off by default and has to be turned on by hand.",
            "",
            "  1. https://discord.com/developers/applications",
            "  2. Click your app, then Bot in the left menu",
            "  3. Scroll to Privileged Gateway Intents",
            "  4. Turn ON  Server Members Intent",
            "  5. Leave Presence Intent and Message Content Intent OFF",
            "  6. Click Save Changes in the green bar at the bottom",
            "",
            "Step 6 is the one people miss. Without it nothing is saved and",
            "you land back here.",
            "",
            "Then run this file again.",
        ])
        raise SystemExit(1)

    except discord.LoginFailure:
        explain("Discord rejected that token", [
            "",
            "Check steward\\.env holds the bot token itself, not the",
            "Application ID and not the Client Secret. If you have reset the",
            "token since copying it, the old one stopped working.",
            "",
            "  1. https://discord.com/developers/applications",
            "  2. Your app, then Bot, then Reset Token",
            "  3. Copy it and paste it after DISCORD_TOKEN= in steward\\.env",
        ])
        raise SystemExit(1)

    except KeyboardInterrupt:
        pass
