# Moderation

What is automated, what is not, what the escalation ladder is, and the API
limits that decided the shape of it.

---

## The split

| Layer | Does | Cost |
|---|---|---|
| **Discord AutoMod** | Content filtering, spam, mention floods, profile names | Free, native, no bot |
| **Raid Protection** | ML join-spike detection, CAPTCHAs new joiners for an hour | Free, native, one toggle |
| **Wick** | Anti-nuke, CAPTCHA verification, join gating on account age | Free tier |
| **Steward** | The moderation log, and nothing else | Ours |
| **Humans** | Everything that requires judgement | The expensive part |

**Steward deliberately does not moderate.** It records what moderators did.
Anti-nuke and verification are security-critical and hard, and a half-built
version of either is worse than not having one, so those stay with Wick.

---

## AutoMod, as configured

Five rules. The provisioner creates them; they are editable in the setup page.

**1. Slurs and sexual content** — `keyword_preset`, using Discord's own
maintained lists. Blocks and alerts `#mod-log`. Nothing here for you to write
or keep up to date, which is the entire appeal: a hand-written slur list is out
of date the week you write it.

**2. Spam** — `spam`, Discord's ML classifier. Blocks and alerts. Staff exempt.

**3. Mention spam** — blocks any message with more than 6 mentions, alerts, and
times the sender out for **10 minutes**. Mention raid protection on. Staff
exempt.

**4. Invite links and advertising** — two regex patterns, blocks, alerts, and
times out for **5 minutes**:

    (discord\.(gg|io|me|li)|discordapp\.com/invite)/[a-zA-Z0-9-]+
    (?i)(free\s+nitro|steam\s+gift|claim\s+your\s+reward)

`#looking-for-group` is exempt, because recruiters legitimately post invites
there. The second pattern is the standard scam-bait phrasing and catches the
compromised-account posts that arrive before the link does.

**5. Nickname and profile filter** — `member_profile`, which catches an
offensive name at the point it is set rather than after somebody reports it.

### The real API limits

Discord's own Safety page says 3 keyword rules. **That page is stale**; the API
reference is authoritative:

| | |
|---|---|
| Keyword rules | **6** |
| Regex patterns per rule | **10**, at **260 characters** each |
| Spam rules | 1 |
| Keyword-preset rules | 1 |
| Mention-spam rules | 1 |
| Member-profile rules | 1 |
| Timeout as an action | keyword and mention-spam rules **only**, max 4 weeks |

That last row is the one that bites. Attaching a timeout to a spam or preset
rule is accepted by nothing and fails as an opaque 400. The setup page validates
it before sending.

**AutoMod does not need Community mode.** Common misconception; it works on any
server.

---

## The escalation ladder

Written down so that two moderators reach the same answer, which is the only
thing that makes moderation feel fair rather than arbitrary.

| # | Situation | Action |
|---|---|---|
| 1 | First minor breach: heat, mild rudeness, wrong channel | Say so publicly, in channel, once. No punishment. |
| 2 | It continues after being asked | 10-minute timeout. Explain why in `#mod-log`. |
| 3 | Repeat within a week | 24-hour timeout, and a DM explaining what happens next. |
| 4 | Repeat after that | 7-day timeout. |
| 5 | Sustained after a 7-day | Ban. |

**Straight to ban, no ladder:**

- Sexual content involving minors. Ban and **report to Discord Trust & Safety**;
  this is not a server matter.
- Doxxing, or threats of violence.
- Slurs used at somebody rather than caught in passing.
- Raid or scam-link accounts. These are usually compromised, not malicious, but
  the ban goes on and can come off after the owner recovers the account.
- Advertising by DM to members. Nobody who does this on day one is here for the
  game.

**Never punish for:** disliking the game, criticising a decision, reporting a
bug rudely, or being wrong in an argument. A community that times people out
for negative opinions gets a reputation faster than it gets quiet.

### Two rules for the moderators rather than the members

**Never moderate an argument you are in.** Ask another moderator. This is the
single most common way a community loses trust in its staff.

**Every action gets a reason.** Discord's audit log has a reason field and
Steward reads it into `#mod-log`. An action with no reason is unreviewable six
weeks later, including by the person who took it.

---

## The moderation log

Steward writes to `#mod-log`. It reads the audit log, so it captures who acted
and why, which the raw gateway events do not carry.

Logged: bans, unbans, kicks, timeouts, role changes, nickname changes, channel
creation and deletion, role deletion, message deletion.

**Message deletions are logged as metadata only.** Channel, author, timestamp.
Not the content.

That is a consequence of a deliberate choice, not a gap. Steward does not
request the `MESSAGE_CONTENT` intent, so it never had the text to log. The
tradeoffs, both ways:

- You cannot see what a deleted message said. When a moderator deletes something
  and the reporter asks what it was, the log cannot answer.
- There is no copy of your members' conversations sitting in a SQLite file on a
  VPS. The honest answer to "what does the bot store" is "who posted where and
  when". And once the app passes 10,000 users, `MESSAGE_CONTENT` requires an
  application and, since **10 June 2026**, an annual reapplication to keep.

The log says which it is rather than leaving a moderator wondering whether the
content is missing or the bot is broken.

---

## Raid Protection

**Turn it on before your first raid, not after.** Server Settings, Safety Setup,
Raid Protection. It is ML-based join-spike detection that CAPTCHAs new joiners
for an hour when it fires.

There is no API for it. It is on the by-hand list in the setup page for exactly
that reason.

---

## Things to do by hand, once

- **Rules Screening.** Not the same as the rules message. This is a gate: nobody
  can post, react or DM until they tick the box. 16 rules maximum, and the
  blueprint ships exactly 16. No endpoint, so the setup page gives you the text
  to paste.
- **Raid Protection**, above.
- **Wick**, for anti-nuke and verification. Install from Discord's App Directory
  rather than a link anyone hands you: a wrong client id sends your server to
  the wrong application, permanently.

---

## What has actually been moderated

*Nothing yet. The server is new.*

Keep this section, and fill it in as things happen. What a studio would pay for
is not the config above, which anyone can copy. It is the record of what
actually came up, what the rule turned out to be wrong about, and what got
changed as a result. Write it the week it happens; six months later you will
write a smoother, less useful version from memory.
