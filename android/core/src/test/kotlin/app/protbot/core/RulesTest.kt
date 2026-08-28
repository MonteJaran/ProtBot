package app.protbot.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The shared rules, held to the same cases as the Python desktop app.
 *
 * These run without the Android SDK, without a device and without a clock, so
 * both platforms can be checked against one standard on any machine.
 */
class FocusHoursTest {

    private val weekdays = FocusHours(
        enabled = true,
        days = setOf(0, 1, 2, 3, 4),
        startMinutes = 9 * 60,
        endMinutes = 17 * 60,
    )

    private fun at(hour: Int, minute: Int = 0) = hour * 60 + minute

    // ── A normal daytime window ──────────────────────────────────────────

    @Test fun `inside the window is active`() {
        assertTrue(weekdays.isActive(weekday = 0, minuteOfDay = at(10)))
    }

    @Test fun `before the window is not active`() {
        assertFalse(weekdays.isActive(0, at(8, 59)))
    }

    @Test fun `the start minute is inside`() {
        assertTrue(weekdays.isActive(0, at(9, 0)))
    }

    @Test fun `the end minute is outside`() {
        assertFalse(weekdays.isActive(0, at(17, 0)))
        assertTrue(weekdays.isActive(0, at(16, 59)))
    }

    @Test fun `a day outside the schedule is not active`() {
        assertFalse(weekdays.isActive(weekday = 5, minuteOfDay = at(10)))
    }

    @Test fun `disabled means never active`() {
        assertFalse(weekdays.copy(enabled = false).isActive(0, at(10)))
    }

    @Test fun `no days selected means never active`() {
        assertFalse(weekdays.copy(days = emptySet()).isActive(0, at(10)))
    }

    @Test fun `a zero length window is never active`() {
        // Reading start == end as "all day" would lock someone out of everything.
        val zero = weekdays.copy(startMinutes = at(9), endMinutes = at(9))
        assertFalse(zero.isActive(0, at(9)))
        assertFalse(zero.isActive(0, at(14)))
    }

    // ── Overnight windows ────────────────────────────────────────────────

    private val overnight = weekdays.copy(startMinutes = at(22), endMinutes = at(6))

    @Test fun `late evening is inside an overnight window`() {
        assertTrue(overnight.isActive(0, at(23)))
    }

    @Test fun `after midnight is inside an overnight window`() {
        // A naive start <= now < end is false here. That is the whole point.
        assertTrue(overnight.isActive(weekday = 1, minuteOfDay = at(2)))
    }

    @Test fun `the middle of the day is outside an overnight window`() {
        assertFalse(overnight.isActive(0, at(13)))
    }

    @Test fun `early morning after the window is outside`() {
        assertFalse(overnight.isActive(1, at(7)))
    }

    @Test fun `a friday night block still applies on saturday morning`() {
        // The window belongs to the day it STARTED on.
        val fridayOnly = overnight.copy(days = setOf(4))
        assertTrue(fridayOnly.isActive(weekday = 4, minuteOfDay = at(23)))
        assertTrue(fridayOnly.isActive(weekday = 5, minuteOfDay = at(1)))
    }

    @Test fun `a saturday block does not leak into saturday morning`() {
        val saturdayOnly = overnight.copy(days = setOf(5))
        assertFalse(saturdayOnly.isActive(weekday = 5, minuteOfDay = at(1)))
        assertTrue(saturdayOnly.isActive(weekday = 5, minuteOfDay = at(23)))
    }

    @Test fun `the week wraps from sunday to monday`() {
        val sundayOnly = overnight.copy(days = setOf(6))
        assertTrue(sundayOnly.isActive(weekday = 0, minuteOfDay = at(2)))
    }

    // ── Time parsing ─────────────────────────────────────────────────────

    @Test fun `valid times parse`() {
        assertEquals(9 * 60, FocusHours.parseTime("09:00"))
        assertEquals(0, FocusHours.parseTime("00:00"))
        assertEquals(23 * 60 + 59, FocusHours.parseTime("23:59"))
    }

    @Test fun `invalid times return null rather than guessing`() {
        for (bad in listOf("", "banana", "25:00", "12:99", "12", null)) {
            assertNull(FocusHours.parseTime(bad), "should reject: $bad")
        }
    }

    @Test fun `formatting round trips`() {
        assertEquals("07:05", FocusHours.formatTime(FocusHours.parseTime("07:05")!!))
    }
}

class LimitsTest {

    private val focusing = FocusHours(
        enabled = true, days = setOf(0), startMinutes = 0, endMinutes = 24 * 60 - 1,
    )
    private val notFocusing = FocusHours(enabled = false)

    @Test fun `an app with no limit is untouched`() {
        // The user never asked for this app to be limited.
        assertEquals(
            Limits.NO_LIMIT,
            Limits.effectiveDailyLimit(0, focusing, 0, 600),
        )
    }

    @Test fun `outside focus hours the apps own limit applies`() {
        assertEquals(60, Limits.effectiveDailyLimit(60, notFocusing, 0, 600))
    }

    @Test fun `a zero cap blocks outright`() {
        assertEquals(
            Limits.BLOCKED,
            Limits.effectiveDailyLimit(60, focusing.copy(capMinutes = 0), 0, 600),
        )
    }

    @Test fun `a cap tightens the limit`() {
        assertEquals(
            15,
            Limits.effectiveDailyLimit(60, focusing.copy(capMinutes = 15), 0, 600),
        )
    }

    @Test fun `focus hours can only tighten never loosen`() {
        // A schedule that quietly raised a limit would defeat the point of it.
        assertEquals(
            30,
            Limits.effectiveDailyLimit(30, focusing.copy(capMinutes = 120), 0, 600),
        )
    }

    @Test fun `zero means unlimited and minus one means blocked`() {
        assertFalse(Limits.isActive(Limits.NO_LIMIT))
        assertTrue(Limits.isActive(60))
        assertTrue(Limits.isActive(Limits.BLOCKED))
    }

    @Test fun `a blocked limit allows no seconds and never goes negative`() {
        assertEquals(3600, Limits.allowedSeconds(60))
        assertEquals(0, Limits.allowedSeconds(Limits.NO_LIMIT))
        assertEquals(0, Limits.allowedSeconds(Limits.BLOCKED))
    }

    @Test fun `a blocked app reads as fully used the moment it is open`() {
        // The desktop version returned 0% here, so a blocked app never
        // triggered at all. This is that bug, as a test.
        assertEquals(100.0, Limits.usagePercent(0, Limits.BLOCKED))
        assertTrue(Limits.isOverLimit(0, Limits.BLOCKED))
    }

    @Test fun `an unlimited app is never over`() {
        assertEquals(0.0, Limits.usagePercent(99999, Limits.NO_LIMIT))
        assertFalse(Limits.isOverLimit(99999, Limits.NO_LIMIT))
    }

    @Test fun `usage percentage is computed against the limit`() {
        assertEquals(50.0, Limits.usagePercent(1800, 60))
        assertEquals(100.0, Limits.usagePercent(3600, 60))
    }

    @Test fun `over the limit is detected at exactly the limit`() {
        assertFalse(Limits.isOverLimit(3599, 60))
        assertTrue(Limits.isOverLimit(3600, 60))
    }
}

class AccountingTest {

    private val interval = 60L

    @Test fun `a normal interval counts in full`() {
        assertEquals(60L, Accounting.countedSeconds(60, interval, requireForeground = false))
    }

    @Test fun `a backwards clock counts as nothing`() {
        assertEquals(0L, Accounting.countedSeconds(-3600, interval, requireForeground = false))
    }

    @Test fun `a long gap is capped rather than credited whole`() {
        // Device off overnight, or the collector was killed by doze.
        val eightHours = 8L * 60 * 60
        assertEquals(90L, Accounting.countedSeconds(eightHours, interval, requireForeground = false))
    }

    @Test fun `a long gap is recognised as an interruption`() {
        assertTrue(Accounting.wasInterrupted(8L * 60 * 60, interval))
        assertFalse(Accounting.wasInterrupted(60, interval))
        assertFalse(Accounting.wasInterrupted(75, interval))
    }

    @Test fun `nothing counts while the user is away`() {
        assertEquals(
            0L,
            Accounting.countedSeconds(60, interval, idleSeconds = 9999, requireForeground = false),
        )
    }

    @Test fun `time counts while the user is active`() {
        assertEquals(
            60L,
            Accounting.countedSeconds(60, interval, idleSeconds = 5, requireForeground = false),
        )
    }

    @Test fun `unknown idle time counts rather than silently dropping`() {
        assertEquals(
            60L,
            Accounting.countedSeconds(
                60, interval, idleSeconds = Accounting.UNKNOWN, requireForeground = false,
            ),
        )
    }

    @Test fun `background apps do not accrue when foreground is required`() {
        assertEquals(0L, Accounting.countedSeconds(60, interval, isForeground = false))
    }

    @Test fun `the foreground app accrues`() {
        assertEquals(60L, Accounting.countedSeconds(60, interval, isForeground = true))
    }

    @Test fun `unknown foreground counts`() {
        assertEquals(60L, Accounting.countedSeconds(60, interval, isForeground = null))
    }

    @Test fun `idle beats foreground`() {
        assertEquals(
            0L,
            Accounting.countedSeconds(60, interval, isForeground = true, idleSeconds = 9999),
        )
    }

    // ── Midnight ─────────────────────────────────────────────────────────

    @Test fun `a session inside one day is not split`() {
        val (today, tomorrow) = Accounting.splitAtMidnight(startMinuteOfDay = 10 * 60, durationSeconds = 3600)
        assertEquals(3600L, today)
        assertEquals(0L, tomorrow)
    }

    @Test fun `a session crossing midnight is split`() {
        // Starts 23:50, runs 20 minutes: 10 before midnight, 10 after.
        val (today, tomorrow) = Accounting.splitAtMidnight(
            startMinuteOfDay = 23 * 60 + 50, durationSeconds = 20 * 60,
        )
        assertEquals(10L * 60, today)
        assertEquals(10L * 60, tomorrow)
    }

    @Test fun `a session ending exactly at midnight is not split`() {
        val (today, tomorrow) = Accounting.splitAtMidnight(
            startMinuteOfDay = 23 * 60 + 50, durationSeconds = 10 * 60,
        )
        assertEquals(10L * 60, today)
        assertEquals(0L, tomorrow)
    }

    @Test fun `a zero length session splits to nothing`() {
        assertEquals(0L to 0L, Accounting.splitAtMidnight(600, 0))
    }
}

class ProtectedTest {

    @Test fun `system packages are protected`() {
        for (pkg in listOf(
            "com.android.settings", "com.android.systemui", "com.android.phone",
            "com.google.android.dialer", "com.android.packageinstaller",
        )) {
            assertTrue(Protected.isProtected(pkg), "$pkg must be protected")
        }
    }

    @Test fun `launchers are protected`() {
        // Blocking the home screen leaves the user nowhere to go.
        for (pkg in listOf(
            "com.google.android.apps.nexuslauncher", "com.miui.home",
            "com.sec.android.app.launcher",
        )) {
            assertTrue(Protected.isProtected(pkg), "$pkg must be protected")
        }
    }

    @Test fun `protbot cannot block itself`() {
        assertTrue(Protected.isProtected("app.protbot"))
    }

    @Test fun `ordinary apps are blockable`() {
        for (pkg in listOf(
            "com.instagram.android", "com.zhiliaoapp.musically",
            "com.google.android.youtube", "com.facebook.katana", "com.reddit.frontpage",
        )) {
            assertFalse(Protected.isProtected(pkg), "$pkg should be blockable")
        }
    }

    @Test fun `matching is case insensitive and trims`() {
        assertTrue(Protected.isProtected("  COM.ANDROID.SETTINGS  "))
    }

    @Test fun `empty input is not protected`() {
        assertFalse(Protected.isProtected(null))
        assertFalse(Protected.isProtected(""))
        assertFalse(Protected.isProtected("   "))
    }

    @Test fun `oem systemui variants are covered by prefix`() {
        assertTrue(Protected.isProtected("com.android.systemui.overlay"))
    }

    @Test fun `protected packages carry a reason and ordinary ones do not`() {
        assertTrue(Protected.reason("app.protbot").isNotEmpty())
        assertTrue(Protected.reason("com.miui.home").isNotEmpty())
        assertTrue(Protected.reason("com.android.settings").isNotEmpty())
        assertEquals("", Protected.reason("com.instagram.android"))
    }
}
