package app.protbot.sync

import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * One HTTP POST, returning parsed JSON or null.
 *
 * An interface rather than a function so tests can exercise every response
 * shape — timeout, 500, an HTML error page, valid JSON with the wrong types —
 * without a network or a server. `SyncClient` is written against this and
 * never sees a socket.
 *
 * `token` is this device's bearer token from registration (AUDIT SF-09; see
 * `core/syncclient.py` and `server/models.py` note 4 on the desktop side) —
 * a parameter rather than constructor state, so one Transport keeps working
 * across a re-registration without SyncClient rebuilding it. Blank for
 * [SyncClient.register] itself, which is how a token is obtained in the
 * first place.
 */
interface Transport {
    suspend fun post(path: String, payload: JSONObject, token: String = ""): JSONObject?
}

/**
 * The real one.
 *
 * Returns null for every failure rather than throwing. The caller is a
 * background sync cycle; there is no user waiting on it, and the correct
 * response to "the network is down" is to try again later, not to raise.
 */
class HttpTransport(
    baseUrl: String,
    private val userAgent: String,
    private val timeoutMillis: Int = 10_000,
) : Transport {

    private val baseUrl = baseUrl.trimEnd('/')

    override suspend fun post(path: String, payload: JSONObject, token: String): JSONObject? =
        withContext(Dispatchers.IO) {
            if (baseUrl.isEmpty()) return@withContext null
            // Usage data leaves the phone here. Plain http would put it on the
            // wire in clear text, so refuse rather than downgrade — and on
            // Android 9+ cleartext is blocked by default anyway, which would
            // fail later and less clearly.
            if (!baseUrl.startsWith("https://", ignoreCase = true)) {
                android.util.Log.e(TAG, "Sync URL is not https; not sending usage data.")
                return@withContext null
            }

            var connection: HttpURLConnection? = null
            try {
                connection = (URL(baseUrl + path).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = timeoutMillis
                    readTimeout = timeoutMillis
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    setRequestProperty("User-Agent", userAgent)
                    // Absent only for /register itself. See AUDIT SF-09: the
                    // token, not the device id, is what proves this request.
                    if (token.isNotBlank()) {
                        setRequestProperty("Authorization", "Bearer $token")
                    }
                }

                connection.outputStream.use { it.write(payload.toString().toByteArray()) }

                if (connection.responseCode !in 200..299) {
                    android.util.Log.d(TAG, "Sync $path returned ${connection.responseCode}")
                    return@withContext null
                }

                val body = connection.inputStream.bufferedReader().use { it.readText() }

                // Responses are a total per tracked app: a few kilobytes even
                // for a heavy user. Anything past the cap means the server is
                // not answering what we asked, and parsing it is how a bad
                // response becomes a crash instead of a skipped cycle.
                if (body.length > MAX_RESPONSE_CHARS) {
                    android.util.Log.w(TAG, "Sync $path response is too large; ignoring.")
                    return@withContext null
                }

                if (body.isBlank()) null else JSONObject(body)
            } catch (e: Exception) {
                android.util.Log.d(TAG, "Sync $path failed: ${e.message}")
                null
            } finally {
                connection?.disconnect()
            }
        }

    private companion object {
        const val TAG = "ProtBotSync"
        const val MAX_RESPONSE_CHARS = 256 * 1024
    }
}
