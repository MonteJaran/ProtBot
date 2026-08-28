// ProtBot for Android.
//
// Two modules, deliberately:
//
//   core  — pure Kotlin/JVM. Every rule the app enforces lives here: focus
//           hours, effective limits, usage accounting. No Android imports, so
//           it compiles and its tests run without the Android SDK, on any
//           machine, in CI. These rules are ported from the Python desktop
//           app and the test cases came with them.
//
//   app   — the Android layer: UsageStatsManager, the blocker service, Room,
//           Compose UI, sync. Needs the Android SDK to build.
//
// The split is what makes the shared behaviour testable. Anything that can be
// decided without asking the operating system belongs in core.

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "protbot-android"

include(":core")

// The app module needs the Android SDK. Including it without one fails the
// whole build, so it is opt-in: enable with -PwithAndroid or by setting
// ANDROID_HOME. `gradle :core:test` always works either way.
val hasAndroidSdk = System.getenv("ANDROID_HOME") != null ||
    System.getenv("ANDROID_SDK_ROOT") != null ||
    providers.gradleProperty("withAndroid").isPresent

if (hasAndroidSdk) {
    include(":app")
} else {
    logger.lifecycle(
        "Android SDK not found — building :core only. " +
        "Set ANDROID_HOME or pass -PwithAndroid to include :app."
    )
}
