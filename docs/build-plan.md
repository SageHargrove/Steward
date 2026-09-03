# Community Operations — Build Plan

*14 Aug 2026. The Giltgrave server, the automation behind it, and the reusable thing both become.*

---

## Direct answer to your question

**No, you don't need to build a Discord bot to get a polished server.** Almost everything that makes a server feel professional is native Discord or a free third-party bot. If you build a custom bot first you'll spend six weeks rebuilding moderation that Sapphire does better for free.

**Yes, you need to build a bot to get the thing you actually want** — the automated, redeployable, potentially sellable version. But it's a narrow bot doing seven jobs nothing else does, not a general-purpose community bot.

The split matters because it determines what you do in September versus what you do in January. Three layers:

| Layer | What | Effort | When |
|---|---|---|---|
| **1. Blueprint** | Channel/role/onboarding architecture, written as a spec | 1 weekend | Now |
| **2. Configured stack** | Native Discord + four free bots | 1–2 days | Now |
| **3. Steward** *(working name)* | Your custom bot — the proactive layer | Ongoing, staged | Starts week 2, never really finishes |

Layer 3 is the product. Layers 1 and 2 are what make Giltgrave's server good next week.

---

## Before any of it: the Giltgrave decisions that gate everything

You were right to push back on announcing publicly. But there are two separate things and only one of them can wait.

**An internal ship date cannot wait.** It's the anchor every dated artifact in the playbook hangs off. Nobody outside your friends needs to know it.

**Public announcement can absolutely wait** for art. Announce when it looks like the thing you want people to see.

And then there's a third thing I didn't know when I wrote the first roadmap, which changes the calendar meaningfully.

### Steam Next Fest: do not rush October

October 2026 Next Fest registration closes **August 31, 2026, 11:59 PM PDT** — 17 days out. It requires a published, publicly visible store page, and store page review takes 3–5 business days.

**You could make it. You shouldn't.**

A title may participate in **exactly one Next Fest, ever.** And the data is unambiguous that Next Fest amplifies an existing audience rather than creating one:

| Wishlists entering the fest | Median wishlists gained |
|---|---|
| 0–999 | **322** |
| 1,000–9,999 | 1,006 |
| 10,000–99,999 | 5,215 |
| 100,000+ | 12,882 |

*(Feb 2026 survey, n≈170. Spearman r = 0.825 between pre-fest wishlists and wishlists earned.)*

June 2026's fest had **4,000+ demos** — the largest ever — and games entering with under 1,000 wishlists were, in the analyst's word, drowned out. Burning your one-and-only slot to gain ~322 wishlists would be the single most wasteful thing available to you.

**Target February 2027 instead.** Registration closes Jan 10, 2027; the fest runs Feb 22 – Mar 1. That gives you five months to build an audience with the exact playbook you're trying to develop — and it means the case study covers a full T-minus cycle rather than a scramble. A newer finding makes this even more attractive: **two-week wishlist velocity going into the fest predicts outcomes better than raw totals** (ρ = 0.81 vs 0.76), and velocity is precisely what a well-run community produces.

### The Steam page itself should still go up soon

Separate from Next Fest. Reasons:

- **Steam Direct's 30-day clock.** There's a mandatory 30 days between paying the $100 and being allowed to release, *plus* a 2-week minimum for the Coming Soon page. Start it early; it costs $100 and it's recoupable once you hit $1,000 revenue.
- **The Personal Calendar rewards committing early.** Steam's June 2026 homepage redesign promoted a per-user Personal Calendar covering a rolling ~8-week window, and its click-through rates are staggering compared to the old widget — one tracked game saw **33.8% CTR on 80k impressions** versus **0.81% on 1.3M** from Popular Upcoming. But you only appear if you have a date set roughly two months out. Meanwhile Popular Upcoming's threshold reportedly jumped from ~7,000 wishlists to somewhere near 80,000–100,000 after the redesign, which puts it out of reach. **Personal Calendar is the path now, and it's a path that requires a date.**
- Wishlists don't decay. Cohort analysis shows conversion is flat regardless of cohort age. Every day the page isn't up is wishlists you don't get.

### Three Steam compliance issues specific to Giltgrave

I read the playtest README. These are real and worth handling before you submit, not after.

**1. The player-supplied Anthropic API key is the biggest one.** Valve's Content Survey FAQ addresses this scenario head-on:

> "If you wish to integrate an external service like this into your game, you'll need to manage both access to that external service on behalf of your players and collecting payment from your player using a Steam-supported payment method."

Every sanctioned option Valve then lists routes money through Steam — bake it into the price, sell it as microtransactions, subscription, or DLC. "Player brings their own key and pays Anthropic directly" isn't among them. You also can't link to `console.anthropic.com` from your store page; Steam store pages permit no external links at all.

**The good news is your architecture already has the compliant shape** — the game works fully without a key, using the pre-written text pool. That's the *AI Roguelite* pattern, which ships on Steam today: a working default path, with bring-your-own-key as an optional power-user override. Just never position the AI text as required or as a headline feature. Keep it in Settings, describe it as an optional enhancement, and make sure the store page describes a game that is complete without it.

**2. Both AI features are "Live-Generated"** under Valve's taxonomy — content created while the game is running. That's the category with the extra obligation: you must describe **what guardrails prevent illegal content**. The local Stable Diffusion path is the harder answer, because a model running on the player's GPU is where your control is weakest. Have a real answer written before you submit — negative prompts, model choice, whatever it actually is. Valve auto-publishes your disclosure text on your store page under an "AI Generated Content Disclosure" heading, so write it as something you'd want a customer to read.

**3. The account system needs a "Requires 3rd-Party Account" notice and a custom EULA.** Steam renders this automatically on store pages that declare it (there's a "Generic Account System" variant for devs without a branded service). Shipping an account requirement without that notice is a reliable way to earn a wave of negative reviews on day one.

**On the gacha:** if the summon currency is earned-only and never purchasable with real money, no Valve rule triggers and no jurisdiction's odds-disclosure law applies. Publish the rates and pity thresholds anyway — it costs nothing, it's required the moment you ever add a real-money on-ramp, and Korea's Article 33 now carries active enforcement. Also keep pulled items untradeable; the New York AG's February 2026 suit against Valve over loot boxes turns on items having real-world value.

### So the shape of the Giltgrave calendar

| When | What |
|---|---|
| **Now** | Internal ship date set. Steam Direct paid, onboarding started (tax forms take 2–7 business days) |
| **Sept** | Coming Soon page live with a date ~Feb/Mar 2027. Discord server live. Friends playtest = founding cohort |
| **Sept–Jan** | The community playbook runs its full T-minus cycle |
| **Jan 10, 2027** | Next Fest registration deadline |
| **Feb 22 – Mar 1** | Next Fest, entering with a real audience |
| **Mar 2027** | Launch |
| **Mar–Apr** | Case study written with five months of real numbers |

That's slower than my first roadmap and it produces a much better launch, a much better case study, and doesn't waste the one-shot. Cleave's timeline doesn't change — it runs in parallel and its 90-day bar still lands in November.

---

## Layer 1 — The blueprint

Write this as a spec file, not as clicks in a UI. `blueprint/giltgrave.yaml` or similar. The spec is the deliverable you eventually sell; the server is just its first instantiation.

### Enable Community mode first

No member threshold — you can do it today. Requirements: verification level requiring a verified email, explicit media filter on all media, a rules channel, a mod-only updates channel, and agreeing to the community guidelines.

It unlocks Announcement channels, Forum channels, Onboarding, Server Guide, Rules Screening, Raid Protection, and Server Insights. Without it you have a chat room; with it you have a community platform. (AutoMod works either way — that's a common misconception.)

### Channels

Onboarding requires **≥7 default channels, of which ≥5 must allow @everyone to view *and* send.** Design around that constraint.

**INFO**
- `#welcome` — Server Guide resource. Read-only.
- `#rules` — Rules Screening, max 16 rules.
- `#announcements` — **Announcement channel.** Other servers can Follow it. Publishes are capped at 10/hour, and `@everyone`/`@here` get stripped when propagating to followers.
- `#patch-notes` — Announcement channel. Separate from announcements on purpose; people who want builds don't want events.

**PLAY** *(all open — these are your five)*
- `#general`
- `#screenshots`
- `#hero-showcase` — for a gacha, this is the highest-engagement channel you will have. People post pulls. Give it its own home.
- `#looking-for-guild`
- `#tower-talk` — strategy, floor progression

**FEEDBACK**
- `#bug-reports` — **Forum channel.** Mandatory tags: `crash`, `visual`, `balance`, `multiplayer`, `generation`, `account`. Post guidelines requiring build number and repro steps.
- `#suggestions` — Forum channel with upvote convention.
- `#playtest-lounge` — role-gated to `@Playtester`.

**DEV**
- `#devlog` — **Announcement channel.** Underused by most indies. Other game-dev servers can Follow it, which is free reach.
- `#ask-the-dev` — Forum channel, so questions become a browsable archive instead of scrolling away.

**OFF-TOPIC**
- `#off-topic`, `#other-games`

Forum posts auto-archive after 3 days by default; bump that to a week for `#bug-reports`. Only one post can be pinned at a time per forum — plan around it.

### Roles

**Interest roles, assigned by Onboarding answers:**
`@Tower Climber` · `@Guild Seeker` · `@Bug Hunter` · `@Lore Reader`

**The important one:** `@Ping Me For Playtests`

That role is the mechanism the entire proactive layer runs on, and the reason is compliance — see below. Every future announcement that would otherwise want to be a DM goes to a role someone opted into.

**Progression roles:** `@Founding Member` (auto-granted to anyone who joins before the public announcement — a free scarcity mechanic that costs nothing and people genuinely care about), `@Playtester`, `@Veteran`.

**Staff:** `@Dev`, `@Mod`.

### Onboarding questions

- **"What brings you here?"** — multi-select, assigns interest roles.
- **"Want to be pinged for playtests?"** — single select. This is your opt-in.
- **"How'd you find us?"** — attribution you cannot otherwise get. Steam / a creator / a friend / Reddit / elsewhere. Costs the member three seconds and tells you which channel is working.

That third question is worth more than it looks. Discord's own Server Insights doesn't unlock until 500 members, and even then its attribution is coarse.

### AutoMod

All available without Community mode. The real limits, from the API reference:

- **6 keyword rules** max (Discord's own Safety page says 3 — it's stale; the API reference is authoritative)
- **10 regex patterns**, 260 chars each, Rust-flavored regex
- 1 spam rule (ML-based), 1 keyword-preset rule, 1 mention-spam rule, 1 member-profile rule
- Timeout as an action works only on keyword and mention-spam rules, max 4 weeks

Plus **Raid Protection** — ML-based join-spike detection that CAPTCHAs new joiners for an hour when it fires. Turn it on now, not after your first raid.

---

## Layer 2 — The configured stack (all free)

| Tool | Job | Cost |
|---|---|---|
| **Sapphire** | Moderation, join roles, reaction roles, logging | **Genuinely free.** The developer states on Patreon that features "will of course stay free." Best value in the category |
| **Wick** | Security: anti-nuke, heat-system automod, captcha verification, join gate (filters new/avatarless accounts), raid detection | Free tier. ~970k servers |
| **Statbot** | Analytics, charts, channel counters, activity-based roles | Free tier caps history at **30 days** — which is exactly why you need your own ledger (below) |
| **Steamy** | Auto-posts new Steam reviews to Discord, weekly rating digests, free translation | **Free for all teams.** 500+ game dev servers use it. Set it up the day the Steam page exists |
| **BetaHub** *(optional)* | Bug reports and feedback. Its "Listen Mode" files a bug report automatically when players just *mention* a problem in chat — no command, no form | Core feedback capture free on any size server |

Skip MEE6 (~$12/mo per server, and levels/social alerts are behind the paywall), Carl-bot, Dyno, Arcane. They're reactive and Sapphire covers the overlap for free.

**One thing to know now:** you cannot programmatically install a bot into a server. Bot installation is an OAuth flow requiring a human with Manage Server to click through. Every "server blueprint" product ever built has a manual bot-setup step. Design the eventual onboarding around that rather than pretending otherwise.

---

## Layer 3 — Steward, the custom bot

This is the part that doesn't exist yet, in any product, for anyone.

I looked at this from four angles and the gap is real: **every established Discord bot is reactive or, at best, scheduled.** MEE6 has timed messages. Carl-bot has autofeeds. Statbot reports. None of them decide what programming a community needs based on the community's actual state. The closest thing is CommunityOne's "Hype Engine," which is trigger-based gamification, not programming.

### Stack

**Python, discord.py 2.7.1** (current, actively maintained, released March 2026). You're already a Python shop because of Cleave — one language for two codebases matters when you're one person. SQLite for the ledger; it's local, portable, and a server's worth of activity data is small. Hosting: a $5–7/month VPS. Add ~$7–15 if you eventually want managed Postgres, but you won't for a while.

### The seven jobs

**1. The activity ledger** — build this first, see below for why.

Record `MESSAGE_CREATE`, `VOICE_STATE_UPDATE`, `GUILD_MEMBER_ADD`, `GUILD_MEMBER_REMOVE`, and onboarding completion into SQLite: member, channel, timestamp, event type. Nothing clever.

The reason this is job one: **Discord's API has no per-member last-active field.** The Guild Member object gives you `joined_at`, roles, nickname, flags — and nothing about activity. There is no `last_seen`, no `last_message_at`. Every "who went quiet" feature anyone has ever built is derived from an event stream someone recorded themselves. That's why Statbot's value is its historical database rather than its API access, and why their free tier caps history at 30 days.

**You cannot backfill this.** Data you don't record on day one is gone. That single fact is why the ledger goes first even though it's the least visible thing in the list.

**2. Cohort retention reporting**

A weekly digest posted to a mod channel: joins this week, join → first-message conversion, D7 and D30 retention by join cohort, channel activity ranking, and — the one from your own idea doc — **which cohort of members quietly stopped showing up.** That's the report no bot produces and the one an owner would pay for.

**3. The calendar engine**

Reads a content calendar from a file (YAML, dates relative to T-minus rather than absolute, so it's redeployable) and executes it: posts prompts, creates Scheduled Events, runs recurring beats. Devlog Monday, screenshot Saturday, whatever the rhythm is.

The file being T-minus-relative is what makes it a product rather than a config. `T-42: post "first look at the guild system"` redeploys to any launch; `2026-09-14` doesn't.

Scheduled Events cap at 100 per server. I could not confirm whether Discord has native recurring events — assume not and handle recurrence yourself.

**4. Decay detection**

Per-channel rolling activity compared against that channel's own baseline. Alert the mod channel when a channel drops meaningfully below its trend. This is the "notices a channel decaying" line in your idea doc and it falls straight out of job 1's data.

**5. The playtest pipeline**

Role-gated signup, key issuance with an audit trail, feedback routed into a forum thread. Two constraints worth designing around:

- **Steam's beta-key ceiling is 2,500 total** (Release State Override keys, "intended for small beta tests and press/influencer access"). That's your real budget for pre-release distribution, and it's much lower than people assume.
- **Steam Playtest keys are far more generous** — Valve's docs treat 50,000 as the point where it's "effectively an open beta." If you use Steam's native Playtest feature instead of key distribution, the constraint mostly disappears. Native Playtest also lives on your main store page, so signups don't cost you the wishlist.

One gotcha: **opening a Steam Playtest does not notify wishlisters.** Valve is explicit about this. Announcements reach *Followers*, not wishlisters — wishlist emails fire only on release, on discounts ≥20% lasting >8 hours, and once for a demo going live. Driving playtest signups is therefore work *you* have to do, which is exactly the job Discord is best at and the clearest thing to point at in a case study.

**6. Onboarding funnel measurement**

Joins → completed onboarding → posted once → still active at day 7 / day 30. Four numbers. No third-party tool gives you this, and it's the most legible thing you can put in front of a studio.

**7. The provisioner** — build this **last**

This is the thing that feels like the product, and it's the last thing you need, because you don't need it until you deploy server number two.

When you do: **Discord's native server template is nearly useless for this.** It captures roles, channels, permission overwrites and server settings — but explicitly **not** Forum, Announcement or Stage channels ("not transferable" in Discord's own words), not bots, not AutoMod rules, not onboarding configuration. And it can only create a *new* server; it cannot be applied to an existing one.

The actual mechanism is your bot doing REST calls with Manage Server / Manage Roles / Manage Channels: create channels including forum and announcement types, roles, permission overwrites, forum tags, AutoMod rules, scheduled events, and — the one that surprises people — **onboarding configuration via `PUT /guilds/{guild.id}/onboarding`.** That covers everything the native template misses except installing other bots.

### Build order, and why

```
1. Ledger          ← week 2. Impossible to backfill. Everything else reads from it.
2. Cohort reports  ← week 4. First visible payoff; makes the ledger feel worth it.
3. Calendar engine ← week 6. The actual daily-labor saver.
5. Playtest pipe   ← when you start recruiting testers.
4. Decay detection ← once you have ~8 weeks of baseline. Meaningless before that.
6. Funnel metrics  ← anytime after 1; it's a query, not a feature.
7. Provisioner     ← when server #2 exists. Not before.
```

The temptation will be to build the provisioner first because it's the most product-shaped. Resist it. A provisioner that deploys a blueprint you haven't validated is a way to make the same mistakes twice.

---

## The compliance rails — non-negotiable, design them in from commit one

These aren't bureaucracy; they're the difference between a product and a bot that gets banned.

**No mass DM. Ever.** Discord's Developer Policy: *"Do not contact users on Discord without their explicit permission. This includes frequently sending unsolicited direct messages."* The Community Guidelines separately prohibit facilitating it. And Discord's own API docs for the create-DM endpoint say plainly: *"You should not use this endpoint to DM everyone in a server about something."* There's an undocumented DM-open quota and blowing it gets you quarantined with no warning.

This is why the `@Ping Me For Playtests` role exists. **Every proactive reach must route through channels, roles, mentions, scheduled events, or announcement channels.** That's not a workaround — it's the only compliant path, and any credible product in this space has to be architected around it. Worth noting this is also a *better* product: an opt-in role is visible, revocable, and doesn't feel like spam.

**Data deletion is a hard requirement.** The Developer ToS obliges you to give users "an easily accessible way to ask for their API Data to be modified and deleted," and to delete when retention is no longer necessary. For a bot whose whole value is a member activity history, that's architecture, not a feature. Build `/forget-me` on day one, and write a retention policy before you have data to retain.

**Channel Obfuscation goes mandatory November 16, 2026.** Bots will stop receiving full metadata for channels they can't access — names and permission details get obfuscated behind a `CHANNEL_OBFUSCATED` flag. Anything that enumerates full server structure needs to handle this. That's the provisioner and any audit feature. Three months' notice; don't let it surprise you.

**Privileged intents:** you'll need `GUILD_MEMBERS` and `MESSAGE_CONTENT`. Under 10,000 unique users you just toggle them in the Developer Portal, no application. Over 10,000 you apply, with 90 days to submit — and as of **June 10, 2026 you must reapply annually** to keep access. Separately, **bot verification is required to scale past 100 servers** and requires identity verification through Stripe. Plan for both as operational facts, not surprises.

**If you ever sell paid features:** since October 2024, Discord requires paid app capabilities to be purchasable through Discord's Premium Apps at prices no higher than you offer elsewhere. Price parity, not exclusivity — you can still sell on your own site. Discord's cut is 15% on the first $1M, 30% after. Note the asymmetry: server owners selling their own subscriptions get 90/10. Worth knowing before you design pricing.

**Selling or transferring the app itself requires Discord's prior written consent.** If the endgame is ever an acquisition, that's a clause to have read.

---

## The playbook artifacts — what you're actually documenting to sell

Your idea doc says the documentation *is* the deliverable. Concretely, that's six files, written as you go, not reconstructed afterward:

1. **`blueprint.yaml`** — the machine-readable server spec. Channels, roles, permissions, onboarding questions, AutoMod rules, forum tags.
2. **`onboarding-flow.md`** — the questions, why each one, what role each answer grants, and what you learned when you changed them.
3. **`content-calendar.yaml`** — T-minus-relative beats. The single most reusable artifact in the set.
4. **`moderation.md`** — AutoMod config, escalation ladder, what you actually had to intervene on.
5. **`playtest-pipeline.md`** — recruitment, gating, key handling, feedback routing, and the Steam constraints above.
6. **`outreach-tracker.csv`** — creators and press: who, when, what happened. Note that automated *outreach* via Discord DM is prohibited, so this is a tracking artifact, not an automation.

**The discipline that makes or breaks this:** write the reusable version in the same sitting you do the thing. Not "I'll document it after launch." After launch you'll write a worse version from memory, and the memory will have smoothed out exactly the parts that were hard — which are the parts a studio would pay for.

---

## The T-minus calendar

Anchored to a March 2027 launch. Adjust the absolute dates when you set yours; the relative structure is the product.

| Phase | Weeks | Work |
|---|---|---|
| **T-26 (Sept)** | 1–2 | Community mode on. Blueprint written and deployed by hand. Free bot stack configured. Steward's ledger recording from day one. **Friends' playtest starts — these are your `@Founding Member` cohort.** |
| **T-24** | 3–4 | Steam Coming Soon page live with date. Steamy connected. Cohort reporting shipped. First devlog post. |
| **T-22 to T-16** | 5–12 | Calendar engine live. Content rhythm running. Playtest pipeline built and recruiting. Creator/press list built (aim 40, same discipline as Cleave's consultancy list). |
| **T-16 to T-8** | 13–20 | Decay detection online (needs baseline). Wider playtest. Creator outreach starts — **months before launch, not weeks.** The data on this is stark: one dev emailed 30 creators and got zero replies; the first response came two months later and produced 1,000 wishlists in two days. |
| **T-8 to T-2** | 21–26 | Next Fest registration (Jan 10). Demo finalized. Wishlist velocity is the metric that matters — the two weeks before the fest predict its outcome better than your total. |
| **Next Fest** | Feb 22 – Mar 1 | Patch fast, don't buy ads (you're bidding against publishers), don't expect creators to slot you in — their schedules are booked. |
| **Launch** | March | Execute. Nothing new. |
| **T+2 to T+4** | | **Write the case study.** |

---

## What to measure — this list is the case study

Track from day one, even when every number is single digits. Small honest numbers with a clean methodology beat big vague ones.

**Discord:** members, join → onboarding completion, onboarding → first message, D7/D30 retention by cohort, weekly active posters, messages per active member, channel distribution, `@Ping Me For Playtests` opt-in rate, attribution from the "how'd you find us" question.

**Steam:** wishlist adds per day, wishlist velocity in rolling 2-week windows, followers (the ~10× followers ≈ wishlists heuristic is a useful sanity check), deletions, regional split.

**Pipeline:** playtest signups, signup → actually played, bug reports filed, unique reporters.

**Outreach:** creators contacted, responded, covered, and — because coverage arrives on a long tail — wishlists in the 72 hours after each piece of coverage.

**The honest framing for the eventual sales conversation:** I could not find a single credibly-sourced case study quantifying Discord community work driving Steam wishlists. The best-documented 2026 wishlist attribution study — a game that reached 200,000 wishlists — lists showcases, an IGN feature, and aggregator accounts, and **no Discord contribution at all.** Everything claiming a Discord→wishlist conversion rate traces to AI content farms.

That's not bad news for you. It means Discord's documented value is retention, playtest recruitment, feedback quality, and converting people who already found you — and that **you'd be producing one of the few honest datasets on it.** Sell that. A studio that's been pitched vague community-growth numbers before will notice someone who says "here's what it did and here's what it didn't."

---

## Productizing it later

Your idea doc's build order is right: run it, package it, sell it three times, then productize the repeated part. Three notes on the eventual product shape, from what the research turned up:

- **The proactive gap is real and unoccupied.** Nobody has shipped a bot that plans community programming from community state. That was your thesis and it survives contact with the 2026 landscape.
- **Target servers with money.** Your doc already says this and it's the single most important targeting decision. But note that Discord's own monetization has matured — Server Subscriptions at a 90/10 split, Server Shop, Server Tags at 3 boosts — so "servers with revenue" is now a much larger and more identifiable category than it was.
- **Discord itself is moving into this space.** GDC 2026 brought Official Game Profiles (claim your game, including Steam titles, through the Developer Portal — free, and you should do it), Social Commerce, Instant Play Quests, and the Social SDK. That's a platform holder building adjacent to you. It doesn't invalidate the plan — Discord builds for the top of the market and the platform, not for the person running one server — but it's a reason to move while the gap is open, and a reason to keep the product's value in the *history and the programming*, which Discord has shown no interest in owning.
