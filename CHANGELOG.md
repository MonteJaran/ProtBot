# Changelog

All notable changes to ProtBot are recorded here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file exists because `core/updates.py` tells users a newer version is
available. Telling someone to update without telling them what changed asks
them to take it on trust, and it is also how a security fix goes out looking
like every other release. The `notes` field in the update manifest should
carry the relevant entry from here.

## [Unreleased]

Nothing has been released yet. Everything below is in the repository and, apart
from the Windows-specific pieces listed in `STATUS.md` under "Never been run",
covered by tests — but **no build has ever been produced**, so no user has run
any of it. The first entry under a real version number will be written when
`BUILD.md` is walked on a Windows machine.

### Added

- **Linking a phone to a PC by QR code.** The PC shows a code, the phone scans
  it, and the two join a sync group. The eight characters stay on screen beside
  it, because a camera that will not focus is a bad reason to be unable to link
  a device. The key travels in the URL fragment, which never reaches a web
  server, and the code stops being displayed before the server forgets it.
- **A QR encoder in the standard library** (`core/qrcode.py`). Byte mode,
  versions 1 to 10, all four error levels. Written rather than depended on:
  every Python QR library pulls in Pillow, which was removed when pystray went.
  Verified by reading generated symbols back with a real decoder.
- **Cross-device sync.** A limit now counts phone and PC time together instead
  of each device allowing the full amount. The rules are shared between
  platforms (`core/syncproto.py`, `android/core/.../Sync.kt`) and held to the
  same test cases. Off until a device is registered. The server it talks to
  does not exist yet.
- **An Android app** (`android/`). A second application sharing the desktop's
  rules — focus hours, limit semantics, usage accounting, the protected list.
  The shared module compiles and passes its tests; the Android layer has never
  been built, because it needs an SDK.
- **Scheduled focus hours.** A recurring window that tightens existing limits,
  including windows that cross midnight.
- **Data retention.** History older than the configured window is dropped on
  the daily rollover. Defaults to one year.
- **An update check** that fetches a small static manifest and never downloads
  or installs anything itself.
- **A licence gate** (`core/licensing.py`), signed and machine-bound, with a
  14-day offline grace period. Server errors never revoke; only an explicit
  refusal does.
- **A first-run privacy consent gate.** Nothing is recorded until the policy
  has been shown and accepted.
- **Export my data** (Settings → Data). GDPR Art. 15 and 20: the app could
  already delete everything and could not hand any of it back. Licence and sync
  credentials are deliberately excluded so the file is safe to send on.
- **Crash handling** (`core/crash.py`). Unhandled exceptions on the main
  thread, on background threads, and inside Tk callbacks now reach the log. A
  frozen build has no console, so previously a dead monitor thread meant limits
  silently stopped being enforced while the window looked fine.
- **A licence, and third-party notices.** `LICENSE` states the
  all-rights-reserved default explicitly; `THIRD_PARTY_NOTICES.md` reproduces
  the psutil and plyer notices that both licences require a distribution to
  carry.
- **A security policy** (`SECURITY.md`), including the weaknesses that are
  known and accepted, so nobody has to rediscover them.
- **Tests and CI.** The suite runs on Python 3.10 and 3.12, on Linux and
  Windows, with lint, a byte-compile pass over the Tk modules, a packaging
  config check, `pip-audit` against the pinned lockfile, and the Android rule
  tests.
- **A software bill of materials.** CI generates a CycloneDX SBOM from
  `requirements.lock` and publishes it as a build artifact on every push —
  Regulation (EU) 2024/2847 requires one for products with digital elements
  sold in the EU.

### Changed

- **Renamed from FocusGuard to ProtBot**, including the data directory.
  `core/paths.py` migrates an existing `%LOCALAPPDATA%\FocusGuard` folder on
  first run, never overwriting newer data and never deleting the old folder if
  the move fails.
- **Apps are now closed gracefully.** `WM_CLOSE` first, a wait, and only then a
  forced terminate — instead of an immediate kill that lost unsaved work.
- **The tray icon is a direct `Shell_NotifyIcon` implementation** rather than
  pystray, which removed the LGPL-3.0 §4 obligations that are awkward to
  satisfy in a frozen build.
- **Dependencies are pinned by exact version and SHA-256 hash**
  (`requirements.lock`).
- **ProtBot is now an installable package.** `main.py` no longer hand-rolls
  `sys.path.insert`; `pyproject.toml` declares a build backend and a
  `protbot` console-script entry point instead. `build.ps1` installs it
  (editable) before PyInstaller runs, so `protbot.spec` imports
  `core.version` directly rather than patching `sys.path` itself.

### Fixed

- **The package could not actually be built.** `pyproject.toml` carried both
  a PEP 639 `license` expression and a "License ::" trove classifier, which
  current setuptools refuses as conflicting — invisible until something
  actually ran `pip install -e .`, which nothing had.

- **Usage accrued while the machine was asleep.** Closing the lid overnight
  with a browser open booked eight hours of "usage" and closed it on resume.
  A gap longer than 1.5 poll intervals is now credited as one interval.
- **Time spent after midnight was filed under the previous day.** The session
  is split before the interval is credited, not after.
- **A blocked app was never actually blocked.** The `-1` sentinel multiplied
  out to a negative limit and produced a 0% usage reading. All limit reads go
  through one function now.
- **ProtBot could close critical Windows processes**, the shell, Task Manager,
  security software, or itself. `core/protected.py` is enforced in three
  places, not just in the dialog that adds an app.
- **Config writes could truncate the file** on a crash mid-write, resetting
  every setting. Writes are atomic.
- **Third-party brand names shipped in an in-app advertising slot.** Removed,
  with a test that fails the build if one returns.
- **The plan comparison advertised features that did not exist.** Removed, with
  a test that fails if an unimplemented feature is listed as included.

### Security

- **The sync API had no authentication (AUDIT SF-09).** A device ID alone was
  the credential, and one code path put it straight in a URL, where it lands
  in server, proxy and log lines. Registration now also returns a bearer
  token that every later request sends as `Authorization: Bearer`. Fixing
  this surfaced two more copies of the same problem: `ui/devices_page.py` and
  `ui/processes_page.py` each carried their own unauthenticated request code
  — a leftover from before `core/syncclient.py` existed — instead of using
  it. Both now do. The server-side check waits on the server existing at all;
  the client sends the header regardless.
