# What's left

Current state and remaining work. `AUDIT.md` is the historical record of what
was found and fixed; this is the forward-looking list.

**Where things stand:** 693 Python tests green on 3.10 and 3.12, plus 115
Kotlin tests for the shared Android rules; lint clean. Every safety-critical
and legal finding from the audit is closed or has its remaining part named
below. What is left splits cleanly into *things only you can do* and *things
anyone can code*.

*Last re-audited 2026-08-29.* That pass found six things that were missing
rather than half-built — no licence file, no third-party notices, no crash
handling, no way to export your own data, no security policy, no changelog —
plus one live legal gap: consent could be given and never withdrawn. All are
now closed. What it could not close is listed below.

---

## Blocked on you — nothing can proceed without these

These are the real gates. No amount of coding moves them.

| # | What | Cost | Why it blocks |
|---|---|---|---|
| 1 | **Unlock GitHub billing** | Unknown — check https://github.com/settings/billing | CI has never run. Every check is red, and every job fails with "account is locked due to a billing issue". You are flying blind on every push. |
| 2 | **Microsoft Store developer account** | ~$19 one-time, possibly free now | Microsoft signs Store packages, so **SmartScreen stops warning** — same result as a €300/yr certificate. Also gives you a distribution channel and a payment system. Cheapest unlock on this list by a wide margin. |
| 3 | **Merchant of record** (Paddle or Lemon Squeezy) | ~5% of revenue | The client licensing gate is built. Without this there is nothing to sell keys with. Both handle EU VAT for you. |
| 4 | **A `/license/verify` endpoint** | A morning's work on the server | The client calls it and handles every failure mode. It does not exist. |
| 4b | **The sync server** — `/register`, `/apps`, `/upload`, `/sync`, `/link/new`, `/link/join` | A day, on top of item 6 | Both clients are written and tested; there is nothing between them. QR device linking is built on both sides and needs the two `/link` endpoints to do anything. `server/models.py` defines the wire format and spells out the three things a server must get right (cumulative totals, the client's date, matching on the canonical key). Until it exists, the phone and the PC each count their own time. |
| 5 | **Lawyer review of PRIVACY.md, plus ToS and a EULA** | A few hundred euros | The policy is accurate to the code but was not written by a lawyer. You also have no terms and no EULA at all. |
| 6 | **Get the server source into git** | An afternoon | `server/` holds Pydantic models and nothing else. The deployed function holding user emails is unversioned, unreviewed and unbacked-up. |
| 7 | **Trademark-clear the name** | Free (USPTO TESS, EUIPO eSearch) | Cheaper now than after you have users. Also confirm you own the domain. |
| 7b | **Decide a published contact address** | Free, but it is a decision | `PRIVACY.md` and `SECURITY.md` both have a placeholder. GDPR Article 13 *requires* the controller's contact details — a policy without one is not compliant. Whether that is your personal email or a `security@` on your own domain is your call, which is why neither file guesses. A test fails the day the placeholder is deleted without an address replacing it. |
| 7c | **Confirm the licence** | Free, but effectively one-way | `LICENSE` now states the all-rights-reserved default explicitly, which is right for something you intend to sell and preserves every option. If you would rather it were open source, decide that deliberately: a permissive licence cannot be recalled from copies people already hold. |
| 8 | **A clean Windows VM** | Free | Nothing in `packaging/` or `core/tray.py` has ever run. See below. |

---

## Never been run

Everything Windows-specific was written against documentation and verified only
by tests that read the source. It is very likely something here is wrong.

- **`core/tray.py`** — the whole Win32 tray icon, via ctypes. Degrades to "no
  tray" on failure rather than crashing, so the worst case is a missing icon.
- **`packaging/build.ps1`, `protbot.spec`, `installer.iss`** — the entire
  build and installer. `build.ps1` launches the frozen app and checks it stays
  running for eight seconds, which is the gate that matters: a missing hidden
  import kills a frozen GUI app *silently*.
- **`core/activity.py`'s two OS probes** — foreground window and idle time. The
  policy they feed is tested; the probes themselves are not.
- **`create_shortcut.ps1`** — rewritten for PowerShell 5.1 but not executed.

The release checklist in `BUILD.md` walks the first real build.

---

## Can be coded now — no external dependency

Roughly in value order.

### 1. API authentication (AUDIT SF-09)
`GET /sync/{device_id}` sends no token. The device ID *is* the credential and
it travels in the URL path, where it lands in server and proxy logs. Anyone
holding or guessing one can read that user's data.

Client-side plumbing is a day. The server half is item 6 above.

### 2. ~~Pin dependencies by hash~~ — DONE
`requirements.lock` pins every dependency to an exact version and SHA-256 hash.
Install release builds with `--require-hashes`.

### 3. Make it an installable package (AUDIT ST-04 remainder)
`main.py` still does `sys.path.insert`. A real `[project.scripts]` entry point
would drop the hack and make the PyInstaller spec simpler.

### 4. Accessibility (AUDIT ST-06 remainder)
DPI awareness and font sizes are fixed. Still missing: keyboard navigation,
screen-reader labelling, a high-contrast mode. The EU Accessibility Act has
applied to consumer software since June 2025.

### 5. Remaining roadmap features
In `ROADMAP.md`, all buildable, none blocking:
pattern recognition over your own history (plain statistics, no model needed),
predictive alerts, PDF/Excel export, team features (needs #1 and sync first).

### 6. ~~Rename to ProtBot~~ — DONE
The code says ProtBot everywhere, and `core/paths.py` migrates an existing
`%LOCALAPPDATA%\FocusGuard` folder on first run. `LEGACY_APP_NAME` in that file
is the only thing that finds a previous install's data and **must never be
renamed with the app**; there is a test that fails if it is.

### 7. An SBOM, for the EU Cyber Resilience Act
Regulation (EU) 2024/2847 applies to "products with digital elements" made
available in the EU. Vulnerability-reporting obligations begin **11 September
2026** and the regulation applies in full from **11 December 2027**. It expects
a software bill of materials, a vulnerability-handling process, security
updates over a defined support period, and CE marking.

Partly done already: `SECURITY.md` is the vulnerability policy, `pip-audit`
runs in CI, and `requirements.lock` pins by hash. Missing is a generated SBOM —
`cyclonedx-py` over the lockfile in a CI job is most of it. Not urgent with
zero users and nothing released, but the dates are close enough to plan around
rather than discover.

### 8. Linking apps across devices by hand
`syncproto.canonical_app_key` joins the same app on two devices by normalising
its name, and it is a good guess rather than a guarantee — a package named
after its vendor instead of its product will not match the desktop executable.
A small screen letting the user say "these two are the same app" closes the
gap. Nothing depends on it: an unmatched app simply counts per-device, which is
the behaviour without sync.

---

## Known-imperfect, deliberately

Recorded so nobody rediscovers them as bugs.

- **Focus hours is one window, not a scheduler.** Covers work hours, study
  hours, evenings. Multiple named blocks if anyone asks.
- **Client-side licensing is deterrence, not security.** The machine belongs to
  the user. The server is the authority for anything that costs money to
  provide; the client cache is tamper-*evident*, not tamper-proof.
- **The midnight split can misattribute up to one poll interval.** The straddling
  interval goes to the new day. Bounded, and it errs toward the safer side.
- **Premium gates nothing yet.** `_PREMIUM_FEATURES` is deliberately empty — the
  paid tier does not gate a single shipped feature. That is honest, and it is
  also the reason there is nothing to sell.
- **Sync stops enforcing after two hours offline.** A group total older than
  that is dropped and each device falls back to its own usage. Enforcing a
  limit against a two-hour-old guess is the worse failure.
- **The Android app has never been compiled.** The shared rules have; the
  Android layer needs an SDK this machine does not have.
- **The changelog has no released version in it.** Nothing has shipped, so
  every entry sits under Unreleased. A test fails if that claim stops being
  true without a version being added.
- **The export leaves out the licence blob and the device id.** They are
  credentials, and an export is a file the user may send to someone else. The
  file says what was left out and why, rather than omitting it silently.

---

## Android and the app stores

See [`PLATFORMS.md`](PLATFORMS.md) and [`android/README.md`](android/README.md).

Android is a **separate application**, not a build of this one — Tkinter does
not run there, and Android forbids listing or closing other apps, so tracking
goes through `UsageStatsManager` and blocking through an `AccessibilityService`.
What is shared is the rules: focus hours, limit semantics, usage accounting,
the protected list and the sync protocol all live in one place and are held to
the same test cases on both sides.

State: `android/core/` compiles and passes 115 tests. `android/app/` is written
but **has never been built** — this machine has no Android SDK. iOS is not
started and needs an entitlement Apple grants case by case.

Cross-device sync is written on both platforms and wired into both limit
checks, so an hour on the phone plus an hour on the PC reaches a two-hour
limit. The server it talks to does not exist yet — item 4b above.

## What the 2026-08-29 re-audit closed

Recorded so the next audit does not rediscover them.

| Gap | Why it mattered | Closed by |
|---|---|---|
| No `LICENSE` | A public repo with no licence is all-rights-reserved by default and nobody can tell. Some tooling reads the absence as permission. | `LICENSE`, plus `license` metadata in `pyproject.toml` |
| No third-party notices | psutil (BSD-3-Clause) and plyer (MIT) both require their notice to be reproduced in a binary distribution. Shipping without one is a licence breach. | `THIRD_PARTY_NOTICES.md`, bundled by the spec and installer, with a test that fails if the lockfile and the notices drift apart |
| Installer "licence" page showed the privacy policy | It asked the user to *accept* a privacy policy, which is not what a policy is for. | `LicenseFile` now points at `LICENSE`; the policy is shown as information beforehand |
| No crash handling | A frozen build has no console. An exception on a background thread killed the monitor silently — limits stopped being enforced while the window kept showing old numbers. | `core/crash.py`, covering the main thread, background threads and Tk callbacks |
| No data export | The app could delete everything (Art. 17) and hand back nothing (Art. 15, Art. 20). | `core/dataexport.py` and Settings → **Export My Data**; credentials deliberately excluded |
| **Consent could not be withdrawn** | Art. 7(3) requires withdrawal to be as easy as giving consent. `revoke_consent` and `open_policy` existed and *nothing in the UI called either* — consent was given once at first run and never revisitable. | Settings → **Withdraw Consent** and **Read Privacy Policy** |
| No security policy | Nowhere to report a vulnerability, and the known-and-accepted weaknesses were undocumented. | `SECURITY.md` |
| No changelog | `core/updates.py` tells users to update without saying what changed — which is also how a security fix goes out looking routine. | `CHANGELOG.md` |
| No dependency scanning | Pinning by hash makes builds reproducible and also freezes any advisory published after the pin. | `pip-audit` in CI against `requirements.lock`, plus Dependabot |

## Suggested order

1. **Billing** — until CI runs you cannot trust any push
2. **Microsoft Store account** — the cheapest thing that removes SmartScreen
3. **First real Windows build** on a clean VM, working through `BUILD.md`
4. **Rename**, if you are going to — before anyone installs
5. **Merchant of record + `/license/verify`** — the last mile to taking money
6. **Lawyer**, before any public release
7. *Then* features, and only then marketing

Steps 1–3 cost almost nothing and unblock everything. Nothing on the feature
list matters until an install completes without a scary warning.
