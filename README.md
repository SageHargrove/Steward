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

## What it writes for you

The rules and the welcome post are real documents, not placeholders, and the
tool posts and pins them:

```
blueprint/content/rules.md        16 rules, an enforcement ladder, and the
                                  list of things that skip it
blueprint/content/start-here.md   what this is, where things happen, which
                                  roles to pick up, what the ledger records
```

Edit the markdown and re-run; it edits the messages already there rather than
posting duplicates, and deletes any it previously posted that the file no
longer contains. A line containing only `<!-- split -->` starts a new Discord
message, because Discord caps a message at 2000 characters and the provisioner
refuses to send anything longer. `{{game}}` works inside these files too.

It also sets the welcome screen, points Discord's join notices at `#general`,
silences the setup-tip nagging, sets an AFK channel and turns on the boost
progress bar. All of those have endpoints that most guides tell you to click
through by hand.

## What a role colour can actually be

Worth knowing before designing a tier ramp, because the limits are lower than
most people expect.

| | needs boosts |
|---|---|
| Any solid hex colour | no |
| A fade between two hex colours you pick | 3 boosts |
| Discord's animated sheen, in colours Discord fixes | 3 boosts |

That is the whole list. **There is no glow, no halo, no drop shadow, and no
custom animation at any boost level**, so an effect built in CSS elsewhere will
not transfer. A role name is one colour, or a fade between two, or the one
animated style Discord ships.

The tiers in this blueprint are therefore exact solid colours that work on a
server with zero boosts, and only the top one asks for the animated style. On a
server without boosts it falls back to its plain colour, which is also what
Discord does by itself if boosts later lapse.

Every role's colour is editable in the setup page, not only ones you add, with
the name drawn in its own colour so a ramp can be judged where it is set.

## One bot instead of four

A server that installs a leveling bot, a stats bot and a logging bot ends up
with three copies of its own activity sitting in three companies' databases.
Steward already has the data, so it does those jobs too.

**Levels.** XP per message with a cooldown so it cannot be farmed, XP for time
in voice, `/rank` and `/leaderboard`, and role rewards wired to the star tiers.
The word members see is set in the blueprint: call a level a Level, a Rank, or
anything that does not collide with a number your game already shows players.
Level-ups reply to the message that caused them rather than announcing into a
channel, because a level-up firehose is the fastest way to make people mute you.

**The weekly digest.** Joins, posters and messages against last week, this
week's join funnel, and how many of each earlier week's arrivals came back.
That last one is the number the whole project is about, and it needs a history
nobody else kept. `/digest` posts it on demand.

**Charts**, when there is enough to plot. Two stacked panels rather than one
chart with two y-axes: joins and active posters live on different scales, and
twin axes would let the drawing imply a relationship the data does not have.
Below ten days of activity it prints numbers and a text sparkline instead,
because a line through three points says less than the three numbers.
matplotlib is optional; without it the digest still posts.

**The moderation log.** Bans, kicks, timeouts, role changes, nickname changes,
channel and role deletions, each with who did it, read from the audit log.
Message deletions are logged as metadata only. Steward never asks Discord for
permission to read message content, so it cannot quote a deleted message, and
the log says so rather than leaving a moderator wondering.

What is deliberately left to Wick: anti-nuke and CAPTCHA verification. Those
are security-critical and hard, and a half-built version is worse than none.

## Attribution without cluttering profiles

"How did you find us?" is the one number Discord will not give you: Server
Insights needs 500 members and is coarse even then. But Discord rejects any
onboarding answer that grants neither a role nor a channel, so the question
cannot be a pure survey.

The answer grants a role for about a second. Roles marked `ephemeral: true` in
the blueprint are recorded into the ledger by Steward, which then takes the
role straight back off. Nobody wears "Found via Reddit" on their profile, and
`/ledger-status` still shows the split.

This only works while Steward is running. If it is off, the roles sit on
members until it next starts and sweeps them, or until you run `/sweep-roles`.
If you are not going to run Steward, delete the question instead of leaving it
half-working. If the strip fails for lack of permission, the answer is still
recorded and the bot says so once, because the number matters more than the
tidiness.

## Tests

```powershell
python tests
un_tests.py
```

42 checks, no test framework to install. `tests/fake_discord.py` stands in for
the REST API and records every call, so the suite can assert on ordering as
well as on the result. The web-layer tests boot the real server on a spare port
and drive it over HTTP rather than mocking it.

Run it with the same interpreter that runs the app. Every check corresponds to
something that either did break or would have broken silently against a live
server, so a failure here is worth reading rather than deleting:

- **Phase ordering.** Forum and announcement channels cannot be created before
  Community mode is on, and Community mode needs its two channels to exist
  first. Get this wrong and the run half-applies.
- **Idempotency.** A second run must create nothing and duplicate nothing.
- **Dry run sends no writes at all.**
- **Every onboarding answer grants a role or a channel.** Discord rejects the
  whole request otherwise. This one reached a live server before it was caught.
- **Pruning never produces an answer that grants nothing**, which is how that
  bug would come back.
- **Deletion refuses @everyone, bot-managed roles, and anything the run just
  created**, whatever the browser asks for.
- **The token never appears in a response**, cross-origin posts are refused,
  and the blueprint loader cannot be walked out of its folder.

## Backups

`steward/data/steward.sqlite3` is the asset. Roughly 120 bytes per event
including indexes, so 500 messages a day for a year is about 22 MB. Add it to
whatever already backs up `saves/`.
