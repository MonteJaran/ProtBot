# ProGuard/R8 rules for the release build.
#
# `release { isMinifyEnabled = true }` in build.gradle.kts references this
# file. Gradle does not treat a missing rules file as an empty one — it fails
# the release build with "file not found" — so this file existing is itself
# load-bearing. It did not exist, which nobody found out because :app has
# never been compiled.
#
# The defaults in proguard-android-optimize.txt already cover the ordinary
# Android surface. What follows is what R8 cannot see for this app in
# particular: every class below is constructed by the framework by name, so
# nothing in the code references it and R8 is entitled to remove or rename it.
# The symptom is not a build failure — it is an app that installs, launches,
# and silently stops enforcing anything.

# ── Instantiated by the system from the manifest ─────────────────────────────
# Renaming any of these makes the manifest entry point at a class that is no
# longer there.
-keep class app.protbot.ProtBotApplication { *; }
-keep class app.protbot.ui.MainActivity { *; }
-keep class app.protbot.block.BlockScreenActivity { *; }
-keep class app.protbot.block.BlockerAccessibilityService { *; }
-keep class app.protbot.usage.BootReceiver { *; }

# ── WorkManager ──────────────────────────────────────────────────────────────
# Workers are constructed reflectively from a class name stored in WorkManager's
# own database, so a worker that survives an app update under a new name is a
# job that never runs again. The two-argument constructor is the one the
# default WorkerFactory looks for.
-keep class * extends androidx.work.ListenableWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}

# ── Room ─────────────────────────────────────────────────────────────────────
# The generated implementation is found by name at runtime, and entities are
# mapped by field name.
-keep class * extends androidx.room.RoomDatabase { *; }
-keep @androidx.room.Entity class * { *; }
-dontwarn androidx.room.paging.**

# ── Kotlin ───────────────────────────────────────────────────────────────────
# Coroutines ships a service-loader entry and internal classes R8 warns about
# without these; they are the rules kotlinx-coroutines documents.
-keepclassmembers class kotlinx.coroutines.** { volatile <fields>; }
-dontwarn kotlinx.coroutines.**

# ── Diagnostics ──────────────────────────────────────────────────────────────
# Keep line numbers so a stack trace from a tester is readable, and hide the
# original file name, which is what the default configuration does too.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
