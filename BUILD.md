# Building and distributing ProtBot

> **Nothing here has been tested on Windows yet.** These files were written
> against the PyInstaller and Inno Setup documentation but never run — the
> first real build will need adjustment. Treat the smoke test in `build.ps1`
> as the gate, not this document.

## The short way: let GitHub build both

You do not need a Windows machine, and you do not need an Android SDK.
`.github/workflows/build.yml` builds the Windows app, the installer and an
Android debug APK on GitHub's runners and uploads all three as downloadable
artifacts.

    Actions tab → "Build" → "Run workflow"

Artifacts appear at the bottom of the run's summary page when it finishes:

| Artifact | What it is | How to run it |
|---|---|---|
| `protbot-windows-app` | The folder build | Unzip, run `ProtBot.exe` |
| `protbot-windows-installer` | The Inno installer | Unzip, run the `.exe` |
| `protbot-android-debug-apk` | A debug APK | `adb install -r app-debug.apk`, or copy it to the phone and open it |

Two things to expect, neither of them a fault:

- **SmartScreen will warn** on the Windows build. It is unsigned — "More
  info" → "Run anyway". A Microsoft Store account (~$19, `STATUS.md` item 2)
  is what removes that.
- **The Android app needs two permissions no installer can grant**: Usage
  access, and Display over other apps, both under Settings → Apps → Special
  app access. Without the first it records nothing at all.

**The "Run workflow" button only appears once `build.yml` is on `main`.**
That is a GitHub rule, not a quirk of this file: a `workflow_dispatch`
workflow is not registered until it exists on the default branch. Dispatching
it against a feature branch before then returns 404. Once it is on `main` you
can still run it against any branch you like, from the branch dropdown.

**This also requires GitHub Actions to be able to run.** At the time of writing
every job fails within seconds with no runner assigned, which is the billing
lock in `STATUS.md` item 1 — not a fault in the workflow. Until that is
cleared, use the manual routes below.

## Requirements

| Tool | Why | Where |
|---|---|---|
| Python 3.10+ | Building | python.org |
| PyInstaller | Freezes the app | `pip install pyinstaller` |
| Inno Setup 6 | Builds the installer | https://jrsoftware.org/isdl.php |
| `signtool.exe` | Signing | Windows SDK |

## Building

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The script runs the tests and the linter first and refuses to build from a red
tree. Then it generates the Windows version resource from `core/version.py`,
runs PyInstaller, **launches the result and checks it stays running for eight
seconds**, and finally builds the installer.

That smoke test matters more than it looks. A frozen build that is missing a
hidden import fails at launch, and because this is a GUI app it fails
*silently* — no console, no error, just nothing. Without the check you find out
from a user.

Output:

```
dist/ProtBot/            the folder build
dist/installer/ProtBot-<version>-setup.exe
```

## Why a folder build, not one-file

One-file unpacks the entire app to `%TEMP%` on every launch. It is slower, and
"executable unpacks itself to temp and runs from there" is a behaviour
antivirus scores badly — this app already enumerates and closes processes, so
it does not need more suspicion. A folder build also keeps every DLL separately
signable; signing a one-file stub leaves its payload unsigned.

The user still downloads exactly one file, because Inno Setup wraps the folder.

## Code signing

**Unsigned, SmartScreen shows a full-screen "Windows protected your PC" warning
and most people cancel.** For an app that reads your process list, that warning
is fatal to installs.

```powershell
$env:PROTBOT_CERT_THUMBPRINT = "<thumbprint>"
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Sign
```

The build signs the executable *before* packaging and the installer after, so
both are covered.

### Getting a certificate

| Option | Cost | Notes |
|---|---|---|
| **Azure Trusted Signing** | ~$10/month | Cheapest real option. Needs a verified identity. |
| OV certificate | €200–400/yr | Signs immediately, but reputation builds slowly — early users still see warnings. |
| EV certificate | €300–600/yr | Instant SmartScreen reputation. Requires a hardware token. |
| **Microsoft Store** | Very low, possibly free | See below. |

### The Microsoft Store route

Publishing through the Store means **Microsoft signs the package**, so
SmartScreen does not warn at all — the same outcome as a certificate, for a
fraction of the cost. The individual developer account has historically been a
one-time fee of about $19; Microsoft has changed this more than once, so check
the current terms.

It also gives you a distribution channel and a built-in payment system, which
matters because ProtBot has no payment path of its own yet (AUDIT SF-08).

For a pre-traction app this is almost certainly the right first move. The
tradeoff is Store certification review and less control over the listing.

## Antivirus

Even signed, expect some engines to flag early builds. ProtBot enumerates
processes, terminates processes, and registers a startup entry — individually
normal, together a generic-trojan shape.

Before any public release:

1. Sign everything.
2. Submit to Microsoft at https://www.microsoft.com/wdsi/filesubmission
3. Submit false positives to the other major vendors.
4. Say plainly in your listing *why* the app needs process access.

`core/protected.py` matters here too: an app that terminates Task Manager on a
loop is not a false positive to a heuristic engine, it is a correct detection.
Do not weaken that denylist.

## Release checklist

- [ ] Bump `__version__` in `core/version.py` (a test asserts `pyproject.toml` agrees)
- [ ] `python -m pytest` and `python -m ruff check .` — both clean
- [ ] Build, and confirm the smoke test passes
- [ ] Install on a **clean Windows VM**, not your dev machine — that is the only way install-path bugs surface (it is how AUDIT SF-03 hid: `create_shortcut.ps1` used PowerShell 7 syntax and failed for every user on stock Windows)
- [ ] Confirm the first-run privacy gate appears and declining exits
- [ ] Confirm the tray icon appears and Quit works — `core/tray.py` is Win32 ctypes and **has never been run**
- [ ] Confirm Settings → Delete All Data removes the database, config and logs
- [ ] Uninstall, and confirm the Run key and `%LOCALAPPDATA%\ProtBot` are handled
- [ ] Confirm an app is warned before it is closed, and gets a chance to save

## Publishing an update

`core/updates.py` checks a static JSON manifest at startup and tells the user
if a newer version exists. It never downloads or installs anything — an app
that can silently replace its own executable is a much larger security surface
than this project needs.

The manifest is a static file, so host it free on GitHub Pages, Cloudflare
Pages, or anywhere. See `packaging/version.json.example`:

```json
{
  "version": "1.1.0",
  "url": "https://protbot.app/download",
  "notes": "Fixes a crash when...",
  "critical": false
}
```

Set `critical: true` for a security fix — the app then interrupts rather than
showing a dismissible bar. Point `UPDATE_MANIFEST_URL` in `core/updates.py` at
wherever you host it, and publish the new manifest **after** the download is
actually live.

## Reproducible builds

`requirements.lock` pins every dependency to an exact version with a SHA-256
hash, generated by `pip-compile --generate-hashes`. Install from it for a
release build so two builds a month apart are the same software:

```powershell
python -m pip install --require-hashes -r requirements.lock
```

Regenerate after changing a dependency:

```
pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml
```

`requirements.txt` keeps loose bounds for day-to-day development.

## Building the Android APK by hand

Needs a JDK 17+ and the Android SDK with platform 35. Android Studio installs
both; on a headless machine, the command-line tools plus:

```
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
```

Then, with `ANDROID_HOME` set:

```bash
cd android
gradle :app:assembleDebug -PwithAndroid
# android/app/build/outputs/apk/debug/app-debug.apk
```

`-PwithAndroid` is what includes the `:app` module. `settings.gradle.kts`
leaves it out when no SDK is present, so that `gradle :core:test` — the shared
rules, 115 tests — keeps working on machines without one.

**Build debug, not release.** A debug APK is signed with the universal debug
key and installs anywhere. The release build is unsigned until someone creates
a keystore, and Android refuses to install an unsigned package.

`:app` had never been compiled before this workflow existed, and writing it
turned up two things that stop the first build outright: Kotlin 2.0 requires
the Compose compiler Gradle plugin, which was not applied, and the release
build referenced a `proguard-rules.pro` that did not exist. Both are fixed and
both are now pinned by tests in `tests/test_packaging_build.py`. Expect more of
the same — nothing in `android/app/` has run.

## Other platforms

See [`PLATFORMS.md`](PLATFORMS.md). Short version: the Microsoft Store is the
right target, and Android or iOS would be a separate application rather than
another build of this one.
