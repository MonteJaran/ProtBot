package app.protbot.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.protbot.data.UsageRepository
import app.protbot.sync.SyncClientFactory
import kotlinx.coroutines.launch

/**
 * Turn cross-device sync on or off for this phone, and register it under a
 * name the user picked.
 *
 * The screen STATUS.md names as missing: nothing on Android has ever called
 * SyncClient.register before this. `ui/ScanScreen.kt` works around its
 * absence by auto-registering with the phone's model name the first time
 * someone scans a link code -- this is the deliberate version of the same
 * call, and mirrors the desktop's Devices tab ("This Device" section,
 * `core/syncclient.py`'s `register_device`): registering is the explicit
 * opt-in, so nothing about this phone's usage leaves it before the user
 * presses the button below.
 */
@Composable
fun DeviceSyncScreen(onBack: () -> Unit, onLinkDevice: () -> Unit) {
    val context = LocalContext.current
    val repository = remember { UsageRepository.get(context) }
    // One instance for the life of this screen, not re-created per
    // recomposition -- register()/unregister() both write to the same
    // SharedPreferences-backed state this reads back below.
    val client = remember { SyncClientFactory.create(context, repository) }
    val scope = rememberCoroutineScope()

    var deviceId by remember { mutableStateOf(client.deviceId) }
    var name by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf("") }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("Back") }
            Spacer(Modifier.width(8.dp))
            Text("Device sync", style = MaterialTheme.typography.titleMedium)
        }
        HorizontalDivider()

        Column(
            Modifier.fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (deviceId.isEmpty()) {
                Text(
                    "Sync is off. Registering shares this phone's usage totals " +
                        "with your other ProtBot devices, so a limit counts time " +
                        "on all of them together instead of each one allowing " +
                        "the full amount on its own.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name for this device") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    enabled = !busy,
                    onClick = {
                        busy = true
                        errorMessage = ""
                        scope.launch {
                            // A blank name falls back to the model, the same
                            // choice ScanScreen makes when there is no name to
                            // ask for at all -- consistent rather than leaving
                            // an unnamed device in the list.
                            val label = name.trim().ifBlank {
                                android.os.Build.MODEL?.takeIf { it.isNotBlank() } ?: "Android"
                            }
                            val id = runCatching { client.register(label) }.getOrDefault("")
                            busy = false
                            if (id.isEmpty()) {
                                errorMessage = "Could not register. Check your connection and try again."
                            } else {
                                deviceId = id
                            }
                        }
                    },
                ) { Text(if (busy) "Registering…" else "Turn on sync") }
            } else {
                Text("Sync is on.", style = MaterialTheme.typography.titleSmall)
                Text("Device ID: $deviceId", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(4.dp))
                Button(onClick = onLinkDevice) { Text("Link another device") }
                OutlinedButton(onClick = {
                    client.unregister()
                    deviceId = ""
                    name = ""
                }) { Text("Turn off sync") }
            }

            if (errorMessage.isNotBlank()) {
                Text(
                    errorMessage,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}
