# What's left, and what's done

The forward-looking list. `AUDIT.md` is the historical record of what the
readiness audit found; `CHANGELOG.md` is the user-facing record of what
changed. This file is the working todo, and it is kept current — see
`CLAUDE.md`.

**Where things stand:** 794 Python tests green on 3.10 and 3.12, plus 115
Kotlin tests for the shared Android rules. Lint, byte-compile and dependency
audit clean. Every safety-critical and legal finding from the audit is closed
or has its remaining part named below — SF-09 and ST-04 closed this round, and
ST-06 is down to the parts that need a real screen reader.

**The one-line summary:** the code is in better shape than the product. Nothing
has ever been built, nobody has ever installed it, and almost everything now
standing between here and a first release is a decision or an account rather
than a commit.

*Last updated 2026-09-03.*

---

## Blocked on you — no amount of coding moves these

| # | What | Cost | Why it blocks |
|---|---|---|---|
| 1 | **Unlock GitHub billing** | Check https://github.com/settings/billing | CI has never run. Every job fails with "the account is locked due to a billing issue" — not a code failure. Until it runs, the 909 tests below are only as good as the last time someone ran them by hand. |
| 2 | **Microsoft Store developer account** | ~$19 once | Microsoft signs Store packages, so **SmartScreen stops warning** — the same result as a €300/yr certificate. Also a distribution channel and a payment system. Cheapest unlock here by a wide margin. |
| 3 | **A clean Windows VM, and the first build** | Free | Nothing in `packaging/` or `core/tray.py` has ever executed. `BUILD.md` walks it. Expect something to be wrong — finding out before anyone else does is the point. |
| 4 | **Confirm you own `protbot.app`** | Domain cost | Three separate things now point at it: the update manifest (`core/updates.py`), the device-link URL (`core/linking.py`), and Android App Links verification. If the domain is not yours, all three need changing before release, and the link URL is baked into a payload format the phone parses. Cheap to settle now, annoying later. |
| 5 | **Publish a contact address** | Free, but it is a decision | `PRIVACY.md` and `SECURITY.md` both hold a placeholder. GDPR Article 13 *requires* the controller's contact details; a policy without one is not compliant. Whether that is a personal email or `security@` on your own domain is your call, which is why neither file guesses. A test fails the day either placeholder is deleted without a real address replacing it. |
| 6 | **Confirm the licence** | Free, effectively one-way | `LICENSE` states the all-rights-reserved default explicitly, which is right for something you intend to sell and keeps every option open. Open source instead is a deliberate, irreversible decision — a permissive licence cannot be recalled from copies people already hold. |
| 7 | **Trademark-clear the name** | Free (USPTO TESS, EUIPO eSearch) | An evening now, far cheaper than after a store listing is built on the name. |
| 8 | **Get the server source into git** | An afternoon | `server/` holds request models and nothing else. The deployed function that holds user emails is unversioned, unreviewed and unbacked-up. Everything below that touches the server waits on this. |
| 9 | **Build the sync server** — `/register`, `/apps`, `/upload`, `/sync`, `/group`, `/link/new`, `/link/join` | A day, after #8 | Both clients are written and tested against a fake transport; there is nothing between them. `server/models.py` defines the wire format and spells out the four things a server must get right: cumulative totals, the client's own date, matching on the canonical key, and checking the `Authorization` token *before* the device id in the payload. That last one is new and is the one that cannot be got wrong quietly — the totals would still be right, and they would be right for whoever asked. |
| 10 | **Build `/license/verify`** | A morning, after #8 | The client calls it and already handles every failure mode — offline grace, refusal, server error. The endpoint does not exist. |
| 11 | **Sign up a merchant of record** | ~5% of revenue | Paddle or Lemon Squeezy. The licence gate is built and there is nothing to sell keys with. Both handle EU VAT, which is the part you do not want to own. |
| 12 | **Lawyer: review `PRIVACY.md`, write terms and a EULA** | A few hundred € | The policy is accurate to the code — every claim in it is checked by a test — but was not written by a lawyer, and there are no terms and no EULA at all. Before any public release or any money changing hands. |

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

### 3. Screen-reader testing, and the last of the inline colours (ST-06 remainder)
The measurable half is done — see Finished. What is left needs a real Windows
session, because it cannot be asserted from source:

- **Nobody has run a screen reader against this.** Narrator or NVDA, one pass
  over each tab. Tk exposes very little to MSAA/UIA on its own, and the honest
  expectation is that some controls announce nothing useful. Finding out which
  is the work.
- **Whether the tab order makes sense**, as opposed to merely existing.
- **200% display scaling**, which DPI awareness makes possible and does not
  make correct.
- **55 inline hex colours remain**, down from 133: the ad banner (no ad network
  is connected), the plan cards, and the chart series in Insights. They do not
  change with the high-contrast palette. `tests/test_accessibility.py` holds a
  per-file ratchet so the count can only fall. The QR canvas is deliberately
  excluded and must stay black on white — running it through a palette would
  make it unscannable.

### 4. Build the Android app for real
The shared rules compile and pass 115 tests. `android/app/` has never been
compiled, because this machine has no Android SDK. Until someone runs
`gradle :app:assembleDebug`, the Android half is source code rather than
software.

### 5. Write the Android screens
The app picker (the `<queries>` block is declared, the UI is not), limit
editing, and the insights screen. The blocking logic underneath them is done
and tested.

### 6. Let people link apps across devices by hand
`syncproto.canonical_app_key` joins the same app on two devices by normalising
its name — a good guess, not a guarantee. A package named after its vendor
rather than its product will not meet the desktop executable. A small screen
saying "these two are the same app" closes it. Nothing depends on it: an
unmatched app simply counts per-device.

### 7. Restore the per-device breakdown on the Processes tab
The tab used to list each linked device's usage separately, reading an
`appDetails` field from a `GET /sync/{device_id}` it made itself. That request
was unauthenticated with the device id in the URL — AUDIT SF-09, in the UI —
and `appDetails` is not in `server/models.py`, so it was parsing a response no
server was ever specified to send. It is now one "Other devices" row per app,
from the authenticated sync client and the documented protocol.

Naming the device again means adding the field to the wire contract, which is
a decision to take while building the server (#9 above) rather than by
inventing it here. Nothing depends on it; the totals are the same either way.

### 8. The remaining roadmap features
In `ROADMAP.md`, all buildable, none blocking: pattern recognition over the
user's own history (plain statistics, no model needed), predictive alerts, PDF
and Excel export, team features. None worth starting before someone has
installed the app.

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
| **Crash handling** | Unhandled exceptions on the main thread, background threads and Tk callbacks all reach the log. A frozen build has no console, so a dead monitor thread used to mean limits silently stopped being enforced while the window looked fine. |
| **A ctypes tray icon** | Replaced pystray, which dropped the LGPL-3.0 §4 obligations that are awkward to satisfy in a frozen build. |

### Cross-device

| Done | What it means |
|---|---|
| **An Android app** | A second application sharing the desktop's rules — focus hours, limit semantics, usage accounting, the protected list, the block decision. `android/core/` compiles and passes 115 tests. |
| **Cross-device sync** | A two-hour limit means two hours across both devices, not two hours each. Uploads are cumulative so a retry cannot double-count; the day is the client's day; merging subtracts this device's own stale contribution rather than taking the larger number. |
| **QR device linking** | The PC shows a code, the phone scans it. The key travels in the URL fragment, which never reaches a web server. An https App Link, not a custom scheme, so the stock camera can open it. The characters stay on screen beside the code as a fallback. Asking for a code and redeeming one are both authenticated. |
| **An authenticated sync API** | Registration issues a device *token*, not just an id, and every later request carries it in an `Authorization` header. The id was the whole credential before, and it is an identifier — it rides in every payload and is printed in the Devices tab. Nothing goes out without a token now; the client refuses locally rather than letting the server turn it away, because an unauthenticated request reaching the server is the vulnerability, not the error message. A 401 or 403 stops sync and says so instead of retrying a rejected credential every half hour, and registration is all-or-nothing so a server that returns an id without a token leaves nothing stored. AUDIT SF-09. |
| **One HTTP client, in core/** | The Devices tab had its own `_api()` on urllib and the Processes tab had a third, doing `GET /sync/{device_id}` on a timer — no credential, plain http permitted, the device id in the URL path, and an endpoint name the protocol does not define. The Devices one is what registered the device, so the tested client in `core/` was the half of the app that never ran. Both are gone; a test fails the build if a UI module imports an HTTP library or puts a device id in a URL again. |
| **A QR encoder** | `core/qrcode.py`, standard library only — byte mode, versions 1–10, all four error levels. Verified by reading generated symbols back with a real decoder, which caught two bugs that produced pixel-perfect unreadable codes. |

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
| **A bill of materials** | CycloneDX 1.5, generated from `requirements.lock` — which is what a release actually installs, hashes and all — so the document cannot describe a different set of packages from the binary. Written by `packaging/sbom.py`, standard library only, so producing a compliance document never depends on a build machine having an extra toolchain or a network. The build writes it before PyInstaller runs and the spec bundles it, because Regulation (EU) 2024/2847 is about the product, not the repository; CI regenerates it and validates it against the official CycloneDX schema. An empty document fails the build rather than passing quietly. |
| **A high-contrast mode, and a palette that passes WCAG AA** | The European Accessibility Act has applied since June 2025. The palette was nine hex literals copied into six files, which is what made a high-contrast mode unbuildable — there was nothing to swap and nothing to measure. It is `ui/theme.py` now, with both palettes and the contrast maths, and measuring the old one turned up four real failures at ordinary text sizes: secondary text on the darkest surface at 3.98:1, the accent colour as text at 4.15:1, white on the accent button at 3.83:1, and the danger button's own label at 3.62:1. All fixed, all held by tests. AUDIT ST-06. |

### Engineering

| Done | What it means |
|---|---|
| **909 tests** | 794 Python across 3.10 and 3.12, 115 Kotlin. Plus lint, a byte-compile pass over the Tk modules the suite cannot import, a packaging-config check, and a wheel build. |
| **An installable package** | `pyproject.toml` declared no build backend, so the project could not be installed at all, and `main.py` covered for it by editing `sys.path` — a line that was doing nothing, since Python already puts a script's directory there. There is a backend and a `protbot` entry point now, the startup sequence moved to `ui/launcher.py` where the entry point can reach it, and `main.py` is a shim so the spec, the `.bat` and `BUILD.md` are untouched. Building it for the first time turned up a `License ::` classifier that PEP 639 superseded and that setuptools now refuses outright — latent for as long as nobody tried. CI builds the wheel on every push. AUDIT ST-04. |
| **Keyboard navigation, and a focus ring you can see** | clam draws focus as a dotted outline in the foreground colour, which on a dark background is invisible, and every control was borderless — a button and the card behind it differed only in fill. Both fixed at the style level rather than per widget, which is how the one that mattered ends up missed. Ctrl+1–5 jump to a tab, Ctrl+Tab cycles, and the tab strip is a stop in the Tab order so the arrows work there as they do in every other Windows app. |
| **Hash-pinned dependencies** | `requirements.lock` pins every dependency to an exact version and SHA-256 hash. Release builds install with `--require-hashes`. |
| **`pip-audit` in CI, and Dependabot** | Pinning makes builds reproducible and also freezes any advisory published after the pin. This is the other half of that trade. |
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
- **The app-name join across devices is a guess.** No string rule resolves a
  package named after its vendor without a brand list. An unmatched app counts
  per-device, which is the behaviour without sync.
- **A link code is a secret with a short life.** Whoever scans it joins the
  device group and can read its totals. Five minutes, single use, and the
  dialog says so.
- **The Android app has never been compiled.** The shared rules have.
- **The high-contrast palette needs a restart.** Each page binds its colours
  when it is imported, which happens before any window exists, so there is no
  live palette to swap. A toggle that quietly did nothing would be worse; the
  Settings page says so beside the control.
- **The wheel does not carry the icon or the privacy policy.** Both sit at the
  repository root rather than inside a package. The shipping artifact is the
  PyInstaller build, whose spec bundles them; the wheel exists so the project
  is installable and `main.py` no longer edits `sys.path`. Both call sites
  already degrade — no icon, and the policy opens from the URL instead.
- **Client-side authentication is half of an authenticated API.** The client
  now holds up its end completely, and it is worth being plain that this buys
  nothing on its own: a server that checks the device id in the payload and
  ignores the header is exactly as exposed as before. `server/models.py` says
  what the server owes; nothing implements it yet.
- **The changelog has no released version.** Nothing has shipped. A test fails
  if that claim stops being true without a version being added.

---

## Suggested order

1. **Unlock billing.** Until CI runs you cannot trust a single push.
2. **Microsoft Store account.** $19 to stop SmartScreen frightening everyone
   who tries to install.
3. **First real Windows build**, on a clean VM, through `BUILD.md`. Find out
   what is broken.
4. **The three decisions**: the domain, the contact address, the licence. No
   code, all required before the repo goes public.
5. **Server into git, then the endpoints** — sync and linking first, licence
   verification second.
6. **Merchant of record.** The last mile to taking money.
7. **Lawyer**, before any public release.
8. **Then features** — and only then marketing. €50 of ads pointed at an app
   nobody can install is €50 spent teaching people it does not work.

Step 3 now also gets you the first screen-reader pass and the first look at
200% scaling, which is the whole of what is left on ST-06 — both need a real
Windows session and neither needs anything bought.

Steps 1–3 cost almost nothing and unblock everything else.
