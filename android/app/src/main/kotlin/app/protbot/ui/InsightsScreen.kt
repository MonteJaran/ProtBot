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
import app.protbot.core.Insights
import app.protbot.data.UsageRepository

/**
 * Today's and this week's usage per tracked app.
 *
 * The arithmetic (today vs. week totals, percent of limit) is
 * app.protbot.core.Insights.summarize -- tested without a device. This is
 * only the Room fetch and the layout.
 */
@Composable
fun InsightsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val repository = remember { UsageRepository.get(context) }

    var summaries by remember { mutableStateOf<List<Insights.AppSummary>?>(null) }

    LaunchedEffect(Unit) {
        summaries = repository.insightsSummary()
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("Back") }
            Spacer(Modifier.width(8.dp))
            Text("Insights", style = MaterialTheme.typography.titleMedium)
        }
        HorizontalDivider()

        val rows = summaries
        when {
            rows == null -> Text("Loading…", modifier = Modifier.padding(16.dp))
            rows.isEmpty() -> Text(
                "No apps tracked yet. Add some from the home screen.",
                modifier = Modifier.padding(16.dp),
            )
            else -> LazyColumn(Modifier.fillMaxSize()) {
                items(rows, key = { it.packageName }) { row -> InsightsRow(row) }
            }
        }
    }
}

@Composable
private fun InsightsRow(row: Insights.AppSummary) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        Text(row.label, style = MaterialTheme.typography.titleSmall)
        Text(
            "Today: ${formatMinutes(row.todaySeconds)} · This week: ${formatMinutes(row.weekSeconds)}",
            style = MaterialTheme.typography.bodySmall,
        )
        if (row.dailyLimitMinutes > 0) {
            Spacer(Modifier.height(6.dp))
            LinearProgressIndicator(
                progress = { (row.percentOfDailyLimitToday / 100f).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "${row.percentOfDailyLimitToday}% of today's ${row.dailyLimitMinutes}-minute limit",
                style = MaterialTheme.typography.bodySmall,
            )
        } else if (row.dailyLimitMinutes < 0) {
            Text("Blocked outright", style = MaterialTheme.typography.bodySmall)
        }
    }
    HorizontalDivider()
}

/** "1h 20m" or "35m" or "0m" -- matches the desktop app's _fmt_sec. */
private fun formatMinutes(seconds: Long): String {
    if (seconds <= 0) return "0m"
    val totalMinutes = seconds / 60
    val hours = totalMinutes / 60
    val minutes = totalMinutes % 60
    return if (hours > 0) "${hours}h ${minutes}m" else "${minutes}m"
}
