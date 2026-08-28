package app.protbot.data

import android.content.Context
import app.protbot.core.BlockPolicy
import app.protbot.core.FocusHours
import app.protbot.usage.UsageCollector
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId

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

    /** The policy the blocker should enforce right now. */
    suspend fun currentPolicy(
        focusHours: FocusHours,
        blockingEnabled: Boolean,
        today: LocalDate = LocalDate.now(),
    ): BlockPolicy {
        val apps = dao.enabledApps()
        val usage = dao.usageOn(today.toString()).associate { it.packageName to it.seconds }
        return BlockPolicy(
            limits = apps.associate { it.packageName to it.dailyLimitMinutes },
            usedToday = usage,
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
