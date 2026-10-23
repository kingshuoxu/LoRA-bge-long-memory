package com.lorabge.memory

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.json.JSONObject
import java.io.File

@Composable
fun SetupScreen(onFinished: () -> Unit) {
    val context = LocalContext.current
    var lang by remember { mutableStateOf("zh") }
    var tick by remember { mutableStateOf(0) }
    var url by remember { mutableStateOf(FetchService.manifestUrl(context)) }
    var wifi by remember { mutableStateOf(FetchService.wifiOnly(context)) }
    val statusFile = File(context.filesDir, "setup/status.json")
    val raw = if (statusFile.exists()) statusFile.readText() else ""
    val status = remember(raw, tick) { runCatching { if (raw.isBlank()) null else JSONObject(raw) }.getOrNull() }
    LaunchedEffect(Unit) {
        context.startForegroundService(Intent(context, FetchService::class.java))
    }
    val state = status?.optString("state").orEmpty()
    LaunchedEffect(tick) {
        if (File(context.filesDir, "setup/complete").exists() && state == "done") onFinished()
        delay(500)
        tick++
    }
    val serif = rememberSerif()
    MaterialTheme(
        colorScheme = darkColorScheme(background = Night, primary = Accent, onBackground = Ink),
        typography = Typography(
            bodyLarge = TextStyle(fontFamily = serif, fontSize = 16.sp, color = Ink),
            titleLarge = TextStyle(fontFamily = serif, fontSize = 28.sp, color = Ink),
        ),
    ) {
        Box(Modifier.fillMaxSize().background(Night)) {
            MilkyWay(paused = state == "running")
            Column(
                Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(if (lang == "en") "Fetch models" else "准备模型", style = MaterialTheme.typography.titleLarge)
                    Row {
                        Text("中文", color = if (lang == "zh") Gold else Muted, modifier = Modifier.padding(end = 8.dp).clickable { lang = "zh" })
                        Text("EN", color = if (lang == "en") Gold else Muted, modifier = Modifier.clickable { lang = "en" })
                    }
                }
                Text(
                    if (lang == "en") "The phone downloads the base, bge, training weights and five experts. No computer."
                    else "手机会自己下载对话基座、bge、训练权重和五个专家。不用电脑。",
                    color = Muted,
                )
                val mirror = status?.optString("mirror").orEmpty()
                val speed = status?.optLong("speedBps") ?: 0L
                if (mirror.isNotBlank()) {
                    Text((if (lang == "en") "Mirror " else "镜像 ") + mirror + " · " + formatSpeed(speed), color = Accent2)
                }
                val message = status?.optString("message").orEmpty()
                if (message.isNotBlank()) Text(message, color = if (state == "error") Gold else Ink)
                val files = status?.optJSONArray("files")
                if (files != null) {
                    for (i in 0 until files.length()) {
                        val row = files.getJSONObject(i)
                        FileRow(row.getString("dest"), row.getLong("bytes"), row.getLong("size"), row.getString("state"))
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (lang == "en") "Wi-Fi only" else "只在 Wi-Fi 下载", color = Ink, modifier = Modifier.weight(1f))
                    Switch(checked = wifi, onCheckedChange = {
                        wifi = it
                        FetchService.setWifiOnly(context, it)
                    })
                }
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text(if (lang == "en") "Custom manifest URL" else "自定义清单地址") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text(
                        if (state == "running") if (lang == "en") "Pause" else "暂停" else if (lang == "en") "Resume" else "继续",
                        color = Accent,
                        modifier = Modifier.clickable {
                            val action = if (state == "running") FetchService.ACTION_PAUSE else FetchService.ACTION_RESUME
                            context.startForegroundService(Intent(context, FetchService::class.java).setAction(action))
                        },
                    )
                    Text(if (lang == "en") "Use this URL" else "用这个地址", color = Gold, modifier = Modifier.clickable {
                        FetchService.setManifestUrl(context, url)
                        context.startForegroundService(Intent(context, FetchService::class.java).setAction(FetchService.ACTION_RESUME))
                    })
                }
            }
        }
    }
}

@Composable
private fun FileRow(dest: String, bytes: Long, size: Long, state: String) {
    val frac = if (size <= 0) 0f else (bytes.toFloat() / size.toFloat()).coerceIn(0f, 1f)
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(dest.substringAfterLast('/'), color = Ink)
        Text("$state · ${bytes / (1024 * 1024)} / ${size / (1024 * 1024)} MB", color = Muted)
        Box(Modifier.fillMaxWidth().height(6.dp).background(Color(0x33B7D7FF), RoundedCornerShape(3.dp))) {
            Box(Modifier.fillMaxWidth(frac).height(6.dp).background(Accent2, RoundedCornerShape(3.dp)))
        }
    }
}

private fun formatSpeed(bps: Long): String {
    if (bps <= 0) return "0 B/s"
    if (bps < 1024) return "$bps B/s"
    if (bps < 1024 * 1024) return "${bps / 1024} KB/s"
    return String.format("%.1f MB/s", bps / 1024.0 / 1024.0)
}
