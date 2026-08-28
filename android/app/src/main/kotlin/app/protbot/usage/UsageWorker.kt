package app.protbot.usage

import android.content.Context
import androidx.work.*
import java.util.concurrent.TimeUnit

/**
 * Periodic usage collection.
 *
 * WorkManager rather than a bare service because Android will otherwise kill
 * this on most manufacturers' builds. 15 minutes is the platform minimum for
 * periodic work; anything shorter is silently rounded up, so asking for less
 * only creates the illusion of finer tracking.
 *
 * The blocker (an AccessibilityService) is what reacts in real time. This
 * worker keeps the stored totals current for the UI and for limit checks.
 */
object UsageWorker {

    private const val WORK_NAME = "protbot-usage-collection"

    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<CollectUsageWorker>(
            15, TimeUnit.MINUTES,
        ).setConstraints(
            Constraints.Builder()
                .setRequiresBatteryNotLow(false)
                .build(),
        ).build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME,
            // KEEP, not REPLACE: replacing on every launch resets the period
            // and the work never actually runs on a frequently-opened app.
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
    }
}

class CollectUsageWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        return try {
            // Collect and persist; the repository owns the midnight split.
            UsageRepository.get(applicationContext).refreshToday()
            Result.success()
        } catch (e: SecurityException) {
            // Usage access revoked. Retrying will not help until the user
            // grants it again, so stop rather than loop.
            Result.failure()
        } catch (e: Exception) {
            Result.retry()
        }
    }
}
