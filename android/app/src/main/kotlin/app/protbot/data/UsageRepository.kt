package app.protbot.data

import android.content.Context
import app.protbot.core.BlockPolicy
import app.protbot.core.FocusHours
import app.protbot.core.Insights
import app.protbot.core.Sync
import app.protbot.usage.UsageCollector
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import kotlinx.coroutines.flow.Flow

/**
 * Ties the collector, storage and the block policy together.
 *
 * Single place that knows "what has been used today", so the UI, the worker
 * and the blocker cannot disagree about it.
 */
class UsageRepository private constructor(context: Context) {

    private val appContext = context.applicationContext
    private val dao = ProtBotDatabase.get(appContext).dao()
    private val collector = UsageCollector(appContext)

    /** Reads today's foreground time and stores it, one row per app per day. */
    suspend fun refreshToday(now: LocalDateTime = LocalDateTime.now()) {
        val zone = ZoneId.systemDefault()
        val midnight = now.toLocalDate().atStartOfDay(zone).toInstant().toEpochMilli()
        val nowMillis = now.atZone(zone).toInstant().toEpochMilli()

        val totals = collector.secondsToday(nowMillis, midnight)
        val today = now.toLocalDate().toString()

        for ((pkg, seconds) in totals) {
            dao.upsertUsage(DailyUsage(pkg, today, seconds))
        }
    }

    /** Today's usage on this device, by package. */
    suspend fun usageTodayByPackage(today: LocalDate = LocalDate.now()): Map<String, Long> =
        dao.usageOn(today.toString()).associate { it.packageName to it.seconds }

    /** The tracked apps, read once rather than observed. */
    suspend fun trackedAppsOnce(): List<TrackedApp> = dao.allApps()

    /** The tracked apps, observed -- what the App Picker and Insights
     *  screens show, so adding or removing one updates them live. */
    fun trackedAppsFlow(): Flow<List<TrackedApp>> = dao.trackedApps()

    /**
     * Start (or update) tracking one app.
     *
     * Upsert, not insert: called from both the App Picker (a fresh app,
     * limit 0 = unlimited) and the limit-edit screen (an existing one,
     * whatever limit was already set). [TrackedApp.packageName] is the
     * primary key, so this is never a duplicate row.
     */
    suspend fun setApp(
        packageName: String,
        label: String,
        dailyLimitMinutes: Int = 0,
        enabled: Boolean = true,
    ) {
        dao.upsertApp(TrackedApp(packageName, label, dailyLimitMinutes, enabled))
    }

    suspend fun removeApp(packageName: String) = dao.removeApp(packageName)

    /**
     * The Insights screen's rows: every tracked app, today's and this
     * week's usage, and how far into today's limit each one is.
     *
     * One query for every app's usage across the window (`dao.usageSince`)
     * rather than one per app -- a user with fifty tracked apps should not
     * mean fifty queries to open one screen. The actual arithmetic is
     * app.protbot.core.Insights.summarize, which is what has tests; this is
     * just the Room shape it needs.
     */
    suspend fun insightsSummary(
        days: Int = 7,
        today: LocalDate = LocalDate.now(),
    ): List<Insights.AppSummary> {
        val apps = dao.allApps().map {
            Insights.AppInfo(it.packageName, it.label, it.dailyLimitMinutes)
        }
        val weekDates = Insights.trailingDates(today, days)
        val usageByDate: Map<String, Map<String, Long>> = dao.usageSince(weekDates.first())
            .groupBy { it.date }
            .mapValues { (_, rows) -> rows.associate { it.packageName to it.seconds } }
        return Insights.summarize(apps, usageByDate, today.toString(), weekDates)
    }

    /**
     * The policy the blocker should enforce right now.
     *
     * [remoteSeconds] is time spent on the user's other devices today, from
     * `SyncClient.remoteSecondsByPackage`, and is added to this device's own
     * usage before the policy sees it. That addition is the whole point of
     * sync: an hour on the phone and an hour on the PC have to add up to the
     * two-hour limit the user set, rather than each device allowing two.
     *
     * Empty when sync is off, has never succeeded, or its last figure is too
     * old to trust — in which case this behaves exactly as it did before sync
     * existed, enforcing against local usage only. Remote time can only ever
     * add, never subtract; see `Sync.mergeAppTotal`.
     */
    suspend fun currentPolicy(
        focusHours: FocusHours,
        blockingEnabled: Boolean,
        today: LocalDate = LocalDate.now(),
        remoteSeconds: Map<String, Long> = emptyMap(),
    ): BlockPolicy {
        val apps = dao.enabledApps()
        val local = usageTodayByPackage(today)
        val combined = if (remoteSeconds.isEmpty()) local else {
            (local.keys + remoteSeconds.keys).associateWith { pkg ->
                Sync.mergeAppTotal(
                    localSeconds = local[pkg] ?: 0L,
                    groupSeconds = remoteSeconds[pkg] ?: 0L,
                    uploadedSeconds = 0L,   // already subtracted by the client
                )
            }
        }
        return BlockPolicy(
            limits = apps.associate { it.packageName to it.dailyLimitMinutes },
            usedToday = combined,
            focusHours = focusHours,
            enabled = blockingEnabled,
        )
    }

    /** Retention, matching the desktop default of one year. */
    suspend fun prune(retentionDays: Int, today: LocalDate = LocalDate.now()): Int {
        if (retentionDays <= 0) return 0            // 0 keeps everything
        return dao.pruneBefore(today.minusDays(retentionDays.toLong()).toString())
    }

    /** Delete everything, and mean it — history and the app list both. */
    suspend fun deleteAllData() {
        dao.deleteAllUsage()
        dao.deleteAllApps()
    }

    companion object {
        @Volatile private var instance: UsageRepository? = null

        fun get(context: Context): UsageRepository =
            instance ?: synchronized(this) {
                instance ?: UsageRepository(context).also { instance = it }
            }
    }
}
