package app.protbot.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.protbot.data.UsageRepository
import kotlinx.coroutines.launch

/**
 * Set (or turn off) one app's daily limit.
 *
 * 0 minutes means unlimited -- the same convention as the desktop app and
 * app.protbot.core.Limits.NO_LIMIT, not a limit of zero seconds. The
 * distinct "Blocked outright" switch is Limits.BLOCKED (-1), which a
 * plain number field cannot express without asking someone to type -1
 * minutes, which is not a thing anyone would guess to try.
 */
@Composable
fun LimitEditScreen(packageName: String, label: String, onDone: () -> Unit) {
    val context = LocalContext.current
    val repository = remember { UsageRepository.get(context) }
    val scope = rememberCoroutineScope()

    var minutesText by remember { mutableStateOf("") }
    var blockedOutright by remember { mutableStateOf(false) }
    // Whether this app is paused, independent of its limit -- preserved
    // rather than assumed, so saving a limit here cannot silently unpause
    // an app the user turned off some other way.
    var wasEnabled by remember { mutableStateOf(true) }
    var loaded by remember { mutableStateOf(false) }

    // Loads the app's current limit once, so opening this screen shows what
    // is actually set rather than a blank field that looks like "no limit"
    // until the user notices otherwise.
    LaunchedEffect(packageName) {
        val current = repository.trackedAppsOnce().firstOrNull { it.packageName == packageName }
        val minutes = current?.dailyLimitMinutes ?: 0
        blockedOutright = minutes < 0
        minutesText = if (minutes > 0) minutes.toString() else ""
        wasEnabled = current?.enabled ?: true
        loaded = true
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text(label, style = MaterialTheme.typography.titleLarge)
        Text(packageName, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(20.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Block outright (no daily allowance)", modifier = Modifier.weight(1f))
            Switch(checked = blockedOutright, onCheckedChange = { blockedOutright = it })
        }
        HorizontalDivider(Modifier.padding(vertical = 12.dp))

        if (!blockedOutright) {
            Text("Daily limit, in minutes (leave blank for unlimited)",
                style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = minutesText,
                onValueChange = { text -> if (text.all { it.isDigit() }) minutesText = text },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
            )
        }

        Spacer(Modifier.height(24.dp))
        Row {
            Button(onClick = {
                // BLOCKED (-1) if the switch is on; otherwise the typed
                // minutes, or NO_LIMIT (0) for a blank field -- never a
                // negative number from anywhere but the switch itself.
                val limit = when {
                    blockedOutright -> -1
                    minutesText.isBlank() -> 0
                    else -> minutesText.toIntOrNull()?.coerceAtLeast(0) ?: 0
                }
                scope.launch {
                    repository.setApp(packageName, label, dailyLimitMinutes = limit, enabled = wasEnabled)
                    onDone()
                }
            }, enabled = loaded) { Text("Save") }
            Spacer(Modifier.width(12.dp))
            TextButton(onClick = onDone) { Text("Cancel") }
        }
    }
}
