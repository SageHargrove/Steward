"""
Steward, stage one: the activity ledger and nothing else.

It records events and offers three commands. It posts no digests, runs no
calendar, detects no decay. Those are built later on top of the history this
accumulates, and they are only worth building once there is history.

Notably it does NOT request the MESSAGE_CONTENT intent. on_message fires
without it; only the content field comes back empty, and the ledger records
who posted where and when rather than what was said. That means less to
protect, no annual reapplication once the bot passes 10,000 users, and an
honest answer when a member asks what is stored.

Run:
    python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from ledger import Ledger

load_dotenv()

TOKEN = os.environ.get("DISCORD_TOKEN")
DB_PATH = os.environ.get("STEWARD_DB", "data/steward.sqlite3")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "400"))
REPORT_CHANNEL = os.environ.get("REPORT_CHANNEL", "steward-reports")
BLUEPRINT = os.environ.get("STEWARD_BLUEPRINT", "../blueprint/giltgrave.yaml")

# The status message identifies itself by its title, so restarts reuse the
# same message instead of stacking up.
STATUS_TITLE = "Ledger"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("steward")


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


class Steward(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.ledger = Ledger(DB_PATH)
        self.ephemeral = ephemeral_roles(BLUEPRINT)
        self.started_at = int(time.time())

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

    async def setup_hook(self):
        await self.tree.sync()
        self.nightly_purge.start()
        self.heartbeat.start()

    # -- backfill ---------------------------------------------------------

    async def on_ready(self):
        log.info("connected as %s", self.user)
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
        if self.ephemeral and {r.id for r in before.roles} != {r.id for r in after.roles}:
            await self.absorb_attribution(after)

    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        gid = member.guild.id
        if before.channel is None and after.channel is not None:
            self.ledger.record(guild_id=gid, user_id=member.id,
                               channel_id=after.channel.id, event_type="voice_join")
        elif before.channel is not None and after.channel is None:
            self.ledger.record(guild_id=gid, user_id=member.id,
                               channel_id=before.channel.id, event_type="voice_leave")
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            self.ledger.record(guild_id=gid, user_id=member.id,
                               channel_id=after.channel.id, event_type="voice_move",
                               **{"from": before.channel.id})

    # -- visible proof of life --------------------------------------------

    async def status_channel(self, guild):
        return discord.utils.get(guild.text_channels, name=REPORT_CHANNEL)

    async def find_status_message(self, channel):
        """The one status message, reused so restarts do not stack up."""
        try:
            async for m in channel.history(limit=30):
                if m.author.id == self.user.id and m.embeds:
                    if (m.embeds[0].title or "").startswith(STATUS_TITLE):
                        return m
        except discord.HTTPException:
            pass
        return None

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
        e.set_footer(text="Only who posted where and when. Never what was said.")
        return e

    async def update_status(self, running=True):
        for guild in self.guilds:
            channel = await self.status_channel(guild)
            if channel is None:
                continue
            try:
                embed = self.status_embed(guild, running)
                existing = await self.find_status_message(channel)
                if existing:
                    await existing.edit(embed=embed)
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
            await self.update_status(running=False)
        except Exception:                                    # noqa: BLE001
            pass
        await super().close()

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


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("No DISCORD_TOKEN. Copy .env.example to .env and fill it in.")
    try:
        client.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        pass
