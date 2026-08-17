# The onboarding flow

The three questions a new member answers, why each one exists, what each answer
actually grants, and what Discord will and will not allow.

Discord calls this feature **Onboarding**. It runs once, on join, before the
member sees the server. It needs Community mode on.

---

## The rule that shapes everything

**Every answer must grant a role or reveal a channel.** An answer that does
neither is rejected, and Discord rejects the *whole* onboarding request rather
than the one bad option:

```
PUT /guilds/{id}/onboarding  ->  400
{"code": 50035, "errors": {"prompts": {"0": {"options": {"3":
  {"_errors": [{"code": "ROLE_OR_CHANNEL_REQUIRED"}]}}}}}}
```

So **a pure survey question is impossible.** This is not a limit you can design
around by being clever with wording; the API will not store the option.

That single constraint is why question three works the way it does.

---

## Question 1: "What brings you to {{game}}?"

Multi-select. Each answer grants an interest role.

| Answer | Grants |
|---|---|
| Tactics and builds | `Strategist` |
| Playing with other people | `Group Finder` |
| Finding and reporting problems | `Bug Hunter` |
| The world and how it is made | `Lore Reader` |

**Why it exists.** These roles are mentionable and colourless. They are how you
reach thirty people who care about one thing without pinging four hundred who
do not. A post in `#looking-for-group` that mentions `@Group Finder` is the
compliant version of a DM, and it is also the better one: visible, revocable,
and it does not feel like spam.

**What was learned.** Multi-select matters. The first version was single-select
and forced people to pick a primary interest, which most found arbitrary and
which made the roles useless for targeting, because someone who ticked
"Tactics" was often equally interested in bugs.

---

## Question 2: "Want to be pinged for playtests?"

Single select. Yes grants `Ping Me For Playtests`. No grants nothing and is
therefore **not a valid option**, so the "no" answer reveals `#general`
instead. That is the workaround for the rule above: revealing a channel counts,
and `#general` is visible to everyone anyway, so revealing it changes nothing.

**Why it exists.** This is the compliance rail for the entire proactive layer.

Discord's Developer Policy is explicit:

> Do not contact users on Discord without their explicit permission. This
> includes frequently sending unsolicited direct messages.

And the API reference for creating a DM says plainly that you should not use
the endpoint to message everyone in a server. There is an undocumented
DM-opening quota, and exceeding it gets an application quarantined with no
warning and no appeal worth the name.

So **every proactive reach in this project routes through a role somebody opted
into.** The calendar mentions roles. The playtest announcements mention roles.
The only direct message Steward ever sends is a playtest key, to somebody who
asked for one.

That is not a workaround. An opt-in role is visible on a profile, removable by
the person wearing it, and it does not arrive in a private inbox uninvited.

---

## Question 3: "How did you find us?"

Single select. Six answers, each granting one of the `Found via ...` roles.

    Found via Steam        Found via a creator     Found via a friend
    Found via Reddit       Found via search        Found via elsewhere

**Why it exists.** Attribution is the one number Discord will not give you.
Server Insights does not unlock until 500 members and its attribution is coarse
even then. Three seconds of a new member's time buys you the answer to "which
channel is actually working", which is the number that decides where the next
month of effort goes.

**Why the roles are ephemeral.** Nobody wants "Found via Reddit" on their
profile forever, and a member list cluttered with six meaningless roles makes
the server look unfinished. But the answer cannot grant nothing.

So the role is granted for about a second. Steward's `on_member_update` sees
it, writes the answer into the ledger, and removes the role. The number lives
in a database column instead of on somebody's profile.

**Consequences of that design, all of which are real:**

- The roles must never be given a colour, a hoist, or any permission. They are
  not roles anyone keeps, and styling them would make the flicker visible.
- Stripping them needs `MANAGE_ROLES`, and Steward's own role must sit **above**
  them in the list. This is why the ledger invite asks for that permission.
- **It only works while Steward is running.** If the bot is off, the roles pile
  up on members until it next starts and sweeps them, or until somebody runs
  `/sweep-roles`. If you are not going to run Steward, delete this question
  rather than leaving it half-working.
- If the strip fails for lack of permission, the answer is still recorded and
  the bot logs it once rather than every join. The number matters more than the
  tidiness.

Read the split with `/ledger-status`.

---

## Default channels

Discord requires **at least 7 default channels, of which at least 5 must allow
`@everyone` to both view and send.** Below either number the request is
rejected.

    start-here  rules  announcements       (readable, not writable)
    general  screenshots  strategy  looking-for-group  off-topic   (fully open)

Eight defaults, five fully open. There is one channel of headroom on each
count, which is deliberate: removing a channel in the setup page should not
silently break onboarding, and the live validation catches it before anything
is sent if it would.

---

## Editing any of this

The setup page turns all three questions into editable lists: rename an answer,
delete one, add your own, and point it at a different role. Two things it does
automatically that are worth knowing:

**Deleting a role prunes the answers that granted it.** Otherwise you would be
left with an option granting nothing, which is the `ROLE_OR_CHANNEL_REQUIRED`
failure above, and it would surface as an opaque 400 halfway through a run.

**An answer that ends up granting nothing is dropped, not sent.** Validation
catches it first and says so in the page.

---

## What went wrong, so it does not go wrong again

**The dropped prompt.** An early version substituted `{{game}}` into the
blueprint before matching the customization keep-lists, so a prompt titled
"What brings you to {{game}}?" never matched an entry naming the raw string,
and it was silently dropped. The server came up with two questions instead of
three and nothing said so. Substitution now happens last, after every keep-list,
rename and default has been matched against raw blueprint names. A test asserts
it.

**The live rejection.** The first real run against a real server failed with
`ROLE_OR_CHANNEL_REQUIRED` because seven options granted nothing. The
attribution question was, at that point, a pure survey. That is the failure
that produced the `Found via ...` design.
