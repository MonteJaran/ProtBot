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

- **Status:** client-side plumbing exists (`ui/devices_page.py`,
  `ui/processes_page.py`, `server/models.py`), server is unversioned
- **Blocked on:** committing the backend to this repo (AUDIT ST-05) and adding
  API authentication (AUDIT SF-09)
- **Notes:** device registration, 8-char link codes and the 30-minute upload
  protocol are already designed and partly built

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

### 6. Team challenges & leaderboards
Shared goals across a group of linked users.

- **Status:** not started
- **Blocked on:** #1, and a real user account model — device IDs are not
  identities
- **Notes:** biggest scope of anything here, and the largest privacy surface.
  Needs its own consent step beyond the first-run gate, since it publishes one
  person's usage to others

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

## Before any of this ships

Premium cannot be sold at all until the monetization chain works. From
`AUDIT.md`:

- **SF-08** — mostly done. `core/licensing.py` holds the entitlement gate,
  signed and machine-bound, with a 14-day offline grace period; activation is a
  real flow. What remains is a `/license/verify` endpoint on the server and a
  merchant of record to sell keys
- **SF-09** — the sync API has no authentication
- **ST-05** — the backend is not in version control

Sequence: fix SF-08 and SF-09, commit the server, integrate a merchant of
record, *then* build features 1–7.

---

## Deliberately not doing

- **Ads.** The ad slot exists in `ui/app.py` but `_ADS` is empty and stays that
  way until a real ad network is integrated. Never fill it with real companies'
  names or taglines as placeholder content — that is false endorsement
  (AUDIT BL-01)
