package app.protbot.data

import android.content.Context
import app.protbot.core.FocusHours

/**
 * The handful of settings the blocker needs, in SharedPreferences.
 *
 * Not in Room. These are read on the accessibility service's thread on a
 * refresh tick, and a database query there is both unnecessary and a source of
 * jank; they are a dozen scalars, which is exactly what SharedPreferences is
 * for. Usage history stays in Room because it is a table.
 *
 * Defaults match `core/config.py` on the desktop so an install on either
 * platform behaves the same before the user touches anything — in particular
 * blocking is **on** and focus hours are **off**, because a focus schedule the
 * user did not configure would start restricting apps out of nowhere.
 */
class Settings(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences("protbot_settings", Context.MODE_PRIVATE)

    var blockingEnabled: Boolean
        get() = prefs.getBoolean(KEY_BLOCKING, true)
        set(value) = prefs.edit().putBoolean(KEY_BLOCKING, value).apply()

    var focusHours: FocusHours
        get() = FocusHours(
            enabled = prefs.getBoolean(KEY_FOCUS_ENABLED, false),
            days = readDays(),
            startMinutes = prefs.getInt(KEY_FOCUS_START, 9 * 60),
            endMinutes = prefs.getInt(KEY_FOCUS_END, 17 * 60),
            capMinutes = prefs.getInt(KEY_FOCUS_CAP, 0),
        )
        set(value) {
            prefs.edit()
                .putBoolean(KEY_FOCUS_ENABLED, value.enabled)
                .putStringSet(KEY_FOCUS_DAYS, value.days.map { it.toString() }.toSet())
                .putInt(KEY_FOCUS_START, value.startMinutes)
                .putInt(KEY_FOCUS_END, value.endMinutes)
                .putInt(KEY_FOCUS_CAP, value.capMinutes)
                .apply()
        }

    private fun readDays(): Set<Int> {
        val stored = prefs.getStringSet(KEY_FOCUS_DAYS, null) ?: return DEFAULT_DAYS
        // A day outside 0..6 could only come from a corrupt preference, and
        // letting it through would make the window silently never match.
        return stored.mapNotNull { it.toIntOrNull()?.takeIf { d -> d in 0..6 } }
            .toSet()
            .ifEmpty { DEFAULT_DAYS }
    }

    private companion object {
        const val KEY_BLOCKING = "blocking_enabled"
        const val KEY_FOCUS_ENABLED = "focus_enabled"
        const val KEY_FOCUS_DAYS = "focus_days"
        const val KEY_FOCUS_START = "focus_start"
        const val KEY_FOCUS_END = "focus_end"
        const val KEY_FOCUS_CAP = "focus_cap"

        val DEFAULT_DAYS = setOf(0, 1, 2, 3, 4)
    }
}
