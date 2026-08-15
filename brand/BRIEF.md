# Design brief: Steward

Paste everything below the line into Claude Design (or hand it to a
human designer). It is written to be read cold, with no other context.

---

## What I need

Two pieces for a Discord bot called **Steward**.

1. **Avatar.** Square, 1024x1024 PNG, no transparency needed. Discord crops it
   to a circle, so nothing important goes in the corners.
2. **Banner.** 680x240 PNG. It sits behind the bot's profile card. Discord
   darkens the bottom third and lays the bot's name and avatar over the
   lower-left, so keep the lower-left quarter quiet.

They have to read as one thing. Same two or three colours, same weight.

## What Steward is

A Discord bot that keeps a game community's server running. It counts what
people do, hands out levels and roles for taking part, posts a weekly digest
with charts, and logs what the moderators do. Nothing exciting: it is the
thing that quietly keeps the room in order.

The name is the whole idea. A steward is a keeper of a house, not a guard and
not a butler. Present, unglamorous, trusted with the keys. Whatever you make
should feel like that: composed, a little formal, not cute and not aggressive.

## The constraint that has killed every attempt so far

**A bot avatar is seen at 40 pixels in a member list and 20 pixels beside a
message.** Not 512. Not 128. Forty and twenty.

At those sizes:

- Line art disappears. Any stroke thinner than about 1/20th of the image width
  turns to grey mush.
- Interior detail disappears. Two shapes inside the circle is the ceiling;
  one is safer.
- Only two things survive: a **filled silhouette with a lot of contrast**, or
  a **single letterform**.

So design it at 40px first and scale up, not the reverse. If it does not work
as a 40px thumbnail it does not work, no matter how good the 512px version is.

Please show me the result at 512, 96, 40 and 20 in one image so I can judge it
the way I will actually see it.

## What I have already rejected, so please do not send it back

- A monogram **S** in a circle. Correct by the rules above, completely dead.
- A wax seal.
- A key, a keyring, or a keyhole.
- A shield or a crest.
- A hand holding anything.

The problem with all of those was not the size, it was that they were the
first idea. If a letterform really is the answer, it has to earn it with the
drawing itself: an unusual cut, a ligature, a counter doing something, weight
where you would not expect it.

## What might work, if it helps to have somewhere to start

Not a list to pick from, just the direction of travel.

- Something architectural. A stewardship is of a building.
- A mark built from negative space rather than a drawn object.
- The letterform treated as a piece of lettering rather than a font at a size:
  hand-cut, one deliberate oddity.
- A single geometric solid with one bevel or notch that gives it a reading.

## Colour

I do not have a brand palette and I am not attached to one. Two colours plus
the ground. Whatever you pick has to hold up against Discord's dark chrome,
which is `#313338` behind a message and `#2B2D31` in the member list, and also
against Discord's light mode at `#FFFFFF`. Something that vanishes into a dark
grey background is a fail.

I have been sitting on violet by default and I am bored of it. Talk me out of
it if you have something better.

## Type

The banner can be the word **STEWARD** and nothing else. A plain wordmark
never dates and it is legible at any size, which is more than the avatar can
say for itself.

If you do that, the letterforms have to carry it. I have been using **Cinzel**
(a Roman-inscription face, free, on Google Fonts) and it is fine but it is the
obvious choice for anything vaguely classical. Open to anything with actual
character, including something drawn rather than set. Wide letter-spacing has
been reading well at banner size.

## Licensing, which is a hard requirement

This may end up published in Discord's App Directory, and it may end up sold.
So:

- No traced or adapted existing logos, game art, or anything recognisable.
- Any typeface has to be licensed for commercial use and for embedding in a
  logo. Google Fonts (SIL Open Font License) is safe. Anything bundled with
  Adobe or Microsoft usually is not.
- If you use a reference, tell me what it was and where it came from.

## Deliverables

- Avatar at 1024x1024, and the 512 / 96 / 40 / 20 contact sheet described above.
- Banner at 680x240.
- The same avatar on `#313338` and on `#FFFFFF`, so I can see it in both themes.
- The hex codes.
- If it is a wordmark, the typeface name and its licence.

Two or three genuinely different directions beats one polished one. I would
rather choose than approve.
