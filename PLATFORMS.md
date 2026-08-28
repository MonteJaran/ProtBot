# Other platforms: stores, Android, iOS

Short answer to the two questions:

- **Microsoft Store — yes.** ProtBot is a Windows app and that is its store.
- **Everything else — no.** Not "port it", not "add a build target". A phone
  version is a **different application**, written from scratch, in a different
  language, using a completely different mechanism to do the one thing this app
  exists to do.

This document explains why, so the decision is made with the real numbers
rather than by discovering it three weeks in.

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

That works. It is also the single riskiest dependency you could build on.

### The Play Store problem

Google restricts `AccessibilityService` heavily and has tightened it repeatedly.
Policy is that accessibility APIs must be used for accessibility purposes; app
blockers are a contested category, and apps in it have been removed, forced to
re-architect, or held in review for a long time. You must declare the use in
Play Console and justify it.

This is not a hypothetical risk to plan around later. It is the load-bearing
mechanism of the entire product, and the platform owner can withdraw it.

### And the competition is preinstalled

**Digital Wellbeing** ships on every Android device, free, made by the company
that controls the APIs you would be fighting to use. Screen Time does the same
on iOS. On Windows there is no equivalent — which is a real part of why the
desktop version has a reason to exist at all.

### What an Android version would actually cost

| Piece | Reality |
|---|---|
| Language & UI | Kotlin + Jetpack Compose, or Flutter. Nothing reused. |
| Usage tracking | `UsageStatsManager` — different data model entirely |
| Blocking | `AccessibilityService` + overlay, under policy risk |
| Permissions | Two special grants, each a manual Settings trip |
| Background work | `WorkManager`, plus per-manufacturer battery-optimisation fights |
| Storage | Room, not SQLite-via-Python |
| Store review | Play, with an accessibility justification |
| **Reusable from this repo** | **The sync protocol and server. That is all.** |

Realistically 6–10 weeks for a competent Android developer to reach parity with
what ProtBot does today, and the result shares no code with it.

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
| Google Play | Only after an Android rewrite | Plus accessibility-policy risk |
| Apple App Store | Only after an iOS rewrite | Plus an entitlement Apple may decline |
| Mac App Store | Effectively no | Sandboxing forbids controlling other apps; Mac blockers ship outside the store |

---

## The recommendation

**Do not start Android now.** Not because it is a bad idea eventually, but
because of the order:

1. ProtBot has **zero users** and has **never been built on Windows**.
2. It **cannot take money** yet — no merchant of record, no licence endpoint.
3. An Android version would be a second product with zero shared code, built
   on a mechanism the platform owner actively restricts, competing with a free
   preinstalled Google app.

Ship the Windows version through the Microsoft Store. Find out whether anyone
wants this at all. If a few hundred people do, and they ask for a phone
version, *then* the Android question is worth 6–10 weeks — and you will know
what to build because they will have told you.

Building it now means two unfinished products instead of one finished one.
