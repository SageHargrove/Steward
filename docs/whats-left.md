# What is left

Everything in the build plan is built. This is what stands between "built" and
"a stranger can use it", in the order it matters.

---

## Blocked on you

**1. Make the repository public.**

Nothing else on this list matters until this happens, because a private
repository means nobody can download a release and the in-app update check
returns "no public releases". One switch in Settings, and no code changes.

Before flipping it:

- The git history is clean. The bot token you once pasted went into a chat, not
  into a file, so it is not in the repository. Rotate it anyway if you have any
  doubt: Developer Portal, your app, Bot, Reset Token.
- `docs/build-plan.md` contains your Steam dates, revenue plans and compliance
  notes. Decide whether that is public. Moving it out of the repository is the
  easy answer.
- `blueprint/calendars/steam-game.yaml` has `anchor: 2027-03-01` in it,
  which announces your target launch date.

**2. Run it once against your live server.**

The calendar and playtest commands have never executed against real Discord.
Everything else has. Restart the bot, then:

    /calendar-run post:launch-day     drafts into #steward-reports
    /playtest-open wave:test
    /playtest-issue wave:test member:@you

---

## Worth doing before other people use it

**3. A second pair of eyes on a fresh machine.** The download has only ever
been unpacked on the machine that built it. Give the zip to one person with no
Python installed and watch where they get stuck without helping. That will find
more than another week of my testing.

**4. A screenshot or two in the README.** People decide whether to download
from the picture. There is no picture.

**5. A short "first five minutes" section.** The README says what it does and
how to get it. It does not walk somebody from download to a finished server,
which is what SETUP.md is, and SETUP.md is written for a developer.

---

## Real but not urgent

**6. macOS and Linux downloads.** `start.sh` works, but there is no bundled
build for either, so both still need Python installed. The same
`tools/build_dist.py` approach does not transfer: neither platform has an
equivalent of Windows' embeddable package. The honest options are a `pipx`
install, a Homebrew formula, or telling those users to install Python. Most
Discord server owners are on Windows, so this can wait for someone to ask.

**7. Code signing.** Roughly $200 a year, and it removes Windows' blue
"Windows protected your PC" panel. The README explains the panel instead. Worth
buying only if this becomes something you actively promote.

**8. The Inno Setup installer.** `install/setup.iss` is written but has never
been compiled, and the zip plus `INSTALL.bat` covers the same ground without an
unsigned `.exe`. Only worth finishing if you want a Programs and Features entry.

**9. Retention of the decay report.** It goes live in mid-October, once the
ledger has eight weeks of history. Nothing to do until then except let it run.

---

## The three documents that stay unfinished on purpose

`docs/moderation.md`, `docs/playtest-pipeline.md` and `docs/onboarding-flow.md`
each end with a section on what actually happened, and each is empty. They can
only be filled in by things happening.

That is the half worth paying for. The configuration above is copyable by
anybody; the record of what the rules turned out to be wrong about is not.
Write each entry the week it happens. After launch you will write a smoother
version from memory, and the memory will have removed exactly the parts that
were hard.
