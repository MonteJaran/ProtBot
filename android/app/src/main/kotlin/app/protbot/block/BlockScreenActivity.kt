package app.protbot.block

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.OnBackPressedCallback
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * The screen shown over an app that is over its limit.
 *
 * Deliberately not a dialog and not dismissible by back: a block the user can
 * tap past in one gesture is not a block. The only ways out are Home and the
 * explicit button, both of which take them away from the blocked app rather
 * than into it.
 */
class BlockScreenActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val limitMinutes = intent.getIntExtra(EXTRA_LIMIT_MINUTES, 0)
        val usedSeconds = intent.getIntExtra(EXTRA_USED_SECONDS, 0)
        val blockedOutright = intent.getBooleanExtra(EXTRA_BLOCKED_OUTRIGHT, false)
        val label = intent.getStringExtra(EXTRA_PACKAGE) ?: ""

        // Back must not return to the blocked app. Going Home is the correct
        // outcome and leaves the device usable.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = goHome()
        })

        setContent {
            MaterialTheme {
                BlockScreen(
                    appLabel = label,
                    limitMinutes = limitMinutes,
                    usedMinutes = usedSeconds / 60,
                    blockedOutright = blockedOutright,
                    onDismiss = ::goHome,
                )
            }
        }
    }

    private fun goHome() {
        startActivity(
            Intent(Intent.ACTION_MAIN).apply {
                addCategory(Intent.CATEGORY_HOME)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            },
        )
        finish()
    }

    companion object {
        const val EXTRA_PACKAGE = "package"
        const val EXTRA_LIMIT_MINUTES = "limit_minutes"
        const val EXTRA_USED_SECONDS = "used_seconds"
        const val EXTRA_BLOCKED_OUTRIGHT = "blocked_outright"
    }
}

@Composable
private fun BlockScreen(
    appLabel: String,
    limitMinutes: Int,
    usedMinutes: Int,
    blockedOutright: Boolean,
    onDismiss: () -> Unit,
) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = if (blockedOutright) "Not now" else "Time's up",
                style = MaterialTheme.typography.headlineLarge,
            )
            Spacer(Modifier.height(12.dp))

            // Say what happened and why, in the user's own terms — they set
            // this limit, so remind them of it rather than scolding them.
            Text(
                text = when {
                    blockedOutright ->
                        "You set focus hours that block this app right now."
                    else ->
                        "You've used $usedMinutes of your $limitMinutes minutes " +
                            "for $appLabel today."
                },
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(32.dp))
            Button(onClick = onDismiss) { Text("Back to home screen") }

            Spacer(Modifier.height(8.dp))
            Text(
                text = "Change this in ProtBot settings.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
