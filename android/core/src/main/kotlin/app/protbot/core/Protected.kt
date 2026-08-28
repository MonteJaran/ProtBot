package app.protbot.core

/**
 * Packages ProtBot must never block.
 *
 * The desktop equivalent (`core/protected.py`) exists because the app could
 * otherwise close a Windows critical process and bluescreen the machine. The
 * Android risk is different but just as real: blocking the launcher, the
 * dialer, the Settings app or ProtBot itself produces a device the user cannot
 * operate and cannot use to turn the blocking off.
 *
 * Matching is by package name, which is what an AccessibilityService sees.
 */
object Protected {

    /** The user's escape hatches. Blocking these traps them. */
    private val SYSTEM = setOf(
        "com.android.settings",              // turn ProtBot off
        "com.android.systemui",              // status bar, recents, dialogs
        "android",
        "com.android.phone",                 // calls
        "com.android.server.telecom",
        "com.android.dialer",
        "com.google.android.dialer",
        "com.android.emergency",             // emergency dialer
        "com.android.packageinstaller",      // uninstall ProtBot
        "com.google.android.packageinstaller",
        "com.android.permissioncontroller",
        "com.android.keyguard",
    )

    /** Launchers. Blocking the home screen leaves nowhere to go. */
    private val LAUNCHERS = setOf(
        "com.android.launcher",
        "com.android.launcher3",
        "com.google.android.apps.nexuslauncher",
        "com.sec.android.app.launcher",      // Samsung
        "com.miui.home",                     // Xiaomi
        "com.huawei.android.launcher",
        "com.oppo.launcher",
        "com.oneplus.launcher",
    )

    /** ProtBot itself. Blocking it means the user cannot change a setting. */
    private val SELF = setOf("app.protbot")

    val PACKAGES: Set<String> = SYSTEM + LAUNCHERS + SELF

    /** Prefixes that cover OEM variants without listing every one. */
    private val PREFIXES = listOf(
        "com.android.systemui",
        "com.android.settings",
    )

    fun isProtected(packageName: String?): Boolean {
        val name = packageName?.trim()?.lowercase() ?: return false
        if (name.isEmpty()) return false
        if (name in PACKAGES) return true
        return PREFIXES.any { name.startsWith(it) }
    }

    /** Why it is protected, for the UI. Empty when it is not. */
    fun reason(packageName: String?): String {
        val name = packageName?.trim()?.lowercase() ?: return ""
        return when {
            name in SELF -> "Blocking ProtBot would stop you changing your own settings."
            name in LAUNCHERS -> "This is your home screen. Blocking it leaves nowhere to go."
            isProtected(name) -> "This is part of Android and blocking it could stop your phone working."
            else -> ""
        }
    }
}
