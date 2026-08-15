# Steward's face

## What ships

    steward-avatar.png          1024x1024, upload as the bot's avatar
    steward-banner.png          680x240, upload as the bot's banner
    steward-avatar-slate.png    the same two colours, swapped
    steward-banner-slate.png
    steward-contact-sheet.png   the avatar at 512, 96, 40 and 20 on both themes

Mark is **gate3**: three voussoirs carried down onto two piers. A steward keeps
a house, and an arch is the part of a house that only stands because every
piece leans on the next one.

Type is **Newsreader** at weight 600, letter-spaced. SIL Open Font License, so
it is clear for commercial use and for embedding in a logo.

Colour is **limestone** `#E8E1D3` on **slate** `#2A2E36`. The light ground is
deliberate: nearly every bot avatar in a member list is dark, so a pale one is
the one you can find. Swap to the slate files if you would rather it sat back.

## The rule everything here obeys

**A bot avatar spends its life at about 40px in a member list and 20px beside a
message.** Not 512. Line art dies there, interior detail dies there, and only a
filled silhouette or a letterform survives. So every mark was drawn at 8x,
downsampled, and then judged at 20px before anything else about it mattered.

`steward-contact-sheet.png` is that test. Judge from it, not from the 1024 file.

Two things this settled, both of which cost a round of drawing to find out:

- **A tally mark cannot work.** Five strokes need six gaps, and at 20px wide a
  gap under about 1.5px closes up. Heavier strokes make it fill in sooner, not
  later. `marks-sheet.png` has the failed version.
- **Gaps have to be sized in the final pixels, not the drawing.** The first
  keystone used 2-degree joints between stones, which is a third of a pixel at
  20px, so the stones fused into a blob. Nine degrees is the floor. The
  constant is `GAP` in `keystones.py` and the arithmetic is in the comment
  above it.

## The sheets, in the order they were made

    marks-sheet.png        six directions: tally, arch, column, keystone,
                             s-cut, stack. Tally failed outright
    keystones-sheet.png    six ways to draw the keystone once it was chosen.
                             The fan versions read as a crown; only the ones
                             with piers under them read as an arch
    wordmarks-sheet.png    twelve OFL faces setting STEWARD at real banner size
    colourways-sheet.png   eight two-colour schemes, banner and avatar together

## Regenerating

    python getfonts.py      pulls the OFL faces into brand/fonts (gitignored)
    python keystones.py     the mark variants + their sheet
    python wordmarks.py     the typeface comparison
    python final.py         colourways and the delivery files

All plain Pillow, no design tool involved. To change the colour, edit
`PALETTES` at the top of `final.py`; to change the mark, edit `gate3` in
`keystones.py`. Everything downstream rebuilds.

## If you want someone else to draw it instead

`BRIEF.md` is written to be handed to a designer or pasted into a design tool
with no other context. It leads with the 20px constraint, because that is what
every previous attempt died on.
