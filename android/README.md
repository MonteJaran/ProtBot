# ProtBot for Android

A second application, sharing the desktop app's rules but none of its code.
Python and Tkinter do not run on Android, so the UI, storage and enforcement
are all native — but every rule the two versions enforce lives in one place and
is tested against the same cases.

## What is verified and what is not

| Module | State |
|---|---|
| `core/` | **Compiles and passes 67 tests.** Pure Kotlin/JVM, no Android imports, no SDK needed. |
| `app/` | **Written, never built.** Needs the Android SDK, which this machine does not have. |

Run the verified part anywhere with a JDK:

```bash
cd android
gradle :core:test
```

Build the app once you have the SDK:

```bash
export ANDROID_HOME=/path/to/sdk
gradle :app:assembleDebug
```

`:app` is excluded from the build unless `ANDROID_HOME` is set or you pass
`-PwithAndroid`, so `gradle :core:test` works either way instead of failing on
a missing SDK.

## Why the module split

`core/` holds every decision that can be made without asking the operating
system: focus hours, effective limits, usage accounting, the protected-package
list, and the block decision itself. That is deliberate — an
`AccessibilityService` is awkward to test and easy to get subtly wrong, and the
block decision is the most consequential logic in the app. Get it wrong one way
and nothing is blocked; get it wrong the other and the user is locked out of
their own phone.

So `BlockerAccessibilityService` does almost nothing: it receives an event,
asks `BlockPolicy` what to do, and either ignores it or launches a screen.
Everything worth testing is on the other side of that call.

## How it works, and why not the obvious way

**Tracking.** `getRunningAppProcesses()` has returned only your own process
since Android 5.1 — that capability was removed deliberately. The sanctioned
route is `UsageStatsManager`, and specifically `queryEvents` rather than
`queryUsageStats`: the bucketed stats are coarse and reset unpredictably, while
the raw event stream gives exact foreground and background transitions, which
is what a limit has to be counted against.

**Blocking.** There is no equivalent of the desktop version's
`TerminateProcess`. `killBackgroundProcesses()` only touches background
processes, never the app in front of the user — the one that matters. So the
mechanism is an `AccessibilityService` watching window-state changes, which
launches a full-screen block activity when a limited app appears.

**Storage.** Room, keyed by `(package, date)` rather than open-ended sessions.
UsageStatsManager already reports per-interval totals, and a per-day row makes
the midnight boundary impossible to get wrong — which is exactly the bug the
desktop version shipped with.

## The two permissions

Neither is a runtime dialog. Both send the user to a Settings screen and hope
they come back, which is the biggest drop-off in the app.

| Permission | Granted via | Without it |
|---|---|---|
| `PACKAGE_USAGE_STATS` | Settings → Special app access → Usage access | No usage data at all |
| Accessibility service | Settings → Accessibility | Tracking works, blocking does not |

The UI explains what each is for **before** sending the user, not after. That
is the difference between a grant and a bounce.

## Play Store review

Google reviews accessibility use closely, and app blockers are a scrutinised
category. Apps that ship in it — StayFree, ActionDash, Freedom, Opal — do so by
making the purpose unmistakable. Three things this project does on purpose:

- **`canRetrieveWindowContent="false"`.** ProtBot only needs to know which app
  is in front. Requesting content it does not use would be a larger privacy
  surface and much harder to justify.
- **Only `typeWindowStateChanged`.** The narrowest event type that works.
- **A `<queries>` block, not `QUERY_ALL_PACKAGES`.** The broad permission
  invites a review conversation that the narrow declaration avoids.

You will still need to complete the Play Console accessibility declaration and
say plainly what the service does.

## Protected packages

`core/Protected.kt` is the Android counterpart of the desktop denylist, and it
exists for the same reason with different consequences. Blocking Settings, the
launcher, the dialer or ProtBot itself produces a phone the user cannot operate
and cannot use to turn blocking off. It is enforced in the policy, not just the
UI, so a bad database row cannot get past it.

## Shared with the desktop app

| Shared | Not shared |
|---|---|
| Focus-hours rules, including overnight windows | UI — Compose vs Tkinter |
| Limit semantics (`0` unlimited, `-1` blocked) | Storage — Room vs SQLite |
| Usage-accounting guards | Enforcement — accessibility vs `WM_CLOSE` |
| The sync protocol (`server/models.py`) | Everything platform-specific |

The limit sentinels matter most. On the desktop, `-1` multiplied out to a
negative limit and produced a 0% usage reading, so a blocked app never
triggered. `LimitsTest` carries that case across so it cannot happen twice.

## Still to build

- Sync client against the existing protocol, so phone and PC share totals
- App picker (the `<queries>` block is declared; the UI is not written)
- Limit editing and the insights screen
- Retention scheduling — `UsageRepository.prune` exists, nothing calls it yet
- The first actual build, on a machine with the SDK
