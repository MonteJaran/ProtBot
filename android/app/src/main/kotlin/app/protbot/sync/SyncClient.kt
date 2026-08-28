package app.protbot.sync

import android.content.Context
import app.protbot.core.Sync
import app.protbot.data.UsageRepository
import java.time.LocalDate
import java.time.LocalDateTime
import org.json.JSONArray
import org.json.JSONObject

/**
 * Talking to the sync server.
 *
 * The rules are in `core/Sync.kt`; this is the part with a socket in it. It
 * posts today's totals, keeps the group totals it gets back, and exposes them
 * so a limit on this phone counts the user's PC time too.
 *
 * The desktop counterpart is `core/syncclient.py`, and the properties are the
 * same on both:
 *
 *  * **Never throws into the caller.** The blocker's decision path must not be
 *    able to fail because DNS did.
 *  * **Never blocks the blocker.** [remoteSecondsFor] reads memory, nothing
 *    else. All I/O happens in [syncOnce], off the main thread.
 *  * **Off unless the user turned it on.** No device id means no requests.
 *    Registration is the opt-in.
 *  * **Failure is local-only, never permissive.** Down, empty, slow or hostile
 *    server all result in limits enforced against this device's own usage —
 *    exactly the behaviour before sync existed. No response can make a limit
 *    looser; see [Sync.mergeAppTotal].
 *
 * No server implements this protocol yet. The paths and payloads come from
 * `server/models.py`, and the client is tested against a fake [Transport], so
 * what is verified is how it behaves on every response shape — including the
 * ones a broken server would send.
 */
class SyncClient(
    context: Context,
    private val transport: Transport,
    private val repository: UsageRepository,
) {

    private val prefs = context.applicationContext
        .getSharedPreferences("protbot_sync", Context.MODE_PRIVATE)

    /** Group totals from the last successful /sync, keyed by server app id. */
    private var groupTotals: Map<Int, Long> = emptyMap()
    private var groupFetchedAt: Long = 0L

    /**
     * The date those totals describe.
     *
     * Freshness alone is not enough. A sync at 23:50 is still inside the
     * freshness window at 00:30, but it is yesterday's figure — applying it
     * would give the user a limit that was already spent before midnight.
     */
    private var groupDate: String = ""

    /**
     * What we last uploaded, so our own stale contribution can be removed from
     * the group figure. Not persisted: after a restart the safe assumption is
     * that we have uploaded nothing, which makes the next merge conservative
     * rather than subtracting a figure we cannot verify.
     */
    private var uploaded: Map<Int, Long> = emptyMap()
    private var uploadedDate: String = ""

    val deviceId: String get() = prefs.getString(KEY_DEVICE_ID, "").orEmpty()

    val enabled: Boolean get() = deviceId.isNotEmpty()

    // ── What the blocker reads ───────────────────────────────────────────

    /**
     * Seconds this app was used today on the user's *other* devices.
     *
     * 0 whenever there is any doubt — sync off, never synced, no server id for
     * this package yet, or the group figure too old to enforce against. 0
     * means "local usage only", which is always safe.
     *
     * Synchronized rather than left to chance: the blocker calls this from the
     * accessibility service's thread while [syncOnce] may be writing from a
     * worker.
     */
    @Synchronized
    fun remoteSecondsFor(packageName: String, nowEpochSec: Long = nowSeconds()): Long {
        if (!groupIsUsable(nowEpochSec)) return 0L

        val serverId = serverIdFor(packageName) ?: return 0L
        val ours = if (uploadedIsCurrent()) uploaded[serverId] ?: 0L else 0L
        return Sync.otherDevicesSeconds(groupTotals[serverId] ?: 0L, ours)
    }

    /** Remote seconds for every package with a server id, for the policy. */
    @Synchronized
    fun remoteSecondsByPackage(nowEpochSec: Long = nowSeconds()): Map<String, Long> {
        if (!groupIsUsable(nowEpochSec)) return emptyMap()

        val current = uploadedIsCurrent()
        return appIdMap().mapNotNull { (pkg, serverId) ->
            val ours = if (current) uploaded[serverId] ?: 0L else 0L
            val other = Sync.otherDevicesSeconds(groupTotals[serverId] ?: 0L, ours)
            if (other > 0L) pkg to other else null
        }.toMap()
    }

    // ── One cycle ────────────────────────────────────────────────────────

    /**
     * Map apps, upload today's totals, fetch the group's. True if the group
     * totals were refreshed.
     *
     * Call from a worker, never the main thread. Wrapped whole because this
     * runs unattended: an exception escaping it would stop sync for the rest
     * of the process with nothing to show for it.
     */
    suspend fun syncOnce(now: LocalDateTime = LocalDateTime.now()): Boolean = try {
        runSync(now)
    } catch (e: Exception) {
        android.util.Log.w(TAG, "Sync cycle failed", e)
        false
    }

    private suspend fun runSync(now: LocalDateTime): Boolean {
        if (!enabled) return false

        ensureAppIds()

        val today = Sync.localDate(now)
        val localTotals = localTotalsByServerId(now.toLocalDate())

        if (localTotals.isNotEmpty()) {
            val payload = JSONObject().apply {
                put("d", deviceId)
                put("t", now.atZone(java.time.ZoneId.systemDefault()).toEpochSecond())
                put("z", today)
                put("a", JSONArray(localTotals.map { JSONArray(listOf(it.key, it.value)) }))
            }
            // Recorded only once the server accepted it. Recording an upload
            // that never landed would make the merge subtract a contribution
            // the group total does not contain, and this device's own minutes
            // would go missing from the shared limit.
            transport.post(ENDPOINT_UPLOAD, payload) ?: return false
            synchronized(this) {
                uploaded = localTotals
                uploadedDate = today
            }
        }

        val response = transport.post(ENDPOINT_SYNC, JSONObject().put("d", deviceId))
            ?: return false

        val totals = parseSync(response)
        synchronized(this) {
            // A new day means our recorded upload is about yesterday. Keeping
            // it would subtract yesterday's seconds from today's group total.
            if (!Sync.uploadIsForToday(uploadedDate, now.toLocalDate())) {
                uploaded = emptyMap()
                uploadedDate = today
            }
            groupTotals = totals
            groupFetchedAt = now.atZone(java.time.ZoneId.systemDefault()).toEpochSecond()
            groupDate = today
        }
        return true
    }

    // ── Registration ─────────────────────────────────────────────────────

    /**
     * Register this device and store the id it is given. Returns it, or "".
     *
     * The moment sync turns on, so it is an explicit call from the settings
     * screen rather than something that happens at startup. Nothing leaves the
     * phone before it.
     */
    suspend fun register(deviceName: String, email: String = ""): String {
        val payload = JSONObject().put("n", deviceName)
        if (email.isNotBlank()) payload.put("e", email)

        val response = transport.post(ENDPOINT_REGISTER, payload) ?: return ""
        val id = response.optString("id").orEmpty().trim()
        if (id.isEmpty()) return ""

        prefs.edit().putString(KEY_DEVICE_ID, id).apply()
        return id
    }

    /**
     * Turn sync off and forget what it needs.
     *
     * Clearing the device id alone would leave the app quiet but still holding
     * the identifier tying this phone to data on the server, and the stale
     * app-id mapping would be wrong if the user registered again.
     */
    @Synchronized
    fun unregister() {
        prefs.edit().remove(KEY_DEVICE_ID).remove(KEY_APP_IDS).apply()
        groupTotals = emptyMap()
        groupFetchedAt = 0L
        groupDate = ""
        uploaded = emptyMap()
        uploadedDate = ""
    }

    // ── App identity ─────────────────────────────────────────────────────

    /**
     * Make sure every tracked app has a server id, sending the list if not.
     *
     * Sent only when something is missing: the app list changes when the user
     * adds an app, so re-sending it every cycle would be noise on the wire.
     *
     * The canonical key goes on the wire rather than the label, because the
     * server's job is to put "Discord.exe" from the PC and "com.discord" from
     * here in one row and it cannot do that from display names.
     */
    private suspend fun ensureAppIds() {
        val apps = repository.trackedAppsOnce()
        val known = appIdMap()
        if (apps.all { known.containsKey(it.packageName) }) return

        val entries = apps.mapNotNull { app ->
            val key = Sync.canonicalAppKey(app.label.ifBlank { app.packageName })
            if (key.isEmpty()) null else JSONArray(listOf(app.packageName, key, ""))
        }
        if (entries.isEmpty()) return

        val response = transport.post(
            ENDPOINT_APPS,
            JSONObject().put("d", deviceId).put("a", JSONArray(entries)),
        ) ?: return

        val mapping = response.optJSONObject("m") ?: return
        val merged = known.toMutableMap()
        for (pkg in mapping.keys()) {
            val id = mapping.optInt(pkg, 0)
            if (id > 0) merged[pkg] = id
        }
        saveAppIdMap(merged)
    }

    private fun appIdMap(): Map<String, Int> {
        val raw = prefs.getString(KEY_APP_IDS, "") ?: ""
        if (raw.isEmpty()) return emptyMap()
        return try {
            val json = JSONObject(raw)
            json.keys().asSequence().mapNotNull { key ->
                val id = json.optInt(key, 0)
                if (id > 0) key to id else null
            }.toMap()
        } catch (e: Exception) {
            // A corrupt preference must not stop sync forever. Losing the map
            // costs one extra /apps request; refusing to parse costs sync.
            android.util.Log.w(TAG, "Discarding an unreadable app id map", e)
            emptyMap()
        }
    }

    private fun saveAppIdMap(map: Map<String, Int>) {
        val json = JSONObject()
        for ((pkg, id) in map) json.put(pkg, id)
        prefs.edit().putString(KEY_APP_IDS, json.toString()).apply()
    }

    private fun serverIdFor(packageName: String): Int? =
        appIdMap()[packageName]?.takeIf { it > 0 }

    private suspend fun localTotalsByServerId(today: LocalDate): Map<Int, Long> {
        val ids = appIdMap()
        return repository.usageTodayByPackage(today)
            .mapNotNull { (pkg, seconds) ->
                val id = ids[pkg] ?: return@mapNotNull null
                if (seconds <= 0L) null else id to Sync.sanitizeSeconds(seconds)
            }
            .toMap()
    }

    /**
     * Whether the stored group total may be enforced against right now.
     *
     * Sync on, a figure recent enough to trust, and that figure about today.
     * All three, because each rules out a different way of being wrong.
     */
    private fun groupIsUsable(nowEpochSec: Long): Boolean =
        enabled &&
            Sync.isFresh(groupFetchedAt, nowEpochSec) &&
            Sync.uploadIsForToday(groupDate, LocalDate.now())

    private fun uploadedIsCurrent(): Boolean =
        Sync.uploadIsForToday(uploadedDate, LocalDate.now())

    private fun parseSync(response: JSONObject): Map<Int, Long> {
        val apps = response.optJSONObject("apps") ?: return emptyMap()
        val totals = mutableMapOf<Int, Long>()
        for (key in apps.keys()) {
            val id = key.toIntOrNull() ?: continue
            if (id <= 0) continue
            // Clamped, so a server bug cannot hand back a number that
            // instantly exhausts every limit the user has.
            totals[id] = Sync.sanitizeSeconds(apps.optLong(key, 0L))
        }
        return totals
    }

    private fun nowSeconds(): Long = System.currentTimeMillis() / 1000L

    companion object {
        private const val TAG = "ProtBotSync"

        const val ENDPOINT_REGISTER = "/register"
        const val ENDPOINT_APPS = "/apps"
        const val ENDPOINT_UPLOAD = "/upload"
        const val ENDPOINT_SYNC = "/sync"

        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_APP_IDS = "server_app_ids"
    }
}
