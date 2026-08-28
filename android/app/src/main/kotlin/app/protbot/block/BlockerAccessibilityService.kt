package app.protbot.block

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import app.protbot.core.BlockDecision
import app.protbot.core.BlockPolicy
import app.protbot.core.Limits
import app.protbot.core.Protected
import app.protbot.data.Settings
import app.protbot.data.UsageRepository
import app.protbot.sync.SyncClientFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Notices a blocked app coming to the foreground and puts a screen over it.
 *
 * There is no Android equivalent of the desktop version's TerminateProcess.
 * killBackgroundProcesses only touches background processes — never the app in
 * front of the user, which is the one that matters. So the mechanism is:
 * watch window-state changes, and when a limited app appears, show our own
 * full-screen activity over it.
 *
 * Two things this service deliberately does NOT do, because both would be
 * dishonest given what the user was asked to grant:
 *
 *   - read window content. The config requests no content capability, only
 *     window-state events. It sees which app is in front, nothing inside it.
 *   - run when blocking is off. The policy is consulted on every event and an
 *     empty policy means every event is dropped immediately.
 */
class BlockerAccessibilityService : AccessibilityService() {

    /**
     * What the service enforces. Null until the first load, and every event is
     * dropped until then — refusing to guess is the right failure here.
     */
    @Volatile
    var policy: BlockPolicy? = null

    private val scope = CoroutineScope(SupervisorJob())

    /**
     * The package we most recently acted on.
     *
     * Without this, every window change inside a blocked app re-launches the
     * block screen, which flickers and can trap the user in a loop they cannot
     * escape even by pressing home.
     */
    private var lastBlocked: String? = null
    private var lastBlockedAt: Long = 0

    override fun onServiceConnected() {
        super.onServiceConnected()
        lastBlocked = null
        startPolicyRefresh()
    }

    /**
     * Keep `policy` current.
     *
     * The service cannot query the database on an accessibility event: that
     * callback runs on the main thread and is expected to return immediately,
     * and a disk read there is felt as the whole phone stuttering. So the
     * policy is loaded off-thread on a tick and the event handler only reads a
     * value already in memory.
     *
     * The interval is a deliberate trade. Longer, and usage accrued since the
     * last refresh is not counted, so an app can run over its limit for up to
     * that long. Shorter, and a background service is hitting the database
     * every few seconds for the life of the process.
     */
    private fun startPolicyRefresh() {
        scope.launch {
            val repository = UsageRepository.get(applicationContext)
            val settings = Settings(applicationContext)
            val sync = SyncClientFactory.create(applicationContext, repository)

            while (isActive) {
                try {
                    policy = repository.currentPolicy(
                        focusHours = settings.focusHours,
                        blockingEnabled = settings.blockingEnabled,
                        // Time on the user's other devices. Empty when sync is
                        // off or its last figure is stale, in which case this
                        // enforces local usage only.
                        remoteSeconds = sync.remoteSecondsByPackage(),
                    )
                } catch (e: Exception) {
                    // Keep the previous policy rather than dropping to null: a
                    // transient database error must not silently disable
                    // blocking until the next successful load.
                    android.util.Log.w(TAG, "Could not refresh the block policy", e)
                }
                delay(POLICY_REFRESH_MS)
            }
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return

        val pkg = event.packageName?.toString() ?: return
        val current = policy ?: return

        // Never act on the launcher, Settings, the dialer or ourselves. This
        // is the difference between a focus app and a device that cannot be
        // used or recovered.
        if (Protected.isProtected(pkg)) {
            lastBlocked = null
            return
        }

        if (pkg == lastBlocked && System.currentTimeMillis() - lastBlockedAt < REBLOCK_COOLDOWN_MS) {
            return
        }

        when (val decision = current.decide(pkg, System.currentTimeMillis())) {
            is BlockDecision.Allow -> lastBlocked = null

            is BlockDecision.Block -> {
                lastBlocked = pkg
                lastBlockedAt = System.currentTimeMillis()
                showBlockScreen(pkg, decision.limitMinutes, decision.usedSeconds)
            }
        }
    }

    private fun showBlockScreen(pkg: String, limitMinutes: Int, usedSeconds: Int) {
        val intent = Intent(this, BlockScreenActivity::class.java).apply {
            addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_CLEAR_TASK or
                    Intent.FLAG_ACTIVITY_NO_ANIMATION,
            )
            putExtra(BlockScreenActivity.EXTRA_PACKAGE, pkg)
            putExtra(BlockScreenActivity.EXTRA_LIMIT_MINUTES, limitMinutes)
            putExtra(BlockScreenActivity.EXTRA_USED_SECONDS, usedSeconds)
            putExtra(
                BlockScreenActivity.EXTRA_BLOCKED_OUTRIGHT,
                limitMinutes == Limits.BLOCKED,
            )
        }
        startActivity(intent)
    }

    override fun onInterrupt() {
        lastBlocked = null
    }

    override fun onUnbind(intent: Intent?): Boolean {
        // The user turned the service off in Settings. Leaving the refresh
        // loop running would keep reading the database for a service that is
        // no longer allowed to act on what it finds.
        scope.cancel()
        return super.onUnbind(intent)
    }

    companion object {
        private const val TAG = "ProtBotBlocker"

        /**
         * How long before the same package can be blocked again.
         *
         * Long enough that a blocked app cannot re-trigger in a tight loop,
         * short enough that reopening it a moment later is still caught.
         */
        const val REBLOCK_COOLDOWN_MS = 1_500L

        /** How often the policy is reloaded. See startPolicyRefresh. */
        const val POLICY_REFRESH_MS = 60_000L
    }
}
