# What's left, and what's done

The forward-looking list. `AUDIT.md` is the historical record of what the
readiness audit found; `CHANGELOG.md` is the user-facing record of what
changed. This file is the working todo, and it is kept current — see
`CLAUDE.md`.

**Where things stand:** 955 Python tests green on 3.10 and 3.12, plus 118
Kotlin tests for the shared Android rules. Lint, byte-compile and dependency
audit clean. Every safety-critical and legal finding from the audit is closed
or has its remaining part named below.

**The one-line summary:** the code is in better shape than the product. Nothing
has ever been built, nobody has ever installed it, and almost everything now
standing between here and a first release is a decision or an account rather
than a commit.

*Last updated 2026-09-04.*

---

## Blocked on you — no amount of coding moves these

| # | What | Cost | Why it blocks |
|---|---|---|---|
| 1 | **Unlock GitHub billing** | Check https://github.com/settings/billing | CI is currently **off** (`.github/workflows/ci.yml.disabled` — owner's instruction), and it had never run even before that: every job failed with "the account is locked due to a billing issue," not a code failure. Until billing is unlocked and someone renames the workflow back on, the test count in the header above is only as good as the last time someone ran it by hand. |
| 2 | **Microsoft Store developer account** | ~$19 once | Microsoft signs Store packages, so **SmartScreen stops warning** — the same result as a €300/yr certificate. Also a distribution channel and a payment system. Cheapest unlock here by a wide margin. |
| 3 | **A clean Windows VM, and the first build** | Free | Nothing in `packaging/` or `core/tray.py` has ever executed. `BUILD.md` walks it. Expect something to be wrong — finding out before anyone else does is the point. **This one genuinely cannot be coded around**: there is no Windows machine anywhere this session can reach, so nobody has attempted it on your behalf — this line is exactly as true as it was before. |
| 4 | **Confirm you own `protbot.app`** | Domain cost | Three separate things now point at it: the update manifest (`core/updates.py`), the device-link URL (`core/linking.py`), and Android App Links verification. If the domain is not yours, all three need changing before release, and the link URL is baked into a payload format the phone parses. Cheap to settle now, annoying later. |
| 5 | **Publish a contact address** | Free, but it is a decision | `PRIVACY.md` and `SECURITY.md` both hold a placeholder. GDPR Article 13 *requires* the controller's contact details; a policy without one is not compliant. Whether that is a personal email or `security@` on your own domain is your call, which is why neither file guesses. A test fails the day either placeholder is deleted without a real address replacing it. |
| 6 | **Confirm the licence** | Free, effectively one-way | `LICENSE` states the all-rights-reserved default explicitly, which is right for something you intend to sell and keeps every option open. Open source instead is a deliberate, irreversible decision — a permissive licence cannot be recalled from copies people already hold. |
| 7 | **Trademark-clear the name** | Free (USPTO TESS, EUIPO eSearch), then a lawyer if it's close | A plain web search (not a formal TESS/EUIPO search — that's still yours to run) already found a real conflict worth knowing about before going further: an existing **"ProtBot" Discord bot**, live on top.gg, in the same general "bot/software" space this app is in. That does not by itself mean the name is unavailable — but it's common-law prior use in the same category, which is exactly the kind of thing that turns into a dispute later rather than earlier. Worth the formal search and possibly item 12's lawyer before more is built on the name. |
| 8 | **Deploy the sync server** | An hour or two, once a host is picked | The code is done — see Finished below, `server/`, all 7 endpoints plus `/license/verify`, tested. What's left is entirely infrastructure only you can choose: a host (`server/README.md` deliberately does not pick one — a VPS, Fly.io, Render, Railway, whatever you already have), a domain/subdomain with TLS pointed at it, `config.set("server_url", ...)` on the desktop side, and backups of `protbot_server.db`. `server/README.md`'s "Deploying it" section is the checklist. Separately: the *old* deployed function this replaces — unversioned, holding user emails — still exists somewhere and was never reachable from here to migrate or decommission; worth finding and shutting down once the new one is live, so there are not two servers with two different sets of rules. |
| 9 | **Provision licence keys once Paddle exists** | Minutes per sale, until automated | `/license/verify` is real and tested against a `license_keys` table, but nothing fills that table automatically yet — there is no Paddle account to know its webhook payload shape (item 10). `server/issue_license.py` is the manual bridge: run it by hand for now. Once Paddle is set up, its webhook event on a successful sale is what a small `server/paddle_webhook.py` would turn into the same `license_issue()` call this script already makes — share the webhook payload shape when that account exists and this becomes one more file rather than a redesign. |
| 10 | **Sign up a merchant of record** | ~5% of revenue | Paddle or Lemon Squeezy. The licence gate is built and there is nothing to sell keys with. Both handle EU VAT, which is the part you do not want to own. Checked for Montenegro specifically: **Stripe does not support a Montenegro-based seller account at all.** **Paddle does** — Montenegro, Albania, Bosnia and Kosovo are all on its supported-seller list — and its checkout takes any Visa/Mastercard regardless of issuing bank, so a CKB- or Addiko-issued card works there the same as any other. Lemon Squeezy's country list did not confirm or rule out Montenegro in what was checked; ask them directly before picking it over Paddle. Local alternative if a merchant-of-record's cut is unwanted: CKB's own eCommerce gateway, or CorvusPay (regional, Croatian-licensed) — either bills as a Montenegro merchant directly, but then VAT/tax compliance is yours to handle instead of the MoR's. **You're doing this one yourself.** |
| 11 | **Lawyer: review `PRIVACY.md`, write terms and a EULA** | A few hundred € | The policy is accurate to the code — every claim in it is checked by a test — but was not written by a lawyer, and there are no terms and no EULA at all. Before any public release or any money changing hands. |

---

## Can be coded now — no external dependency

Roughly in value order.

### 1. Publish `assetlinks.json` on protbot.app
The Android manifest declares `autoVerify="true"` for the device-link URL.
Without the assetlinks file served from the domain, Android shows a chooser
instead of opening ProtBot directly — it still works, it is one tap worse.
Waits on #4 above.

### 2. The in-app QR scanner
`Linking.parsePayload` reads a scanned code and the manifest opens the app from
one, so the stock-camera path is complete. What is missing is scanning from
*inside* the app, which needs CameraX and ML Kit — and cannot be verified on a
machine with no Android SDK.

### 3. Generate an SBOM, for the EU Cyber Resilience Act
Regulation (EU) 2024/2847 applies to products with digital elements sold in the
EU. Vulnerability-reporting obligations begin **11 September 2026**; full
application **11 December 2027**. Partly covered already — `SECURITY.md` is the
vulnerability policy, `pip-audit` runs in CI, dependencies are hash-pinned.
Missing is the bill of materials; `cyclonedx-py` over the lockfile in a CI job
is most of it.

### 4. Build the Android app for real
The shared rules compile and pass the Kotlin count in the header above.
`android/app/` has never been compiled, because this machine has no Android
SDK. Until someone runs `gradle :app:assembleDebug`, the Android half is
source code rather than software.

### 5. Write the Android screens
The app picker (the `<queries>` block is declared, the UI is not), limit
editing, and the insights screen. The blocking logic underneath them is done
and tested — including, now, the manual app-matching data layer (see
Finished below): `SyncClient.kt` has `manualKeyFor`/`setManualKey`/
`clearManualKey` ready, and no screen calls them yet.

### 6. The remaining roadmap features
In `ROADMAP.md`. Two items are now fully shipped, free, see Finished below:
pattern recognition (item 3, all three pieces) and PDF/Excel report export
(item 5, both formats). Still open: predictive alerts (deliberately not
attempted alongside item 3 — the live half belongs in `core/monitor.py`,
the app's one safety-critical always-running loop, and wants its own pass
rather than being rushed in on the side; see `ROADMAP.md` item 4) and team
features (biggest scope of anything here, its own consent surface, not
worth starting before someone has installed the app).

---

## Written but never executed

Everything Windows-specific was written against documentation and verified only
by tests that read the source rather than run it. It is likely something here
is wrong. Listed so it surprises you on your own machine rather than a user's.

- **`core/tray.py`** — the whole Win32 tray icon, through ctypes. Degrades to
  "no tray" on failure rather than crashing, so the worst case is a missing
  icon.
- **`packaging/build.ps1`, `protbot.spec`, `installer.iss`** — the entire build
  and installer. `build.ps1` launches the frozen app and checks it survives
  eight seconds; that is the gate that matters, because a missing hidden import
  kills a frozen GUI app *silently*.
- **`core/activity.py`'s two OS probes** — foreground window and idle time. The
  policy they feed is tested thoroughly; the probes have never returned a real
  value.
- **`create_shortcut.ps1`** — rewritten for PowerShell 5.1, never executed.
- **`android/app/`** — written in full, never compiled. No Android SDK here.

`BUILD.md` walks the first real build.

---

## Finished

### The app itself

| Done | What it means |
|---|---|
| **Graceful close** | `WM_CLOSE`, a wait, then a forced terminate only as a last resort — instead of an immediate kill that lost unsaved work. |
| **Protected-process denylist** | ProtBot can never close Windows critical processes, the shell, Task Manager, security software, or itself. Enforced in three places, not just the dialog that adds an app. |
| **Sleep and idle accounting** | Closing the lid overnight with a browser open used to book eight hours of "usage" and close it on resume. A gap longer than 1.5 poll intervals is now credited as one interval. |
| **The midnight split** | Time after midnight was filed under the previous day. The session is now split *before* the interval is credited. |
| **Blocked apps actually block** | The `-1` sentinel multiplied out to a negative limit and produced a 0% reading, so a blocked app never triggered. All limit reads go through one function. |
| **Scheduled focus hours** | A recurring window that tightens existing limits, including windows crossing midnight. Never loosens one. |
| **Data retention** | History past the window is dropped on the daily rollover. One year by default. |
| **Atomic config writes, thread locking, storage hardening** | A crash mid-write used to truncate the config and reset every setting. |
| **Rotating logs** | And a log the user can delete, because it is a plaintext record of every app opened. |
| **DPI awareness** | The UI is no longer bitmap-stretched on any display above 100% scaling. |
| **Keyboard navigation and a high-contrast mode (AUDIT ST-06)** | Every dialog closes on Escape; a Canvas used for scrolling — three of them, one per page — is reachable by Tab, which Tk does not do by default; the app's one click-only control (an ad banner, currently unused — `_ADS` is empty) responds to Enter/Space too. A visible focus ring on every focusable control, in both palettes: `ui/a11y.py` sets it once, application-wide, rather than per widget. `ui/theme.py` adds a second, WCAG AA-verified palette (`tests/test_theme.py` checks the actual contrast ratio, not by eye) behind a Settings toggle — restart-required, said plainly, because Tk cannot re-theme a window already on screen. What this does not do, and says so in `ui/a11y.py`: full screen-reader support. Tk does not implement MSAA or UI Automation for the widgets it draws, so NVDA or Narrator would see an unlabelled pane, not a button — closing that gap for real means a different GUI toolkit or unverifiable native interop, not a Settings screen. |
| **Crash handling** | Unhandled exceptions on the main thread, background threads and Tk callbacks all reach the log. A frozen build has no console, so a dead monitor thread used to mean limits silently stopped being enforced while the window looked fine. |
| **A ctypes tray icon** | Replaced pystray, which dropped the LGPL-3.0 §4 obligations that are awkward to satisfy in a frozen build. |
| **Pattern recognition across your history (`ROADMAP.md` item 3)** | All three pieces, all free, all in `core/trends.py` + `ui/insights_page.py`. "This Week vs Last Week": total time this week against last week, the percent change, up to three apps with the biggest move either direction (`week_over_week_delta`, `biggest_movers`). "Patterns in Your History": which app tends to run right before a distraction-category session starts (`preceding_app_triggers`, reusing the page's existing `_DISTRACTING` category set rather than a new taxonomy), and average usage per day of week with how far each day drifts from the overall average (`weekday_breakdown`). `_draw_premium`'s old teasers for all three are gone; a regression test guards against teasing something already shipped as still "Planned" — this class of bug happened once already this session. |
| **PDF and Excel report export (`ROADMAP.md` item 5)** | Both formats, both free, same 30-day per-app history the CSV export already sends. `core/export_xlsx.py` (openpyxl, MIT, hash-pinned in `requirements.lock`, noticed in `THIRD_PARTY_NOTICES.md`) builds a styled `.xlsx` workbook. `core/export_pdf.py` builds a multi-page `.pdf` by writing PDF objects directly — no library: `fpdf2` is LGPL-3.0 (the same problem class AUDIT BL-05 already fixed once, for pystray), and `reportlab` mandates Pillow (permitted under BL-05's own reasoning, but against the standing decision to keep it out — the same call `core/qrcode.py` already made). Verified against `qpdf --check` and `pdftotext`, dev-only tools, same role OpenCV/segno play for `core/qrcode.py`'s tests. "Export Excel" and "Export PDF" sit next to "Export CSV" in the Processes tab. |

### Cross-device

| Done | What it means |
|---|---|
| **An Android app** | A second application sharing the desktop's rules — focus hours, limit semantics, usage accounting, the protected list, the block decision. `android/core/` compiles and passes 115 tests. |
| **Cross-device sync** | A two-hour limit means two hours across both devices, not two hours each. Uploads are cumulative so a retry cannot double-count; the day is the client's day; merging subtracts this device's own stale contribution rather than taking the larger number. |
| **QR device linking** | The PC shows a code, the phone scans it. The key travels in the URL fragment, which never reaches a web server. An https App Link, not a custom scheme, so the stock camera can open it. The characters stay on screen beside the code as a fallback. |
| **A QR encoder** | `core/qrcode.py`, standard library only — byte mode, versions 1–10, all four error levels. Verified by reading generated symbols back with a real decoder, which caught two bugs that produced pixel-perfect unreadable codes. |
| **The sync API is authenticated, end to end (AUDIT SF-09)** | Registration returns a bearer token as well as a device id, and every client — desktop and the Android app's `SyncClient.kt` — sends it as `Authorization: Bearer <token>` on every request after; no device id travels in a URL path anywhere any more. `ui/devices_page.py` also turned out to be a *third*, older, unauthenticated implementation of registration and linking that never called the tested `core/syncclient.py` / `core/linking.py` it duplicated — including a `/r` endpoint that had drifted from the real `/register`, and a "cross-device rows" display in the Processes tab reading response fields no server contract ever defined. Both are now gone in favour of the one implementation; a new `core.linking.list_group()` lists the Devices tab's group with no device id in the request at all. The server side of this (see below) now checks the token against the device it claims to be, closing the finding rather than just the client half of it. |
| **Matching an app across devices by hand** | `syncproto.canonical_app_key` is a best-effort guess and cannot resolve every pair (Firefox.exe never meets `org.mozilla.firefox` on its own — see Known-imperfect below). The Devices tab's new "Match Apps…" dialog lets the user give an app the same sync key on both devices instead; an override wins outright over the computed key, and setting one drops that app's cached server id so the next sync cycle re-sends it under the new key. Mirrored in the Android app's `SyncClient.kt` (`manualKeyFor`/`setManualKey`/`clearManualKey`) so the data is ready whenever Android has a screen to call it from — it does not yet. |

### The sync server (`server/`)

| Done | What it means |
|---|---|
| **All 7 sync/linking endpoints, plus `/license/verify`** | `/register`, `/apps`, `/upload`, `/sync`, `/link/new`, `/link/join`, `/group`, `/license/verify` — a real FastAPI app (`server/app.py`) implementing `server/models.py`'s contract exactly, which both clients were already written and tested against. `server/models.py` itself gained the pieces it was missing to actually be that contract: a `z` (date) field on `UploadReq` that `core/syncproto.py`'s real `build_upload()` has always sent but the model never declared, plus `SyncReq`/`LinkNewReq`/`LicenseVerifyReq`/`LicenseVerifyResp`, none of which existed as named models despite every client already sending and reading exactly that shape. Additive only — nothing an existing client does had to change. |
| **Every device its own group from birth** | `server/db.py`: a device gets a fresh group id the moment it registers, so "not yet linked to anyone" is a group of one rather than a null case every query has to special-case. Linking moves a device's group id to match the host's and migrates its already-assigned app ids along where nothing in the new group already claims the same one — the one case that is not migrated (both devices had already synced the same app solo, under separate ids, before ever linking) is documented in `join_group()`'s own docstring as a narrow, accepted gap, the same "best-effort, and it says so" posture `canonical_app_key` already has. |
| **Group totals exclude a device that has gone quiet** | Not specified in `server/models.py`, and a real gap if left unhandled: naively summing "each device's most recent upload" would let a device offline for days sit in every `/sync` response forever, inflating a live device's limit for as long as the other stayed off. `server/db.py`'s `group_totals()` only counts a device's contribution if it has been seen within `GROUP_CONTRIBUTION_MAX_AGE_SEC` (2 days — deliberately generous, so a real timezone difference is never mistaken for staleness; note 2 already settled that dates are the client's own to keep). |
| **Bearer tokens are stored hashed and checked in constant time** | `server/auth.py`: SHA-256 over the token, `hmac.compare_digest` for the check, and the same 401 whether the device does not exist, the header is missing, or the token is simply wrong — so a probe cannot learn which case it hit. `/group` authenticates by token alone, with no device id anywhere in its request, matching what `server/models.py` already specified for it. |
| **The link-code endpoints are rate-limited** | `server/ratelimit.py` — the other half of AUDIT SF-09 `server/models.py` names directly ("rate-limiting the link-code endpoint — is still open; nothing in the client can substitute for that"). In-memory, per-process, documented as exactly that rather than built out into something distributed this project does not need yet. |
| **A manual bridge for licence keys until Paddle exists** | `server/issue_license.py` — a CLI that writes the same row a Paddle webhook would write on a successful sale. Nothing calls it automatically yet; there is no Paddle account to know the webhook's payload shape (see "Blocked on you" above). |
| **43 tests, entirely through FastAPI's `TestClient`** | No real network, no real deployment — but every request/response shape a real client produces, including the ones AUDIT SF-09 specifically named: a token that does not match the device it claims, and unthrottled link-code guessing. `tests/test_server.py`. **Never deployed anywhere** — see "Blocked on you" above and `server/README.md`. |

### Legal and compliance

| Done | What it means |
|---|---|
| **Third-party ads removed** | Real brand names were shipping in an in-app ad slot. A test fails the build if one returns. |
| **No advertising features that do not exist** | The plan comparison listed unimplemented features as included. A test fails if that returns. |
| **Privacy consent gate** | Nothing is recorded until the policy has been shown and accepted. |
| **Consent can be withdrawn** | GDPR Art. 7(3). `revoke_consent` and `open_policy` existed and nothing in the UI called either — consent was taken once at first run and could never be revisited. |
| **Export My Data** | GDPR Art. 15 and 20. The app could delete everything and hand back nothing. Licence and sync credentials deliberately excluded, so the file is safe to send on. |
| **`LICENSE`** | A public repo with no licence is all-rights-reserved by default and nobody can tell. |
| **`THIRD_PARTY_NOTICES.md`** | psutil (BSD-3-Clause) and plyer (MIT) both require their notice reproduced in a binary distribution. Bundled *in the build*, with a test that fails if the lockfile and the notices drift apart. |
| **`SECURITY.md`** | Somewhere to report a vulnerability, plus the weaknesses that are known and accepted so nobody rediscovers them. |
| **`CHANGELOG.md`** | `core/updates.py` tells users to update; without this it asks them to take it on trust, and a security fix ships looking routine. |
| **The installer licence page** | Pointed at `PRIVACY.md`, asking users to "accept" a privacy policy. It shows `LICENSE` now. |

### Engineering

| Done | What it means |
|---|---|
| **A full test suite** | Counts are at the top of this file, which a test holds current — not repeated here, after this row itself went stale once. Plus lint, a byte-compile pass over the Tk modules the suite cannot import, and a packaging-config check. |
| **Hash-pinned dependencies** | `requirements.lock` pins every dependency to an exact version and SHA-256 hash. Release builds install with `--require-hashes`. |
| **`pip-audit` in CI, and Dependabot** | Pinning makes builds reproducible and also freezes any advisory published after the pin. This is the other half of that trade. |
| **An installable package (AUDIT ST-04)** | `pyproject.toml` declares a real build backend and a `protbot = "main:main"` entry point; `main.py`'s `sys.path.insert` — which only ever worked because it happens to sit at the repo root beside `core/` and `ui/` — is gone. Verified with an actual `pip install -e .`, not just read back: that install caught a real bug (a `License ::` classifier that current setuptools now refuses to combine with a license expression, PEP 639 — pre-existing, never triggered because nothing had ever run `pip install .` here before), fixed alongside it. The `dependencies` CI job now installs the package for real and imports `main` on Windows, the target platform. |
| **Renamed to ProtBot** | Including the data directory, with a migration that never overwrites newer data and never deletes the old folder if the move fails. |
| **Signed, machine-bound licence gate** | 14-day offline grace. Server errors never revoke; only an explicit refusal does. |
| **A real distribution** | PyInstaller spec, Inno installer, working uninstaller. Never run — see above. |

---

## Known-imperfect, deliberately

Recorded so nobody rediscovers them as bugs.

- **Focus hours is one window, not a scheduler.** Covers work hours, study
  hours, evenings. Multiple named blocks if anyone asks.
- **Client-side licensing is deterrence, not security.** The machine belongs to
  the user. The server is the authority for anything that costs money to
  provide; the client cache is tamper-*evident*, not tamper-proof.
- **The midnight split can misattribute up to one poll interval.** The
  straddling interval goes to the new day. Bounded, and it errs safe.
- **Premium gates nothing yet.** `_PREMIUM_FEATURES` is deliberately empty. That
  is honest, and it is also the reason there is nothing to sell.
- **Sync stops enforcing after two hours offline.** A group total older than
  that is dropped and each device falls back to its own usage. Enforcing a limit
  against a two-hour-old guess is the worse failure.
- **The server's rate limiter is in-memory, one process.** Resets on
  restart, does not coordinate across multiple instances behind a load
  balancer. Sized for the single-instance deployment this whole server is
  sized for; a distributed limiter is real scope it does not need yet.
  `server/ratelimit.py`.
- **Linking after already syncing solo, to the same app, on both sides, is
  the one app-matching case the server does not carry forward.** Both
  devices' rows survive; only the one that was already claimed on the
  side you did not link from goes unreachable until it happens to
  re-sync. Same "best-effort, and it says so" posture as the client-side
  app-name join above. `server/db.py`'s `join_group()`.
- **The app-name join across devices is a guess.** No string rule resolves a
  package named after its vendor without a brand list. An unmatched app counts
  per-device, which is the behaviour without sync — or the user closes it by
  hand from the Devices tab's "Match Apps…" dialog.
- **A link code is a secret with a short life.** Whoever scans it joins the
  device group and can read its totals. Five minutes, single use, and the
  dialog says so.
- **The Android app has never been compiled.** The shared rules have.
- **No screen-reader support.** Every control is keyboard-operable and has a
  visible focus ring; naming those controls to NVDA or Narrator would need
  MSAA/UI Automation, which Tk does not implement and this project has no
  way to build or test blind. See `ui/a11y.py`.
- **High-contrast mode takes a restart.** Tk bakes a colour into a widget at
  the moment it is built; there is no live "re-theme everything on screen."
- **The changelog has no released version.** Nothing has shipped. A test fails
  if that claim stops being true without a version being added.

---

## Suggested order

1. **Unlock billing, then turn CI back on** (`git mv
   .github/workflows/ci.yml.disabled .github/workflows/ci.yml`). Until it
   runs you cannot trust a single push.
2. **Microsoft Store account.** $19 to stop SmartScreen frightening everyone
   who tries to install.
3. **First real Windows build**, on a clean VM, through `BUILD.md`. Find out
   what is broken.
4. **The three decisions**: the domain, the contact address, the licence. No
   code, all required before the repo goes public.
5. **Deploy the sync server.** The code is done and tested — this is a
   hosting choice now, not a coding task. `server/README.md`.
6. **Merchant of record**, then wire its webhook to `server/issue_license.py`'s
   `license_issue()` call so a sale provisions a key automatically.
7. **Lawyer**, before any public release. Also the trademark question if
   the top.gg "ProtBot" bot turns out to matter.
8. **Then features** — and only then marketing. €50 of ads pointed at an app
   nobody can install is €50 spent teaching people it does not work.

Steps 1–3 cost almost nothing and unblock everything else.
