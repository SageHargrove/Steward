<!--
  Pinned in the staff reporting channel. Explains what lands here before
  anything does, so an empty channel is not a mystery.
-->
# What lands in here

Nothing yet, if the ledger bot has not been started.

Once it is running, this channel gets the numbers that nothing else will tell you:

**The weekly digest.** How many people joined, how many finished the join questions, how many posted at least once, and how many of each previous week's arrivals are still here. That last one is the number that matters and the one no third-party bot produces.

**Decay alerts.** When a channel drops well below its own normal, which is different from being quiet. Needs a couple of months of history before it means anything.

**Where people came from.** The join question hands out a temporary role, the bot records the answer and removes the role again, so the split shows up here rather than on anybody's profile.

**Why a separate bot at all**
Discord's API has no per-member last-active field. There is no way to ask who has gone quiet, and no way to ask later about a week nothing was recording. Any answer to "did people come back after that build" has to come from something that was listening at the time.

It records who posted in which channel and when. It does not record what anyone wrote, and it does not ask Discord for permission to read message content. Members can run `/my-data` and `/forget-me` themselves.

Run `/ledger-status` here for the current numbers at any time.
