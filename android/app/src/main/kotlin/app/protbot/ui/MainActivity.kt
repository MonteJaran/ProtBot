package app.protbot.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.protbot.permissions.Permissions
import app.protbot.sync.SyncWorker
import app.protbot.usage.UsageWorker

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        UsageWorker.schedule(this)
        // Scheduled even when sync is off: the same job runs the retention
        // sweep, and it returns immediately when there is no device id. Both
        // are enqueueUniquePeriodicWork with KEEP, so this is a no-op after
        // the first launch.
        SyncWorker.schedule(this)
        setContent { MaterialTheme { HomeScreen() } }
    }
}

@Composable
private fun HomeScreen() {
    val context = LocalContext.current

    // Re-read on every composition: the user grants these in Settings and
    // comes back, so a value captured once is stale by the time they return.
    var usageGranted by remember { mutableStateOf(Permissions.hasUsageAccess(context)) }
    var blockerOn by remember { mutableStateOf(Permissions.isBlockerEnabled(context)) }

    LifecycleResumeEffect {
        usageGranted = Permissions.hasUsageAccess(context)
        blockerOn = Permissions.isBlockerEnabled(context)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("ProtBot", style = MaterialTheme.typography.headlineMedium)

        if (!usageGranted) {
            SetupCard(
                title = "Allow usage access",
                body = "ProtBot needs this to see how long you spend in each " +
                    "app. It reads time totals only — never what is on your " +
                    "screen or what you type.",
                action = "Open settings",
                onClick = { context.startActivity(Permissions.usageAccessIntent()) },
            )
        }

        if (!blockerOn) {
            SetupCard(
                title = "Turn on blocking",
                body = "To close an app when you hit your limit, ProtBot needs " +
                    "the accessibility service. It only watches which app is " +
                    "in front — it does not read anything inside them.",
                action = "Open settings",
                onClick = { context.startActivity(Permissions.blockerSettingsIntent()) },
            )
        }

        if (usageGranted && blockerOn) {
            Text(
                "Tracking is on. Add apps and set daily limits below.",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun SetupCard(title: String, body: String, action: String, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(body, style = MaterialTheme.typography.bodyMedium)
            Button(onClick = onClick) { Text(action) }
        }
    }
}

/** Re-runs its body every time the screen comes back to the foreground. */
@Composable
private fun LifecycleResumeEffect(onResume: () -> Unit) {
    val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_RESUME) onResume()
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
}
