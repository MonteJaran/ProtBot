# ProtBot for Android

A second application, sharing the desktop app's rules but none of its code.
Python and Tkinter do not run on Android, so the UI, storage and enforcement
are all native — but every rule the two versions enforce lives in one place and
is tested against the same cases.

## What is verified and what is not

| Module | State |
|---|---|
| `core/` | **Compiles and passes 115 tests.** Pure Kotlin/JVM, no Android imports, no SDK needed. |
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

## Sharing totals with the PC

This is the point of having two apps rather than two products: a two-hour
limit means two hours across both devices, not two hours each.

`core/Sync.kt` holds the rules, and its Python twin is `core/syncproto.py`.
Both are tested against the same cases, because the two have to agree — the
canonical key is the only thing joining `Discord.exe` on the PC to
`com.discord` here, and if they disagree the user gets two half-counted apps
and no error anywhere to explain it.

Three decisions that are not the obvious ones:

- **Uploads are cumulative.** Sending "seconds since the last upload"
  double-counts every time a response is lost and the client retries. An
  upload carries today's running total instead, so re-sending it changes
  nothing and a phone that was offline all morning catches up in one request.
- **The day is the device's day.** A server bucketing by UTC puts a Belgrade
  evening into tomorrow, and the user watches their limit reset at 2am.
- **Merging is not "take the bigger number".** The group total already
  contains this device's last upload, which is stale by up to the upload
  interval. Our own contribution is subtracted before the remainder is added
  to the live local figure. `SyncTest` carries a case for each way the naive
  version goes wrong, including the one where usage vanishes at midnight.

Sync stays off until the user registers a device, and a server that is down,
empty or hostile can only ever result in local usage being enforced — never a
looser limit than this phone measured itself.

**No server implements the protocol yet.** `server/models.py` defines the wire
format and documents what a server has to do with it; the client is tested
against a fake transport, so what is verified is how it behaves on every
response shape a broken server could produce.

## Linking to a PC

The PC shows a QR code and this app reads it. `core/Linking.kt` is the shared
half — the payload format, the key alphabet, the expiry — and its Python twin
is `core/linking.py`; the two are held to the same cases, because the PC writes
the payload and the phone parses it with nothing in between to absorb a
disagreement.

    https://protbot.app/l#1.ABCD2345

An https App Link rather than a `protbot://` scheme, because a custom scheme
shows up in the stock camera as "no app can open this" exactly when ProtBot is
not installed yet. The key sits in the fragment, which Android hands to the app
but no browser ever sends to a server — so opening the link without the app
installed does not leak the key into a web access log.

`autoVerify="true"` on the intent filter needs `assetlinks.json` served from
protbot.app. Until that is published Android shows a chooser rather than
opening straight away; it still works, it is one tap worse.

## Still to build

- **Written, not verified: the in-app scanner, the app picker, limit
  editing, the insights screen, and device-sync management.** All five now
  exist (`ui/ScanScreen.kt`, `ui/AppPickerScreen.kt`, `ui/LimitEditScreen.kt`,
  `ui/InsightsScreen.kt`, `ui/DeviceSyncScreen.kt`), wired into
  `MainActivity.kt`, but `:app` has never compiled — no Android SDK here,
  and `settings.gradle.kts` excludes the module entirely without one. The
  scanner needed two new dependencies (CameraX, ML Kit's on-device barcode
  reader) that have never resolved a dependency graph, let alone run.
  `DeviceSyncScreen.kt` is the first thing on Android to ever call
  `SyncClient.register`/`unregister`. Each screen's arithmetic lives in
  `:core` (`Insights.kt`) and is tested; the screens, the camera binding
  and the permission flow are not. Check those first on a real device —
  see STATUS.md.
- Manually linking an app on one device to the same app on the other, for
  packages named after a vendor rather than the product — the canonical key
  is a good guess, not a guarantee. The desktop app has this now (the Files
  tab's "Sync Name" field, `core/syncproto.py`'s `aliases` parameter); the
  Android side of it does not exist yet.
- The first actual build, on a machine with the SDK.
