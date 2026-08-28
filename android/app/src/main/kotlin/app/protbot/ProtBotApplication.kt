package app.protbot

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build

class ProtBotApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return

        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_LIMITS,
                "Limit warnings",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply { description = "Tells you when an app is close to its daily limit." },
        )

        // Low importance on purpose: the collector notification is a legal
        // requirement of a foreground service, not something worth a sound.
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_COLLECTOR,
                "Usage tracking",
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "Shown while ProtBot is measuring your app usage." },
        )
    }

    companion object {
        const val CHANNEL_LIMITS = "limits"
        const val CHANNEL_COLLECTOR = "collector"
    }
}
