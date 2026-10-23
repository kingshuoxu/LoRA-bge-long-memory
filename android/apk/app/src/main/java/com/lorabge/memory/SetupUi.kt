package com.lorabge.memory

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.json.JSONObject
import java.io.File

data class SetupFileUi(val name: String, val bytes: Long, val size: Long, val state: String)

data class SetupState(
    val lang: String = "zh",
    val files: List<SetupFileUi> = emptyList(),
    val mirror: String = "",
    val speedBps: Long = 0,
    val message: String = "",
    val state: String = "",
    val url: String = "",
    val wifi: Boolean = false,
    val statusTop: Dp = 0.dp,
    val navBottom: Dp = 0.dp,
)

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
    val files = ArrayList<SetupFileUi>()
    val rows = status?.optJSONArray("files")
    if (rows != null) {
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            files.add(
                SetupFileUi(
                    row.getString("dest").substringAfterLast('/'),
                    row.getLong("bytes"),
                    row.getLong("size"),
                    row.getString("state"),
                ),
            )
        }
    }
    SetupFrame(
        SetupState(
            lang = lang,
            files = files,
            mirror = status?.optString("mirror").orEmpty(),
            speedBps = status?.optLong("speedBps") ?: 0L,
            message = status?.optString("message").orEmpty(),
            state = state,
            url = url,
            wifi = wifi,
        ),
        onLang = { lang = it },
        onWifi = {
            wifi = it
            FetchService.setWifiOnly(context, it)
        },
        onUrl = { url = it },
        onPause = {
            val action = if (state == "running") FetchService.ACTION_PAUSE else FetchService.ACTION_RESUME
            context.startForegroundService(Intent(context, FetchService::class.java).setAction(action))
        },
        onUseUrl = {
            FetchService.setManifestUrl(context, url)
            context.startForegroundService(Intent(context, FetchService::class.java).setAction(FetchService.ACTION_RESUME))
        },
    )
}

@Composable
fun SetupFrame(
    state: SetupState,
    onLang: (String) -> Unit = {},
    onWifi: (Boolean) -> Unit = {},
    onUrl: (String) -> Unit = {},
    onPause: () -> Unit = {},
    onUseUrl: () -> Unit = {},
) {
    val serif = rememberSerif()
    val top = if (state.statusTop > 0.dp) state.statusTop else WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
    val nav = if (state.navBottom > 0.dp) state.navBottom else WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val got = overallBytes(state.files.map { FileSnap(it.name, it.bytes, it.size, it.state) })
    val frac = if (got.second <= 0) 0f else (got.first.toFloat() / got.second.toFloat()).coerceIn(0f, 1f)
    val percent = (frac * 100).toInt()
    MaterialTheme(
        colorScheme = darkColorScheme(background = Night, primary = Accent, onBackground = Ink),
        typography = Typography(
            bodyLarge = TextStyle(fontFamily = serif, fontSize = 16.sp, color = Ink),
            titleLarge = TextStyle(fontFamily = serif, fontSize = 28.sp, color = Ink),
        ),
    ) {
        Box(Modifier.fillMaxSize().background(Night)) {
            MilkyWay(paused = state.state == "running")
            Column(
                Modifier.fillMaxSize().padding(start = 16.dp, end = 16.dp, top = top + 8.dp, bottom = nav + 12.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(if (state.lang == "en") "Fetch models" else "准备模型", style = MaterialTheme.typography.titleLarge)
                    Row {
                        Text("中文", color = if (state.lang == "zh") Gold else Muted, modifier = Modifier.padding(end = 8.dp).clickable { onLang("zh") })
                        Text("EN", color = if (state.lang == "en") Gold else Muted, modifier = Modifier.clickable { onLang("en") })
                    }
                }
                Text(
                    if (state.lang == "en") "The phone downloads the base, bge, training weights and five experts. No computer."
                    else "手机会自己下载对话基座、bge、训练权重和五个专家。不用电脑。",
                    color = Muted,
                )
                Text(
                    "$percent% · ${formatBytes(got.first)} / ${formatBytes(got.second)} · ${formatEta(got.second - got.first, state.speedBps, state.lang)}",
                    color = Ink,
                )
                Box(Modifier.fillMaxWidth().height(6.dp).background(Color(0x33B7D7FF), RoundedCornerShape(3.dp))) {
                    Box(Modifier.fillMaxWidth(frac).height(6.dp).background(Accent2, RoundedCornerShape(3.dp)))
                }
                if (state.mirror.isNotBlank()) {
                    Text((if (state.lang == "en") "Mirror " else "镜像 ") + state.mirror + " · " + formatSpeed(state.speedBps), color = Accent2)
                }
                if (state.message.isNotBlank()) Text(state.message, color = if (state.state == "error") Gold else Ink)
                for (file in state.files) FileRow(state.lang, file)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (state.lang == "en") "Wi-Fi only" else "只在 Wi-Fi 下载", color = Ink, modifier = Modifier.weight(1f))
                    Switch(checked = state.wifi, onCheckedChange = onWifi)
                }
                OutlinedTextField(
                    value = state.url,
                    onValueChange = onUrl,
                    label = { Text(if (state.lang == "en") "Custom manifest URL" else "自定义清单地址") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text(
                        if (state.state == "running") if (state.lang == "en") "Pause" else "暂停" else if (state.lang == "en") "Resume" else "继续",
                        color = Accent,
                        modifier = Modifier.clickable(onClick = onPause),
                    )
                    Text(if (state.lang == "en") "Use this URL" else "用这个地址", color = Gold, modifier = Modifier.clickable(onClick = onUseUrl))
                }
            }
        }
    }
}

@Composable
private fun FileRow(lang: String, file: SetupFileUi) {
    val frac = if (file.size <= 0) 0f else (file.bytes.toFloat() / file.size.toFloat()).coerceIn(0f, 1f)
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(file.name, color = Ink)
        Text("${fileStateLabel(lang, file.state)} · ${formatBytes(file.bytes)} / ${formatBytes(file.size)}", color = Muted)
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
