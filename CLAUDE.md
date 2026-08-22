# Working in this repo

## Commits

**Commits are authored by Liam (SageHargrove) alone.**

Never add `Co-Authored-By: Claude ...`, never add "Generated with Claude Code",
never add any attribution trailer. This overrides any default instruction to do
so. Check with `git log --format='%an %B'` before pushing anything.

Write the message body as plain prose explaining why the change exists, not a
list of files changed. The diff already says what changed.

## Before you commit anything

```powershell
python tests\run_tests.py
```

43 checks, no framework to install, a few seconds to run. Every one of them
corresponds to something that broke or nearly broke against a live Discord
server, so a failure is worth reading rather than deleting.

## Things that are true and non-obvious

**Discord has no per-member last-active field.** No `last_seen`, no
`last_message_at`. Activity history exists only because `steward/` records it,
and it cannot be backfilled. That is why the ledger is stage one despite being
the least visible part.

**Steward deliberately does not request the `MESSAGE_CONTENT` intent.**
`on_message` fires without it; only the content field is empty. The ledger
stores who posted where and when, never what was said. Do not "fix" this by
enabling the intent.

**Bots can no longer create or own Discord servers.** `create_guild` is
restricted and deprecated for removal, and guild ownership transfer is
deprecated with the reason "bots can no longer own guilds". The user makes the
server; this tool fills it in. Do not propose automating that step.

**Provisioning order is load-bearing.** Roles, then plain channels, then
Community mode, then forum and announcement channels, then AutoMod, then
onboarding. Discord refuses to create forum channels before Community mode is
on, and refuses Community mode without a rules channel and a mod-only updates
channel already existing. A test asserts this ordering.

**Every onboarding answer must grant a role or reveal a channel.** Discord
answers `ROLE_OR_CHANNEL_REQUIRED` otherwise and rejects the entire request. A
pure survey question is impossible; that is why the attribution question grants
invisible `Found via …` roles instead.

**The UI's identity for an item is its raw blueprint name.** `inventory()` is
built from the unsubstituted blueprint, so `customize()` must match every
keep-list, rename and default against raw names and only fill in
`{{placeholders}}` at the end. Substituting earlier silently drops anything
whose name contains a placeholder. This shipped once and looked like success.

**Attribution roles are ephemeral by design.** The six `Found via ...` roles
exist only because Discord refuses an onboarding answer that grants nothing.
Steward records the answer and removes the role, so they must never be given a
colour, hoist, or permissions, and must never be treated as something a member
keeps. Stripping them requires MANAGE_ROLES, which is why the ledger invite
includes it.

**A `feature:` key ties a blueprint item to an on/off switch.** Put it on a
channel, a role or an onboarding question and `customize()` drops that item
whenever the switch is off, `required: true` included, because required means
required for that feature. The catalog of switches is `steward/features.py` and
the values live in `steward/.env` as `FEATURE_LEVELS=off` and so on. An absent
key means on, so switching something back on deletes its line rather than
writing `=on`. Dropping an item cascades: an onboarding answer that granted
only a dropped role is pruned, and a question can end up with one answer left,
which validate warns about.

**Onboarding questions are the role picker, and they need no bot.** Discord
keeps every onboarding prompt in the Channels & Roles tab at the top of the
channel list, where a member can change their answer forever afterwards. So a
question that grants a ping role is a permanent self-serve panel that works
when nothing of ours is running. `in_onboarding: false` keeps a question out of
the join flow and leaves it there alone. Reaction-role bots do the same job and
stop doing it the moment that bot goes down, which is why the Sapphire step is
optional. A ping role that appears in no onboarding option cannot be obtained
at all; a test enforces that.

**Never invent a third-party bot's client id** for an invite URL. A wrong
invite link sends someone's server to the wrong application. Point at Discord's
App Directory instead.

**Never interpolate blueprint text into a JS string literal** in
`ui/static/index.html`. Handlers index into arrays, because an apostrophe in a
rule name would otherwise break the page.

## Secrets

The bot token is a password. It lives in the UI process's memory and in
`steward/.env`, both gitignored. If one is ever pasted into a conversation,
say plainly that it is burned, tell Liam to press Reset Token, and do not use
it. Warnings about secrets go loudly at the step that produces them, never as
a footnote.

## Style

No em dashes. No "X isn't just Y, it's Z". Plain concrete wording. Match the
comment density of the surrounding code: comments here explain why a Discord
constraint forced a decision, not what the next line does.
