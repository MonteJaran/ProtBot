package app.protbot.core

/**
 * Pairing a phone with a PC by scanning a code off its screen.
 *
 * The Kotlin half of `core/linking.py`, held to the same cases. These two have
 * to agree exactly or the feature does not work at all — the PC builds the
 * payload and the phone parses it, and there is nothing in between to absorb a
 * disagreement.
 *
 * The payload:
 *
 *     https://protbot.app/l#1.ABCD2345
 *     └──────────────────┘ │ │  └─ the link key
 *                          │ └─ payload version
 *                          └─ a URL fragment
 *
 * **An https URL rather than a `protbot://` scheme**, because a custom scheme
 * shows up in a phone camera as "no app can open this" precisely when ProtBot
 * is not installed yet — which is when someone is most likely to be scanning.
 *
 * **The key sits in the fragment.** Everything after `#` stays in the browser
 * and is never sent to a server, so opening the link on a phone without the
 * app does not put the key in a web access log or a proxy cache.
 *
 * **A version number**, because the payload will change and a code from a
 * newer build has to be refused rather than misread.
 *
 * The key is a secret: whoever scans it joins the device group and can see the
 * totals in it. The server issues it for five minutes and single use, and the
 * PC stops showing it before then.
 */
object Linking {

    const val PAYLOAD_VERSION = 1

    const val BASE_URL = "https://protbot.app/l"

    /** A little under the server's five minutes, so the code stops being
     *  offered before it stops working. */
    const val DISPLAY_SECONDS = 4 * 60 + 30

    /**
     * Uppercase letters and digits without O, I, 0 and 1.
     *
     * Typing the key is the fallback when a camera will not focus, and those
     * four characters are the ones people transcribe wrongly. The lost entropy
     * is worth less than the support conversation.
     */
    const val KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    const val KEY_LENGTH = 8

    private val KEY_RE = Regex("^[$KEY_ALPHABET]{$KEY_LENGTH}$")
    private val PAYLOAD_RE = Regex("^(\\d+)\\.([A-Z0-9]+)$")

    /** Why a link attempt failed, in words worth showing someone. */
    sealed class Result {
        data class Key(val key: String) : Result()
        data class Failed(val reason: String) : Result()
    }

    fun isValidKey(key: String?): Boolean =
        !key.isNullOrBlank() && KEY_RE.matches(key.trim().uppercase())

    /**
     * The text that goes in a QR code, or null for an unusable key.
     *
     * Null rather than an encoded bad key: a QR carrying a malformed key is
     * worse than no QR, because it fails at the far end after the user has
     * already done the work of scanning it.
     */
    fun buildPayload(key: String?, baseUrl: String = BASE_URL): String? {
        val clean = key?.trim()?.uppercase() ?: return null
        if (!isValidKey(clean)) return null
        return "$baseUrl#$PAYLOAD_VERSION.$clean"
    }

    /**
     * The key from something scanned or typed.
     *
     * Accepts a bare key as well as the full URL — reading the characters off
     * the screen is the fallback path, and nobody should have to reproduce a
     * URL by hand to use it.
     */
    fun parsePayload(text: String?): Result {
        val input = text?.trim().orEmpty()
        if (input.isEmpty()) return Result.Failed("Nothing was scanned.")

        if (isValidKey(input)) return Result.Key(input.uppercase())

        if (!input.contains('#')) {
            return Result.Failed("That code is not a ProtBot link code.")
        }

        val fragment = input.substringAfterLast('#').trim().uppercase()
        val match = PAYLOAD_RE.matchEntire(fragment)
            ?: return Result.Failed("That code is not a ProtBot link code.")

        val version = match.groupValues[1].toIntOrNull()
            ?: return Result.Failed("That code is not a ProtBot link code.")

        // Forwards, not backwards: a newer PC can produce a code this build
        // has never seen, and guessing at it would be worse than saying so.
        if (version > PAYLOAD_VERSION) {
            return Result.Failed(
                "That code was made by a newer version of ProtBot. " +
                    "Update this device and try again.",
            )
        }
        if (version < PAYLOAD_VERSION) {
            return Result.Failed("That code was made by an old version of ProtBot.")
        }

        val key = match.groupValues[2]
        if (!isValidKey(key)) {
            return Result.Failed("That link code is damaged. Ask for a new one.")
        }
        return Result.Key(key)
    }

    /**
     * How long a displayed code is still good for. Never negative.
     *
     * Clamped at both ends, and both ends matter. A clock that has jumped
     * *forward* gives a negative remainder, which as a countdown renders as a
     * growing number and looks like the code is getting more valid. A clock
     * that has jumped *backwards* gives a remainder larger than the lifetime,
     * which would keep a code the server has already forgotten on screen
     * indefinitely — the worse of the two, because it is the one that hands
     * someone a key that cannot work.
     *
     * The only acceptable failure here is expiring early.
     */
    fun secondsRemaining(
        issuedAtEpochSec: Long,
        nowEpochSec: Long,
        lifetime: Int = DISPLAY_SECONDS,
    ): Int {
        if (issuedAtEpochSec <= 0L) return 0
        val left = lifetime - (nowEpochSec - issuedAtEpochSec)
        return left.coerceIn(0L, lifetime.toLong()).toInt()
    }

    fun isExpired(issuedAtEpochSec: Long, nowEpochSec: Long): Boolean =
        secondsRemaining(issuedAtEpochSec, nowEpochSec) <= 0

    /** The key in two groups, for the person reading it aloud. */
    fun formatKey(key: String): String =
        if (key.length != KEY_LENGTH) key
        else "${key.take(KEY_LENGTH / 2)} ${key.drop(KEY_LENGTH / 2)}"
}
