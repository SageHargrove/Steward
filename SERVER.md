# Hosting Steward on a Linux server

START.bat and start.sh run Steward on the machine in front of you. This
runbook runs it on a server instead, so the ledger keeps recording when your
PC is off. Every command pastes fine from a phone SSH client.

One rule before anything else: **run the bot in exactly one place.** Two
processes on the same token both receive every event and each writes its own
local database, so histories diverge and neither is complete. Stop the bot on
your PC (the Stop button in the UI, or close its window) before starting it
on a server, and vice versa.

## 1. Get the code and its needs

```
cd ~ && git clone https://github.com/SageHargrove/Steward.git steward-app
cd steward-app && python3 -m venv .venv
.venv/bin/pip install -r steward/requirements.txt
```

The venv is not optional politeness: current Ubuntu marks the system Python
as externally managed and refuses bare `pip install`.

## 2. The token

```
nano steward/.env
```

One line: `DISCORD_TOKEN=` followed by your bot token (SETUP.md section 0
is how to get one; resetting the token from the developer portal is fine and
invalidates the old copy). The optional settings — `STEWARD_DB`,
`RETENTION_DAYS`, `REPORT_CHANNEL`, `MOD_CHANNEL` — have sensible defaults
and can be added later.

## 3. Prove it runs, then make it a service

First run in the foreground, so a wrong token is a readable message instead
of a silent restart loop:

```
cd ~/steward-app/steward && ../.venv/bin/python bot.py
```

Once it says it is connected, Ctrl-C and hand it to systemd:

```
sudo cp ~/steward-app/install/steward.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now steward
systemctl status steward --no-pager
```

If your username is not `ubuntu` or the clone is not at
`~/steward-app`, fix the three paths in the unit file first — it says where.

## Updating

```
cd ~/steward-app && git pull && sudo systemctl restart steward
```

## Moving an existing ledger

Activity history lives in `steward/data/` where the bot runs, and it cannot
be backfilled — Discord keeps no per-member activity record. If the bot has
been running on your PC, copy that folder to the server before the first
start (`scp -r steward/data ubuntu@SERVER:~/steward-app/steward/`), or the
server starts a fresh ledger from day zero.

## Backups

Two things hold everything: `steward/data/` and `steward/.env`. Add both to
whatever already backs up the server.
