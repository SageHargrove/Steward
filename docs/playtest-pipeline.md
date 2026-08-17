# The playtest pipeline

Recruiting testers, gating access, handling keys, and routing what comes back.

---

## The decision that matters most

**Use Steam's native Playtest feature, not keys.**

| | Release State Override keys | Steam Playtest |
|---|---|---|
| Ceiling | **2,500 in total, ever** | Valve calls 50,000 "effectively an open beta" |
| Lives on | nothing; you distribute them | your existing store page |
| Costs a wishlist | yes, if signup replaces wishlisting | no |
| Admin | you track every key | Valve tracks it |

The 2,500 figure surprises people. It is a lifetime budget across press,
influencers, friends and testers, and Valve's own description of those keys is
"intended for small beta tests and press/influencer access". Spend them on
people who need a build outside Steam and on press. Everyone else goes through
native Playtest.

**The catch: opening a Steam Playtest does not notify wishlisters.** Valve is
explicit. Wishlist emails fire on release, on discounts of 20% or more lasting
over 8 hours, and once when a demo goes live. Announcements reach *Followers*,
who are a different and much smaller group.

So driving playtest signups is work you have to do, and Discord is the best
place to do it. That is also the cleanest thing to point at in a case study,
because the counterfactual is measurable: nobody else was going to tell them.

---

## The flow

    /playtest-join          member opts in, gets the role, goes on the list
    /playtest-open          staff open a wave
    /playtest-keys          staff add keys to it
    /playtest-issue         staff send one person a key, by DM
    /playtest-status        who has what, how many are left
    /playtest-close         close the wave
    /playtest-report        a tester files a bug into the forum
    /playtest-leave         member opts out

### Signup

`/playtest-join` grants `Ping Me For Playtests` and records the signup. The
role is the same one the onboarding question hands out, so somebody who
answered yes on the way in is already on the list.

The role is the point. **Every playtest announcement mentions the role and
nothing else.** Discord's Developer Policy prohibits unsolicited direct
messages, and the quota that enforces it is undocumented and quarantines
applications without warning. An opt-in role is the only compliant way to
reach people, and it is also better: visible, revocable by the wearer, and it
does not arrive in a private inbox uninvited.

### Keys, and why they are handled the way they are

Keys live in `steward/data/steward.sqlite3`, because issuing one requires
having it. **That file is a secret.** It holds live keys and members' activity.
Do not commit it, do not attach it to a bug report, and do not paste it
anywhere, including into an AI assistant.

Four behaviours worth knowing, each of which exists because the obvious version
is wrong:

- **The claim is atomic.** The `UPDATE` picks the row itself rather than reading
  then writing, so two moderators issuing at the same moment cannot hand the
  same key to two people.
- **Asking twice returns the same key**, rather than burning a second one.
  People lose DMs.
- **If the DM bounces, the key goes back in the pool.** It is never posted where
  anyone else can see it. A member with closed DMs costs you nothing.
- **A revoked key is dead and stays dead.** Whoever held it has seen it, so
  returning it to the pool would hand out a key two people know.

`/forget-me` scrubs the member off the key row but leaves it spent. Deleting
the row would put a live Steam key back in the pool for the next person, which
is a bug the tests caught rather than review.

### Feedback

`/playtest-report` creates a forum post in `#bug-reports` with the reporter,
build number, what happened and the steps, already laid out. It also records
that this person actually played, which is the conversion number the pipeline
exists to produce: **signed up** against **reported at least once**, visible in
`/playtest-status`.

The forum has mandatory tags: `crash`, `visual`, `balance`, `multiplayer`,
`generation`, `account`. Forum posts auto-archive after 3 days by default;
`#bug-reports` is set to a week, because a bug filed on Friday should not be
gone by Tuesday. Only one post can be pinned per forum, so the pin is the
posting guidelines and nothing else.

---

## Waves

Run it in waves rather than opening the gates. A wave is a name, an optional
cap, and a set of keys.

**Wave 1, around T-112.** The people who signed up first. Small enough that you
can read every report and reply to every reporter, which is what makes them
stay. Expect the build to be broken; that is what they are for.

**Wave 2, around T-84.** Wider. By now the obvious crashes are gone and you are
looking for the things only volume finds.

**Native Playtest, from T-84.** No cap, no keys, no admin.

The calendar has beats for all three at `playtest-signup-open`,
`playtest-wave-one` and `wider-playtest`.

---

## Steam compliance, before you submit

Three things specific to a game with a bring-your-own-API-key feature and a
gacha. Worth handling before submission rather than after a rejection.

**A player-supplied API key is the big one.** Valve's Content Survey FAQ
addresses it directly: if you integrate an external paid service, you must
manage access to it on the player's behalf and collect payment through a
Steam-supported method. Every sanctioned option routes money through Steam.
"Player brings their own key and pays the provider directly" is not among them,
and you cannot link to the provider from the store page, because Steam store
pages permit no external links at all.

The compliant shape is the one where the game **works fully without a key**,
with the key as an optional power-user override. Keep it in Settings, never
position it as a headline feature, and make sure the store page describes a
game that is complete without it.

**Live-generated content needs a guardrails answer.** Anything created while
the game runs falls into Valve's "Live-Generated" category, which carries the
extra obligation to describe what prevents illegal content. A model running on
the player's own GPU is where that answer is hardest, so have a real one
written: negative prompts, model choice, whatever it actually is. Valve
auto-publishes your text on the store page under an AI Generated Content
Disclosure heading, so write it as something a customer will read.

**An account system needs the "Requires 3rd-Party Account" notice and a custom
EULA.** Steam renders it automatically when declared, and there is a Generic
Account System variant for developers without a branded service. Shipping an
account requirement without the notice is a reliable way to collect negative
reviews on day one.

**On the gacha:** if the summon currency is earned-only and never purchasable
with real money, no Valve rule triggers and no odds-disclosure law applies.
Publish the rates and pity thresholds anyway. It costs nothing, it is required
the moment you add any real-money on-ramp, and Korea's Article 33 now carries
active enforcement. Keep pulled items untradeable: the New York Attorney
General's February 2026 suit against Valve over loot boxes turns on items
having real-world value.

---

## What to measure

Four numbers, all of which Steward can answer:

| | |
|---|---|
| Signed up | `/playtest-status` |
| Issued a key | `/playtest-status` |
| Reported at least once | `/playtest-status`, the conversion that matters |
| Unique reporters against total reports | the forum |

Signed up against actually played is the honest measure of whether a community
converts to a tester base. It is also a number almost nobody publishes, which
is what makes it worth having.

---

## What actually happened

*Nothing yet. No wave has run.*

Fill this in as it happens: how many of the signups played, what the reports
were like, what you changed about the process between wave one and wave two.
That record is the reusable part. The commands above are just software.
