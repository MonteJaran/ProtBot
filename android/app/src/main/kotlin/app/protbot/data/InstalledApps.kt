package app.protbot.data

import android.content.Context
import android.content.Intent

/**
 * The apps a user could plausibly track -- everything with a launcher icon.
 *
 * Reads via the `<queries>` block AndroidManifest.xml declares for exactly
 * this (MAIN/LAUNCHER), not QUERY_ALL_PACKAGES: Android 11+ hides the
 * installed app list otherwise, and the broader permission is a sensitive
 * one Google reviews closely for a use this narrow. See the manifest's own
 * comment on it, and android/README.md.
 */
object InstalledApps {

    data class Entry(
        val packageName: String,
        val label: String,
    )

    /**
     * Every launchable app, sorted by label. ProtBot excludes itself --
     * there is nothing to track by watching its own foreground time.
     */
    fun list(context: Context): List<Entry> {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)

        return pm.queryIntentActivities(intent, 0)
            .mapNotNull { it.activityInfo?.applicationInfo }
            .distinctBy { it.packageName }
            .filter { it.packageName != context.packageName }
            .map { info ->
                Entry(
                    packageName = info.packageName,
                    // Falls back to the package name itself: getApplicationLabel
                    // never returns null, but an app with no label at all would
                    // otherwise show as an empty row.
                    label = pm.getApplicationLabel(info).toString().ifBlank { info.packageName },
                )
            }
            .sortedBy { it.label.lowercase() }
    }
}
