package app.protbot.sync

import android.content.Context
import androidx.work.*
import app.protbot.core.Sync
import app.protbot.data.UsageRepository
import java.util.concurrent.TimeUnit

/**
 * Periodic sync, and the retention sweep that goes with it.
 *
 * Separate from `UsageWorker` because the two have different failure modes and
 * different constraints: collection must run whether or not there is a
 * network, and sync must not run without one. Folding them together would mean
 * a plane journey either loses tracking or burns the battery retrying a
 * request that cannot succeed.
 *
 * `NetworkType.CONNECTED` is the constraint doing that work. It is also why
 * this is worth a worker at all rather than a timer: WorkManager holds the job
 * until connectivity comes back and runs it once, instead of failing thirty
 * times on the way.
 */
object SyncWorker {

    private const val WORK_NAME = "protbot-sync"

    /** Matches the desktop default in core/config.py. */
    const val DEFAULT_RETENTION_DAYS = 365

    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<RunSyncWorker>(
            Sync.UPLOAD_INTERVAL_SEC, TimeUnit.SECONDS,
        ).setConstraints(
            Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build(),
        ).setBackoffCriteria(
            // The server being down is the common failure and it is not
            // urgent. Exponential from a minute keeps a long outage from
            // costing battery, and a cumulative upload means the catch-up is
            // one request however long it lasted.
            BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS,
        ).build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME,
            // KEEP, not REPLACE: replacing on every launch resets the period,
            // so on a frequently-opened app the work never actually runs.
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
    }
}

class RunSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val repository = UsageRepository.get(applicationContext)

        // Retention runs here regardless of whether sync is on, because it is
        // the only periodic job with a reason to touch old rows and history
        // must not grow forever on a device the user never registered.
        try {
            repository.prune(SyncWorker.DEFAULT_RETENTION_DAYS)
        } catch (e: Exception) {
            android.util.Log.w(TAG, "Retention sweep failed", e)
        }

        val client = SyncClientFactory.create(applicationContext, repository)
        if (!client.enabled) {
            // Not registered: sync is off and that is the user's choice, not a
            // failure. Retrying would mean a permanently failing job on every
            // install that never turns sync on.
            return Result.success()
        }

        return if (client.syncOnce()) Result.success() else Result.retry()
    }

    private companion object {
        const val TAG = "ProtBotSync"
    }
}

/**
 * Builds a client with the real transport.
 *
 * Exists so the worker has no knowledge of URLs or user agents, and so tests
 * construct `SyncClient` with a fake transport directly.
 */
object SyncClientFactory {

    /** Overridable so a self-hosted server can be pointed at without a rebuild. */
    var baseUrl: String = "https://api-tk3y3h4s3q-uc.a.run.app"

    fun create(context: Context, repository: UsageRepository): SyncClient =
        SyncClient(
            context = context,
            transport = HttpTransport(
                baseUrl = baseUrl,
                userAgent = "ProtBot-Android/" +
                    (runCatching {
                        context.packageManager
                            .getPackageInfo(context.packageName, 0).versionName
                    }.getOrNull() ?: "0"),
                // Read before SyncClient exists to ask (AUDIT SF-09): the
                // token has to be on the Transport at construction time, not
                // patched in after.
                token = SyncClient.storedToken(context),
            ),
            repository = repository,
        )
}
