"""The weekly digest, and the charts that go with it.

Two rules shape this file.

The first: a chart of four data points is worse than four numbers. Early on a
server has single digits and a plotted line says nothing a sentence could not,
so the digest always states the numbers and only draws a chart once there is
enough history for the shape to mean something.

The second: matplotlib is optional. It is a large dependency for a bot that
mostly writes rows to SQLite, so its absence downgrades the digest to text
rather than breaking it.
"""

from __future__ import annotations

import io
import time
from datetime import datetime, timezone

DAY = 86400

# Discord's own dark surface, so the image sits in the message rather than on
# a white card punched through it. Series colours are the dark steps of a
# palette validated against this exact surface: adjacent CVD dE 9.4, normal
# vision 26.5, all above 3:1 contrast.
SURFACE = "#2b2d31"
INK = "#dbdee1"
MUTED = "#949ba4"
GRID = "#3f4147"
JOINS = "#3987e5"
POSTERS = "#d95926"
RETAINED = "#199e70"

# Below this there is not enough shape to plot, and the numbers say it better.
MIN_DAYS_FOR_CHART = 10


def day_key(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def daily_series(ledger, guild_id: int, days: int = 30) -> dict:
    """Joins and distinct posters per day, oldest first."""
    since = int(time.time()) - days * DAY
    joins = {r["d"]: r["n"] for r in ledger.db.execute(
        "SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS d, COUNT(*) AS n "
        "FROM events WHERE guild_id = ? AND event_type = 'join' AND ts >= ? "
        "GROUP BY d", (guild_id, since))}
    posters = {r["d"]: r["n"] for r in ledger.db.execute(
        "SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS d, "
        "       COUNT(DISTINCT user_id) AS n "
        "FROM events WHERE guild_id = ? AND event_type = 'message' AND ts >= ? "
        "GROUP BY d", (guild_id, since))}

    labels, j, p = [], [], []
    start = int(time.time()) - (days - 1) * DAY
    for i in range(days):
        key = day_key(start + i * DAY)
        labels.append(key)
        j.append(joins.get(key, 0))
        p.append(posters.get(key, 0))
    return {"labels": labels, "joins": j, "posters": p}


def week_over_week(ledger, guild_id: int) -> dict:
    """This week against last, which is the only comparison worth making when
    the absolute numbers are small."""
    now = int(time.time())

    def window(start, end):
        joined = ledger.db.execute(
            "SELECT COUNT(*) AS n FROM members "
            "WHERE guild_id = ? AND first_joined_at >= ? AND first_joined_at < ?",
            (guild_id, start, end)).fetchone()["n"]
        posted = ledger.db.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM events "
            "WHERE guild_id = ? AND event_type = 'message' AND ts >= ? AND ts < ?",
            (guild_id, start, end)).fetchone()["n"]
        messages = ledger.db.execute(
            "SELECT COUNT(*) AS n FROM events "
            "WHERE guild_id = ? AND event_type = 'message' AND ts >= ? AND ts < ?",
            (guild_id, start, end)).fetchone()["n"]
        return {"joined": joined, "posted": posted, "messages": messages}

    return {"this_week": window(now - 7 * DAY, now),
            "last_week": window(now - 14 * DAY, now - 7 * DAY)}


def cohort_retention(ledger, guild_id: int, weeks: int = 6) -> list[dict]:
    """For each recent week of arrivals: how many joined, and how many of them
    have posted since.

    This is the number the build plan is about and the one no third-party bot
    produces, because it needs an event history nobody else kept.
    """
    now = int(time.time())
    out = []
    for w in range(weeks, 0, -1):
        start, end = now - w * 7 * DAY, now - (w - 1) * 7 * DAY
        members = [r["user_id"] for r in ledger.db.execute(
            "SELECT user_id FROM members "
            "WHERE guild_id = ? AND first_joined_at >= ? AND first_joined_at < ?",
            (guild_id, start, end))]
        if not members:
            out.append({"week": w, "joined": 0, "retained": 0, "rate": None})
            continue
        marks = ",".join("?" * len(members))
        retained = ledger.db.execute(
            f"SELECT COUNT(DISTINCT user_id) AS n FROM events "
            f"WHERE guild_id = ? AND event_type = 'message' AND ts >= ? "
            f"AND user_id IN ({marks})",
            (guild_id, end, *members)).fetchone()["n"]
        out.append({"week": w, "joined": len(members), "retained": retained,
                    "rate": retained / len(members)})
    return out


def spark(values: list[int], width: int = 7) -> str:
    """A bar drawn in text, for when there is no image and none is needed."""
    if not values or max(values) == 0:
        return "no activity"
    blocks = " ▁▂▃▄▅▆▇█"
    top = max(values)
    return "".join(blocks[min(8, round(v / top * 8))] for v in values[-width * 4:])


def render_chart(series: dict, cohorts: list[dict]):
    """A PNG of the last 30 days, or None if it cannot or should not be drawn.

    Two stacked panels rather than one chart with two y-axes. Joins and active
    posters live on different scales, and putting them on twin axes would let
    the drawing imply a relationship the data does not have.
    """
    active_days = sum(1 for v in series["posters"] if v) + \
                  sum(1 for v in series["joins"] if v)
    if active_days < MIN_DAYS_FOR_CHART:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MaxNLocator
    except ImportError:
        return None

    labels = [d[5:] for d in series["labels"]]          # MM-DD
    has_cohorts = any(c["rate"] is not None for c in cohorts)
    rows = 3 if has_cohorts else 2

    fig, axes = plt.subplots(rows, 1, figsize=(8, 1.95 * rows), dpi=160,
                             facecolor=SURFACE)
    fig.subplots_adjust(hspace=0.62, left=0.09, right=0.97, top=0.93, bottom=0.08)

    def dress(ax, title):
        ax.set_facecolor(SURFACE)
        ax.set_title(title, color=INK, fontsize=10, loc="left", pad=8)
        ax.tick_params(colors=MUTED, labelsize=8, length=0)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
        ax.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.7)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)

    step = max(1, len(labels) // 8)
    ticks = list(range(0, len(labels), step))

    dress(axes[0], "Members joined per day")
    axes[0].bar(range(len(labels)), series["joins"], color=JOINS, width=0.62)
    axes[0].set_xticks(ticks); axes[0].set_xticklabels([labels[i] for i in ticks])

    dress(axes[1], "People who posted, per day")
    axes[1].plot(range(len(labels)), series["posters"], color=POSTERS,
                 linewidth=2, marker="o", markersize=3.5)
    axes[1].set_xticks(ticks); axes[1].set_xticklabels([labels[i] for i in ticks])

    if has_cohorts:
        dress(axes[2], "Of each week's arrivals, how many came back")
        xs = [f"{c['week']}w ago" for c in cohorts]
        ys = [round((c["rate"] or 0) * 100) for c in cohorts]
        bars = axes[2].bar(xs, ys, color=RETAINED, width=0.55)
        # Headroom above 100 so a full bar's label has somewhere to sit without
        # climbing into the title.
        axes[2].set_ylim(0, 124)
        axes[2].set_yticks([0, 50, 100])
        axes[2].set_yticklabels(["0%", "50%", "100%"])
        # Direct labels on a handful of bars beat a legend nobody reads.
        for bar, c in zip(bars, cohorts):
            if c["joined"]:
                axes[2].text(bar.get_x() + bar.get_width() / 2,
                             bar.get_height() + 4, f"{c['retained']}/{c['joined']}",
                             ha="center", va="bottom", color=MUTED, fontsize=7.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    return buf


def build(ledger, guild_id: int) -> dict:
    """Everything the digest needs, ready to be turned into an embed."""
    series = daily_series(ledger, guild_id)
    wow = week_over_week(ledger, guild_id)
    cohorts = cohort_retention(ledger, guild_id)
    return {
        "series": series,
        "week": wow,
        "cohorts": cohorts,
        "funnel": ledger.funnel(guild_id, cohort_days=7),
        "attribution": ledger.attribution_counts(guild_id),
        "counts": ledger.counts(guild_id),
        "chart": render_chart(series, cohorts),
    }


def delta(now: int, before: int) -> str:
    if before == 0:
        return "" if now == 0 else "  (first week with any)"
    change = round((now - before) / before * 100)
    if change == 0:
        return "  (level with last week)"
    return f"  ({change:+d}% on last week)"
