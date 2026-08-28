package app.protbot.data

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "tracked_apps")
data class TrackedApp(
    @PrimaryKey val packageName: String,
    val label: String,
    val dailyLimitMinutes: Int = 0,
    val enabled: Boolean = true,
)

/**
 * One day's usage of one app.
 *
 * Keyed by (package, date) rather than storing open-ended sessions, because
 * UsageStatsManager already reports per-interval totals — and because a
 * per-day row makes the midnight boundary impossible to get wrong, which is
 * the bug the desktop version shipped with.
 */
@Entity(tableName = "daily_usage", primaryKeys = ["packageName", "date"])
data class DailyUsage(
    val packageName: String,
    /** ISO yyyy-MM-dd, local time. */
    val date: String,
    val seconds: Long,
)

@Dao
interface ProtBotDao {

    @Query("SELECT * FROM tracked_apps ORDER BY label")
    fun trackedApps(): Flow<List<TrackedApp>>

    @Query("SELECT * FROM tracked_apps WHERE enabled = 1")
    suspend fun enabledApps(): List<TrackedApp>

    @Upsert
    suspend fun upsertApp(app: TrackedApp)

    @Query("DELETE FROM tracked_apps WHERE packageName = :packageName")
    suspend fun removeApp(packageName: String)

    @Upsert
    suspend fun upsertUsage(usage: DailyUsage)

    @Query("SELECT * FROM daily_usage WHERE date = :date")
    suspend fun usageOn(date: String): List<DailyUsage>

    @Query("SELECT * FROM daily_usage WHERE packageName = :pkg AND date >= :since ORDER BY date")
    fun history(pkg: String, since: String): Flow<List<DailyUsage>>

    /** Retention. Mirrors the desktop app's pruning, default one year. */
    @Query("DELETE FROM daily_usage WHERE date < :cutoff")
    suspend fun pruneBefore(cutoff: String): Int

    @Query("DELETE FROM daily_usage")
    suspend fun deleteAllUsage()

    @Query("DELETE FROM tracked_apps")
    suspend fun deleteAllApps()
}

@Database(
    entities = [TrackedApp::class, DailyUsage::class],
    version = 1,
    exportSchema = true,
)
abstract class ProtBotDatabase : RoomDatabase() {
    abstract fun dao(): ProtBotDao

    companion object {
        @Volatile private var instance: ProtBotDatabase? = null

        fun get(context: Context): ProtBotDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    ProtBotDatabase::class.java,
                    "protbot.db",
                )
                    // No fallbackToDestructiveMigration: silently wiping a
                    // user's history on a schema change is the same class of
                    // mistake as the desktop app's missing migrations.
                    .build()
                    .also { instance = it }
            }
    }
}
