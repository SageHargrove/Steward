# Setup runbook

Ordered. Roughly 90 minutes end to end, most of it waiting on Discord's UI.
Sections 1 to 3 are the server. Section 4 is the free bot stack. Section 5 is
Steward. Section 6 is the soft launch.

Do not skip section 0. The bot app has to exist before anything else works.

---

## 0. Prerequisites, 10 minutes

**These same instructions are built into the UI**, step 1, with the exact
button labels. If you are using the UI you can skip this section and follow it
there instead.

### Create the server

1. In the Discord app, look at the narrow column of round server icons on the
   far left.
2. At the bottom of that column, click the green **+** button. Its tooltip
   says *Add a Server*.
3. Click **Create My Own**, then **For me and my friends**.
4. Name it **Giltgrave** and click **Create**.

You are now its owner, which matters below. You do not need the server id: the
UI lists your servers by name, and the CLI takes it from Developer Mode
(User Settings, Advanced, Developer Mode on, then right-click the server icon,
Copy Server ID).

### Create the bot

A "bot" here is just an account you own that the tool logs in as. You will not
write any bot code. It exists so that something has permission to create your
channels.

1. Open <https://discord.com/developers/applications>. Log in with your normal
   Discord account. There is no separate developer account.
2. Top right, click **New Application**.
3. Name it `Steward`. Tick the box agreeing to the Developer Terms of Service,
   then click **Create**. This name is internal and changeable.
4. You land on **General Information**. In the left-hand menu, click **Bot**.

Everything from here is on that one page, working straight down it. You should
not need to scroll back up.

5. **Token**, the first section. Click **Reset Token**, confirm with
   **Yes, do it!**, and enter your 2FA code if your account has one.
6. Click **Copy**, and paste it somewhere safe immediately, or straight into
   the tool. Discord shows a token once and never again; lose it and you press
   Reset Token for a new one, which invalidates the old.
7. Next section down, **Authorization Flow**. Turn **Public Bot OFF**, so
   nobody else can add your bot to their server.
8. Next section down, **Privileged Gateway Intents**. Turn **Server Members
   Intent ON**. Leave **Presence Intent** and **Message Content Intent** OFF.

   Server Members is what lets the ledger see joins and leaves. Message Content
   stays off on purpose: the ledger records who posted where and when, never
   what was written. Less to protect, an honest answer when a member asks what
   is stored, and it sidesteps the annual reapplication that Message Content
   requires once an app passes 10,000 users.
9. Click **Save Changes** in the green bar at the bottom. Skip this and the two
   switches above do not stick, and the ledger fails to start later with no
   obvious reason why.

> **The token is a password.** Do not paste it into a chat, a screenshot, a
> message, an AI assistant, or a repo. Anyone who sees it controls the bot
> until you reset it. If one does leak, the fix is quick and free: Developer
> Portal, your app, Bot, **Reset Token**. The old one dies instantly. Discord
> also auto-revokes tokens it finds in public GitHub repos, but it will not
> catch one pasted into a conversation, so that reset is on you.

### Add the bot to the server

**If you are using the UI, it builds this link for you** once you paste the
token, because a bot's user id is its application id. Just click the button and
pick your server.

By hand, substitute your Application ID (Developer Portal, General
Information):

```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=8
```

Pick your server in the **ADD TO SERVER** dropdown, then **Continue** and
**Authorize**.

`permissions=8` is Administrator, and it is deliberate for the first run: the
blueprint creates a `Dev` role carrying Administrator, and Discord refuses to
let a bot grant a permission it does not hold itself. It is your own server and
the bot is private.

Afterwards you can drop it to the ledger-only set, `permissions=2147568640`
(view channels, send messages, read history, embed links, slash commands), by
editing the bot's role in Server Settings, Roles. The provisioner will then
fail loudly if you re-run it, which is the correct behaviour.

---

## 1. Apply the blueprint

### The easy way: Server Setup for Discord

```powershell
C:\CommunityOps\ui\SETUP-UI.bat
```

It installs what it needs, starts a local server on `127.0.0.1:8770` and opens
your browser. Six numbered steps: connect the bot, add it to the server (it
generates the invite link for you, so you never assemble a URL by hand), pick
the server, tick what you want, build, then work down the by-hand checklist.
There is a Dry run button that shows you every change without making any of
them.

The token lives in that process's memory for as long as it runs. It is never
written to disk and never sent back to the page. Closing the window forgets it.
The server refuses any request from another origin, so a page in another tab
cannot drive it.

Everything in section 2 and 3 below appears as a checklist at the bottom of the
page, so you can work down it without switching back here.

The rest of this section is the command-line equivalent. Skip to section 2 if
you used the UI.

### The command line

```powershell
cd C:\CommunityOps\provision
python -m pip install -r requirements.txt

# Check the spec offline first. No token, no network, no changes.
python provision.py --blueprint ..\blueprint\giltgrave.yaml --validate

$env:DISCORD_TOKEN = "your-bot-token"

# See what it would do.
python provision.py --guild YOUR_SERVER_ID --blueprint ..\blueprint\giltgrave.yaml --dry-run

# Do it.
python provision.py --guild YOUR_SERVER_ID --blueprint ..\blueprint\giltgrave.yaml
```

It runs in this order, and the order is load-bearing: roles, then categories
and plain text/voice channels, then Community mode (which needs `#rules` and
`#server-updates` to already exist), then the forum and announcement channels
(which Discord refuses to create before Community mode is on), then AutoMod,
then onboarding, then role ordering.

**It is idempotent.** Verified against a stubbed API: a second run makes zero
creates and 45 updates, with no duplicates. So changing the server means
changing the blueprint (or the UI selection) and re-running, rather than
clicking around in Discord's settings. The blueprint is the artifact you
eventually sell, and a server that has drifted from its spec is worth nothing
as a product.

**Fill-in-the-blanks.** Anything written `{{game}}` in the YAML is a variable.
The UI shows them as form fields; on the command line pass `--var game="One
Trick"`. This is what lets One Trick fork this blueprint instead of starting
over.

### If something fails

- **A role says NOT CREATED with a 403.** The bot lacks a permission the role
  wants. Re-invite with `permissions=8`.
- **Onboarding rejected.** Almost always the channel minimum: Discord needs 7
  or more default channels, at least 5 of which let `@everyone` both view and
  send. `--validate` checks this offline, so if validate passed, look at the
  raw error it printed instead.
- **An AutoMod rule says `!`.** Rules are applied independently and one failing
  does not abort the run. Usual causes are a regex Discord's Rust engine
  rejects (no lookahead, no backreferences) or exceeding a per-trigger limit.
- **Role order not applied.** Expected and harmless. Nothing can be positioned
  above the bot's own integration role. Drag them in Server Settings, Roles.

### Verify

Server Settings should now show: Community enabled, Onboarding with 3
questions, AutoMod with 5 rules, and 21 channels across 7 categories.

---

## 2. The things the API cannot do

Five minutes of clicking. None of it is automatable and no product in this
space automates it either.

1. **Rules Screening.** Server Settings, Safety Setup, Rules Screening.
   Paste the rules (max 16). Draft below in section 7.
2. **Server Guide.** Server Settings, Onboarding, Server Guide tab. Add
   `#start-here`, `#announcements`, `#bug-reports` as resource pages with a
   line each. This is the panel new members see first.
3. **Raid Protection.** Server Settings, Safety Setup, Raid Protection ON.
   ML join-spike detection that CAPTCHAs new joiners for an hour when it
   fires. Turn it on now, not after your first raid.
4. **Server icon.** Either upload by hand or pass `--icon path\to\icon.png`
   to the provisioner.
5. **Post the pinned content** in `#start-here`. Nothing else in the server
   works if that channel is empty.

---

## 3. Install the free bot stack

**You cannot automate this.** Bot installation is an OAuth flow requiring a
human with Manage Server to click through. Every server-blueprint product ever
built has a manual bot-setup step; design around it rather than fighting it.

Install in this order, because each one's config references channels the
previous one assumes exist.

| Bot | Job | Config after install |
|---|---|---|
| **Wick** | Anti-nuke, heat-system automod, captcha verification, join gate that filters new and avatarless accounts | Set the join gate to reject accounts under 7 days old. Log channel `#mod-log` |
| **Sapphire** | Moderation, join roles, reaction roles, logging | Logging to `#mod-log`. Skip its join-role feature, onboarding already handles roles |
| **Statbot** | Charts, counters, activity roles | Connect and forget. Its free tier caps history at 30 days, which is exactly why Steward's ledger exists |
| **Steamy** | Posts new Steam reviews to Discord, weekly rating digests | Install the day the Steam page exists, not before. Target `#patch-notes` |

Skip MEE6 (about $12/month per server, and levels and social alerts are behind
the paywall), Carl-bot, Dyno, Arcane. Sapphire covers the overlap for free.

**BetaHub** is optional and worth a look later: its Listen Mode files a bug
report automatically when a player just mentions a problem in chat, no command
and no form. Hold off until the forum has enough traffic that triage is a
chore, because before that it adds noise.

---

## 4. Start the ledger

Do this the same day the server exists, and before you invite anyone.

Step 7 of the setup page runs it: **Install what it needs**, then **Start**.
It shows a green dot while recording, the last of its output, and a Stop
button. Started that way it is detached, so closing the setup page leaves it
running.

`steward\START-LEDGER.bat` does the same thing from a terminal, in its own
window.

Either way it needs `steward\.env` with your bot token. The batch file creates
that from the example and opens it in Notepad; if you use the page, make the
file first.

**If it stops with a message about privileged intents**, the Server Members
Intent is not enabled. Developer Portal, your app, Bot, Privileged Gateway
Intents, turn on Server Members Intent, and press Save Changes in the green bar
at the bottom. That last step is the one people miss.

On first connect it seeds every current member from Discord's `joined_at`,
which is the one field that can legitimately be backfilled. Everything else
starts from zero the moment the process starts.

Check it with `/ledger-status` in any channel. Staff only, ephemeral.

On startup discord.py warns `PyNaCl is not installed, voice will NOT be
supported`. Ignore it. That is about transmitting voice audio. Steward only
reads voice *state* changes (who joined which channel and when), which needs
no audio support.

**Why this cannot wait.** Discord's API has no per-member last-active field.
The Guild Member object gives you `joined_at`, roles, nickname and flags, and
nothing about activity. There is no `last_seen`, no `last_message_at`. Every
"who went quiet" feature anyone has ever built is derived from an event stream
somebody recorded themselves. Days that pass before the bot runs are
permanently missing, and no amount of later work recovers them.

### Keep it running

Local for the friends-only phase is fine. Move it to the Oracle box before the
public announcement. Systemd unit:

```ini
[Unit]
Description=Steward ledger
After=network-online.target

[Service]
WorkingDirectory=/opt/steward
ExecStart=/opt/steward/.venv/bin/python bot.py
Restart=always
RestartSec=10
User=steward

[Install]
WantedBy=multi-user.target
```

**Back up `data/steward.sqlite3`.** It is the asset. About 120 bytes per event
including indexes, so 500 messages a day for a year is roughly 22 MB. Add it
to whatever already backs up `saves/`.

---

## 5. Soft launch to friends

The server is a `@Founding Member` cohort generator and a data source. It is
not a marketing surface yet.

1. **Do not** set a vanity URL or enable Discovery.
2. Create an invite: right-click `#general`, Invite People, Edit invite link,
   **never expire, unlimited uses**. Keep it in this repo's notes, not
   anywhere public.
3. Invite the friends who are playtesting. As each joins, grant
   `@Founding Member` and `@Playtester` by hand.
4. Grant yourself `@Dev`.
5. Post in `#devlog` within the first week. An empty devlog channel reads
   worse than no devlog channel.

`@Founding Member` stops being granted the day you announce publicly. That is
the whole mechanic: it costs nothing and people genuinely care.

### What to watch in the first fortnight

Run `/ledger-status` weekly and write the four numbers down by hand. They are
tiny and that is fine. Small honest numbers with a clean methodology beat big
vague ones, and the case study is built from the series, not the snapshot.

---

## 6. Rules draft

For Rules Screening. Sixteen is Discord's cap, five is enough. Edit before
pasting.

1. Be decent to each other. Disagreement is fine, contempt is not.
2. No slurs, harassment, or sexual content. The filter catches some of it and
   a human catches the rest.
3. No advertising or invite links outside `#looking-for-guild`.
4. Playtest builds are unreleased. Do not post screenshots, footage, or files
   from them outside `#playtest-lounge` until a build is public.
5. Bugs go in `#bug-reports` with a build number and repro steps. A bug
   reported in `#general` is a bug that gets lost.

---

## 7. What is next, in order

The build order below is from the community-ops build plan, unchanged, with
the reasoning compressed.

| # | Thing | When | Why then |
|---|---|---|---|
| 1 | Ledger | **done, this pass** | Impossible to backfill. Everything else reads from it |
| 2 | Cohort reports | ~2 weeks in | First visible payoff. Makes the ledger feel worth it |
| 3 | Calendar engine | ~4 weeks in | The actual daily-labour saver. Reads T-minus-relative beats from `content-calendar.yaml` |
| 4 | Playtest pipeline | when you start recruiting testers | Steam beta keys cap at 2,500 total. Native Steam Playtest has no practical cap and lives on your store page |
| 5 | Decay detection | after ~8 weeks of baseline | Meaningless before that. It is a comparison against a channel's own trend, and there is no trend yet |
| 6 | Funnel metrics | any time | It is a query, not a feature. `/ledger-status` already does the 7-day version |
| 7 | Provisioner | already exists | Built early here because it saved you a day of clicking and forces the blueprint to be real rather than a document. Do not extend it further until server #2 exists |

The temptation will be to build more provisioner. Resist it. A provisioner
that deploys a blueprint you have not validated is a way to make the same
mistakes twice.

---

## 8. The rails, restated because they are architecture

**No mass DM. Ever.** Discord's Developer Policy: "Do not contact users on
Discord without their explicit permission. This includes frequently sending
unsolicited direct messages." The API docs for the create-DM endpoint say
plainly: "You should not use this endpoint to DM everyone in a server about
something." There is an undocumented DM-open quota and blowing it gets you
quarantined with no warning.

This is why `@Ping Me For Playtests` exists. Every proactive reach routes
through channels, roles, mentions, scheduled events, or announcement channels.
That is the only compliant path, and it is also the better product: an opt-in
role is visible, revocable, and does not read as spam.

**Data deletion is a hard requirement,** not a feature. The Developer ToS
obliges you to give users "an easily accessible way to ask for their API Data
to be modified and deleted." `/forget-me` and `/my-data` ship in this pass for
that reason. The retention window is enforced in code (`RETENTION_DAYS`,
nightly purge), not written in a policy document nobody runs.

**Channel Obfuscation goes mandatory 16 November 2026.** Bots stop receiving
full metadata for channels they cannot access; names and permission details
get obfuscated behind a `CHANNEL_OBFUSCATED` flag. The provisioner enumerates
server structure, so it is the thing that will break. Three months' notice.
Put it in the calendar.
