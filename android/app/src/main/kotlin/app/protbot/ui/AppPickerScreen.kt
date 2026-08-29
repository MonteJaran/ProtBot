package app.protbot.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.protbot.data.InstalledApps
import app.protbot.data.UsageRepository
import kotlinx.coroutines.launch

/**
 * Pick which installed apps ProtBot tracks.
 *
 * `InstalledApps.list` only sees anything past Android 11 because of the
 * `<queries>` block in AndroidManifest.xml -- see that file's comment on it.
 * Tapping a tracked row for its limit is [onEditLimit], not this screen: an
 * app just added has no limit worth setting yet (0 = unlimited, the same
 * default the desktop app uses), and editing an existing one is a separate,
 * focused screen rather than an inline control in a long list.
 */
@Composable
fun AppPickerScreen(onBack: () -> Unit, onEditLimit: (packageName: String, label: String) -> Unit) {
    val context = LocalContext.current
    val repository = remember { UsageRepository.get(context) }
    val scope = rememberCoroutineScope()

    // Reading installed packages touches PackageManager, which is not free
    // on a phone with a couple hundred apps -- computed once, not on every
    // recomposition.
    val installed = remember { InstalledApps.list(context) }
    val tracked by repository.trackedAppsFlow().collectAsState(initial = emptyList())
    val trackedByPackage = remember(tracked) { tracked.associateBy { it.packageName } }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("Back") }
            Spacer(Modifier.width(8.dp))
            Text("Add apps to track", style = MaterialTheme.typography.titleMedium)
        }
        HorizontalDivider()

        if (installed.isEmpty()) {
            Text(
                "No launchable apps were found.",
                modifier = Modifier.padding(16.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
            return@Column
        }

        LazyColumn(Modifier.fillMaxSize()) {
            items(installed, key = { it.packageName }) { app ->
                val trackedApp = trackedByPackage[app.packageName]
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(app.label, modifier = Modifier.weight(1f))
                    if (trackedApp != null) {
                        TextButton(onClick = { onEditLimit(app.packageName, app.label) }) {
                            Text("Edit limit")
                        }
                        Spacer(Modifier.width(4.dp))
                        TextButton(onClick = {
                            scope.launch { repository.removeApp(app.packageName) }
                        }) { Text("Remove") }
                    } else {
                        Button(onClick = {
                            scope.launch {
                                repository.setApp(app.packageName, app.label, dailyLimitMinutes = 0)
                            }
                        }) { Text("Add") }
                    }
                }
                HorizontalDivider()
            }
        }
    }
}
