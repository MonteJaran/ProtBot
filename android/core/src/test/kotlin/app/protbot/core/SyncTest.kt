package app.protbot.core

import java.time.LocalDate
import java.time.LocalDateTime
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * The cross-device sync rules.
 *
 * These cases are the Kotlin half of a pair: `tests/test_sync.py` asserts the
 * same things about `core/syncproto.py`. They have to agree, because the
 * canonical key is the only thing joining "Discord.exe" on the PC to
 * "com.discord" on the phone — and if the two implementations disagree, the
 * user gets two half-counted apps and no error anywhere to explain it.
 */
class SyncTest {

    // ── Canonical app keys ───────────────────────────────────────────────

    @Test fun `one product gets one key whatever it is called`() {
        for (name in listOf("Discord.exe", "Discord", "com.discord", "DISCORD.EXE", "  Discord  ")) {
            assertEquals("discord", Sync.canonicalAppKey(name), "from '$name'")
        }
    }

    @Test fun `both android package shapes reduce to the product`() {
        // Taking the last segment blindly gets com.instagram.android wrong;
        // taking the first gets youtube wrong. The platform segment says which.
        val cases = mapOf(
            "com.instagram.android" to "instagram",
            "com.whatsapp" to "whatsapp",
            "com.google.android.youtube" to "youtube",
            "com.android.chrome" to "chrome",
            "com.spotify.music" to "spotify",
            "org.telegram.messenger" to "telegram",
        )
        for ((pkg, expected) in cases) {
            assertEquals(expected, Sync.canonicalAppKey(pkg), "from '$pkg'")
        }
    }

    @Test fun `desktop and android names meet on one key`() {
        val pairs = listOf(
            "Spotify.exe" to "com.spotify.music",
            "Telegram" to "org.telegram.messenger",
            "Chrome.exe" to "com.android.chrome",
            "Instagram" to "com.instagram.android",
            "Telegram" to "Telegram for Android",
        )
        for ((desktop, android) in pairs) {
            assertEquals(
                Sync.canonicalAppKey(desktop),
                Sync.canonicalAppKey(android),
                "$desktop and $android must share a key",
            )
        }
    }

    @Test fun `punctuation and spacing do not split an app`() {
        for (name in listOf("VS Code", "vs-code", "VS_Code", "vscode")) {
            assertEquals("vscode", Sync.canonicalAppKey(name), "from '$name'")
        }
    }

    @Test fun `an unusable name produces no key`() {
        // "" must be read as "do not sync this app". Used as a key it would
        // collide every unnameable app onto one row.
        for (name in listOf("", "   ", null, "!!!", "---")) {
            assertEquals("", Sync.canonicalAppKey(name), "from '$name'")
        }
    }

    @Test fun `a name of nothing but noise words keeps them`() {
        // A poor name, but merging it with every other poor name is worse.
        assertEquals("freeapp", Sync.canonicalAppKey("Free App"))
    }

    @Test fun `distinct apps stay distinct`() {
        val keys = listOf("Discord", "Slack", "Telegram", "Signal", "WhatsApp")
            .map { Sync.canonicalAppKey(it) }
            .toSet()
        assertEquals(5, keys.size)
    }

    @Test fun `the join is best effort and says so`() {
        // A vendor-named package no string rule resolves without a brand list.
        // Documented rather than papered over: the user links these by hand.
        // If a future change makes this pass, update the docs with it.
        assertTrue(
            Sync.canonicalAppKey("Firefox.exe") != Sync.canonicalAppKey("org.mozilla.firefox"),
        )
    }

    // ── Matching an app across devices by hand ───────────────────────────

    @Test fun `no override falls back to the automatic key`() {
        assertEquals("firefox", Sync.effectiveAppKey("Firefox.exe", null))
        assertEquals("firefox", Sync.effectiveAppKey("Firefox.exe", ""))
        assertEquals("firefox", Sync.effectiveAppKey("Firefox.exe", "   "))
    }

    @Test fun `an override wins outright, not as a tie breaker`() {
        // This is the whole point of the join the desktop's own name for it
        // does not resolve on its own — see "the join is best effort" above.
        assertEquals(
            Sync.effectiveAppKey("Firefox.exe", "firefox"),
            Sync.effectiveAppKey("org.mozilla.firefox", "firefox"),
        )
    }

    @Test fun `the override is trimmed but not otherwise renormalised here`() {
        // Mirrors core/syncclient.py's set_manual_key: normalisation
        // (canonicalAppKey's own rules) happens once, when the override is
        // stored, not again on every read — this function trusts what it is
        // given past trimming stray whitespace.
        assertEquals("Our-Firefox", Sync.effectiveAppKey("Firefox.exe", "  Our-Firefox  "))
    }

    // ── The merge rule ───────────────────────────────────────────────────

    @Test fun `the other devices time is added to local`() {
        // We uploaded 600s. The group says 1500s, so the PC did 900s. We have
        // since reached 700s on this phone.
        assertEquals(1600L, Sync.mergeAppTotal(700, 1500, 600))
    }

    @Test fun `taking the maximum would lose time`() {
        // max(700, 1500) is 1500 — 100 seconds of our own usage dropped,
        // because the group figure predates it.
        assertTrue(Sync.mergeAppTotal(700, 1500, 600) > 1500L)
    }

    @Test fun `our own upload is not counted twice`() {
        // Nobody else used it: the group is entirely our own last upload.
        assertEquals(600L, Sync.mergeAppTotal(600, 600, 600))
    }

    @Test fun `an uningested upload does not subtract real time`() {
        // Uploaded 900s, server has not stored it, group still reads 0.
        // `others` is negative and must clamp, not remove minutes really spent.
        assertEquals(900L, Sync.mergeAppTotal(900, 0, 900))
    }

    @Test fun `after midnight yesterdays group total cannot bleed through`() {
        // Local has rolled over (0s); the server still holds yesterday's group
        // total and our upload with it.
        assertEquals(0L, Sync.mergeAppTotal(0, 7200, 7200))
    }

    @Test fun `sync can only ever add usage`() {
        // No response of any shape may produce less than local usage. A server
        // that is empty, wrong or hostile must not loosen a limit.
        for ((group, uploaded) in listOf(
            0L to 0L, 0L to 5000L, 10L to 9999L, -5L to 0L,
        )) {
            assertTrue(
                Sync.mergeAppTotal(1200, group, uploaded) >= 1200L,
                "group=$group uploaded=$uploaded",
            )
        }
    }

    @Test fun `an absurd group total is clamped to a day`() {
        // Otherwise one bad row instantly exhausts every limit the user has.
        assertEquals(Sync.MAX_PLAUSIBLE_DAILY_SEC, Sync.mergeAppTotal(0, 1_000_000_000L, 0))
    }

    @Test fun `negatives never reach the arithmetic`() {
        assertEquals(0L, Sync.mergeAppTotal(-100, -100, -100))
    }

    @Test fun `merging includes apps only the other device used`() {
        val merged = Sync.mergeTotals(
            local = mapOf(1 to 600L),
            group = mapOf(1 to 600L, 2 to 1800L),
            uploaded = mapOf(1 to 600L),
        )
        assertEquals(mapOf(1 to 600L, 2 to 1800L), merged)
    }

    @Test fun `other devices seconds never goes negative`() {
        assertEquals(0L, Sync.otherDevicesSeconds(groupSeconds = 0, uploadedSeconds = 900))
        assertEquals(900L, Sync.otherDevicesSeconds(groupSeconds = 1500, uploadedSeconds = 600))
    }

    // ── Freshness ────────────────────────────────────────────────────────

    @Test fun `a recent figure is fresh`() {
        assertTrue(Sync.isFresh(fetchedAtEpochSec = 1000, nowEpochSec = 1060))
    }

    @Test fun `an old figure is not enforced against`() {
        assertFalse(
            Sync.isFresh(
                fetchedAtEpochSec = 1000,
                nowEpochSec = 1000 + Sync.REMOTE_STALE_AFTER_SEC + 1,
            ),
        )
    }

    @Test fun `never synced is not fresh`() {
        assertFalse(Sync.isFresh(fetchedAtEpochSec = 0, nowEpochSec = 5000))
    }

    @Test fun `a future timestamp is not fresh`() {
        // A clock problem. Trusting it keeps a stale figure alive forever.
        assertFalse(Sync.isFresh(fetchedAtEpochSec = 9000, nowEpochSec = 5000))
    }

    // ── The day boundary ─────────────────────────────────────────────────

    @Test fun `the upload date is the devices own local date`() {
        // Not UTC. A server bucketing by its own date puts a Belgrade evening
        // into tomorrow and the user's limit resets at 2am.
        assertEquals("2026-06-15", Sync.localDate(LocalDateTime.of(2026, 6, 15, 22, 30)))
        assertEquals("2026-06-16", Sync.localDate(LocalDateTime.of(2026, 6, 16, 0, 5)))
    }

    @Test fun `a recorded upload from yesterday is not current`() {
        val today = LocalDate.of(2026, 6, 15)
        assertTrue(Sync.uploadIsForToday("2026-06-15", today))
        assertFalse(Sync.uploadIsForToday("2026-06-14", today))
        assertFalse(Sync.uploadIsForToday("", today))
        assertFalse(Sync.uploadIsForToday(null, today))
    }

    @Test fun `sanitize clamps anything off the network into a day`() {
        assertEquals(0L, Sync.sanitizeSeconds(-1))
        assertEquals(1800L, Sync.sanitizeSeconds(1800))
        assertEquals(Sync.MAX_PLAUSIBLE_DAILY_SEC, Sync.sanitizeSeconds(Long.MAX_VALUE))
    }

    // ── The end of the chain ─────────────────────────────────────────────

    @Test fun `a limit is reached by two devices together`() {
        // 40 minutes on the phone, 25 on the PC, a 60-minute limit. Neither
        // device reaches it alone; together they are over. This is the whole
        // reason sync exists.
        val phoneSeconds = 40L * 60
        val pcSeconds = 25L * 60
        val limitMinutes = 60

        assertFalse(Limits.isOverLimit(phoneSeconds.toInt(), limitMinutes))

        val combined = Sync.mergeAppTotal(
            localSeconds = phoneSeconds,
            groupSeconds = pcSeconds,
            uploadedSeconds = 0,
        )
        assertTrue(Limits.isOverLimit(combined.toInt(), limitMinutes))
    }
}
