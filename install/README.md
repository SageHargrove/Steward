# Installing

## The one you want

Double-click **`INSTALL.bat`** in the folder above this one.

It adds a Start Menu folder called *Server Setup for Discord* and offers a
desktop shortcut. Then press the Windows key, type "Server Setup", and press
Enter.

Nothing is copied, registered, or written outside your own Start Menu, and it
needs no administrator rights. The shortcuts point at the files where they
already sit, so `git pull` updates what the Start Menu launches. That is the
right shape while the code still changes.

Undo it with `install\Uninstall.bat`, or the *Remove these shortcuts* entry in
the same Start Menu folder. Neither touches `steward\data\steward.sqlite3`.
Discord cannot rebuild that file, so nothing in this project deletes it.

## Files

    INSTALL.bat              double-click this
    install/Install.ps1      what it runs. Per-user, no admin, no registry
    install/Uninstall.bat    removes the shortcuts
    install/Uninstall.ps1
    install/setup.iss        for later: a real distributable installer
    brand/steward.ico        the shortcut icon, 16px to 256px

The icon is the same arch as the bot's avatar, rendered separately at every
size Windows uses rather than scaled down from one large image. Regenerate it
with `python brand\icon.py`.

## Later: a real installer

`install/setup.iss` is an [Inno Setup](https://jrsoftware.org/isdl.php) script.
It builds one `.exe` that installs into Program Files, adds a Programs and
Features entry, and needs no terminal at any point. Open it in the Inno Setup
Compiler and press F9; the result lands in `install/dist/`.

**It has not been compiled or tested.** Inno Setup is not installed here, so it
is written from the documented behaviour and should be treated as a first draft
until somebody builds it once.

It deliberately does not package `steward/.env` or `steward/data/`. One holds a
live bot token and the other holds members' activity history, and shipping
either inside an installer would be a straightforward breach rather than an
oversight.

### The Python problem

As written, the installer lays down the files and shortcuts but still needs
Python on the machine. Fine for a developer audience, not fine for anyone else.
Three ways out, in the order they are worth considering:

**1. Ship the embeddable Python.** About 15 MB zipped, from python.org's
"Windows embeddable package". Unpack it to `{app}\python`, install the
dependencies into it once during setup, and point `START.bat` at
`{app}\python\python.exe` instead of whatever is on PATH. Nothing global is
touched and there is no existing install to conflict with. This is the right
answer and it is roughly a day of work.

**2. Chain python.org's installer as a prerequisite.** Simpler, but it modifies
the machine's PATH and can collide with a Python already there.

**3. Freeze it with PyInstaller.** Avoid. Much larger download, regularly trips
antivirus heuristics, and an unsigned executable that asks for a Discord token
is exactly the shape of thing people are right to be suspicious of. The
blueprint and calendar YAML still sit beside it as loose files you edit, so it
does not even buy a single-file result.

### Signing

Whichever route, an unsigned installer shows Windows SmartScreen's blue
*"Windows protected your PC"* panel the first time anyone runs it. A
code-signing certificate is roughly $200 a year and is the only thing that
removes it. Worth knowing before promising anyone a clean install.
