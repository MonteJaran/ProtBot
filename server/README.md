# ProtBot sync server

Implements the contract `server/models.py` defines and both clients
(`core/syncclient.py`, `core/linking.py`, `core/licensing.py` on desktop;
`android/core/.../Sync.kt` on Android) are already written and tested
against. Read `server/models.py`'s docstring before changing anything here
— the four notes in it are what a server has to get right, and this
implementation exists to satisfy exactly those.

## Running it

```bash
pip install -r server/requirements.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Data lives in `PROTBOT_SERVER_DATA_DIR` (default: the current directory) as
a single SQLite file, `protbot_server.db`. Set that environment variable to
somewhere durable before running for real — the default is fine for local
testing, not for a deployment that has to survive a restart.

## What this is not

**Not deployed anywhere.** This has been run locally, through FastAPI's
`TestClient` (no real network) and through `uvicorn` directly on this
machine — not on any actual host. The same honesty `STATUS.md` applies to
the Windows build applies here: expect something to be wrong the first time
it meets a real network, a real reverse proxy, or real concurrent load, and
finding that out is the point of doing it before anyone depends on it.

**Not behind TLS.** `core/syncclient.py`'s `Transport` refuses to send
usage data anywhere that isn't `https://`, so this needs a reverse proxy
(nginx, Caddy, or your host's managed TLS) in front of it before either
client can talk to it at all. Nothing in this repository sets that up,
because it depends entirely on where you deploy — see "Deploying it" below.

**No Paddle integration.** `/license/verify` is complete and correct
against a `license_keys` table, but nothing writes to that table
automatically — there is no webhook handler, because there is no Paddle
account yet to know the webhook's payload shape (STATUS.md item 11).
`server/issue_license.py` is the manual bridge until then; that script's
docstring says exactly what a `server/paddle_webhook.py` would need to do
in its place.

**No broader rate limiting.** `server/models.py` note 4 names one specific
gap — the link-code endpoints — and that is what `server/ratelimit.py`
covers. Registration spam and licence-key brute-forcing are not throttled;
neither was asked for, and adding limits nobody has hit yet is a guess
at a shape the real abuse might not even take.

**In-memory rate limiting, one process.** `server/ratelimit.py` says this
in its own docstring: it resets on restart and does not coordinate across
multiple server instances behind a load balancer. Fine for the single-
instance deployment this whole file is sized for; real scope beyond that.

## Deploying it

No platform is chosen, on purpose — this is a decision about your hosting
account, not something to guess at from inside a sandbox with no access to
it. The app itself is a plain ASGI app (`server.app:app`) with one file
dependency (SQLite), so it runs anywhere that can run `uvicorn` and give it
a writable directory: a small VPS with a systemd unit, Fly.io, Render,
Railway — whatever you already have or want to learn. Whatever you pick,
you still need:

1. **A domain or subdomain pointed at it**, with TLS. `protbot.app` already
   shows up elsewhere in this codebase (`core/updates.py`, `core/linking.py`)
   — `sync.protbot.app` or similar keeps everything under one domain, once
   STATUS.md item 4 (confirming you own it) is settled.
2. **`config.set("server_url", ...)`** on the desktop side pointed at that
   URL — nothing calls this automatically; there is no UI for it yet either
   (out of scope for this pass, and the Devices tab already has the
   registration flow built around whatever `server_url` holds).
3. **A process manager** that restarts it if it crashes and starts it on
   boot — a systemd unit, a Docker restart policy, or whatever your chosen
   platform provides.
4. **Backups of `protbot_server.db`.** It holds device registrations, group
   memberships and usage totals — nothing irreplaceable-to-a-stranger (no
   emails, per server/models.py note — they're discarded on arrival), but
   losing it means every linked device loses its group and has to re-link.

## Testing it

```bash
python -m pytest tests/test_server.py -v
```

Runs entirely through FastAPI's `TestClient` against a temporary SQLite
file — no real network, no real deployment needed. This is what CI would
run (`.github/workflows/ci.yml.disabled` is currently off — see
`STATUS.md` item 1 — but a `server` job belongs there once it is back on).
