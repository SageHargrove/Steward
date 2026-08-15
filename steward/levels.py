"""Levels, XP and the roles they unlock.

Deliberately part of Steward rather than a second bot. Every deployment that
needs a leveling bot is a deployment running one more thing that holds a copy
of its members' activity, and the data is already here.

The curve is the one most members will already have a feel for: the XP needed
to go from level n to n+1 is 5n^2 + 50n + 100. It starts fast enough to feel
responsive in the first week and slows enough that the top of a leaderboard
still means something a year in.

Nothing here reads message content. XP comes from the fact that somebody
posted, not from what they wrote.
"""

from __future__ import annotations

import random


class Curve:
    """Maps XP to levels and back, with the results cached.

    Levels are computed rather than stored so that changing the curve does not
    strand everybody at a level they can no longer reach.
    """

    def __init__(self, base: int = 100, linear: int = 50, quadratic: int = 5):
        self.base, self.linear, self.quadratic = base, linear, quadratic
        self._cumulative = [0]

    def step(self, level: int) -> int:
        """XP to get from `level` to the next one."""
        return self.quadratic * level * level + self.linear * level + self.base

    def total_for(self, level: int) -> int:
        """XP needed to have reached `level` at all."""
        while len(self._cumulative) <= level:
            self._cumulative.append(
                self._cumulative[-1] + self.step(len(self._cumulative) - 1))
        return self._cumulative[level]

    def level_at(self, xp: int) -> int:
        level = 0
        while self.total_for(level + 1) <= xp:
            level += 1
            if level > 1000:                       # a guard, not a real ceiling
                break
        return level

    def progress(self, xp: int) -> tuple[int, int, int]:
        """(level, xp into this level, xp this level needs)."""
        level = self.level_at(xp)
        floor = self.total_for(level)
        return level, xp - floor, self.total_for(level + 1) - floor


class Levels:
    def __init__(self, ledger, config: dict | None = None):
        cfg = config or {}
        self.ledger = ledger
        self.enabled = cfg.get("enabled", True)
        self.noun = cfg.get("noun", "Level")
        low, high = (cfg.get("xp_per_message") or [15, 25])[:2]
        self.xp_range = (int(low), int(high))
        self.cooldown = int(cfg.get("cooldown_seconds", 60))
        self.voice_xp_per_minute = int(cfg.get("voice_xp_per_minute", 5))
        self.announce = cfg.get("announce", "reply")          # reply | channel | off
        self.announce_channel = cfg.get("announce_channel")
        self.only_announce_rewards = bool(cfg.get("announce_only_rewards", True))
        self.no_xp_channels = set(cfg.get("no_xp_channels") or [])
        self.curve = Curve(**(cfg.get("curve") or {}))
        # {level: role name}
        self.rewards = {int(r["level"]): r["role"] for r in cfg.get("rewards", [])}

    # -- awarding ---------------------------------------------------------

    def award_message(self, guild_id: int, user_id: int,
                      channel_name: str | None = None) -> dict | None:
        """Give XP for a message. Returns level-up details, or None."""
        if not self.enabled or (channel_name and channel_name in self.no_xp_channels):
            return None
        amount = random.randint(*self.xp_range)
        return self._apply(guild_id, user_id, amount, cooldown=self.cooldown)

    def award_voice(self, guild_id: int, user_id: int, seconds: int) -> dict | None:
        """Give XP for time spent in voice, paid on leaving."""
        if not self.enabled or seconds < 60 or self.voice_xp_per_minute <= 0:
            return None
        self.ledger.add_voice_seconds(guild_id, user_id, seconds)
        minutes = seconds // 60
        return self._apply(guild_id, user_id, minutes * self.voice_xp_per_minute)

    def _apply(self, guild_id, user_id, amount, cooldown=0) -> dict | None:
        before = self.ledger.xp_of(guild_id, user_id)
        total = self.ledger.add_xp(guild_id, user_id, amount, cooldown=cooldown)
        if total is None:
            return None                                    # cooldown, or opted out

        was = self.curve.level_at(before["xp"])
        now = self.curve.level_at(total)
        if now == was:
            return None
        self.ledger.set_level(guild_id, user_id, now)
        return {"level": now, "previous": was, "xp": total,
                "role": self.rewards.get(now),
                # Someone can cross two levels at once from a voice payout, so
                # collect every reward they passed rather than only the last.
                "roles_passed": [self.rewards[lv] for lv in range(was + 1, now + 1)
                                 if lv in self.rewards]}

    # -- reading ----------------------------------------------------------

    def rank(self, guild_id: int, user_id: int) -> dict:
        row = self.ledger.xp_of(guild_id, user_id)
        level, into, needed = self.curve.progress(row["xp"])
        return {**row, "level": level, "into": into, "needed": needed,
                "total_ranked": self.ledger.ranked_count(guild_id)}

    def board(self, guild_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
        out = []
        for i, row in enumerate(self.ledger.leaderboard(guild_id, limit, offset), 1):
            out.append({**row, "position": offset + i,
                        "level": self.curve.level_at(row["xp"])})
        return out

    def bar(self, into: int, needed: int, width: int = 12) -> str:
        """A progress bar that works without an image."""
        if needed <= 0:
            return "=" * width
        filled = max(0, min(width, round(width * into / needed)))
        return "=" * filled + "." * (width - filled)


def from_blueprint(ledger, blueprint: dict | None):
    """Build the leveling config out of the blueprint, so the words members see
    are set in the same place as everything else about the server."""
    cfg = (blueprint or {}).get("levels") or {}
    return Levels(ledger, cfg)
