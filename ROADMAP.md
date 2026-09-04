# ProtBot Roadmap

Where planned features live so they are not forgotten — and so they stay **out**
of the marketing surface until they actually work.

## The rule

A feature may only appear in `_FREE_FEATURES` or `_PREMIUM_FEATURES`
(`ui/devices_page.py`) once it works end to end in the shipped build.

Everything else goes in `_PLANNED_FEATURES`, which renders greyed out under a
"Planned" heading with a "not included in any purchase" note. Selling a feature
that does not exist is deceptive advertising, and becomes a refund and
chargeback problem the moment the app takes money.

When a feature ships, move it up the list here **and** in `devices_page.py`.

---

## Planned Premium features

These are the features that were previously advertised as if they existed. They
are the intended Premium tier — kept here in full so the plan survives.

### 1. Cross-device sync
Usage totals aggregated across every linked device, so a daily limit applies to
you rather than to one machine.

- **Status:** done in code, on both ends — the client-side plumbing
  (`ui/devices_page.py`, `ui/processes_page.py`) and now a real, tested
  server (`server/`) implementing every endpoint it calls. Nothing between
  them is fake or stubbed any more.
- **Blocked on:** deployment — a hosting decision, not a coding task. See
  STATUS.md and `server/README.md`.
- **Notes:** device registration, 8-char link codes and the 30-minute upload
  protocol are built, authenticated (AUDIT SF-09) and rate-limited on the
  link endpoints. `ST-05` (backend in version control) is closed.

### 2. Configurable data retention — SHIPPED

- **Status:** done. `retention_days` defaults to 365; 0 keeps everything.
  Pruning runs on the daily date rollover the monitor already detects, not at
  startup, so launch stays fast.
- **Note:** this is now a plain user setting rather than a paid tier. Making
  someone pay to keep their own history is a poor trade, and the database
  indices (SF-11) solved the performance half of the problem anyway.

### 3. Pattern recognition across your history — SHIPPED
Surface real patterns from recorded usage: which app tends to precede a long
distraction session, which days drift worst, how a week compares to the last.

- **Status:** done, all three pieces, all free. `core/trends.py`:
  `week_over_week_delta` / `biggest_movers` (this week vs last),
  `preceding_app_triggers` (which app tends to run right before a
  distraction-category session starts), `weekday_breakdown` (average usage
  per day of week, and how far each day drifts from the overall average).
  `ui/insights_page.py` renders all three — "This Week vs Last Week" and
  "Patterns in Your History" (distraction triggers + day-of-week
  breakdown). `_draw_premium`'s old teasers for these are gone.
- **Notes:** was advertised as "AI pattern recognition". Plain statistics
  over the existing `usage_sessions` table, no model — genuinely useful on
  its own. Only call it AI if a model is actually involved. "Distraction"
  reuses `ui/insights_page.py`'s existing `_DISTRACTING` category set
  rather than inventing a second taxonomy.

### 4. Predictive distraction alerts
Warn *before* a distraction session starts, based on time of day and what was
just opened.

- **Status:** not started. #3 shipped, so the statistics this would be
  built on already exist (`core/trends.py`) — the part not started is the
  live half: catching the moment a session opens and deciding, in real
  time, whether to warn.
- **Blocked on:** nothing, but deliberately not attempted alongside #3.
  `core/monitor.py` is the one safety-critical, always-running loop in this
  app (limit enforcement, the kill watcher, grace periods) — a live "warn
  right now" hook belongs there, not bolted on separately, and that is a
  different, higher-stakes kind of change than a statistics function
  rendered on a tab someone opens when they feel like it. Wants its own
  pass rather than being rushed in on the back of a pattern-recognition
  session.
- **Notes:** the honest v1 is a threshold rule ("you have opened this app at
  this hour on 4 of the last 5 days"), not a prediction model. A passive
  Insights-tab card reusing `preceding_app_triggers`/`weekday_breakdown`
  would technically be buildable today, but "alerts" means something that
  reaches the user *at* the risky moment — a retrospective report on a tab
  they have to go open is a different feature wearing this one's name, and
  advertising it as this one is exactly what AUDIT BL-02 exists to catch.
- **Design settled, when this is built:** the tracked device computes its
  own risk entirely locally (the statistics already exist —
  `core/trends.py`'s `preceding_app_triggers`/`weekday_breakdown` — no
  server round-trip needed to decide whether to warn). If a parent-facing
  view of this is wanted at all, only a fired/not-fired signal and the
  device id cross the network — never the app-open pattern behind it. The
  server already has no way to identify a device except by an id the
  parent already labelled themselves (Devices tab), so this needs no new
  server-side model or endpoint, only a client-side decision never to send
  the raw pattern anywhere.

### 5. PDF / Excel report export — SHIPPED
Formatted weekly and monthly reports.

- **Status:** done, both halves, both free. `core/export_xlsx.py` builds a
  styled `.xlsx` workbook (header row, sized columns, frozen header);
  `core/export_pdf.py` builds a multi-page `.pdf` (title, page numbers,
  the same table). Both read the same 30-day per-app history the existing
  CSV export already sends. `ui/processes_page.py` wires "Export Excel"
  and "Export PDF" buttons next to "Export CSV".
- **Notes:** Excel export added `openpyxl` (MIT) as a runtime dependency —
  checked against the packaging decision in AUDIT BL-05, hash-pinned in
  `requirements.lock`, notice added to `THIRD_PARTY_NOTICES.md`. PDF export
  added **no** dependency: `fpdf2` is LGPL-3.0 (the exact problem BL-05
  already fixed once, for pystray — reintroducing that class of licence for
  a report-export feature would undo the fix), and `reportlab`, while BSD
  itself, mandates Pillow — permitted under BL-05's own reasoning (Pillow's
  licence was never the problem, pystray's was) but against the standing
  decision to keep it out, the same call `core/qrcode.py` already made for
  the same reason. `core/export_pdf.py` writes PDF objects directly instead
  — verified against `qpdf --check` and `pdftotext`, dev-time tools only,
  same role OpenCV/segno play for `core/qrcode.py`'s tests.

### 6. Team challenges & leaderboards — DROPPED
Shared goals across a group of linked users.

- **Status:** not building this. Owner's call: not necessary. Kept here,
  struck rather than deleted, so nobody re-proposes it without knowing it
  was already considered and declined.
- **Notes (for the record):** would have been the biggest scope of
  anything on this list, and the largest privacy surface — it publishes
  one person's usage to others, and device IDs are not identities, so it
  would have needed a real account model first.

### 7. Scheduled focus hours — SHIPPED

- **Status:** done. `core/schedule.py` plus a Settings section. One recurring
  window (days, start, end, cap) rather than a multi-block scheduler — that
  covers work hours, study hours and evenings, and it ships complete.
- **Semantics:** only affects apps that already have a daily limit, and can
  only ever tighten, never loosen. A cap of 0 blocks outright.
- **Note:** overnight windows (22:00–06:00) work, and the window belongs to the
  day it started on, so a Friday-night block still applies at 01:00 Saturday.
  That is the case a naive `start <= now <= end` gets wrong.
- **Next:** multiple named blocks, if anyone asks for them. One window first.

### 8. Priority support
A commitment, not a feature.

- **Notes:** only advertise once there is a support channel and a response
  target you can actually meet

---

## Recovered scope — found in two old builds, not yet in ProtBot

Two builds of an earlier, much more feature-complete system turned up
during this project (`FocusGuardChild_1.exe` — a Windows child agent with a
live Firebase backend, and a React Native/Expo phone app covering iOS and
Android). Neither build itself is part of ProtBot and neither is being
touched further — this section is the feature list they surfaced, to be
built fresh in ProtBot's own stack (Python/Tkinter desktop, Kotlin Android,
the FastAPI `server/`) if and when each is wanted. Nothing here is
committed; everything is `not started`.

### 9. Anti-tamper hardening (Windows)
A scheduled-task watchdog that relaunches ProtBot if it's killed, admin
auto-elevation with no UAC prompt at every logon (a task run at `/rl
highest`), and an ACL lock on the install folder so a standard account
gets read+execute only — even from a terminal.
- **Status:** not started.
- **Notes:** three separate, independently-useful pieces; the watchdog and
  elevation depend on each other, the folder lock doesn't. None of them
  hide the app — it stays visible in Task Manager, consistent with this
  project's consent-based positioning (see AUDIT BL-01 and the ads note
  below for why that posture matters generally).

### 10. Parent PIN
A PIN a parent sets, required to quit ProtBot (and, later, to uninstall
it) once one exists.
- **Status:** not started.
- **Notes:** needs a settings UI plus hashed storage (pbkdf2 + salt, not
  plaintext). Standalone — doesn't need #9 first.

### 11. Shutdown-as-consequence for a force-killed session
If ProtBot wasn't closed via the PIN flow, optionally shut the PC down
with a warning; the PIN cancels it.
- **Status:** not started.
- **Note — decide deliberately before building:** this is a real step up
  in aggressiveness from anything ProtBot does today (closing an *app*
  vs. shutting down the whole PC). Worth being sure this is the tone
  wanted, the same way team challenges (#6) got a deliberate "no."

### 12. Web filtering
DNS-level blocking (point network adapters at a filtering resolver —
CleanBrowsing or Cloudflare for Families, both free) plus browser
window-title matching as a crude backstop for what DNS misses.
- **Status:** not started — a new capability area. ProtBot tracks app
  usage only today; nothing looks at web content at all.
- **Notes:** needs admin (same elevation as #9). Deliberately not a local
  TLS-intercepting proxy — that needs installing a root certificate,
  a real security trade-off for a home user to take on.

### 13. Location on request
A parent requests it, the device answers once (OS location API, falling
back to IP-level geolocation) — never polled continuously.
- **Status:** not started.
- **Notes:** real privacy and legal weight — put it on the lawyer list
  (STATUS.md) before building, not after.

### 14. "Request more time," with parent approval
The tracked person asks for extra minutes (optionally scoped to one app,
with a short reason); a parent approves or declines remotely.
- **Status:** not started.
- **Blocked on:** a server endpoint for the request/approval round trip —
  `server/app.py` has nothing like this yet.

### 15. New-app detection
Notice when an app outside the tracked list gets installed or opened, and
optionally hold it pending a parent's approval, rather than only ever
tracking apps someone added by hand.
- **Status:** not started.

### 16. Weekly summary report, sent to the parent
- **Status:** partly there. The actual statistics already exist and run
  entirely on-device (`core/trends.py`) — what's missing is packaging one
  into a summary, a server endpoint to receive it, and a parent-side view.
  Not new analysis work, just plumbing.

### 17. SOS / emergency alert
One tap notifies every linked parent, with a location if one is available.
- **Status:** not started.
- **Notes:** should never be gated behind a paid tier — this is a safety
  feature, not a premium one.

### 18. Remote command channel
A parent pushes a command to a linked device; the device acknowledges.
- **Status:** not started.
- **Blocked on:** new server endpoints (nothing in `server/app.py` does
  this today) and a client-side poll/handler on each platform. Biggest
  "what would it even do" question of anything on this list — needs a
  concrete first command (lock now? something smaller?) before it's
  buildable at all, not just server plumbing.

### 19. Token economy, chores, and prize redemption
Earn tokens for staying under a limit, spend them for extra minutes,
optionally gift them to a sibling; a separate chores list with parent
approval; a parent-managed catalog of real-world prizes tokens can be
redeemed for.
- **Status:** not started.
- **Blocked on:** real server-side balance/transaction logic — `server/`
  has nothing like an account balance today, and getting "spend" right
  (no double-spend across two devices) is its own small design problem,
  not just a table.
- **Notes:** three features but one dependency chain — chores and prizes
  both assume the token balance exists first.

### 20. Parent↔child chat
Text messaging between linked devices.
- **Status:** not started.
- **Notes:** decide deliberately before building — real moderation and
  privacy surface, the same category of decision team challenges (#6)
  got a "no" on. Not a default-yes just because the old system had it.

### 21. Geofencing ("Places")
Parent sets one or more locations, gets notified on arrival/departure.
- **Status:** not started.
- **Notes:** heavier than #13 — continuous rather than on-request. Same
  lawyer-list flag, more so.

### 22. An iOS app
ProtBot has no iOS presence today — Windows desktop and Android only.
- **Status:** not started. Biggest single item on this whole list.
- **Notes:** the old system used Apple's actual Screen Time API (Family
  Controls / DeviceActivity / ManagedSettings, via `react-native-device-
  activity`) — the real, Apple-sanctioned way to build this on iOS, not a
  workaround. A new ProtBot iOS app means a real build from scratch
  against that framework, in whatever stack gets chosen — nothing here
  carries over as code, only the fact that this is the right API to
  target.

---

## Before any of this ships

Premium cannot be sold at all until the monetization chain works. From
`AUDIT.md`:

- **SF-08** — mostly done. `core/licensing.py` holds the entitlement gate,
  signed and machine-bound, with a 14-day offline grace period; activation is a
  real flow. `/license/verify` is now built and tested (`server/app.py`).
  What remains is entirely outside code: a merchant of record to sell keys,
  and the server actually running somewhere (see STATUS.md)
- **SF-09** — fixed, client and server. Every endpoint checks the bearer
  token against the device it claims to be for; `/link/new` and
  `/link/join` are rate-limited. `server/`, `tests/test_server.py`
- **ST-05** — fixed. `server/` holds a real, tested implementation now, not
  just the request models it used to

Sequence: deploy the server (a hosting decision now, not a coding task —
STATUS.md, `server/README.md`), integrate a merchant of record, *then*
build features 1–6.

---

## Deliberately not doing

- **Ads.** The ad slot exists in `ui/app.py` but `_ADS` is empty and stays that
  way until a real ad network is integrated. Never fill it with real companies'
  names or taglines as placeholder content — that is false endorsement
  (AUDIT BL-01)
