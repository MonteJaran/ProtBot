package app.protbot.core

import java.time.LocalDateTime
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

/**
 * The blocking decision.
 *
 * This is the most consequential logic in the Android app — get it wrong in
 * one direction and the app blocks nothing, get it wrong in the other and the
 * user is locked out of their own phone. It lives in `core` precisely so it
 * can be tested here rather than only on a device.
 */
class BlockPolicyTest {

    // 2026-06-15 is a Monday, so dayOfWeek.value - 1 == 0.
    private val monday10am = LocalDateTime.of(2026, 6, 15, 10, 0)

    private fun policy(
        limits: Map<String, Int> = mapOf(INSTAGRAM to 60),
        used: Map<String, Long> = emptyMap(),
        focus: FocusHours = FocusHours(),
        enabled: Boolean = true,
        now: LocalDateTime = monday10am,
    ) = BlockPolicy(limits, used, focus, enabled) { now }

    private fun decide(p: BlockPolicy, pkg: String = INSTAGRAM) = p.decide(pkg, 0L)

    // ── Under the limit ──────────────────────────────────────────────────

    @Test fun `an app under its limit is allowed`() {
        assertIs<BlockDecision.Allow>(decide(policy(used = mapOf(INSTAGRAM to 1800L))))
    }

    @Test fun `an app with no limit set is allowed`() {
        assertIs<BlockDecision.Allow>(decide(policy(limits = emptyMap())))
    }

    @Test fun `a zero limit means unlimited not blocked`() {
        // 0 is the "no limit" sentinel. Reading it as "blocked" would block
        // every app the user has ever added.
        assertIs<BlockDecision.Allow>(
            decide(policy(limits = mapOf(INSTAGRAM to 0), used = mapOf(INSTAGRAM to 99999L))),
        )
    }

    @Test fun `an untracked app is allowed`() {
        assertIs<BlockDecision.Allow>(decide(policy(), pkg = "com.example.other"))
    }

    // ── Over the limit ───────────────────────────────────────────────────

    @Test fun `an app over its limit is blocked`() {
        val decision = decide(policy(used = mapOf(INSTAGRAM to 3700L)))
        assertIs<BlockDecision.Block>(decision)
        assertEquals(60, decision.limitMinutes)
        assertEquals(3700, decision.usedSeconds)
    }

    @Test fun `blocking starts exactly at the limit`() {
        assertIs<BlockDecision.Allow>(decide(policy(used = mapOf(INSTAGRAM to 3599L))))
        assertIs<BlockDecision.Block>(decide(policy(used = mapOf(INSTAGRAM to 3600L))))
    }

    // ── Protected packages ───────────────────────────────────────────────

    @Test fun `protected packages are never blocked even if limited`() {
        // Blocking Settings or the launcher leaves a phone the user cannot
        // operate and cannot use to turn blocking off.
        for (pkg in listOf("com.android.settings", "com.miui.home", "app.protbot")) {
            val p = policy(limits = mapOf(pkg to 1), used = mapOf(pkg to 99999L))
            assertIs<BlockDecision.Allow>(decide(p, pkg), "$pkg must never be blocked")
        }
    }

    // ── The master switch ────────────────────────────────────────────────

    @Test fun `nothing is blocked when blocking is off`() {
        val p = policy(used = mapOf(INSTAGRAM to 99999L), enabled = false)
        assertIs<BlockDecision.Allow>(decide(p))
    }

    // ── Focus hours ──────────────────────────────────────────────────────

    private val focusingNow = FocusHours(
        enabled = true, days = setOf(0), startMinutes = 9 * 60, endMinutes = 17 * 60,
    )

    @Test fun `focus hours with a zero cap block immediately`() {
        // Blocked outright: over the limit the moment the app is opened, with
        // no usage at all.
        val p = policy(used = emptyMap(), focus = focusingNow.copy(capMinutes = 0))
        val decision = decide(p)
        assertIs<BlockDecision.Block>(decision)
        assertEquals(Limits.BLOCKED, decision.limitMinutes)
    }

    @Test fun `focus hours tighten an existing limit`() {
        // 15-minute cap, 20 minutes used: over, though well under the app's
        // own 60-minute limit.
        val p = policy(
            used = mapOf(INSTAGRAM to 20L * 60),
            focus = focusingNow.copy(capMinutes = 15),
        )
        val decision = decide(p)
        assertIs<BlockDecision.Block>(decision)
        assertEquals(15, decision.limitMinutes)
    }

    @Test fun `outside focus hours the apps own limit applies`() {
        val evening = LocalDateTime.of(2026, 6, 15, 20, 0)
        val p = policy(
            used = mapOf(INSTAGRAM to 20L * 60),
            focus = focusingNow.copy(capMinutes = 15),
            now = evening,
        )
        assertIs<BlockDecision.Allow>(decide(p))
    }

    @Test fun `focus hours never loosen an existing limit`() {
        // 120-minute cap must not raise a 60-minute limit.
        val p = policy(
            used = mapOf(INSTAGRAM to 70L * 60),
            focus = focusingNow.copy(capMinutes = 120),
        )
        val decision = decide(p)
        assertIs<BlockDecision.Block>(decision)
        assertEquals(60, decision.limitMinutes)
    }

    @Test fun `an overnight focus window blocks after midnight`() {
        val overnight = FocusHours(
            enabled = true, days = setOf(4),          // Friday
            startMinutes = 22 * 60, endMinutes = 6 * 60, capMinutes = 0,
        )
        // Saturday 01:00 — still inside the Friday-night window.
        val saturdayEarly = LocalDateTime.of(2026, 6, 20, 1, 0)
        assertEquals(5, saturdayEarly.dayOfWeek.value - 1)

        val p = policy(focus = overnight, now = saturdayEarly)
        assertIs<BlockDecision.Block>(decide(p))
    }

    // ── The weekday mapping ──────────────────────────────────────────────

    @Test fun `java DayOfWeek is converted to a zero based monday`() {
        // DayOfWeek.MONDAY.value is 1, and FocusHours expects 0. Getting this
        // off by one shifts every schedule by a day.
        val mondayFocus = FocusHours(
            enabled = true, days = setOf(0),
            startMinutes = 0, endMinutes = 24 * 60 - 1, capMinutes = 0,
        )
        assertIs<BlockDecision.Block>(decide(policy(focus = mondayFocus, now = monday10am)))

        val tuesday = LocalDateTime.of(2026, 6, 16, 10, 0)
        assertIs<BlockDecision.Allow>(decide(policy(focus = mondayFocus, now = tuesday)))
    }

    @Test fun `a decision is reached for every package without throwing`() {
        val p = policy(limits = mapOf(INSTAGRAM to 30), used = mapOf(INSTAGRAM to 60L))
        for (pkg in listOf("", "   ", "com.unknown", INSTAGRAM, "com.android.settings")) {
            assertTrue(decide(p, pkg) is BlockDecision)
        }
    }

    private companion object {
        const val INSTAGRAM = "com.instagram.android"
    }
}
