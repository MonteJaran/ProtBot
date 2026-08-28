package app.protbot.usage

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.protbot.sync.SyncWorker

/**
 * Re-arms the periodic work after a reboot.
 *
 * Without this, tracking silently stops the first time the phone restarts and
 * the user's limits quietly stop being enforced — which looks exactly like the
 * app not working. Sync is re-armed for the same reason: totals that stop
 * being uploaded make the *other* device under-count, so the failure shows up
 * somewhere the user would never think to look.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        UsageWorker.schedule(context)
        SyncWorker.schedule(context)
    }
}
