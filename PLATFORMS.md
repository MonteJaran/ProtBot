# Other platforms: stores, Android, iOS

Short answer to the two questions:

- **Microsoft Store — yes.** ProtBot is a Windows app and that is its store.
- **Android — started.** See [`android/`](android/). It is a *second
  application*, not a build of this one: Tkinter does not run on Android and
  the enforcement mechanism is completely different. But the rules are shared,
  and the shared module compiles and passes 93 tests today.
- **iOS — not started**, and harder than Android.

This document explains the constraints, so decisions are made with the real
numbers rather than by discovering them three weeks in.

---

## What ProtBot actually is

A count of the platform-specific calls in the current codebase:

| API | Uses | What it does |
|---|---|---|
| `user32` | 30 | Foreground window, posting `WM_CLOSE`, tray messages, menus |
| `tkinter` | 19 | The entire user interface |
| `winreg` | 18 | Start-with-Windows entry |
| `kernel32` | 7 | Process handles, idle time |
| `winsound` | 5 | Notification sound |
| `Shell_NotifyIcon` | 5 | The tray icon |
| `psutil.process_iter` | 3 | Listing every running process |

There is no cross-platform layer under this. It is Windows all the way down,
by necessity — the app's core function is *see every running program and close
one of them*, and that is an operating-system-specific privilege.

**Tkinter does not run on Android or iOS at all.** Not slowly, not with a
wrapper. There is no path from this UI to a phone.

---

## Android

### The two things that make it a rewrite, not a port

**1. You cannot see what other apps are running.**

`getRunningAppProcesses()` has returned only your *own* process since Android 5.1.
`getRunningTasks()` is deprecated and restricted to your own tasks. This was
deliberate — the ability to enumerate running apps was removed precisely
because it is a surveillance capability.

The sanctioned replacement is **`UsageStatsManager`**, which gives you
aggregated per-app usage over time windows. It needs the `PACKAGE_USAGE_STATS`
permission, which is not a normal runtime prompt: you send the user to a
Settings screen and they grant it manually. Many never come back.

**2. You cannot close another app.**

There is no Android equivalent of `TerminateProcess`. `killBackgroundProcesses()`
touches background processes only, never the app in front of the user, which is
exactly the one you would want to close.

How real blockers do it: an **`AccessibilityService`** watches window-state
changes, notices the blocked app coming to the foreground, and immediately
launches your own full-screen overlay or sends the user home. Combined with
`SYSTEM_ALERT_WINDOW` for the overlay.

That works, and it is how every app in this category ships — StayFree,
ActionDash, Freedom and Opal all do it. It is also the part most exposed to a
policy change, which is worth designing around rather than worrying about.

### Play Store review

Google reviews `AccessibilityService` use closely and has tightened the rules
several times. You must declare the use in Play Console and justify it, and
apps that were vague about it have been removed or held in review.

Apps in this category do ship, though — the bar is making the purpose
unmistakable. `android/` is built for that: it requests
`canRetrieveWindowContent="false"`, only `typeWindowStateChanged`, and a
narrow `<queries>` block instead of `QUERY_ALL_PACKAGES`. Asking for less than
you could is the whole strategy.

### And the competition is preinstalled

**Digital Wellbeing** ships on every Android device, free, made by the company
that controls the APIs you would be fighting to use. Screen Time does the same
on iOS. On Windows there is no equivalent — which is a real part of why the
desktop version has a reason to exist at all.

### What has been built

`android/core/` — the shared rules, ported from the Python and held to the same
test cases. Compiles and passes without the Android SDK.

`android/app/` — the Android layer: `UsageStatsManager` collection, the
accessibility blocker, Room storage, the permission flow, the block screen.
Written, not yet built; it needs the SDK.

### What the rest would cost

| Piece | Reality |
|---|---|
| Language & UI | Kotlin + Jetpack Compose, or Flutter. Nothing reused. |
| Usage tracking | `UsageStatsManager` — different data model entirely |
| Blocking | `AccessibilityService` + overlay, under policy risk |
| Permissions | Two special grants, each a manual Settings trip |
| Background work | `WorkManager`, plus per-manufacturer battery-optimisation fights |
| Storage | Room, not SQLite-via-Python |
| Store review | Play, with an accessibility justification |
| **Shared with the desktop** | The rules — focus hours, limit semantics, accounting guards, the protected list, and the sync protocol |

The rules being shared is the part that matters: both platforms enforce the
same thing because both call the same tested logic, rather than two
reimplementations drifting apart.

That now includes the sync rules, which is what makes a limit mean one thing
across two devices — an hour on the phone plus an hour on the PC reaches a
two-hour limit, instead of each device allowing the full two. See
[`android/README.md`](android/README.md) and `core/syncproto.py`. The protocol
is defined and both clients are written and tested; **the server that would sit
between them is not built**, which is the one piece still missing.

---

## iOS

Harder than Android, not easier.

iOS has never allowed listing or terminating other apps. The only sanctioned
route is the **Screen Time API** — `FamilyControls`, `DeviceActivity` and
`ManagedSettings` (iOS 15+) — which is what Opal and similar apps use.

`FamilyControls` requires a **special entitlement you must apply to Apple for**,
with a stated use case. It is granted case by case and can be declined. Without
it there is no legitimate way to build this on iOS at all.

---

## So: which stores?

| Store | Possible? | Notes |
|---|---|---|
| **Microsoft Store** | **Yes** | The right move. Microsoft signs the package, so SmartScreen stops warning — the same result as a €300/yr certificate for roughly $19. See `BUILD.md`. |
| Direct download | Yes | Needs a code-signing certificate to avoid the warning. |
| Google Play | Once `android/` is finished and built | Needs the accessibility declaration |
| Apple App Store | Only after an iOS app is written | Plus an entitlement Apple may decline |
| Mac App Store | Effectively no | Sandboxing forbids controlling other apps; Mac blockers ship outside the store |

---

## On sequencing

The Android app now exists in outline, but the ordering argument still holds:

1. ProtBot has **zero users** and has **never been built on Windows**.
2. It **cannot take money** yet — no merchant of record, no licence endpoint.
3. The Android app is a second product to support, competing with a free
   preinstalled Google app — even with the rules shared, the UI, storage,
   permissions and store listing are all separate work.

Ship the Windows version through the Microsoft Store. Find out whether anyone
wants this at all. If a few hundred people do, and they ask for a phone
version, *then* finishing Android is worth the remaining effort — and you will
know what to build because they will have told you.

The risk is two unfinished products instead of one finished one — so treat the
Android module as groundwork that is ready when you are, not as a second track
to run in parallel.
