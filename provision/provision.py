"""
Apply a server blueprint to a Discord guild, from the command line.

    python provision.py --blueprint ../blueprint/giltgrave.yaml --validate
    python provision.py --guild 123... --blueprint ../blueprint/giltgrave.yaml --dry-run
    python provision.py --guild 123... --blueprint ../blueprint/giltgrave.yaml

For a UI instead of flags, run ../ui/app.py.

Idempotent: matches existing roles, channels and AutoMod rules by name and
updates them in place, so re-running after editing the blueprint is the normal
workflow rather than a recovery path.

What it cannot do, because Discord does not allow it: create the server (bots
can no longer own guilds) or install other bots (an OAuth flow needing a human
click). Run with --manual to print those steps.

Token comes from --token or the DISCORD_TOKEN environment variable.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import core


def print_report(report: dict, verbose=True):
    s = report["summary"]
    if verbose:
        print(f"  {s['roles']} roles, {s['channels']} channels in {s['categories']} "
              f"categories, {s['automod']} automod rules")
        print(f"  onboarding: {s['defaults']} default channels ({s['defaults_open']} "
              f"fully open), {s['prompts']} prompts")
        print(f"  community mode: {'on' if s['community'] else 'off'}")
    for w in report["warnings"]:
        print(f"  warning  {w}")
    for e in report["errors"]:
        print(f"  ERROR    {e}")
    return report["errors"]


def main():
    ap = argparse.ArgumentParser(description="Apply a server blueprint to a Discord guild.")
    ap.add_argument("--blueprint", required=True, type=Path)
    ap.add_argument("--guild", help="guild (server) id")
    ap.add_argument("--token", default=os.environ.get("DISCORD_TOKEN"))
    ap.add_argument("--var", action="append", default=[], metavar="KEY=VALUE",
                    help="fill a {{placeholder}} in the blueprint. Repeatable")
    ap.add_argument("--server-name", help="rename the server itself")
    ap.add_argument("--icon", type=Path, help="local image file to set as the server icon")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would happen, change nothing")
    ap.add_argument("--validate", action="store_true",
                    help="check the blueprint offline and exit. No token needed")
    ap.add_argument("--manual", action="store_true",
                    help="print the steps no API can perform, and exit")
    args = ap.parse_args()

    if args.manual:
        for step in core.manual_steps():
            print(f"\n[{step['kind']}] {step['title']}")
            if step.get("where"):
                print(f"  where: {step['where']}")
            print(f"  why:   {step['why']}")
            if step.get("url"):
                print(f"  link:  {step['url']}")
        return

    if not args.blueprint.exists():
        sys.exit(f"No blueprint at {args.blueprint}")

    variables = {}
    for pair in args.var:
        if "=" not in pair:
            sys.exit(f"--var wants KEY=VALUE, got {pair!r}")
        k, v = pair.split("=", 1)
        variables[k] = v

    blueprint = core.customize(core.load(args.blueprint), {"variables": variables})
    name = blueprint.get("meta", {}).get("name", args.blueprint.stem)

    if args.validate:
        print(f"Validating {args.blueprint}")
        if print_report(core.validate(blueprint)):
            sys.exit("\nBlueprint has errors.")
        print("\nBlueprint is valid.")
        return

    if not args.guild:
        sys.exit("--guild is required (or use --validate to check the blueprint offline)")
    if not args.token:
        sys.exit("No token. Pass --token or set DISCORD_TOKEN.")

    print(f"Blueprint: {name}")
    print(f"Guild:     {args.guild}")
    if args.dry_run:
        print("Mode:      DRY RUN, nothing will be changed")

    # Always validate before touching the guild. A half-applied blueprint is
    # worse than an unapplied one.
    print()
    if print_report(core.validate(blueprint)):
        sys.exit("\nNothing was changed.")

    icon = args.icon.read_bytes() if args.icon else None
    client = core.Client(args.token, dry_run=args.dry_run)
    prov = core.Provisioner(client, args.guild, blueprint)
    try:
        problems = prov.run(server_name=args.server_name, icon=icon,
                            icon_name=args.icon.name if args.icon else "icon.png")
    except core.Failed as e:
        sys.exit(f"\nFailed:\n{e}")

    print("\nDone." if not problems else f"\nDone, with {len(problems)} problem(s) above.")
    print("Run with --manual for the steps no API can perform.")


if __name__ == "__main__":
    main()
