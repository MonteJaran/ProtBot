package app.protbot.core

import java.time.LocalDate
import java.time.LocalDateTime

/**
 * The cross-device sync protocol, as pure functions.
 *
 * The Kotlin counterpart of the desktop's `core/syncproto.py`, carrying the
 * same three rules and held to the same test cases. Both sides talk to the
 * wire format in `server/models.py`.
 *
 * This is what makes a limit mean one thing across two devices: an hour on the
 * phone and an hour on the PC add up to the two-hour limit the user set,
 * rather than each device allowing the full two on its own.
 *
 * The rules, and why they are not the obvious ones:
 *
 * **1. Uploads are cumulative, not deltas.** Sending "seconds since the last
 * upload" double-counts every time a response is lost and the client retries.
 * An upload carries today's running total instead, so re-sending it changes
 * nothing and a device that was offline all morning catches up in one request.
 *
 * **2. The day is the device's day.** The upload names its own local date. A
 * server bucketing by UTC puts a Belgrade evening into tomorrow and the user
 * watches their limit reset at 2am.
 *
 * **3. Merging is not "take the bigger number".** The group total the server
 * returns includes this device's own last upload, which is stale by up to the
 * upload interval. Our contribution is subtracted before the remainder is
 * added to the live local figure — see [mergeAppTotal].
 */
object Sync {

    /** Uploads carry a full snapshot, so a missed one costs freshness, not data. */
    const val UPLOAD_INTERVAL_SEC = 30 * 60L

    /**
     * A group total older than this is not enforced against. If the network
     * has been down for an hour the other device's figure is a guess, and
     * blocking an app on a guess is worse than counting local usage only.
     */
    const val REMOTE_STALE_AFTER_SEC = 2 * 60 * 60L

    /** A day holds 86400 seconds. Anything past it is a bug or a hostile response. */
    const val MAX_PLAUSIBLE_DAILY_SEC = 24 * 60 * 60L

    private val EXE_SUFFIX = Regex("""\.(exe|app|apk)$""", RegexOption.IGNORE_CASE)
    private val NON_ALNUM = Regex("""[^a-z0-9]+""")

    private val PACKAGE_PREFIXES = setOf(
        "com", "org", "net", "io", "app", "co", "me", "tv", "dev",
    )

    /**
     * Platform segments. Their position in a package says where the product
     * name is: `com.<vendor>.android.<product>` puts it after,
     * `com.<product>.android` puts it before.
     */
    private val PLATFORM_SEGMENTS = setOf("android", "ios", "mobile", "desktop", "windows")

    /**
     * Generic product-type words. Deliberately no brand names: that list would
     * need constant maintenance, and `core/apps_list.py` is the one file in
     * this project that carries them.
     */
    private val GENERIC_SEGMENTS = setOf("app", "apps", "client", "music", "messenger")

    private val NOISE_WORDS = setOf(
        "for", "android", "ios", "mobile", "desktop", "app", "beta", "free",
        "lite", "pro", "plus", "premium", "the", "inc", "llc", "ltd",
        "windows", "pc", "x64", "x86", "32bit", "64bit",
    )

    /**
     * A stable identity for one app across platforms.
     *
     * The desktop knows apps by executable ("Discord.exe"); Android knows them
     * by package ("com.discord") and label ("Discord"). Sync joins them on this
     * key, so this function and `syncproto.canonical_app_key` have to agree
     * exactly — `SyncTest` and `tests/test_sync.py` share the cases that pin it.
     *
     * This is a best-effort join, and worth being plain about: no string rule
     * turns "org.mozilla.firefox" into "firefox" without a list of brand names
     * to consult. It gets the common shapes right, and where it does not the
     * answer is the user linking the two apps by hand, not a cleverer regex.
     *
     * Returns "" for anything unusable. Callers must read that as "do not sync
     * this app" rather than as a key; an empty key would collide every
     * unnameable app onto one row.
     */
    fun canonicalAppKey(name: String?): String {
        if (name.isNullOrBlank()) return ""
        var text = name.trim().lowercase()
        if (text.isEmpty()) return ""

        if (text.contains('.') && !text.contains(' ') && !EXE_SUFFIX.containsMatchIn(text)) {
            text = productSegment(text)
        }

        text = EXE_SUFFIX.replace(text, "")
        val words = NON_ALNUM.split(text).filter { it.isNotEmpty() }
        val kept = words.filter { it !in NOISE_WORDS }

        // If every word was noise the name was noise-only ("app", "for
        // windows"). Falling back to the unfiltered words keeps it distinct
        // instead of merging it with every other such app.
        return (kept.ifEmpty { words }).joinToString("")
    }

    /**
     * The segment of a package name that identifies the product.
     *
     * Not simply the last one. Android packages come in two shapes, and taking
     * either end blindly gets half of them wrong:
     *
     *     com.instagram.android         product first, platform last
     *     com.google.android.youtube    vendor first, product after the platform
     *
     * So the platform segment is used as the marker it is. When one appears
     * with something after it, the product is what follows; when it trails,
     * the product came before. Generic type words ("music", "messenger") are
     * dropped either way, which is what makes com.spotify.music meet
     * Spotify.exe on the desktop.
     *
     * Falls back to the first segment whenever the rules leave nothing:
     * returning "" would silently drop the app from sync.
     */
    private fun productSegment(packageName: String): String {
        var segments = packageName.split('.').filter { it.isNotEmpty() }
        if (segments.isEmpty()) return packageName

        if (segments.size > 1 && segments[0] in PACKAGE_PREFIXES) {
            segments = segments.drop(1)
        }

        val platformAt = segments.indexOfFirst { it in PLATFORM_SEGMENTS }
        if (platformAt >= 0 && platformAt + 1 < segments.size) {
            segments = segments.drop(platformAt + 1)
        }

        val meaningful = segments.filter {
            it !in PLATFORM_SEGMENTS && it !in GENERIC_SEGMENTS
        }
        return (meaningful.ifEmpty { segments })[0]
    }

    /** Today, in the user's timezone, as the server stores it. */
    fun localDate(now: LocalDateTime): String = now.toLocalDate().toString()

    /**
     * This app's usage across every linked device, for the limit check.
     *
     * [groupSeconds] is the server's figure for all devices including this
     * one, but it only knows about this device up to [uploadedSeconds] — our
     * last upload. So our stale contribution is removed and the live local
     * figure used instead:
     *
     *     others = groupSeconds - uploadedSeconds
     *     merged = localSeconds + max(0, others)
     *
     * The clamp matters. `others` goes negative whenever our latest upload has
     * not been ingested yet, and right after midnight, when this device has
     * rolled over and the server still holds yesterday's group total. Negative
     * would subtract minutes the user really did spend.
     *
     * The result is never below [localSeconds]: sync can only ever add usage.
     * No response — empty, wrong, or hostile — can talk a limit into being
     * looser than what this device measured itself.
     */
    fun mergeAppTotal(localSeconds: Long, groupSeconds: Long, uploadedSeconds: Long): Long {
        val local = maxOf(0L, localSeconds)
        val group = maxOf(0L, groupSeconds)
        val uploaded = maxOf(0L, uploadedSeconds)
        val others = maxOf(0L, group - uploaded)
        return minOf(local + others, MAX_PLAUSIBLE_DAILY_SEC)
    }

    /**
     * [mergeAppTotal] over every app, keyed by server app id.
     *
     * Apps present only in the group total are included: another device may be
     * using an app this phone has never opened today, and that time still
     * counts against a shared limit.
     */
    fun mergeTotals(
        local: Map<Int, Long>,
        group: Map<Int, Long>,
        uploaded: Map<Int, Long>,
    ): Map<Int, Long> =
        (local.keys + group.keys).associateWith { id ->
            mergeAppTotal(local[id] ?: 0L, group[id] ?: 0L, uploaded[id] ?: 0L)
        }

    /**
     * Seconds used on *other* devices — what gets added to local usage.
     *
     * Separated from [mergeAppTotal] because the Android side stores local
     * usage in Room and reads it live; only the remote part comes from here.
     */
    fun otherDevicesSeconds(groupSeconds: Long, uploadedSeconds: Long): Long =
        maxOf(0L, minOf(groupSeconds, MAX_PLAUSIBLE_DAILY_SEC) - maxOf(0L, uploadedSeconds))

    /**
     * Whether a group total is recent enough to enforce a limit against.
     *
     * A timestamp of 0 is "never synced". One in the future is a clock problem
     * and is not fresh either — trusting it would keep a stale figure alive
     * indefinitely.
     */
    fun isFresh(
        fetchedAtEpochSec: Long,
        nowEpochSec: Long,
        maxAgeSec: Long = REMOTE_STALE_AFTER_SEC,
    ): Boolean {
        if (fetchedAtEpochSec <= 0L) return false
        val age = nowEpochSec - fetchedAtEpochSec
        return age in 0..maxAgeSec
    }

    /**
     * Whether the recorded upload still describes today.
     *
     * Kept explicit because getting it wrong is silent: a device that rolls
     * over to a new day while holding yesterday's upload figure subtracts
     * yesterday's seconds from today's group total, and the other device's
     * usage vanishes from the shared limit.
     */
    fun uploadIsForToday(uploadedDate: String?, today: LocalDate): Boolean =
        !uploadedDate.isNullOrEmpty() && uploadedDate == today.toString()

    /** Clamp anything that came off the network into a plausible daily total. */
    fun sanitizeSeconds(seconds: Long): Long =
        seconds.coerceIn(0L, MAX_PLAUSIBLE_DAILY_SEC)
}
