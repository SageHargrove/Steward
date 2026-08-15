# community-ops

The Giltgrave community server, the automation behind it, and the reusable
thing both become.

Planning lives one level up in [docs/build-plan.md](docs/build-plan.md) and
[docs/roadmap.md](docs/roadmap.md). The rest of this repo is the implementation.

```
blueprint/giltgrave.yaml    the server spec. Channels, roles, permissions,
                            forum tags, onboarding prompts, AutoMod rules
provision/core.py           load, template, customize, validate, apply.
                            The CLI and the UI both import this
provision/provision.py      command-line wrapper
ui/app.py                   Server Setup for Discord, the local UI
steward/                    the bot. Stage one: the activity ledger only
SETUP.md                    the runbook. Start there
```

**Server Setup for Discord is the easy path.** Run `ui/SETUP-UI.bat`. Six
numbered steps, with the Developer Portal walkthrough built in so it assumes
you have never made a bot before, and it generates your invite link once you
paste a token. The CLI does the same job with flags.

## State

| | |
|---|---|
| Blueprint | validates clean: 10 roles, 21 channels, 7 categories, 5 AutoMod rules, 3 onboarding prompts |
| Core | verified against a stubbed Discord API: phase ordering, idempotency (second run makes 0 creates, 45 updates), dry-run writes nothing |
| UI | boots and serves; connect / invite / refresh / customize / apply / cleanup all exercised against a stubbed API |
| Ledger | logic smoke-tested against a temp database |
| Server | **not created.** Nothing here has touched real Discord |

Section 0 of [SETUP.md](SETUP.md) is the first thing that does.

## What cannot be automated, and why

Worth knowing before you look for a button that is not there. Checked against
the current API rather than assumed:

- **Creating the server.** `create_guild` is restricted to bots in fewer than
  10 guilds and is deprecated for removal. Guild ownership transfer is
  deprecated too, with the reason given as *"bots can no longer own guilds."*
  So you make the server; this tool fills it in.
- **Installing other bots.** Each is an OAuth flow needing a human with Manage
  Server to click. Every server-blueprint product ever built has this step.
- **Rules Screening, Server Guide, Raid Protection.** No API surface at all.

Everything else in the blueprint is automated, including the parts Discord's
own server templates drop.

## The three layers

From the build plan, unchanged:

1. **Blueprint** — the architecture, written as a spec rather than as clicks.
   `blueprint/giltgrave.yaml`.
2. **Configured stack** — native Discord plus four free bots (Sapphire, Wick,
   Statbot, Steamy). Section 3 of the runbook. Do not build what Sapphire
   already does for free.
3. **Steward** — the custom bot. The proactive layer, which is the part that
   does not exist in any product today. Staged over months.

Layer 3 is the eventual product. Layers 1 and 2 are what make the server good
next week.

## Why the provisioner exists early

The build plan says build the provisioner last, and the reasoning is sound:
a provisioner that deploys an unvalidated blueprint makes the same mistakes
twice. It is here anyway for two reasons that do not contradict that.

It saves a day of clicking, and more importantly it forces the blueprint to be
executable rather than descriptive. A spec you have never run is a document,
and a document is not the thing you sell. Discord's own server templates are
not an alternative: they capture roles, channels, permission overwrites and
server settings, but explicitly not forum, announcement or stage channels, not
bots, not AutoMod rules, and not onboarding configuration. Roughly half this
blueprint is in the part templates drop.

What stays deferred is everything downstream of one server: multi-guild
management, a config UI, drift detection. Those wait until server #2 exists.

## Why the ledger is stage one

Discord's API has no per-member last-active field. `joined_at`, roles,
nickname, flags, and nothing about activity. No `last_seen`, no
`last_message_at`. Every "who went quiet" feature ever built is derived from an
event stream someone recorded themselves, which is why Statbot's value is its
historical database rather than its API access, and why its free tier caps
history at 30 days.

You cannot backfill it. Data not recorded on day one is gone. That single fact
is why the least visible thing in the plan goes first.

Steward deliberately does **not** request the `MESSAGE_CONTENT` intent.
`on_message` fires without it and only the content field comes back empty. The
ledger records who posted where and when, never what was said. Less to
protect, an honest answer when a member asks what is stored, and no annual
reapplication once the app passes 10,000 users.

## Playbook artifacts

The documentation is the deliverable, not the notes. Six files, written in the
same sitting as the work, not reconstructed afterward. Three exist:

- [x] `blueprint/giltgrave.yaml` — the machine-readable server spec
- [x] `SETUP.md` — the runbook, including the manual steps and why they are manual
- [ ] `onboarding-flow.md` — the questions, why each one, what each answer grants,
      and what changed when you changed them
- [ ] `content-calendar.yaml` — T-minus-relative beats. The single most reusable
      artifact in the set, and the one the calendar engine reads
- [ ] `moderation.md` — escalation ladder and what you actually had to intervene on
- [ ] `playtest-pipeline.md` — recruitment, gating, key handling, feedback routing
- [ ] `outreach-tracker.csv` — creators and press. A tracking artifact, not an
      automation: outreach by Discord DM is prohibited

The discipline that makes or breaks this is writing the reusable version in the
same sitting you do the thing. After launch you write a worse version from
memory, and the memory smooths out exactly the parts that were hard, which are
the parts a studio would pay for.

## Running things

```powershell
# the UI: everything below, with checkboxes
ui\SETUP-UI.bat

# or the command line
cd provision
python provision.py --blueprint ..\blueprint\giltgrave.yaml --validate
python provision.py --blueprint ..\blueprint\giltgrave.yaml --manual

$env:DISCORD_TOKEN = "..."
python provision.py --guild SERVER_ID --blueprint ..\blueprint\giltgrave.yaml --dry-run
python provision.py --guild SERVER_ID --blueprint ..\blueprint\giltgrave.yaml `
    --var game="One Trick" --server-name "One Trick"

# the ledger
cd ..\steward
python bot.py
```

## Customizing without editing YAML

The UI reads the blueprint and turns it into a form, so someone who wants
`#general`, `#bug-reports` and nothing else gets exactly that. Three mechanisms
make that safe:

**Fill in the blanks.** Anything written `{{game}}` in the blueprint becomes a
form field. This is what makes a blueprint redeployable to the next project
rather than being a config file for one server.

**Removals clean up after themselves.** Drop the `Playtester` role and every
permission overwrite naming it, every onboarding answer granting it, and every
AutoMod exemption listing it are pruned automatically. Renaming `#mod-log`
retargets the four AutoMod alerts and the safety-alerts setting that point at
it. Those are mechanical consequences, not user errors, so they never surface
as validation failures.

**Add, remove, rename.** The list shown is what gets built. Remove drops an item
to the bottom of its group so it can be put back; the Add row at the foot of each
group takes your own channels and roles; every name is an editable field. Nothing
is a greyed-out checkbox, and the handful of genuinely unavoidable items say
"cannot remove" with the reason next to them.

**Cleaning up what Discord left.** Every new server arrives with a Text Channels
category, a Voice Channels category and a General voice channel. The tool reads
the server, hides anything the blueprint adopts by name, and offers the rest for
deletion. Nothing is deleted unless explicitly ticked, and @everyone, bot
integration roles, and anything the run just created are refused outright.

**Live validation on every toggle.** Discord's real constraints are checked
before anything is sent, with messages that say what to do: onboarding's 7
defaults / 5-fully-open rule, AutoMod's per-trigger ceilings, regex over 260
characters, timeout actions on triggers that do not support them, and forum
channels selected while Community mode is off. Apply stays disabled until the
errors are gone.

A few things cannot be unticked, and say why on hover: `#rules` and
`#server-updates` while Community mode is on, because Discord will not enable
Community without them. Turn Community off and they become optional like
anything else.

`--validate` catches the failures that are otherwise opaque 400s halfway
through a run: unknown permission names, undeclared roles in overwrites,
Discord's onboarding channel minimums (7 defaults, 5 of them fully open),
AutoMod per-trigger limits, regex over 260 characters, and timeout actions on
trigger types that do not support them.

## Backups

`steward/data/steward.sqlite3` is the asset. Roughly 120 bytes per event
including indexes, so 500 messages a day for a year is about 22 MB. Add it to
whatever already backs up `saves/`.
