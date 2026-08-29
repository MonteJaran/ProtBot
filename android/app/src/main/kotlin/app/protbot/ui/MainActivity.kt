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
        setContent { MaterialTheme { AppRoot() } }
    }
}

/**
 * Which screen is showing.
 *
 * Held here rather than through a navigation library: six screens, and
 * nothing but Home has a deep link into it (the QR-code App Link opens
 * MainActivity itself, always at Home -- see AndroidManifest.xml), so a
 * `when` over a sealed class covers it. One fewer new dependency in code
 * with no display to check the result on.
 */
private sealed class Screen {
    data object Home : Screen()
    data object AppPicker : Screen()
    data class LimitEdit(val packageName: String, val label: String) : Screen()
    data object Insights : Screen()
    data object DeviceSync : Screen()
    data object Scan : Screen()
}

@Composable
private fun AppRoot() {
    var screen by remember { mutableStateOf<Screen>(Screen.Home) }

    when (val current = screen) {
        is Screen.Home -> HomeScreen(
            onManageApps = { screen = Screen.AppPicker },
            onInsights = { screen = Screen.Insights },
            onDeviceSync = { screen = Screen.DeviceSync },
            onScan = { screen = Screen.Scan },
        )
        is Screen.AppPicker -> AppPickerScreen(
            onBack = { screen = Screen.Home },
            onEditLimit = { pkg, label -> screen = Screen.LimitEdit(pkg, label) },
        )
        is Screen.LimitEdit -> LimitEditScreen(
            packageName = current.packageName,
            label = current.label,
            // Back to the picker, not Home: the user came from there and
            // most likely wants to add or edit another app next.
            onDone = { screen = Screen.AppPicker },
        )
        is Screen.Insights -> InsightsScreen(onBack = { screen = Screen.Home })
        is Screen.DeviceSync -> DeviceSyncScreen(
            onBack = { screen = Screen.Home },
            onLinkDevice = { screen = Screen.Scan },
        )
        is Screen.Scan -> ScanScreen(onDone = { screen = Screen.Home })
    }
}

@Composable
private fun HomeScreen(
    onManageApps: () -> Unit,
    onInsights: () -> Unit,
    onDeviceSync: () -> Unit,
    onScan: () -> Unit,
) {
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
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onManageApps) { Text("Manage tracked apps") }
                OutlinedButton(onClick = onInsights) { Text("Insights") }
            }
        }

        HorizontalDivider()
        Text("Cross-device sync", style = MaterialTheme.typography.titleMedium)
        Text(
            "Share a limit with your other ProtBot devices, so an hour on the " +
                "PC and an hour here add up to the limit instead of each device " +
                "allowing the full amount.",
            style = MaterialTheme.typography.bodyMedium,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = onDeviceSync) { Text("Manage sync") }
            // Scanning still works without visiting "Manage sync" first --
            // it registers this device automatically if nothing has yet
            // (see ScanScreen.kt) -- so this stays a direct shortcut rather
            // than folding into that screen.
            OutlinedButton(onClick = onScan) { Text("Scan a link code") }
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
