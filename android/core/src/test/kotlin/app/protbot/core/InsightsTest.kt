package app.protbot.core

import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class InsightsTest {

    // ── percentOfLimit ───────────────────────────────────────────────────

    @Test fun `no limit is 0 percent, not a divide-by-zero`() {
        assertEquals(0, Insights.percentOfLimit(usedSeconds = 3600, limitMinutes = 0))
    }

    @Test fun `a blocked app (-1) is also 0 percent here`() {
        // Unlike Limits.usagePercent, which reports BLOCKED as 100% for the
        // block decision -- this is display, not enforcement.
        assertEquals(0, Insights.percentOfLimit(usedSeconds = 1, limitMinutes = Limits.BLOCKED))
    }

    @Test fun `half the limit is 50 percent`() {
        assertEquals(50, Insights.percentOfLimit(usedSeconds = 30 * 60, limitMinutes = 60))
    }

    @Test fun `over the limit still reports the real percentage`() {
        assertEquals(150, Insights.percentOfLimit(usedSeconds = 90 * 60, limitMinutes = 60))
    }

    @Test fun `a corrupt figure clamps rather than overflowing the display`() {
        assertEquals(999, Insights.percentOfLimit(usedSeconds = Long.MAX_VALUE / 2, limitMinutes = 1))
    }

    @Test fun `zero usage is 0 percent`() {
        assertEquals(0, Insights.percentOfLimit(usedSeconds = 0, limitMinutes = 60))
    }

    // ── trailingDates ─────────────────────────────────────────────────────

    @Test fun `seven trailing dates end on today`() {
        val today = LocalDate.of(2026, 6, 15)
        val dates = Insights.trailingDates(today, days = 7)
        assertEquals(7, dates.size)
        assertEquals("2026-06-15", dates.last())
        assertEquals("2026-06-09", dates.first())
    }

    @Test fun `trailing dates are oldest first`() {
        val dates = Insights.trailingDates(LocalDate.of(2026, 1, 3), days = 3)
        assertEquals(listOf("2026-01-01", "2026-01-02", "2026-01-03"), dates)
    }

    @Test fun `a non-positive day count is rejected rather than returning nothing`() {
        assertFailsWith<IllegalArgumentException> {
            Insights.trailingDates(LocalDate.of(2026, 1, 1), days = 0)
        }
    }

    @Test fun `a window crossing a month boundary still lands on real dates`() {
        val dates = Insights.trailingDates(LocalDate.of(2026, 3, 2), days = 5)
        assertEquals(listOf("2026-02-26", "2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02"), dates)
    }

    // ── summarize ─────────────────────────────────────────────────────────

    private val discord = Insights.AppInfo("com.discord", "Discord", dailyLimitMinutes = 60)
    private val slack = Insights.AppInfo("com.slack", "Slack", dailyLimitMinutes = 0)

    @Test fun `today and week totals are read from the usage map`() {
        val usage = mapOf(
            "2026-06-15" to mapOf("com.discord" to 1800L),
            "2026-06-14" to mapOf("com.discord" to 600L),
        )
        val summary = Insights.summarize(
            apps = listOf(discord),
            usageByDate = usage,
            today = "2026-06-15",
            weekDates = listOf("2026-06-14", "2026-06-15"),
        ).single()

        assertEquals(1800L, summary.todaySeconds)
        assertEquals(2400L, summary.weekSeconds)
        assertEquals(50, summary.percentOfDailyLimitToday)   // 1800s of a 60min=3600s limit
    }

    @Test fun `a day or app missing from the usage map reads as zero`() {
        val summary = Insights.summarize(
            apps = listOf(discord),
            usageByDate = emptyMap(),
            today = "2026-06-15",
            weekDates = listOf("2026-06-15"),
        ).single()

        assertEquals(0L, summary.todaySeconds)
        assertEquals(0L, summary.weekSeconds)
    }

    @Test fun `rows are sorted by this week's usage, most first`() {
        val usage = mapOf(
            "2026-06-15" to mapOf("com.discord" to 600L, "com.slack" to 1800L),
        )
        val summaries = Insights.summarize(
            apps = listOf(discord, slack),
            usageByDate = usage,
            today = "2026-06-15",
            weekDates = listOf("2026-06-15"),
        )

        assertEquals(listOf("com.slack", "com.discord"), summaries.map { it.packageName })
    }

    @Test fun `an app with no usage anywhere still gets a row`() {
        // Paused or newly added apps belong on the screen at 0, not hidden.
        val summaries = Insights.summarize(
            apps = listOf(discord, slack),
            usageByDate = emptyMap(),
            today = "2026-06-15",
            weekDates = listOf("2026-06-15"),
        )
        assertEquals(2, summaries.size)
        assertTrue(summaries.all { it.weekSeconds == 0L })
    }

    @Test fun `weekSeconds sums every date in the window, not just today`() {
        val usage = mapOf(
            "2026-06-13" to mapOf("com.discord" to 100L),
            "2026-06-14" to mapOf("com.discord" to 200L),
            "2026-06-15" to mapOf("com.discord" to 300L),
        )
        val summary = Insights.summarize(
            apps = listOf(discord),
            usageByDate = usage,
            today = "2026-06-15",
            weekDates = listOf("2026-06-13", "2026-06-14", "2026-06-15"),
        ).single()

        assertEquals(600L, summary.weekSeconds)
        assertEquals(300L, summary.todaySeconds)
    }
}
