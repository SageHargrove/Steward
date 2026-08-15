# Steward's face

Avatar concepts and banners, plus the contact sheets they were judged on.

## Why the first attempt failed

A line-art key looked fine at 512px and turned to noise at 20px. That is not a
taste problem, it is a size problem: **a bot avatar spends its life at about
40px in a member list and 20px beside a message.** Thin outlines disappear
there. Everything here is either a filled silhouette or a letterform, both of
which survive being shrunk.

`marks-sheet.png` shows every option at 128, 64, 40 and 20px, masked to a
circle the way Discord renders them. That sheet is the actual test; judge from
it rather than from the full-size files.

## What is here

    mark-monogram-gold.png          S in gold on near-black
    mark-monogram-ivory-violet.png  S in ivory on violet
    mark-wax-seal.png               crimson seal
    mark-wax-seal-gold.png          gold seal
    mark-solid-key.png              a key, filled rather than outlined
    mark-ledger.png                 a closed book
    mark-lantern.png                a lantern

    banner-gold-on-deep.png         wordmark, 680x240
    banner-ivory-on-violet.png
    banner-seal-left.png            mark and wordmark together
    banner-discord-grey.png         on Discord's own grey, so the word floats

## The typeface

Cinzel, converted from the copy already bundled with the game, so the tool
reads as the same hand without borrowing the game's name. Cinzel is an
all-caps face and needs letter-spacing to read as a wordmark rather than a
word; every banner here sets it with tracking.

Licensed under the SIL Open Font License, which permits commercial use.

## Regenerating

`marks.py` and `banner.py` in the session scratchpad produced these. Both are
plain Pillow, no design tool needed. Change a colour constant at the top and
re-run to get the whole set again.


## Palettes

`palettes-sheet.png` is the one to look at: eight two-colour schemes, each shown
as the banner and as the matching avatar at 96px and 40px, so the pair can be
judged together rather than separately.

    pal-banner-<name>.png    680x240
    pal-seal-<name>.png      512x512, the same two colours

The banner is deliberately plain. A wordmark on a flat ground is the one thing
that never dates, and nothing more elaborate survives being a strip nobody
looks at twice.

Both files of a pair use the same two colours in opposite roles, which is what
makes the profile read as one thing instead of two.

Regenerate the whole set from `palettes.py` by editing the PALETTES dict at the
top; every file rebuilds from those eight pairs of hex values.
