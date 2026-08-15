"""Version, update checking, and applying an update.

Two channels, because there are two ways this ends up on a machine.

A **git checkout** is what a developer has, and it is also what the Start Menu
installer points at. Updating is a fetch and a fast-forward, it works whether
the repository is public or private, and it is the only one of the two that can
be fully exercised without publishing anything.

A **release** is what everyone else would have. The check reads GitHub's
releases API, which needs the repository to be public; against a private one it
returns 404 and the check says so plainly rather than looking broken.

Nothing here updates on its own. It reports that something is available and
waits to be told, because an update that restarts the bot without asking is an
update that stops recording activity in the middle of a conversation.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
BACKUPS = ROOT / "backups"
TIMEOUT = 12

# Paths an update must never touch. The first two are gitignored anyway, so
# this is belt and braces, but the cost of being wrong is somebody's bot token
# and an activity history that Discord cannot rebuild.
PROTECTED = ("steward/.env", "steward/data", "backups")


def version() -> str:
    """The first line only. A VERSION file with anything after it would
    otherwise be returned whole, and a multi-line version string gets compared,
    displayed and written into a git tag."""
    try:
        first = VERSION_FILE.read_text(encoding="utf-8").strip().splitlines()
        return first[0].strip() if first else "0.0.0"
    except OSError:
        return "0.0.0"


def parse(v: str) -> tuple:
    """Loose semver. Anything unparseable sorts lowest rather than raising,
    because a bad tag upstream should not break the check on this machine."""
    nums = re.findall(r"\d+", (v or "").lstrip("vV"))
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def newer(a: str, b: str) -> bool:
    """Is `a` a later version than `b`?"""
    return parse(a) > parse(b)


def git(*args, cwd=ROOT, timeout=TIMEOUT):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=timeout)


def is_git_checkout() -> bool:
    try:
        return git("rev-parse", "--git-dir").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def remote_slug() -> str | None:
    """owner/repo, from whatever form the remote URL takes."""
    try:
        url = git("remote", "get-url", "origin").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def dirty_files() -> list[str]:
    """Tracked files edited here. These are what an update would overwrite, and
    the blueprint and the calendar are exactly the files people edit."""
    r = git("status", "--porcelain", "--untracked-files=no")
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        name = line[3:].strip().strip('"')
        if " -> " in name:                       # a rename
            name = name.split(" -> ", 1)[1]
        if name and not any(name.startswith(p) for p in PROTECTED):
            out.append(name)
    return out


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------

def check_git() -> dict:
    fetch = git("fetch", "--tags", "--quiet", timeout=45)
    if fetch.returncode != 0:
        return {"ok": False,
                "error": (fetch.stderr or "git fetch failed").strip()[:300]}

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "master"
    counts = git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
    ahead = behind = 0
    if counts.returncode == 0 and counts.stdout.split():
        parts = counts.stdout.split()
        ahead, behind = int(parts[0]), int(parts[1])

    log = git("log", "--oneline", "--no-decorate", "-20", f"HEAD..origin/{branch}")
    subjects = [l for l in log.stdout.splitlines() if l.strip()]

    # The VERSION file as it stands on the remote, so the page can name the
    # version being offered rather than only a commit count.
    show = git("show", f"origin/{branch}:VERSION")
    lines = show.stdout.strip().splitlines() if show.returncode == 0 else []
    latest = lines[0].strip() if lines else version()

    return {"ok": True, "method": "git", "branch": branch,
            "current": version(), "latest": latest or version(),
            "behind": behind, "ahead": ahead, "changes": subjects,
            "dirty": dirty_files()}


def check_release(slug: str) -> dict:
    url = f"https://api.github.com/repos/{slug}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "CommunityOps-update-check"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "method": "release", "private": True,
                    "current": version(),
                    "error": f"GitHub has no public releases for {slug}. If the "
                             f"repository is private, nobody else can be updated "
                             f"from it."}
        return {"ok": False, "method": "release", "current": version(),
                "error": f"GitHub returned {e.code}."}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "method": "release", "current": version(),
                "error": f"Could not reach GitHub ({type(e).__name__})."}

    tag = (data.get("tag_name") or "").strip()
    return {"ok": True, "method": "release", "current": version(),
            "latest": tag.lstrip("vV") or version(),
            "behind": 1 if newer(tag, version()) else 0, "ahead": 0,
            "changes": [l for l in (data.get("body") or "").splitlines() if l.strip()][:20],
            "url": data.get("html_url"), "dirty": []}


def check() -> dict:
    if is_git_checkout():
        out = check_git()
        out.setdefault("method", "git")
        out["slug"] = remote_slug()
        return out
    slug = remote_slug()
    if not slug:
        return {"ok": False, "method": "none", "current": version(),
                "error": "This copy did not come from git and has no update "
                         "channel configured, so it cannot check for updates."}
    return check_release(slug)


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------

def back_up(files: list[str]) -> str | None:
    """Copy edited files somewhere safe before an update overwrites them.

    Without this the honest options are refusing to update or destroying
    somebody's edited blueprint, and both are worse than a folder of copies.
    """
    if not files:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    dest = BACKUPS / stamp
    for rel in files:
        src = ROOT / rel
        if not src.exists():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return str(dest) if dest.exists() else None


def apply(discard_local=False) -> dict:
    """Fast-forward to the remote. Returns a log rather than raising, because
    the page shows it and half of these failures are things a person can fix."""
    if not is_git_checkout():
        info = check()
        return {"ok": False, "log": [
            "This copy did not come from git, so it cannot update itself.",
            "Download the latest release and run its installer.",
            info.get("url") or ""], "restart": False}

    log = []
    dirty = dirty_files()
    if dirty and not discard_local:
        return {"ok": False, "restart": False, "needs_confirm": True,
                "dirty": dirty, "log": [
                    "These files have been edited here and an update would "
                    "overwrite them:",
                    *[f"  {d}" for d in dirty],
                    "",
                    "Updating anyway copies them into backups/ first. Nothing "
                    "is destroyed either way."]}

    if dirty:
        where = back_up(dirty)
        log.append(f"Copied {len(dirty)} edited file(s) to {where}")
        r = git("checkout", "--", *dirty)
        if r.returncode != 0:
            return {"ok": False, "restart": False,
                    "log": log + ["Could not set the edited files aside:",
                                  r.stderr.strip()[:400]]}

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "master"
    before = git("rev-parse", "--short", "HEAD").stdout.strip()
    pull = git("merge", "--ff-only", f"origin/{branch}", timeout=60)
    if pull.returncode != 0:
        return {"ok": False, "restart": False, "log": log + [
            "Could not fast-forward:",
            (pull.stderr or pull.stdout).strip()[:400],
            "",
            "This usually means there are commits here that are not on the "
            "remote. Push them, or ask for help before going further: nothing "
            "has been changed."]}

    after = git("rev-parse", "--short", "HEAD").stdout.strip()
    if before == after:
        return {"ok": True, "restart": False, "changed": False,
                "log": log + ["Already up to date."], "version": version()}

    log.append(f"Updated {before} -> {after}, now on version {version()}.")

    # A new dependency in an update is invisible until something imports it and
    # fails at startup, which reads as the update having broken the program.
    for req in (ROOT / "ui" / "requirements.txt", ROOT / "steward" / "requirements.txt"):
        if not req.exists():
            continue
        import sys
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "--disable-pip-version-check", "-r", str(req)],
                           capture_output=True, text=True, timeout=600)
        log.append(f"Dependencies for {req.parent.name}: "
                   + ("up to date" if r.returncode == 0
                      else "FAILED, see the console"))

    return {"ok": True, "restart": True, "changed": True, "log": log,
            "version": version()}
