package com.lorabge.memory

import android.graphics.Typeface
import android.graphics.fonts.Font
import android.graphics.fonts.FontFamily
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily as ComposeFontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.sin

internal val Night = Color(0xFF070910)
internal val Ink = Color(0xFFEEF3FB)
internal val Muted = Color(0xFFA9B6C9)
internal val Accent = Color(0xFFB7D7FF)
internal val Accent2 = Color(0xFF7EF0E0)
internal val Gold = Color(0xFFF2D291)

enum class SkyTab { Chat, Consolidate, Nebula, Library }

data class SkyMessage(
    val role: String,
    val text: String,
    val expert: String? = null,
    val reason: String? = null,
    val noticed: Boolean = false,
)

data class SkyExpert(val name: String, val facts: List<String>, val label: String = "")

data class SkyConversation(val id: String, val title: String)

data class PendingCorrection(val entity: String, val statement: String, val value: String)

data class SkyState(
    val lang: String = "zh",
    val tab: SkyTab = SkyTab.Chat,
    val training: Boolean = false,
    val status: String = "",
    val messages: List<SkyMessage> = emptyList(),
    val draft: String = "",
    val conversations: List<SkyConversation> = emptyList(),
    val currentTitle: String = "",
    val loss: List<Float> = emptyList(),
    val experts: List<SkyExpert> = emptyList(),
    val highlightExpert: String? = null,
    val pending: PendingCorrection? = null,
    val entity: String = "",
    val statement: String = "",
    val value: String = "",
    val question: String = "",
    val answer: String = "",
    val force: Boolean = false,
    val note: String = "",
    val toast: String = "",
    val streaming: String = "",
    val generating: Boolean = false,
    val statusTop: Dp = 0.dp,
    val imeBottom: Dp = 0.dp,
    val navBottom: Dp = 0.dp,
    val settingsOpen: Boolean = false,
    val drawerOpen: Boolean = false,
    val backendMode: String = "auto",
    val backendLine: String = "",
    val wifiOnly: Boolean = false,
    val manifestUrl: String = "",
    val storageLabel: String = "",
    val versionName: String = "0.1.3",
    val nebulaJson: String = "",
    val recallJson: String = "",
    val recallBanner: String = "",
    val liveNebula: Boolean = false,
)

sealed class SkyEvent {
    data class Lang(val lang: String) : SkyEvent()
    data class Tab(val tab: SkyTab) : SkyEvent()
    data class Draft(val text: String) : SkyEvent()
    data object Send : SkyEvent()
    data object ConfirmCorrection : SkyEvent()
    data object DismissCorrection : SkyEvent()
    data class Field(val key: String, val text: String) : SkyEvent()
    data class Force(val on: Boolean) : SkyEvent()
    data object Train : SkyEvent()
    data object CancelTrain : SkyEvent()
    data class DeleteExpert(val name: String) : SkyEvent()
    data object NewChat : SkyEvent()
    data object ImportExperts : SkyEvent()
    data object SelfCheck : SkyEvent()
    data class BackendMode(val mode: String) : SkyEvent()
    data object ExportDiagnostics : SkyEvent()
    data object OpenSettings : SkyEvent()
    data object CloseSettings : SkyEvent()
    data object OpenDrawer : SkyEvent()
    data object CloseDrawer : SkyEvent()
    data class OpenConversation(val id: String) : SkyEvent()
    data class WifiOnly(val on: Boolean) : SkyEvent()
    data class ManifestUrl(val url: String) : SkyEvent()
    data object ApplyManifest : SkyEvent()
    data object ClearModels : SkyEvent()
    data object DismissToast : SkyEvent()
}

fun skyText(lang: String, key: String): String {
    val zh = mapOf(
        "chat" to "对话",
        "consolidate" to "巩固",
        "nebula" to "星云",
        "library" to "记忆库",
        "send" to "发送",
        "placeholder" to "发消息…",
        "memoryUsed" to "来源知识",
        "memoryNone" to "未使用记忆",
        "noticed" to "已记下，待巩固",
        "newChat" to "新对话",
        "confirm" to "确认并重新训练",
        "dismiss" to "先不改",
        "entity" to "实体",
        "statement" to "陈述句",
        "value" to "取值",
        "question" to "确认过的问句",
        "answer" to "回答",
        "force" to "立即训练",
        "train" to "确认并训练",
        "cancel" to "取消训练",
        "delete" to "删除",
        "loss" to "损失",
        "steps" to "步",
        "paused" to "训练中，星空暂停",
        "emptyNebula" to "还没有专家。巩固之后，事实会变成星。",
        "recall" to "刚才路由到这里",
        "import" to "导入已推送的专家",
        "selfCheck" to "路由自检",
        "backendAuto" to "自动",
        "backendGpu" to "强制 GPU",
        "backendCpu" to "强制 CPU",
        "exportDiag" to "导出诊断",
        "settings" to "设置",
        "close" to "关闭",
        "wifi" to "只在 Wi-Fi 下载",
        "manifest" to "自定义清单地址",
        "useUrl" to "用这个地址",
        "language" to "语言",
        "storage" to "已用空间",
        "clearModels" to "清除模型",
        "clearConfirm" to "再点一次，清除已下载的模型",
        "about" to "关于",
        "backend" to "推理后端",
        "conversations" to "对话",
        "emptyConv" to "还没有对话",
        "baseReady" to "基座已就绪",
        "baseMissing" to "基座未就绪",
        "bgeReady" to "bge 已就绪",
        "bgeMissing" to "bge 未就绪",
        "maliUnproven" to "这台 Mali 还没在独立进程里证明更快，先用 CPU。",
        "matchedFaster" to "GPU 与 CPU 一致，解码更快。",
        "matched" to "GPU 与 CPU 一致。",
        "noVulkan" to "没有 Vulkan 库。",
        "nativeCrash" to "图形后端异常过，已改用 CPU。",
        "gpuTimeout" to "GPU 自检超时，已改用 CPU。",
        "usingCpu" to "正在使用 CPU。",
        "usingGpu" to "已强制使用 GPU。",
        "checkingGpu" to "正在检测图形后端。",
        "consolidating" to "巩固中",
        "appName" to "长期记忆",
        "stage.select" to "选择对话",
        "stage.extract" to "抽取事实",
        "stage.gate" to "写门",
        "stage.build" to "编训练样本",
        "stage.train" to "训练 LoRA",
        "stage.recall" to "回忆检查",
        "stage.register" to "登记专家",
        "stage.done" to "完成",
        "stage.pending" to "说出一条事实后，会显示在这里",
        "factWrite" to "写入这条事实",
    )
    val en = mapOf(
        "chat" to "Chat",
        "consolidate" to "Consolidate",
        "nebula" to "Nebula",
        "library" to "Library",
        "send" to "Send",
        "placeholder" to "Message…",
        "memoryUsed" to "From memory",
        "memoryNone" to "No memory used",
        "noticed" to "Noted, not consolidated yet",
        "newChat" to "New chat",
        "confirm" to "Confirm and retrain",
        "dismiss" to "Not now",
        "entity" to "Entity",
        "statement" to "Statement",
        "value" to "Value",
        "question" to "Confirmed question",
        "answer" to "Answer",
        "force" to "Train now",
        "train" to "Confirm and train",
        "cancel" to "Cancel training",
        "delete" to "Delete",
        "loss" to "Loss",
        "steps" to "steps",
        "paused" to "Training, the sky is paused",
        "emptyNebula" to "No experts yet. After consolidation, facts become stars.",
        "recall" to "Last route landed here",
        "import" to "Import experts",
        "selfCheck" to "Route check",
        "backendAuto" to "Auto",
        "backendGpu" to "Force GPU",
        "backendCpu" to "Force CPU",
        "exportDiag" to "Export diagnostics",
        "settings" to "Settings",
        "close" to "Close",
        "wifi" to "Wi-Fi only",
        "manifest" to "Custom manifest URL",
        "useUrl" to "Use this URL",
        "language" to "Language",
        "storage" to "Storage used",
        "clearModels" to "Clear models",
        "clearConfirm" to "Tap again to delete downloaded models",
        "about" to "About",
        "backend" to "Inference backend",
        "conversations" to "Chats",
        "emptyConv" to "No conversations yet",
        "baseReady" to "Base ready",
        "baseMissing" to "Base missing",
        "bgeReady" to "bge ready",
        "bgeMissing" to "bge missing",
        "maliUnproven" to "This Mali GPU stays on CPU until an isolated test is faster.",
        "matchedFaster" to "GPU matched CPU and decodes faster.",
        "matched" to "GPU matches CPU.",
        "noVulkan" to "No Vulkan library.",
        "nativeCrash" to "The graphics backend failed and CPU is in use.",
        "gpuTimeout" to "The GPU self-test timed out. Using CPU.",
        "usingCpu" to "Using CPU.",
        "usingGpu" to "GPU is forced.",
        "checkingGpu" to "Checking the graphics backend.",
        "consolidating" to "Consolidating",
        "appName" to "Long memory",
        "stage.select" to "Choose conversations",
        "stage.extract" to "Extract facts",
        "stage.gate" to "Write gate",
        "stage.build" to "Build samples",
        "stage.train" to "Train LoRA",
        "stage.recall" to "Recall check",
        "stage.register" to "Register expert",
        "stage.done" to "Done",
        "stage.pending" to "A new fact shows up here",
        "factWrite" to "Write this fact",
    )
    return (if (lang == "en") en else zh)[key] ?: key
}

@Composable
fun SkyFrame(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    val serif = rememberSerif()
    MaterialTheme(
        colorScheme = darkColorScheme(
            background = Night,
            surface = Color(0xFF10141E),
            primary = Accent,
            onBackground = Ink,
            onSurface = Ink,
        ),
        typography = Typography(
            bodyLarge = TextStyle(fontFamily = serif, fontSize = 16.sp, color = Ink),
            bodyMedium = TextStyle(fontFamily = serif, fontSize = 14.sp, color = Ink),
            titleLarge = TextStyle(fontFamily = serif, fontSize = 28.sp, color = Ink),
            labelLarge = TextStyle(fontFamily = serif, fontSize = 14.sp, color = Accent),
        ),
    ) {
        val top = if (state.statusTop > 0.dp) state.statusTop else WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
        val nav = if (state.navBottom > 0.dp) state.navBottom else WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
        val ime = if (state.imeBottom > 0.dp) state.imeBottom else WindowInsets.ime.asPaddingValues().calculateBottomPadding()
        val keyboard = ime > 0.dp
        val nebulaLive = state.liveNebula && state.tab == SkyTab.Nebula && !state.settingsOpen
        LaunchedEffect(state.toast) {
            if (state.toast.isBlank()) return@LaunchedEffect
            kotlinx.coroutines.delay(4200)
            onEvent(SkyEvent.DismissToast)
        }
        Box(Modifier.fillMaxSize().background(Night)) {
            if (!nebulaLive) MilkyWay(paused = state.training)
            if (nebulaLive) {
                NebulaHost(
                    json = state.nebulaJson,
                    recallJson = state.recallJson,
                    training = state.training,
                    lang = state.lang,
                    modifier = Modifier.fillMaxSize().padding(top = top + 56.dp, bottom = if (keyboard) ime else nav + 64.dp),
                    onOpenConversation = { onEvent(SkyEvent.OpenConversation(it)) },
                )
            }
            Column(Modifier.fillMaxSize().padding(top = top + 8.dp)) {
                if (!state.settingsOpen) TopBar(state, onEvent)
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    if (!nebulaLive && !state.settingsOpen) {
                        Box(Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 8.dp)) {
                            when (state.tab) {
                                SkyTab.Chat -> ChatPane(state, ime, onEvent)
                                SkyTab.Consolidate -> ConsolidatePane(state, onEvent)
                                SkyTab.Nebula -> NebulaFallback(state)
                                SkyTab.Library -> LibraryPane(state, onEvent)
                            }
                        }
                    }
                }
                if (!keyboard && !state.settingsOpen) {
                    BottomNav(state, nav, onEvent)
                }
            }
            if (state.toast.isNotBlank() && !state.settingsOpen) {
                val toastBottom = when {
                    keyboard -> ime + 76.dp
                    else -> nav + 72.dp
                }
                Text(
                    state.toast,
                    color = Ink,
                    fontSize = 14.sp,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(start = 20.dp, end = 20.dp, bottom = toastBottom)
                        .background(Color(0xF210141C), RoundedCornerShape(16.dp))
                        .clickable { onEvent(SkyEvent.DismissToast) }
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                )
            }
            if (state.settingsOpen) SettingsPane(state, top, nav, onEvent)
            if (state.drawerOpen) Drawer(state, top, onEvent)
        }
    }
}

@Composable
private fun TopBar(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (state.tab == SkyTab.Chat) {
            SkyIcon("menu", Accent, Modifier.size(28.dp).clickable { onEvent(SkyEvent.OpenDrawer) })
            Spacer(Modifier.width(10.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(screenTitle(state), style = MaterialTheme.typography.titleLarge, maxLines = 1)
            if (state.training) {
                Text(skyText(state.lang, "consolidating"), color = Gold, fontSize = 12.sp)
            }
        }
        if (state.tab == SkyTab.Chat) {
            SkyIcon("plus", Accent, Modifier.size(28.dp).clickable { onEvent(SkyEvent.NewChat) })
            Spacer(Modifier.width(12.dp))
        }
        SkyIcon("gear", Accent, Modifier.size(28.dp).clickable { onEvent(SkyEvent.OpenSettings) })
    }
}

private fun screenTitle(state: SkyState): String {
    if (state.tab != SkyTab.Chat) return skyText(state.lang, tabKey(state.tab))
    val title = state.currentTitle.trim()
    if (title.isEmpty() || title == "新对话") return skyText(state.lang, "newChat")
    return title
}

private fun tabKey(tab: SkyTab): String = when (tab) {
    SkyTab.Chat -> "chat"
    SkyTab.Consolidate -> "consolidate"
    SkyTab.Nebula -> "nebula"
    SkyTab.Library -> "library"
}

@Composable
private fun BottomNav(state: SkyState, nav: Dp, onEvent: (SkyEvent) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(start = 8.dp, end = 8.dp, top = 4.dp, bottom = nav + 8.dp),
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        NavItem("chat", skyText(state.lang, "chat"), state.tab == SkyTab.Chat) { onEvent(SkyEvent.Tab(SkyTab.Chat)) }
        NavItem("nebula", skyText(state.lang, "nebula"), state.tab == SkyTab.Nebula) { onEvent(SkyEvent.Tab(SkyTab.Nebula)) }
        NavItem("consolidate", skyText(state.lang, "consolidate"), state.tab == SkyTab.Consolidate) { onEvent(SkyEvent.Tab(SkyTab.Consolidate)) }
        NavItem("library", skyText(state.lang, "library"), state.tab == SkyTab.Library) { onEvent(SkyEvent.Tab(SkyTab.Library)) }
    }
}

@Composable
private fun NavItem(icon: String, label: String, on: Boolean, click: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.clickable(onClick = click).padding(horizontal = 8.dp, vertical = 4.dp)) {
        SkyIcon(icon, if (on) Accent2 else Muted, Modifier.size(22.dp))
        Text(label, color = if (on) Accent2 else Muted, fontSize = 12.sp)
    }
}

@Composable
private fun Drawer(state: SkyState, top: Dp, onEvent: (SkyEvent) -> Unit) {
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color(0x88000000)).clickable { onEvent(SkyEvent.CloseDrawer) })
        Column(
            Modifier.fillMaxHeight().width(280.dp).background(Color(0xF010141C)).padding(top = top + 16.dp, start = 16.dp, end = 16.dp, bottom = 16.dp)
                .pointerInput(Unit) { detectTapGestures { } },
        ) {
            Text(skyText(state.lang, "conversations"), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(12.dp))
            if (state.conversations.isEmpty()) {
                Text(skyText(state.lang, "emptyConv"), color = Muted)
            }
            LazyColumn {
                items(state.conversations) { conversation ->
                    val title = conversation.title.ifBlank { skyText(state.lang, "newChat") }.let {
                        if (it == "新对话") skyText(state.lang, "newChat") else it
                    }
                    Text(
                        title,
                        color = Ink,
                        modifier = Modifier.fillMaxWidth().clickable { onEvent(SkyEvent.OpenConversation(conversation.id)) }.padding(vertical = 10.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun SettingsPane(state: SkyState, top: Dp, nav: Dp, onEvent: (SkyEvent) -> Unit) {
    var armed by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxSize().background(Night).verticalScroll(rememberScrollState())
            .padding(start = 16.dp, end = 16.dp, top = top + 12.dp, bottom = nav + 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(skyText(state.lang, "settings"), style = MaterialTheme.typography.titleLarge)
            SkyIcon("close", Accent, Modifier.size(28.dp).clickable { onEvent(SkyEvent.CloseSettings) })
        }
        Text(skyText(state.lang, "backend"), color = Muted)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ModeChip(skyText(state.lang, "backendAuto"), state.backendMode == "auto") { onEvent(SkyEvent.BackendMode("auto")) }
            ModeChip(skyText(state.lang, "backendGpu"), state.backendMode == "gpu") { onEvent(SkyEvent.BackendMode("gpu")) }
            ModeChip(skyText(state.lang, "backendCpu"), state.backendMode == "cpu") { onEvent(SkyEvent.BackendMode("cpu")) }
        }
        if (state.backendLine.isNotBlank()) Text(state.backendLine, color = Ink)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skyText(state.lang, "wifi"), color = Ink, modifier = Modifier.weight(1f))
            Switch(checked = state.wifiOnly, onCheckedChange = { onEvent(SkyEvent.WifiOnly(it)) })
        }
        OutlinedTextField(
            value = state.manifestUrl,
            onValueChange = { onEvent(SkyEvent.ManifestUrl(it)) },
            label = { Text(skyText(state.lang, "manifest")) },
            modifier = Modifier.fillMaxWidth(),
        )
        Text(skyText(state.lang, "useUrl"), color = Gold, modifier = Modifier.clickable { onEvent(SkyEvent.ApplyManifest) })
        Text(skyText(state.lang, "language"), color = Muted)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ModeChip("中文", state.lang == "zh") { onEvent(SkyEvent.Lang("zh")) }
            ModeChip("EN", state.lang == "en") { onEvent(SkyEvent.Lang("en")) }
        }
        Text(skyText(state.lang, "exportDiag"), color = Gold, modifier = Modifier.clickable { onEvent(SkyEvent.ExportDiagnostics) }.padding(vertical = 4.dp))
        Text("${skyText(state.lang, "storage")} · ${state.storageLabel}", color = Ink)
        Text(
            if (armed) skyText(state.lang, "clearConfirm") else skyText(state.lang, "clearModels"),
            color = Gold,
            modifier = Modifier.clickable {
                if (armed) onEvent(SkyEvent.ClearModels) else armed = true
            },
        )
        Text("${skyText(state.lang, "about")} · ${skyText(state.lang, "appName")} ${state.versionName}", color = Muted)
    }
}

@Composable
private fun ModeChip(label: String, on: Boolean, click: () -> Unit) {
    Text(
        label,
        color = if (on) Night else Accent,
        modifier = Modifier.background(if (on) Accent else Color(0x33101828), RoundedCornerShape(12.dp)).clickable(onClick = click).padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Composable
internal fun rememberSerif(): ComposeFontFamily {
    val context = LocalContext.current
    return remember {
        val latin = Font.Builder(context.resources, R.font.eb_garamond).build()
        val cjk = Font.Builder(context.resources, R.font.noto_serif_sc).build()
        val face = Typeface.CustomFallbackBuilder(FontFamily.Builder(latin).build())
            .addCustomFallback(FontFamily.Builder(cjk).build())
            .build()
        ComposeFontFamily(Typeface.create(face, Typeface.NORMAL))
    }
}

@Composable
internal fun SkyIcon(kind: String, tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val w = size.width
        val h = size.height
        val sw = w * 0.08f
        when (kind) {
            "menu" -> {
                for (i in 0..2) {
                    val y = h * (0.28f + i * 0.22f)
                    drawLine(tint, Offset(w * 0.18f, y), Offset(w * 0.82f, y), sw, StrokeCap.Round)
                }
            }
            "gear" -> {
                drawCircle(tint, w * 0.16f, style = Stroke(sw))
                drawCircle(tint, w * 0.06f)
                for (i in 0 until 8) {
                    val a = i * (Math.PI / 4).toFloat()
                    drawCircle(tint, w * 0.055f, Offset(w / 2 + cos(a) * w * 0.34f, h / 2 + sin(a) * h * 0.34f))
                }
            }
            "plus" -> {
                drawLine(tint, Offset(w / 2, h * 0.22f), Offset(w / 2, h * 0.78f), sw, StrokeCap.Round)
                drawLine(tint, Offset(w * 0.22f, h / 2), Offset(w * 0.78f, h / 2), sw, StrokeCap.Round)
            }
            "send" -> {
                val path = Path().apply {
                    moveTo(w * 0.18f, h * 0.18f)
                    lineTo(w * 0.82f, h * 0.50f)
                    lineTo(w * 0.18f, h * 0.82f)
                    lineTo(w * 0.34f, h * 0.50f)
                    close()
                }
                drawPath(path, tint)
            }
            "close" -> {
                drawLine(tint, Offset(w * 0.28f, h * 0.28f), Offset(w * 0.72f, h * 0.72f), sw, StrokeCap.Round)
                drawLine(tint, Offset(w * 0.72f, h * 0.28f), Offset(w * 0.28f, h * 0.72f), sw, StrokeCap.Round)
            }
            "chat" -> {
                drawCircle(tint, w * 0.26f, Offset(w * 0.46f, h * 0.42f), style = Stroke(sw))
                drawLine(tint, Offset(w * 0.30f, h * 0.58f), Offset(w * 0.22f, h * 0.80f), sw, StrokeCap.Round)
            }
            "nebula" -> {
                drawCircle(tint, w * 0.20f, Offset(w * 0.40f, h * 0.54f), style = Stroke(sw))
                drawCircle(tint, w * 0.14f, Offset(w * 0.66f, h * 0.40f), style = Stroke(sw))
            }
            "consolidate" -> {
                val path = Path().apply {
                    moveTo(w * 0.18f, h * 0.52f)
                    lineTo(w * 0.40f, h * 0.74f)
                    lineTo(w * 0.82f, h * 0.28f)
                }
                drawPath(path, tint, style = Stroke(width = sw, cap = StrokeCap.Round))
            }
            "library" -> {
                drawLine(tint, Offset(w * 0.28f, h * 0.22f), Offset(w * 0.28f, h * 0.80f), sw, StrokeCap.Round)
                drawLine(tint, Offset(w * 0.28f, h * 0.22f), Offset(w * 0.74f, h * 0.22f), sw, StrokeCap.Round)
                drawLine(tint, Offset(w * 0.74f, h * 0.22f), Offset(w * 0.74f, h * 0.80f), sw, StrokeCap.Round)
                drawLine(tint, Offset(w * 0.28f, h * 0.80f), Offset(w * 0.74f, h * 0.80f), sw, StrokeCap.Round)
            }
        }
    }
}

@Composable
internal fun MilkyWay(paused: Boolean) {
    var phase by remember { mutableFloatStateOf(0.4f) }
    LaunchedEffect(paused) {
        if (paused) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(48)
            phase += 0.004f
        }
    }
    Canvas(Modifier.fillMaxSize()) {
        drawRect(Night)
        drawOval(
            Color(0x14201848),
            topLeft = Offset(-size.width * 0.1f, size.height * 0.18f),
            size = Size(size.width * 1.2f, size.height * 0.55f),
        )
        drawOval(
            Color(0x10104850),
            topLeft = Offset(size.width * 0.05f, size.height * 0.32f),
            size = Size(size.width * 0.9f, size.height * 0.36f),
        )
        val layers = intArrayOf(70, 130, 210)
        for (layer in layers.indices) {
            val count = layers[layer]
            val radius = if (layer == 0) 1.7f else if (layer == 1) 1.05f else 0.55f
            for (i in 0 until count) {
                val px = ((i * 97 + layer * 53) % 1000) / 1000f * size.width
                val py = ((i * 57 + layer * 91) % 1000) / 1000f * size.height
                val nx = (px / size.width) - 0.5f
                val ny = (py / size.height) - 0.5f
                val rot = -0.42f
                val band = nx * sin(rot) + ny * cos(rot)
                val density = exp(-(band * band) / 0.12f)
                val tw = (0.18f + 0.55f * density) * (0.55f + 0.45f * ((sin(phase * 2f + i + layer) + 1f) / 2f))
                val tint = if ((i + layer) % 5 == 0) Gold else Color.White
                drawCircle(tint.copy(alpha = tw.coerceIn(0.05f, 0.9f)), radius + if (density > 0.65f) 0.45f else 0f, Offset(px, py))
            }
        }
    }
}

@Composable
private fun ChatPane(state: SkyState, ime: Dp, onEvent: (SkyEvent) -> Unit) {
    val shown = state.messages + if (state.generating) {
        listOf(SkyMessage("assistant", state.streaming.ifBlank { "…" }))
    } else {
        emptyList()
    }
    val listState = rememberLazyListState()
    val ordered = shown.asReversed()
    LaunchedEffect(shown.size, state.streaming, ime) {
        if (ordered.isNotEmpty()) listState.scrollToItem(0)
    }
    Column(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState, reverseLayout = true) {
            items(ordered.size) { index ->
                Bubble(state.lang, ordered[index], state.generating && index == 0)
            }
        }
        OutlinedTextField(
            value = state.draft,
            onValueChange = { onEvent(SkyEvent.Draft(it)) },
            modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp),
            placeholder = { Text(skyText(state.lang, "placeholder"), color = Muted) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { onEvent(SkyEvent.Send) }),
            trailingIcon = {
                Box(Modifier.size(40.dp).clickable { onEvent(SkyEvent.Send) }, contentAlignment = Alignment.Center) {
                    SkyIcon("send", if (state.draft.isBlank()) Muted else Accent, Modifier.size(22.dp))
                }
            },
            maxLines = 4,
        )
        if (state.imeBottom > 0.dp) FakeKeyboard(state.imeBottom)
    }
}

@Composable
private fun Bubble(lang: String, message: SkyMessage, streaming: Boolean) {
    val user = message.role == "user"
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = if (user) Arrangement.End else Arrangement.Start) {
        Column(Modifier.widthIn(max = 300.dp)) {
            Text(
                message.text,
                color = Ink,
                modifier = Modifier
                    .background(if (user) Color(0x332A2418) else Color(0x33101828), RoundedCornerShape(16.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            )
            if (!user && !streaming) {
                val tag = if (!message.expert.isNullOrBlank()) skyText(lang, "memoryUsed") else skyText(lang, "memoryNone")
                Text(tag, color = Muted, fontSize = 13.sp, modifier = Modifier.padding(start = 12.dp, top = 8.dp))
                if (message.noticed) {
                    Text(skyText(lang, "noticed"), color = Gold, fontSize = 13.sp, modifier = Modifier.padding(start = 12.dp, top = 4.dp))
                }
            }
        }
    }
}

@Composable
private fun FakeKeyboard(height: Dp) {
    Column(
        Modifier.fillMaxWidth().height(height).padding(top = 8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        repeat(3) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                repeat(8) {
                    Box(Modifier.weight(1f).height(28.dp).background(Color(0xFF1C2230), RoundedCornerShape(6.dp)))
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(Modifier.weight(1f).height(28.dp).background(Color(0xFF1C2230), RoundedCornerShape(6.dp)))
            Box(Modifier.width(72.dp).height(28.dp).background(Accent, RoundedCornerShape(6.dp)))
        }
    }
}

private val stageIds = listOf("select", "extract", "gate", "build", "train", "recall", "register", "done")

internal fun stageStates(training: Boolean, hasFact: Boolean): List<String> {
    val active = when {
        training -> "train"
        hasFact -> "gate"
        else -> "select"
    }
    val at = stageIds.indexOf(active)
    return stageIds.mapIndexed { index, _ ->
        when {
            index < at -> "done"
            index == at -> "active"
            else -> "pending"
        }
    }
}

@Composable
private fun ConsolidatePane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        StageTimeline(state)
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            if (state.statement.isBlank() && state.entity.isBlank()) {
                Text(skyText(state.lang, "stage.pending"), color = Muted, fontSize = 14.sp, modifier = Modifier.padding(vertical = 12.dp))
            } else {
                FactCard(state, onEvent)
            }
            if (state.loss.isNotEmpty() || state.training) {
                Spacer(Modifier.height(12.dp))
                Constellation(state.loss, state.training)
                Text(
                    "${skyText(state.lang, "loss")} · ${state.loss.size} ${skyText(state.lang, "steps")}",
                    color = Muted,
                    fontSize = 13.sp,
                )
            }
            if (state.status.isNotEmpty()) {
                Text(state.status, color = Ink, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
            }
        }
    }
}

@Composable
private fun StageTimeline(state: SkyState) {
    val states = stageStates(state.training, state.entity.isNotBlank() || state.statement.isNotBlank())
    Column(Modifier.fillMaxWidth()) {
        Canvas(Modifier.fillMaxWidth().height(52.dp)) {
            val step = size.width / stageIds.size
            val y = 26.dp.toPx()
            for (index in 1 until stageIds.size) {
                val lit = states[index] != "pending" || states[index - 1] == "done"
                drawLine(
                    if (lit) Gold.copy(alpha = 0.85f) else Color(0x47B4C6DC),
                    Offset(step * (index - 0.5f), y),
                    Offset(step * (index + 0.5f), y),
                    if (lit) 2.4f else 1.4f,
                )
            }
            stageIds.indices.forEach { index ->
                val mark = states[index]
                val on = mark != "pending"
                val radius = if (mark == "active") 7f else if (on) 5.2f else 3.6f
                val fill = if (mark == "active") Gold else if (on) Color(0xFFD7E6FF) else Color(0x73B4C6DC)
                val center = Offset(step * (index + 0.5f), y)
                drawCircle(fill.copy(alpha = if (on) 0.22f else 0.08f), radius + 9f, center)
                drawCircle(fill, radius, center)
            }
        }
        Row(Modifier.fillMaxWidth()) {
            stageIds.forEachIndexed { index, id ->
                val mark = states[index]
                Text(
                    skyText(state.lang, "stage.$id"),
                    color = if (mark == "active") Gold else if (mark == "done") Ink else Muted,
                    fontSize = 13.sp,
                    lineHeight = 15.sp,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun FactCard(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(top = 8.dp)
            .height(IntrinsicSize.Min)
            .background(Color(0x6B080C16), RoundedCornerShape(16.dp))
            .border(1.dp, Color(0x2EC6D6EE), RoundedCornerShape(16.dp)),
    ) {
        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
            Box(Modifier.width(2.dp).fillMaxHeight().background(Gold.copy(alpha = 0.7f)))
            Column(Modifier.weight(1f).padding(horizontal = 14.dp, vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(skyText(state.lang, "factWrite"), color = Gold, fontSize = 13.sp)
                BasicTextField(
                    value = state.statement,
                    onValueChange = { onEvent(SkyEvent.Field("statement", it)) },
                    textStyle = TextStyle(color = Ink, fontSize = 18.sp),
                    modifier = Modifier.fillMaxWidth(),
                )
                FactLine(skyText(state.lang, "entity"), state.entity) { onEvent(SkyEvent.Field("entity", it)) }
                FactLine(skyText(state.lang, "value"), state.value) { onEvent(SkyEvent.Field("value", it)) }
                FactLine(skyText(state.lang, "question"), state.question) { onEvent(SkyEvent.Field("question", it)) }
                FactLine(skyText(state.lang, "answer"), state.answer) { onEvent(SkyEvent.Field("answer", it)) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = state.force, onCheckedChange = { onEvent(SkyEvent.Force(it)) })
                    Text(skyText(state.lang, "force"), color = Muted, fontSize = 14.sp)
                }
                Row {
                    Text(skyText(state.lang, "train"), color = Accent2, fontSize = 15.sp, modifier = Modifier.clickable { onEvent(SkyEvent.Train) }.padding(vertical = 8.dp, horizontal = 4.dp))
                    Text(skyText(state.lang, "cancel"), color = Muted, fontSize = 15.sp, modifier = Modifier.clickable { onEvent(SkyEvent.CancelTrain) }.padding(8.dp))
                }
            }
        }
    }
}

@Composable
private fun FactLine(label: String, value: String, onChange: (String) -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text(label, color = Muted, fontSize = 13.sp)
        BasicTextField(
            value = value,
            onValueChange = onChange,
            textStyle = TextStyle(color = Ink, fontSize = 16.sp),
            modifier = Modifier.fillMaxWidth().padding(top = 2.dp),
        )
    }
}

@Composable
private fun Constellation(loss: List<Float>, training: Boolean) {
    Canvas(Modifier.fillMaxWidth().height(160.dp)) {
        val n = maxOf(loss.size, 6)
        val pts = ArrayList<Offset>()
        for (i in 0 until n) {
            val t = i / (n - 1f)
            val x = 24f + t * (size.width - 48f)
            val y = size.height * 0.55f + sin(t * 6f) * 28f - if (i < loss.size) 10f else 0f
            pts.add(Offset(x, y))
        }
        for (i in 1 until pts.size) {
            drawLine(Accent.copy(alpha = 0.35f), pts[i - 1], pts[i], strokeWidth = 1.5f)
        }
        pts.forEachIndexed { i, p ->
            val done = i < loss.size
            drawCircle(if (done) Gold else Accent.copy(alpha = 0.45f), if (done) 5f else 3f, p)
        }
        if (loss.size >= 2) {
            val minL = loss.min()
            val maxL = loss.max().coerceAtLeast(minL + 1e-3f)
            val path = Path()
            loss.forEachIndexed { i, value ->
                val x = 24f + i / (loss.size - 1f) * (size.width - 48f)
                val y = size.height * 0.9f - ((value - minL) / (maxL - minL)) * size.height * 0.48f
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            drawPath(path, Accent2, style = Stroke(width = 3f))
        }
        if (training) {
            drawCircle(Gold.copy(alpha = 0.15f), 18f, pts[loss.size.coerceAtMost(pts.lastIndex)])
        }
    }
}

@Composable
private fun NebulaFallback(state: SkyState) {
    if (state.experts.isEmpty()) {
        Text(skyText(state.lang, "emptyNebula"), color = Muted)
        return
    }
    Box(Modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            state.experts.forEachIndexed { index, expert ->
                val cx = size.width * (0.28f + (index % 2) * 0.44f)
                val cy = size.height * (0.28f + (index / 2) * 0.34f)
                val hot = expert.name == state.highlightExpert
                drawCircle(if (hot) Accent2.copy(alpha = 0.16f) else Accent.copy(alpha = 0.08f), 86f, Offset(cx, cy))
                drawCircle(if (hot) Gold.copy(alpha = 0.10f) else Color(0x18C4A060), 46f, Offset(cx, cy))
                expert.facts.forEachIndexed { factIndex, _ ->
                    val ang = factIndex * 0.9f + index
                    val r = 36f + (factIndex % 5) * 14f
                    drawCircle(if (hot) Gold else Gold.copy(alpha = 0.75f), if (hot) 3.2f else 2.1f, Offset(cx + cos(ang) * r, cy + sin(ang) * r * 0.72f))
                }
            }
        }
        if (state.recallBanner.isNotBlank()) {
            Text(state.recallBanner, color = Gold, modifier = Modifier.align(Alignment.TopStart).padding(8.dp))
        }
        Column(Modifier.align(Alignment.BottomStart).padding(8.dp)) {
            state.experts.forEach { expert ->
                val hot = expert.name == state.highlightExpert
                Text(expert.label.ifBlank { skyText(state.lang, "library") }, color = if (hot) Gold else Ink, fontSize = 16.sp)
            }
        }
    }
}

@Composable
private fun LibraryPane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(skyText(state.lang, "import"), color = Accent, modifier = Modifier.clickable { onEvent(SkyEvent.ImportExperts) })
            Text(skyText(state.lang, "selfCheck"), color = Accent2, modifier = Modifier.clickable { onEvent(SkyEvent.SelfCheck) })
        }
        if (state.note.isNotEmpty()) {
            Text(state.note, color = Muted, fontSize = 14.sp, modifier = Modifier.padding(vertical = 8.dp))
        }
        LazyColumn(Modifier.weight(1f)) {
            items(state.experts) { expert ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Column(Modifier.weight(1f)) {
                        Text(expert.label.ifBlank { skyText(state.lang, "library") }, color = Ink)
                        Text(expert.facts.take(2).joinToString(" · "), color = Muted)
                    }
                    Text(skyText(state.lang, "delete"), color = Gold, modifier = Modifier.clickable { onEvent(SkyEvent.DeleteExpert(expert.name)) })
                }
            }
        }
    }
}
