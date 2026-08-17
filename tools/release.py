"""Cut a version.

    python tools/release.py 0.4.1
    python tools/release.py 0.4.1 --notes "Fixed the calendar double-posting"
    python tools/release.py 0.4.1 --build      also build and attach the download
    python tools/release.py --dry-run 0.5.0

Bumps VERSION, commits it, tags it, and pushes. With the GitHub CLI installed
it also publishes a release, which is what makes the update check work for
anyone who is not running from a checkout.

With --build it also assembles the no-Python-needed download and attaches it.
Without that the release page offers only source archives, which are no use at
all to somebody who does not have Python, which is most of the audience.

The version number is the whole point of the ceremony. Without one, "are you
on the latest?" has no answer, and every bug report starts with an argument
about which code somebody is running.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provision"))

import updates                                              # noqa: E402


def run(*args, check=True, capture=True):
    r = subprocess.run(list(args), cwd=str(ROOT), text=True,
                       capture_output=capture)
    if check and r.returncode != 0:
        sys.exit(f"\n  {' '.join(args)} failed:\n  "
                 + (r.stderr or r.stdout or "").strip()[:600])
    return r


def main():
    ap = argparse.ArgumentParser(description="Cut a version and push it.")
    ap.add_argument("version", help="the new version, like 0.2.1")
    ap.add_argument("--notes", default="", help="one line for the release notes")
    ap.add_argument("--build", action="store_true",
                    help="also build the download and attach it to the release")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would happen and change nothing")
    args = ap.parse_args()

    new = args.version.lstrip("vV").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        sys.exit(f"  {new!r} is not a version. Use three numbers, like 0.2.1.")

    current = updates.version()
    if not updates.newer(new, current):
        sys.exit(f"  {new} is not newer than the current {current}. Version "
                 f"numbers only go up, or the update check cannot tell which "
                 f"way is forward.")

    # A release built from a tree with uncommitted work is a release nobody can
    # reproduce, including you.
    dirty = run("git", "status", "--porcelain").stdout.strip()
    if dirty:
        print("\n  There is uncommitted work:\n")
        for line in dirty.splitlines()[:20]:
            print("   ", line)
        sys.exit("\n  Commit or stash it first. A tagged version has to match "
                 "what is actually in the repository.")

    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    tag = f"v{new}"
    if run("git", "tag", "-l", tag).stdout.strip():
        sys.exit(f"  {tag} already exists. Pick another number; a tag that "
                 f"moves is worse than no tag.")

    notes = args.notes.strip() or f"Version {new}"
    print(f"\n  {current} -> {new} on {branch}")
    print(f"  tag:   {tag}")
    print(f"  notes: {notes}\n")

    if args.dry_run:
        print("  Dry run. Nothing was changed.\n")
        return

    updates.VERSION_FILE.write_text(new + "\n", encoding="utf-8")
    staged = ["VERSION"]

    # The Inno Setup script carries its own copy, because a .iss cannot read a
    # file at compile time. Bumped here so the two cannot drift apart, and a
    # test fails if they ever do.
    iss = ROOT / "install" / "setup.iss"
    if iss.exists():
        text = iss.read_text(encoding="utf-8")
        bumped = re.sub(r'(#define AppVersion\s+")[^"]*(")',
                        lambda m: m.group(1) + new + m.group(2), text, count=1)
        if bumped != text:
            iss.write_text(bumped, encoding="utf-8")
            staged.append("install/setup.iss")

    run("git", "add", *staged)
    run("git", "commit", "-m", f"Release {new}\n\n{notes}")
    run("git", "tag", "-a", tag, "-m", notes)
    run("git", "push", "origin", branch)
    run("git", "push", "origin", tag)
    print(f"  Pushed {tag}.")

    # gh is optional. Without it the tag is still pushed, and anyone on a
    # checkout updates from it; only the release-API channel needs this.
    gh = run("gh", "--version", check=False)
    if gh.returncode != 0:
        print("\n  The GitHub CLI is not installed, so no release was published.")
        print("  Anyone on a git checkout can still update. Publishing a")
        print("  release additionally covers people who are not, but that only")
        print("  works while the repository is public.\n")
        return

    r = run("gh", "release", "create", tag, "--title", tag, "--notes", notes,
            check=False)
    if r.returncode == 0:
        print(f"  Published the release for {tag}.")
        if args.build:
            # Without this the release page offers only source archives, which
            # are no use to somebody who does not have Python.
            print("  Building the download. This takes a few minutes.")
            b = run(sys.executable, str(ROOT / "tools" / "build_dist.py"),
                    "--clean", "--zip", check=False, capture=False)
            zip_path = ROOT / "dist" / f"Steward-{new}-windows.zip"
            if b.returncode == 0 and zip_path.exists():
                u = run("gh", "release", "upload", tag, str(zip_path), "--clobber",
                        check=False)
                print(f"  Attached {zip_path.name}." if u.returncode == 0 else
                      f"  Could not attach it: {(u.stderr or '').strip()[:200]}")
            else:
                print("  The build failed, so nothing was attached. The tag and "
                      "the release are still published.")
        print()
    else:
        print("\n  The tag is pushed but publishing the release failed:")
        print("  " + (r.stderr or r.stdout).strip()[:400])
        print("  Publish it by hand, or run: "
              f"gh release create {tag} --notes \"{notes}\"\n")


if __name__ == "__main__":
    main()
