package app.protbot.core

/**
 * Turning raw usage samples into time that actually counts.
 *
 * Ported from `core/activity.py`. Android's UsageStatsManager reports
 * foreground time per package, which avoids the desktop version's
 * laptop-lid bug for free — but the same guards still matter, because
 * `queryEvents` gaps, a device that was off, and clock changes all produce
 * intervals that must not be credited in full.
 */
object Accounting {

    /** Treat the user as away after this long with no interaction. */
    const val DEFAULT_IDLE_THRESHOLD_SEC = 300

    /**
     * A gap longer than this multiple of the sampling interval means the
     * process was not running normally — doze, device off, or the collector
     * was killed. Only the expected interval is credited, never the whole gap.
     */
    const val GAP_FACTOR = 1.5

    /** Idle time could not be determined. */
    const val UNKNOWN = -1L

    /**
     * How many of [wallSeconds] count as real usage.
     *
     * Rules, in order:
     *  - a zero or negative interval counts as nothing (clock changes, DST)
     *  - an interval far longer than expected is capped, never credited whole
     *  - past the idle threshold, nothing counts
     *  - if foreground tracking is on and this is not the foreground app,
     *    nothing counts
     *
     * [isForeground] may be null, meaning "could not determine" — the time
     * then counts, because silently under-reporting is worse than crediting a
     * minute the user may not have spent.
     */
    fun countedSeconds(
        wallSeconds: Long,
        samplingIntervalSeconds: Long,
        isForeground: Boolean? = null,
        idleSeconds: Long = UNKNOWN,
        requireForeground: Boolean = true,
        idleThresholdSeconds: Long = DEFAULT_IDLE_THRESHOLD_SEC.toLong(),
    ): Long {
        if (wallSeconds <= 0) return 0

        val cap = (maxOf(samplingIntervalSeconds, 1L) * GAP_FACTOR).toLong()
        val counted = minOf(wallSeconds, cap)

        if (idleSeconds >= 0 && idleSeconds >= idleThresholdSeconds) return 0
        if (requireForeground && isForeground == false) return 0

        return counted
    }

    /** True if this gap is too long to be a normal sampling interval. */
    fun wasInterrupted(wallSeconds: Long, samplingIntervalSeconds: Long): Boolean {
        if (wallSeconds <= 0) return false
        return wallSeconds > (maxOf(samplingIntervalSeconds, 1L) * GAP_FACTOR)
    }

    /**
     * Split a session that crosses midnight into per-day portions.
     *
     * The desktop version filed a 23:50–02:00 session entirely under the start
     * date, and the daily counter — which filters on today — stopped seeing it
     * and silently reset mid-session. Returning the split explicitly makes
     * that impossible to forget.
     *
     * @return (secondsOnStartDay, secondsOnNextDay)
     */
    fun splitAtMidnight(
        startMinuteOfDay: Int,
        durationSeconds: Long,
    ): Pair<Long, Long> {
        if (durationSeconds <= 0) return 0L to 0L
        val secondsUntilMidnight = (24 * 60 - startMinuteOfDay).toLong() * 60
        if (durationSeconds <= secondsUntilMidnight) return durationSeconds to 0L
        return secondsUntilMidnight to (durationSeconds - secondsUntilMidnight)
    }
}
