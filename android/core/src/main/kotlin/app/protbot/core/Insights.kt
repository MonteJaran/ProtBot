package app.protbot.core

import java.time.LocalDate

/**
 * Turning stored daily usage into what the Insights screen shows.
 *
 * Pure, like the rest of this module: `app.protbot.data.UsageRepository`
 * (the `:app` module) reads Room and hands this plain maps; this decides
 * what to show and in what order. No Context, no database, so it is
 * testable without a device -- unlike the screen itself, which has never
 * been built (`android/app/` has no display to render on here).
 */
object Insights {

    /** What summarize() needs to know about one tracked app. */
    data class AppInfo(
        val packageName: String,
        val label: String,
        val dailyLimitMinutes: Int,
    )

    /** One app's row on the Insights screen. */
    data class AppSummary(
        val packageName: String,
        val label: String,
        val todaySeconds: Long,
        val weekSeconds: Long,
        val dailyLimitMinutes: Int,
        /** 0 when there is no limit (Limits.NO_LIMIT); never negative. */
        val percentOfDailyLimitToday: Int,
    )

    /**
     * One summary row per app in [apps], sorted by this week's usage, most
     * first -- what the user is actually spending time in belongs at the
     * top, not whatever order the database happens to return rows in.
     *
     * @param usageByDate seconds used per app per day, e.g.
     *   `{"2026-06-15": {"com.discord": 1800}}`. A day or app missing from
     *   this reads as zero rather than as an error -- the common case for a
     *   newly tracked app or a day it was never opened.
     * @param today the local date [AppSummary.todaySeconds] is measured
     *   against.
     * @param weekDates the dates that make up "this week" -- [trailingDates]
     *   builds the usual one, but the window is the caller's choice, not
     *   assumed here.
     */
    fun summarize(
        apps: List<AppInfo>,
        usageByDate: Map<String, Map<String, Long>>,
        today: String,
        weekDates: List<String>,
    ): List<AppSummary> = apps.map { app ->
        val todaySeconds = usageByDate[today]?.get(app.packageName) ?: 0L
        val weekSeconds = weekDates.sumOf { date -> usageByDate[date]?.get(app.packageName) ?: 0L }
        AppSummary(
            packageName = app.packageName,
            label = app.label,
            todaySeconds = todaySeconds,
            weekSeconds = weekSeconds,
            dailyLimitMinutes = app.dailyLimitMinutes,
            percentOfDailyLimitToday = percentOfLimit(todaySeconds, app.dailyLimitMinutes),
        )
    }.sortedByDescending { it.weekSeconds }

    /**
     * How far through today's limit this usage is, as a whole percentage.
     *
     * 0 when there is no limit (`limitMinutes <= 0`, [Limits.NO_LIMIT]) --
     * unlike [Limits.usagePercent], which reports a *blocked* app (the -1
     * sentinel) as already at 100%. That distinction matters to the block
     * decision; it would just be a confusing display here, since a blocked
     * app is a decision the user already made, not something the Insights
     * screen needs to alarm them about again. Clamped to 999 so a corrupt
     * row cannot render as a nonsense number of digits.
     */
    fun percentOfLimit(usedSeconds: Long, limitMinutes: Int): Int {
        if (limitMinutes <= 0) return 0
        val allowedSeconds = limitMinutes * 60L
        if (allowedSeconds <= 0L || usedSeconds <= 0L) return 0
        // Checked before multiplying, not after: `usedSeconds * 100` overflows
        // Long for a corrupt or hostile row (sync clamps what it accepts, but
        // this is display code and has to be defensive on its own). Integer
        // division cannot overflow, and once the ratio alone is already past
        // 999 the precise value stops mattering -- it renders as 999% either way.
        if (usedSeconds / allowedSeconds >= 999L) return 999
        return (usedSeconds * 100L / allowedSeconds).toInt()
    }

    /** The last [days] dates ending at [today] (inclusive), oldest first --
     *  the window [summarize]'s `weekDates` expects. */
    fun trailingDates(today: LocalDate, days: Int = 7): List<String> {
        require(days > 0) { "days must be positive, got $days" }
        return (days - 1 downTo 0).map { today.minusDays(it.toLong()).toString() }
    }
}
