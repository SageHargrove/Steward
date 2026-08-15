"""
Steward's activity ledger.

Discord's API has no per-member last-active field. The Guild Member object
gives you joined_at, roles, nickname and flags, and nothing about activity.
There is no last_seen and no last_message_at. Every "who went quiet" feature
anyone has ever built is derived from an event stream someone recorded
themselves, and you cannot backfill one. That is the entire reason this file
exists before anything that reads from it.

Storage is one SQLite file. A server's worth of activity is small: roughly
100 bytes per event, so 500 messages a day for a year is about 18 MB.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER,
    channel_id  INTEGER,
    event_type  TEXT    NOT NULL,
    ts          INTEGER NOT NULL,          -- unix seconds, UTC
    meta        TEXT                       -- json, nullable
);
CREATE INDEX IF NOT EXISTS ix_events_guild_ts ON events (guild_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_user_ts  ON events (user_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_type_ts  ON events (event_type, ts);
CREATE INDEX IF NOT EXISTS ix_events_chan_ts  ON events (channel_id, ts);

-- One row per member per guild. The funnel lives here so the four numbers
-- that matter (join, onboarded, first post, still here) are a single query.
CREATE TABLE IF NOT EXISTS members (
    guild_id                INTEGER NOT NULL,
    user_id                 INTEGER NOT NULL,
    first_joined_at         INTEGER NOT NULL,
    last_left_at            INTEGER,
    onboarding_completed_at INTEGER,
    first_message_at        INTEGER,
    last_seen_at            INTEGER,
    -- How they said they found you. Discord will not accept an onboarding
    -- answer that grants nothing, so the answer grants a role for a moment and
    -- the bot writes it here and takes the role back off. The number lives in
    -- this column instead of on the member's profile.
    attribution             TEXT,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_members_joined ON members (guild_id, first_joined_at);

-- Discord's Developer ToS requires an easily accessible way for a user to
-- have their data deleted. /forget-me writes here, and every recording path
-- checks it first, so opting out is permanent rather than a one-time wipe.
CREATE TABLE IF NOT EXISTS opt_outs (
    user_id    INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL
);

-- Bookkeeping so a restart does not re-log the same backfill.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()
        self._opted_out: set[int] = {
            row["user_id"] for row in self.db.execute("SELECT user_id FROM opt_outs")
        }

    def _migrate(self):
        """Add columns that later versions introduced. CREATE TABLE IF NOT
        EXISTS does nothing to a table that already exists, so a database made
        by an older build would otherwise be missing them."""
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(members)")}
        for column, decl in (("attribution", "TEXT"),):
            if column not in have:
                self.db.execute(f"ALTER TABLE members ADD COLUMN {column} {decl}")

    # -- attribution ------------------------------------------------------

    def set_attribution(self, guild_id: int, user_id: int, source: str) -> bool:
        """Record how someone said they found you. First answer wins, so a
        rejoin cannot overwrite the original. Returns whether it was stored."""
        if user_id in self._opted_out:
            return False
        cur = self.db.execute(
            "UPDATE members SET attribution = ? "
            "WHERE guild_id = ? AND user_id = ? AND attribution IS NULL",
            (source, guild_id, user_id))
        self.db.commit()
        return cur.rowcount > 0

    def attribution_counts(self, guild_id: int) -> dict[str, int]:
        return {r["attribution"]: r["n"] for r in self.db.execute(
            "SELECT attribution, COUNT(*) AS n FROM members "
            "WHERE guild_id = ? AND attribution IS NOT NULL "
            "GROUP BY attribution ORDER BY n DESC", (guild_id,))}

    # -- opt-out ----------------------------------------------------------

    def is_opted_out(self, user_id: int) -> bool:
        return user_id in self._opted_out

    def forget(self, user_id: int) -> dict[str, int]:
        """Delete everything about a user and stop recording them. Returns the
        row counts removed, so the command can tell the user what went."""
        now = int(time.time())
        cur = self.db.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
        events = cur.rowcount
        cur = self.db.execute("DELETE FROM members WHERE user_id = ?", (user_id,))
        members = cur.rowcount
        self.db.execute(
            "INSERT OR REPLACE INTO opt_outs (user_id, created_at) VALUES (?, ?)",
            (user_id, now))
        self.db.commit()
        self._opted_out.add(user_id)
        return {"events": max(events, 0), "members": max(members, 0)}

    def unforget(self, user_id: int) -> bool:
        """Opt back in. Nothing is restored, recording simply resumes."""
        if user_id not in self._opted_out:
            return False
        self.db.execute("DELETE FROM opt_outs WHERE user_id = ?", (user_id,))
        self.db.commit()
        self._opted_out.discard(user_id)
        return True

    def summary_for(self, user_id: int) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last "
            "FROM events WHERE user_id = ?", (user_id,)).fetchone()
        by_type = {
            r["event_type"]: r["n"] for r in self.db.execute(
                "SELECT event_type, COUNT(*) AS n FROM events WHERE user_id = ? "
                "GROUP BY event_type ORDER BY n DESC", (user_id,))
        }
        return {
            "total": row["n"], "first": row["first"], "last": row["last"],
            "by_type": by_type, "opted_out": user_id in self._opted_out,
        }

    # -- writes -----------------------------------------------------------

    def record(self, *, guild_id: int, event_type: str, user_id: int | None = None,
               channel_id: int | None = None, ts: int | None = None, **meta):
        if user_id is not None and user_id in self._opted_out:
            return
        ts = ts or int(time.time())
        self.db.execute(
            "INSERT INTO events (guild_id, user_id, channel_id, event_type, ts, meta) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, channel_id, event_type, ts,
             json.dumps(meta, ensure_ascii=False) if meta else None))
        if user_id is not None:
            self.db.execute(
                "UPDATE members SET last_seen_at = ? WHERE guild_id = ? AND user_id = ?",
                (ts, guild_id, user_id))
        self.db.commit()

    def touch_member(self, guild_id: int, user_id: int, joined_at: int):
        """Insert on first sight. joined_at comes from Discord and is real, so
        this is the one field that can legitimately be backfilled."""
        if user_id in self._opted_out:
            return
        self.db.execute(
            "INSERT INTO members (guild_id, user_id, first_joined_at) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET "
            "  first_joined_at = MIN(first_joined_at, excluded.first_joined_at)",
            (guild_id, user_id, joined_at))
        self.db.commit()

    def mark(self, guild_id: int, user_id: int, column: str, ts: int, *, first_only=True):
        """Set one of the funnel timestamps. first_only keeps the earliest."""
        if user_id in self._opted_out or column not in (
                "onboarding_completed_at", "first_message_at", "last_left_at", "last_seen_at"):
            return
        if first_only:
            self.db.execute(
                f"UPDATE members SET {column} = ? "
                f"WHERE guild_id = ? AND user_id = ? AND {column} IS NULL",
                (ts, guild_id, user_id))
        else:
            self.db.execute(
                f"UPDATE members SET {column} = ? WHERE guild_id = ? AND user_id = ?",
                (ts, guild_id, user_id))
        self.db.commit()

    # -- retention --------------------------------------------------------

    def purge_older_than(self, days: int) -> int:
        """Retention policy, enforced in code rather than in a document.
        Member funnel rows survive: they are four timestamps, not a history."""
        cutoff = int(time.time()) - days * 86400
        cur = self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        self.db.commit()
        if cur.rowcount > 0:
            self.db.execute("VACUUM")
        return max(cur.rowcount, 0)

    # -- reads ------------------------------------------------------------

    def counts(self, guild_id: int) -> dict:
        e = self.db.execute(
            "SELECT COUNT(*) AS n, MIN(ts) AS first FROM events WHERE guild_id = ?",
            (guild_id,)).fetchone()
        m = self.db.execute(
            "SELECT COUNT(*) AS n FROM members WHERE guild_id = ?", (guild_id,)).fetchone()
        by_type = {
            r["event_type"]: r["n"] for r in self.db.execute(
                "SELECT event_type, COUNT(*) AS n FROM events WHERE guild_id = ? "
                "GROUP BY event_type ORDER BY n DESC", (guild_id,))
        }
        return {
            "events": e["n"], "since": e["first"], "members": m["n"],
            "by_type": by_type, "opt_outs": len(self._opted_out),
            "db_bytes": self.size_on_disk(),
        }

    def size_on_disk(self) -> int:
        """Checkpoints first. In WAL mode recent writes sit in a sidecar file
        that can be megabytes while the main database still reads as 4 KB, so
        without the checkpoint this number is meaningless in either direction."""
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return self.path.stat().st_size if self.path.exists() else 0

    def close(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()

    def funnel(self, guild_id: int, cohort_days: int = 7) -> dict:
        """Joins, onboarding completion, first post, and still-active, for
        members who joined in the last cohort_days. The four numbers no
        third-party tool will give you."""
        cutoff = int(time.time()) - cohort_days * 86400
        row = self.db.execute(
            "SELECT "
            "  COUNT(*) AS joined, "
            "  SUM(onboarding_completed_at IS NOT NULL) AS onboarded, "
            "  SUM(first_message_at IS NOT NULL) AS posted, "
            "  SUM(last_left_at IS NOT NULL) AS left_server "
            "FROM members WHERE guild_id = ? AND first_joined_at >= ?",
            (guild_id, cutoff)).fetchone()
        return {k: (row[k] or 0) for k in row.keys()}
