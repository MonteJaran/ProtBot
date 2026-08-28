package app.protbot.permissions

import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.text.TextUtils
import app.protbot.block.BlockerAccessibilityService

/**
 * The two special grants ProtBot needs, and how to ask for them.
 *
 * Neither is a runtime dialog. Both send the user to a Settings screen and
 * hope they come back, which is the single biggest drop-off in the whole app —
 * so the UI has to explain what each one is for BEFORE sending them, not after.
 */
object Permissions {

    /**
     * Usage access. Cannot be checked by permission string alone: it is an
     * appops grant, so the honest test is whether a query returns anything.
     */
    fun hasUsageAccess(context: Context): Boolean =
        app.protbot.usage.UsageCollector(context)
            .hasUsageAccess(System.currentTimeMillis())

    fun usageAccessIntent(): Intent =
        Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)

    /** Whether the blocker service is actually switched on. */
    fun isBlockerEnabled(context: Context): Boolean {
        val expected = "${context.packageName}/${BlockerAccessibilityService::class.java.name}"
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        ) ?: return false

        val splitter = TextUtils.SimpleStringSplitter(':')
        splitter.setString(enabled)
        while (splitter.hasNext()) {
            if (splitter.next().equals(expected, ignoreCase = true)) return true
        }
        return false
    }

    fun blockerSettingsIntent(): Intent =
        Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)

    fun canDrawOverlays(context: Context): Boolean =
        Settings.canDrawOverlays(context)

    fun overlayIntent(context: Context): Intent =
        Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            android.net.Uri.parse("package:${context.packageName}"),
        )

    /** Everything needed for blocking to actually work. */
    fun blockingReady(context: Context): Boolean =
        hasUsageAccess(context) && isBlockerEnabled(context)
}
