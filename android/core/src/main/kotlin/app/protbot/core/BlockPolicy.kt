package app.protbot.core

import java.time.LocalDateTime

/** What the blocker should do about one package. */
sealed interface BlockDecision {
    data object Allow : BlockDecision
    data class Block(val limitMinutes: Int, val usedSeconds: Int) : BlockDecision
}

/**
 * The decision the blocker makes, kept out of the service so it can be tested.
 *
 * An AccessibilityService is awkward to test and easy to get subtly wrong, so
 * everything except "show the screen" is decided here against plain data.
 */
data class BlockPolicy(
    /** package -> the user's own daily limit in minutes. */
    val limits: Map<String, Int> = emptyMap(),
    /** package -> foreground seconds used today. */
    val usedToday: Map<String, Long> = emptyMap(),
    val focusHours: FocusHours = FocusHours(),
    val enabled: Boolean = true,
    /** Injectable so tests do not depend on the wall clock. */
    val clock: () -> LocalDateTime = LocalDateTime::now,
) {
    fun decide(packageName: String, @Suppress("UNUSED_PARAMETER") nowMillis: Long): BlockDecision {
        if (!enabled) return BlockDecision.Allow
        if (Protected.isProtected(packageName)) return BlockDecision.Allow

        val own = limits[packageName] ?: return BlockDecision.Allow
        if (own <= 0) return BlockDecision.Allow

        val now = clock()
        val effective = Limits.effectiveDailyLimit(
            ownLimitMinutes = own,
            focus = focusHours,
            weekday = now.dayOfWeek.value - 1,     // DayOfWeek is 1-based
            minuteOfDay = now.hour * 60 + now.minute,
        )

        val used = (usedToday[packageName] ?: 0L).toInt()
        return if (Limits.isOverLimit(used, effective)) {
            BlockDecision.Block(effective, used)
        } else {
            BlockDecision.Allow
        }
    }
}
