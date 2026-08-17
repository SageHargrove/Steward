"""Which channels are going quiet, measured against their own past.

Job four of the build plan, and the one that was deliberately left until last
because it is the only feature here that is meaningless without history. A
channel's baseline is what that channel normally does, and on a two-week-old
server "normally" is the launch spike. Run this too early and every channel
looks like it is dying, which is worse than not running it at all.

Three decisions that matter more than the arithmetic:

**The median, not the mean.** One patch-notes day with forty messages drags a
mean up for a month, and every ordinary week afterwards then reads as decay.
The median ignores it.

**A floor on volume.** A channel averaging one message a day can fall by 100%
and it means somebody went on holiday. Below the floor nothing is reported,
because the noise would bury the signal that matters.

**Compare against its peers, not only against its own past.** If the whole
server is quieter this week, every channel is down and flagging all of them
says nothing; the report would fire every Christmas and nobody would trust it
again. So each channel is judged against how the *other* channels moved.

Leaving the channel out of its own peer group is the part that is easy to get
wrong. Divide by a server total that includes it and a busy channel cancels its
own fall, and on a server where one channel carries most of the traffic it
cancels it exactly, so nothing is ever reported. A test covers that, because
the first version had the bug.
"""

from __future__ import annotations

import time

DAY = 86400

# Defaults, all overridable from the blueprint's `decay:` block.
RECENT_DAYS = 7          # the window being judged
BASELINE_DAYS = 28       # what it is judged against, ending where recent begins
MIN_HISTORY_DAYS = 56    # refuse to report at all below this. Eight weeks
MIN_BASELINE = 1.5       # messages a day, below which a channel is too quiet
DROP = 0.45              # flag at a fall of 45% or more, after normalising
RISE = 0.60              # a rise worth mentioning, since it is also news


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def history_days(ledger, guild_id: int) -> int:
    """How much history there is. The report refuses below MIN_HISTORY_DAYS."""
    row = ledger.db.execute(
        "SELECT MIN(ts) AS first FROM events WHERE guild_id = ? "
        "AND event_type = 'message'", (guild_id,)).fetchone()
    if not row or not row["first"]:
        return 0
    return int((time.time() - row["first"]) // DAY)


def per_channel_daily(ledger, guild_id: int, since: int, until: int) -> dict:
    """{channel_id: {day: count}} for messages in the window."""
    out: dict[int, dict[str, int]] = {}
    for r in ledger.db.execute(
            "SELECT channel_id, strftime('%Y-%m-%d', ts, 'unixepoch') AS d, "
            "       COUNT(*) AS n FROM events "
            "WHERE guild_id = ? AND event_type = 'message' AND channel_id IS NOT NULL "
            "  AND ts >= ? AND ts < ? GROUP BY channel_id, d",
            (guild_id, since, until)):
        out.setdefault(r["channel_id"], {})[r["d"]] = r["n"]
    return out


def _rates(daily: dict, days: int, start: int) -> list[float]:
    """Counts for each day in the window, zeros included.

    The zeros are the point. Skipping days with no messages would make a
    channel that went silent look like it has no data rather than no activity.
    """
    from datetime import datetime, timezone
    out = []
    for i in range(days):
        key = datetime.fromtimestamp(start + i * DAY, timezone.utc).strftime("%Y-%m-%d")
        out.append(float(daily.get(key, 0)))
    return out


def analyse(ledger, guild_id: int, config: dict | None = None,
            now: int | None = None) -> dict:
    cfg = config or {}
    recent_days = int(cfg.get("recent_days", RECENT_DAYS))
    base_days = int(cfg.get("baseline_days", BASELINE_DAYS))
    min_history = int(cfg.get("min_history_days", MIN_HISTORY_DAYS))
    min_base = float(cfg.get("min_baseline", MIN_BASELINE))
    drop = float(cfg.get("drop", DROP))
    rise = float(cfg.get("rise", RISE))

    now = now or int(time.time())
    have = history_days(ledger, guild_id)
    if have < min_history:
        return {"ready": False, "have_days": have, "need_days": min_history,
                "channels": [],
                "why": f"{have} days of history. Channel baselines need "
                       f"{min_history} before they mean anything, or the launch "
                       f"spike gets treated as normal and everything after it "
                       f"reads as decay."}

    recent_start = now - recent_days * DAY
    base_start = recent_start - base_days * DAY
    daily = per_channel_daily(ledger, guild_id, base_start, now)

    rows = []
    for cid, series in daily.items():
        base = _rates(series, base_days, base_start)
        recent = _rates(series, recent_days, recent_start)
        b, r = median(base), median(recent)
        rows.append({"channel_id": cid, "baseline": b, "recent": r,
                     "base_total": sum(base), "recent_total": sum(recent)})

    # The server-wide move, for the summary line.
    server_base = sum(x["baseline"] for x in rows)
    server_recent = sum(x["recent"] for x in rows)
    server_ratio = (server_recent / server_base) if server_base > 0 else 1.0

    out = []
    for x in rows:
        if x["baseline"] < min_base:
            continue                       # too quiet for a change to mean anything
        raw = x["recent"] / x["baseline"] if x["baseline"] else 1.0

        # Judged against its peers, with itself left out. Dividing by a server
        # total that includes this channel lets a busy channel cancel its own
        # fall, and on a server with one active channel it cancels it exactly,
        # so nothing is ever reported.
        peer_base = server_base - x["baseline"]
        peer_recent = server_recent - x["recent"]
        if peer_base >= min_base:
            peer_ratio = peer_recent / peer_base
            rel = raw / peer_ratio if peer_ratio > 0 else raw
        else:
            # Nothing to compare against. Better to judge it on its own past
            # than to invent a peer group out of one other channel.
            rel = raw
        verdict = None
        if rel <= 1 - drop:
            verdict = "quiet"
        elif rel >= 1 + rise:
            verdict = "busy"
        if verdict:
            out.append({**x, "ratio": raw, "relative": rel, "verdict": verdict,
                        "change_pct": (raw - 1) * 100})

    out.sort(key=lambda x: x["relative"])
    return {"ready": True, "have_days": have, "channels": out,
            "server_ratio": server_ratio,
            "server_change_pct": (server_ratio - 1) * 100,
            "window": {"recent_days": recent_days, "baseline_days": base_days},
            "watched": sum(1 for x in rows if x["baseline"] >= min_base),
            "why": None}


def summarise(result: dict, name_of=lambda cid: f"<#{cid}>") -> list[str]:
    """Lines for the digest. Says nothing rather than saying nothing useful."""
    if not result.get("ready"):
        return []
    quiet = [c for c in result["channels"] if c["verdict"] == "quiet"]
    busy = [c for c in result["channels"] if c["verdict"] == "busy"]
    if not quiet and not busy:
        return [f"No channel moved much against its own baseline "
                f"({result['watched']} watched)."]

    lines = []
    server = result["server_change_pct"]
    if abs(server) >= 15:
        lines.append(f"The server as a whole is {'down' if server < 0 else 'up'} "
                     f"{abs(server):.0f}%, and the channels below are measured "
                     f"against that rather than against zero.")
    for c in quiet[:5]:
        lines.append(f"{name_of(c['channel_id'])} is down {abs(c['change_pct']):.0f}% "
                     f"({c['baseline']:.1f} to {c['recent']:.1f} messages a day)")
    for c in busy[:3]:
        lines.append(f"{name_of(c['channel_id'])} is up {c['change_pct']:.0f}% "
                     f"({c['baseline']:.1f} to {c['recent']:.1f} messages a day)")
    return lines
