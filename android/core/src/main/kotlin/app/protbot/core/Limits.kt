package app.protbot.core

/**
 * What an app is allowed today, and whether it is over.
 *
 * Ported from the desktop app's limit handling so both platforms agree. The
 * sentinel convention is the same and is the part most likely to be got wrong:
 *
 *   0   = no limit at all
 *  -1   = not allowed at all (a focus window with a zero cap)
 *   n   = n minutes
 *
 * On the desktop this was a real bug: -1 multiplied out to a negative limit,
 * which produced a 0% usage reading, so a blocked app never triggered.
 */
object Limits {

    const val NO_LIMIT = 0
    const val BLOCKED = -1

    /**
     * The limit to enforce for this app right now, in minutes.
     *
     * Focus hours may only ever *tighten*. A schedule that quietly raised
     * someone's limit would defeat the point of setting one. Apps with no
     * limit of their own are untouched: the user never asked for those to be
     * restricted, and restricting them during a window configured for
     * something else would be a nasty surprise.
     */
    fun effectiveDailyLimit(
        ownLimitMinutes: Int,
        focus: FocusHours,
        weekday: Int,
        minuteOfDay: Int,
    ): Int {
        if (ownLimitMinutes <= 0) return NO_LIMIT
        if (!focus.isActive(weekday, minuteOfDay)) return ownLimitMinutes
        if (focus.capMinutes <= 0) return BLOCKED
        return minOf(ownLimitMinutes, focus.capMinutes)
    }

    /** True when this limit restricts anything at all. */
    fun isActive(limitMinutes: Int): Boolean = limitMinutes != NO_LIMIT

    /** Seconds allowed. BLOCKED allows nothing, and must not go negative. */
    fun allowedSeconds(limitMinutes: Int): Int =
        if (limitMinutes < 0) 0 else limitMinutes * 60

    /**
     * How far through the limit this usage is, as a percentage.
     *
     * A blocked app is at 100% the moment it is open — returning 0 here is
     * exactly the bug the desktop version shipped with.
     */
    fun usagePercent(usedSeconds: Int, limitMinutes: Int): Double {
        val allowed = allowedSeconds(limitMinutes)
        if (allowed <= 0) return if (isActive(limitMinutes)) 100.0 else 0.0
        return usedSeconds.toDouble() / allowed * 100.0
    }

    fun isOverLimit(usedSeconds: Int, limitMinutes: Int): Boolean =
        isActive(limitMinutes) && usedSeconds >= allowedSeconds(limitMinutes)
}
