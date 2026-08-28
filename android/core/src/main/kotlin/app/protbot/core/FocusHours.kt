package app.protbot.core

/**
 * Focus hours: a recurring window where limits tighten.
 *
 * Ported from `core/schedule.py` in the desktop app, rule for rule, so both
 * platforms enforce the same thing. The test cases came across with it.
 *
 * Deliberately one window rather than a multi-block scheduler — that covers
 * work hours, study hours and evenings, and it ships complete.
 */
data class FocusHours(
    val enabled: Boolean = false,
    /** 0 = Monday, matching java.time.DayOfWeek minus one. */
    val days: Set<Int> = setOf(0, 1, 2, 3, 4),
    val startMinutes: Int = 9 * 60,
    val endMinutes: Int = 17 * 60,
    /** Cap applied to already-limited apps while focusing. 0 blocks outright. */
    val capMinutes: Int = 0,
) {
    /**
     * Is the window in effect at this moment?
     *
     * @param weekday 0 = Monday
     * @param minuteOfDay minutes since midnight
     */
    fun isActive(weekday: Int, minuteOfDay: Int): Boolean {
        if (!enabled || days.isEmpty()) return false

        // A zero-length window is almost certainly a mistake, and reading it as
        // "all day" would lock someone out of everything.
        if (startMinutes == endMinutes) return false

        if (startMinutes < endMinutes) {
            return weekday in days && minuteOfDay >= startMinutes && minuteOfDay < endMinutes
        }

        // Wraps midnight. 22:00–06:00 is a normal thing to want, and the naive
        // `start <= now < end` is false for every minute of it.
        //
        // The window belongs to the day it STARTED on, so the minutes before
        // `end` are tested against yesterday's weekday. A Friday-night block
        // still applies at 01:00 on Saturday.
        if (minuteOfDay >= startMinutes) return weekday in days
        if (minuteOfDay < endMinutes) return Math.floorMod(weekday - 1, 7) in days
        return false
    }

    companion object {
        /** Parses "HH:MM" to minutes since midnight, or null if unusable. */
        fun parseTime(value: String?): Int? {
            val parts = value?.trim()?.split(":") ?: return null
            if (parts.size != 2) return null
            val hour = parts[0].toIntOrNull() ?: return null
            val minute = parts[1].toIntOrNull() ?: return null
            if (hour !in 0..23 || minute !in 0..59) return null
            return hour * 60 + minute
        }

        fun formatTime(minutes: Int): String =
            "%02d:%02d".format(minutes / 60 % 24, minutes % 60)

        val DAY_NAMES = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    }
}
