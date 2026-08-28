package app.protbot.usage

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import app.protbot.core.Accounting
import app.protbot.core.Protected

/**
 * Reading how long each app was actually in the foreground.
 *
 * This is the Android answer to the desktop app's process polling.
 * getRunningAppProcesses has returned only your own process since Android 5.1
 * — that capability was removed on purpose — so the sanctioned route is
 * UsageStatsManager.
 *
 * queryEvents is used rather than queryUsageStats because the bucketed stats
 * are coarse and reset unpredictably; the raw event stream gives exact
 * foreground/background transitions, which is what a limit has to be counted
 * against.
 */
class UsageCollector(private val context: Context) {

    private val manager: UsageStatsManager? =
        context.getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager

    /**
     * Foreground seconds per package between [startMillis] and [endMillis].
     *
     * Sessions still open at [endMillis] are counted up to that point, so a
     * currently-open app is included rather than missing until it is closed.
     */
    fun foregroundSeconds(startMillis: Long, endMillis: Long): Map<String, Long> {
        val usageManager = manager ?: return emptyMap()
        val events = try {
            usageManager.queryEvents(startMillis, endMillis)
        } catch (e: SecurityException) {
            // Usage access was revoked while running. Report nothing rather
            // than crashing; the UI checks the permission separately.
            return emptyMap()
        }

        val totals = mutableMapOf<String, Long>()
        val openedAt = mutableMapOf<String, Long>()
        val event = UsageEvents.Event()

        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val pkg = event.packageName ?: continue

            when (event.eventType) {
                UsageEvents.Event.MOVE_TO_FOREGROUND,
                UsageEvents.Event.ACTIVITY_RESUMED -> {
                    openedAt[pkg] = event.timeStamp
                }

                UsageEvents.Event.MOVE_TO_BACKGROUND,
                UsageEvents.Event.ACTIVITY_PAUSED -> {
                    val opened = openedAt.remove(pkg) ?: continue
                    addInterval(totals, pkg, opened, event.timeStamp)
                }
            }
        }

        // Anything still in the foreground when the window ended.
        for ((pkg, opened) in openedAt) {
            addInterval(totals, pkg, opened, endMillis)
        }
        return totals
    }

    /**
     * Adds one foreground interval, capped.
     *
     * The cap matters: a device that was off, or dozing, leaves a gap between
     * a resume and the next event that is not time the user spent in the app.
     * This is the same guard as the desktop version's sleep cap.
     */
    private fun addInterval(
        totals: MutableMap<String, Long>,
        pkg: String,
        fromMillis: Long,
        toMillis: Long,
    ) {
        val seconds = (toMillis - fromMillis) / 1000
        if (seconds <= 0) return
        // A single foreground stretch longer than 12 hours is not real usage.
        val credited = minOf(seconds, 12L * 60 * 60)
        totals[pkg] = (totals[pkg] ?: 0) + credited
    }

    /** Foreground seconds since local midnight, which is what limits use. */
    fun secondsToday(nowMillis: Long, midnightMillis: Long): Map<String, Long> =
        foregroundSeconds(midnightMillis, nowMillis)

    /** The package currently in front, or null. */
    fun currentForegroundPackage(nowMillis: Long, lookBackMillis: Long = 10_000): String? {
        val usageManager = manager ?: return null
        val events = try {
            usageManager.queryEvents(nowMillis - lookBackMillis, nowMillis)
        } catch (e: SecurityException) {
            return null
        }
        var latest: String? = null
        val event = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND ||
                event.eventType == UsageEvents.Event.ACTIVITY_RESUMED
            ) {
                latest = event.packageName
            }
        }
        return latest
    }

    /**
     * Whether usage access has actually been granted.
     *
     * Checking the permission string is not enough — PACKAGE_USAGE_STATS is an
     * appops grant, so the only reliable test is whether a query returns
     * anything for a window that definitely had activity.
     */
    fun hasUsageAccess(nowMillis: Long): Boolean {
        val usageManager = manager ?: return false
        return try {
            val events = usageManager.queryEvents(nowMillis - 60_000, nowMillis)
            events.hasNextEvent()
        } catch (e: SecurityException) {
            false
        }
    }

    /** Packages the user is allowed to pick, with the protected ones removed. */
    fun blockablePackages(candidates: Collection<String>): List<String> =
        candidates.filterNot { Protected.isProtected(it) }.sorted()

    companion object {
        /** How often the collector samples. Matches the desktop default. */
        const val SAMPLE_INTERVAL_SECONDS = 60L

        fun countedSeconds(wallSeconds: Long): Long =
            Accounting.countedSeconds(
                wallSeconds,
                SAMPLE_INTERVAL_SECONDS,
                requireForeground = false,
            )
    }
}
