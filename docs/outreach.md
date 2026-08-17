# Outreach

How to use `outreach-tracker.csv`, and the two rules that make outreach either
work or fail before it starts.

---

## Rule one: start months early, not weeks

The data on this is stark. One developer emailed thirty creators and got zero
replies. **The first response arrived two months later**, and it produced a
thousand wishlists in two days.

Creators plan weeks or months ahead. A game that lands in an inbox two weeks
before launch is competing for a slot that was filled in October. The calendar
has a reminder at **T-112**, which is sixteen weeks out, and that is the late
end of right.

Aim for a list of **forty**. Most will not reply. That is the normal shape of
this and not a signal that the game is bad.

## Rule two: never do it over Discord DMs

Discord's Developer Policy prohibits unsolicited direct messages, the
Community Guidelines separately prohibit facilitating them, and the quota that
enforces it is undocumented and quarantines applications without warning.

This is why the tracker is a **spreadsheet and not an automation**. There is no
tool in this project that contacts anyone, and there should not be. Email,
their business address, or a platform DM they have advertised for the purpose.

---

## The columns

| Column | What goes in it |
|---|---|
| `name` | Person or outlet |
| `kind` | creator / press / curator / festival / publisher |
| `platform` | YouTube, Twitch, a site, wherever they actually are |
| `url` | Their channel or publication |
| `audience_size` | Subscribers or monthly readers. Rough is fine |
| `fit_notes` | **The important one. See below** |
| `contact_method` | email / form / platform DM |
| `contact_handle` | The address or handle you used |
| `first_contacted` | ISO date |
| `followed_up` | ISO date. Once. Never twice |
| `replied` | ISO date, blank if never |
| `covered` | ISO date they published |
| `coverage_url` | The piece |
| `coverage_date` | Same as covered, kept separate for sorting |
| `wishlists_72h` | Steam wishlist adds in the 72 hours after it went up |
| `status` | queued / contacted / replied / declined / covered / dead |
| `notes` | Anything that would be lost otherwise |

### fit_notes is the column that decides whether this works

Not "does roguelikes". That is a category, and a category match is what a mail
merge produces.

Write the specific reason **this person** would care about **this game**: a
video they made about a mechanic yours shares, a genre complaint yours answers,
three similar games they covered last quarter. If you cannot write a sentence
that could only be about them, they are not on the list, they are on a spam run,
and the reply rate reflects it.

### wishlists_72h is the column that makes it a case study

Coverage arrives on a long tail and the effect is easy to lose. Record the
Steam wishlist adds in the 72 hours after each piece goes live and you end up
with something almost nobody has: an attributable per-piece number rather than
a vague claim that coverage helps.

---

## Why this is worth the discipline

There is no credibly-sourced case study quantifying Discord community work
driving Steam wishlists. The best-documented 2026 attribution study, on a game
that reached 200,000 wishlists, credits showcases, an IGN feature and
aggregator accounts, and **no Discord contribution at all**. Everything
claiming a Discord-to-wishlist conversion rate traces back to AI content farms.

That is not bad news. It means Discord's documented value is retention,
playtest recruitment, feedback quality, and converting people who already found
you, and that a clean honest dataset on it does not currently exist.

Small numbers with a clear methodology beat big vague ones, and being explicit
about what did **not** work is the part a studio will believe. They have been
pitched vague community-growth numbers before.
