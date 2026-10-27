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
import androidx.compose.foundation.layout.BoxWithConstraints
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.zIndex
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.editableText
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setText
import androidx.compose.ui.semantics.testTag
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.text.AnnotatedString
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
internal val Glass = Color(0xC010141C)
internal val GlassLine = Color(0x33C6D6EE)
private val Pill = RoundedCornerShape(999.dp)

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
    val updatePhase: String = "",
    val updateVersion: String = "",
    val updateNotes: String = "",
    val updateMessage: String = "",
    val waitSeconds: Int = 0,
    val liveMotion: Boolean = false,
    val train: TrainSnapshot = TrainSnapshot(),
    val pendingFacts: List<String> = emptyList(),
    val nebulaCanvas: Boolean = false,
    val e2e: Boolean = false,
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
    data object CheckUpdate : SkyEvent()
    data object StartUpdate : SkyEvent()
    data object DismissUpdate : SkyEvent()
    data class NebulaGl(val fallback: String) : SkyEvent()
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
        "chatHint" to "把想记住的话，说给这片星空",
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
        "nativeCrash" to "图形后端异常过，已改用 CPU。设置里改成自动可再试 GPU。",
        "gpuTimeout" to "GPU 自检超时，已改用 CPU。",
        "usingCpu" to "正在使用 CPU。",
        "usingGpu" to "已强制使用 GPU。",
        "checkingGpu" to "正在检测图形后端。",
        "consolidating" to "巩固中",
        "appName" to "长期记忆",
        "stage.select" to "选择对话",
        "stage.extract" to "抽取事实",
        "stage.gate" to "写闸门",
        "stage.build" to "生成样本",
        "stage.train" to "训练 LoRA",
        "stage.recall" to "回忆检查",
        "stage.register" to "注册专家",
        "stage.done" to "完成",
        "stage.pending" to "说出一条事实后，会显示在这里",
        "factWrite" to "写入这条事实",
        "checkUpdate" to "检查更新",
        "updateReady" to "可以更新",
        "updateDownload" to "下载并安装",
        "updateLatest" to "已是最新版本",
        "updatePermission" to "请允许本应用安装未知来源应用，只需这一次。打开开关后回到这里再点下载并安装。",
        "updateInstalling" to "请在系统界面确认安装。模型和对话会保留。",
        "pendingHead" to "待巩固",
        "advanced" to "高级",
        "nebulaFallback" to "这台手机绘不出完整星云，已改用兼容画面。",
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
        "chatHint" to "Tell this sky what you want to keep",
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
        "nativeCrash" to "The graphics backend failed and CPU is in use. Set Auto to try the GPU again.",
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
        "checkUpdate" to "Check for updates",
        "updateReady" to "Update available",
        "updateDownload" to "Download and install",
        "updateLatest" to "Already up to date",
        "updatePermission" to "Allow this app to install unknown apps, just once. Turn the switch on, come back, and tap download and install.",
        "updateInstalling" to "Confirm the install. Models and chats stay.",
        "pendingHead" to "Waiting to consolidate",
        "advanced" to "Advanced",
        "nebulaFallback" to "This phone can't draw the full nebula, so a compatible view is on.",
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
            bodyLarge = TextStyle(fontFamily = serif, fontSize = 16.sp, lineHeight = 24.sp, color = Ink),
            bodyMedium = TextStyle(fontFamily = serif, fontSize = 14.sp, lineHeight = 20.sp, color = Ink),
            titleLarge = TextStyle(fontFamily = serif, fontSize = 28.sp, lineHeight = 34.sp, letterSpacing = 0.6.sp, color = Ink),
            labelLarge = TextStyle(fontFamily = serif, fontSize = 13.sp, letterSpacing = 0.4.sp, color = Gold),
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
            MilkyWay(paused = state.training || nebulaLive)
            if (nebulaLive) {
                val nebulaMod = Modifier
                    .fillMaxSize()
                    .padding(top = top + 56.dp, bottom = if (keyboard) ime else nav + 64.dp)
                    .clipToBounds()
                if (state.nebulaCanvas) {
                    NebulaCanvas(
                        json = state.nebulaJson,
                        lang = state.lang,
                        animate = state.liveMotion && !state.training,
                        modifier = nebulaMod,
                    )
                } else {
                    NebulaHost(
                        json = state.nebulaJson,
                        recallJson = state.recallJson,
                        training = state.training,
                        lang = state.lang,
                        modifier = nebulaMod,
                        onOpenConversation = { onEvent(SkyEvent.OpenConversation(it)) },
                        onGl = { onEvent(SkyEvent.NebulaGl(it)) },
                    )
                }
            }
            if (nebulaLive && !state.settingsOpen) {
                TopBar(
                    state,
                    onEvent,
                    Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth()
                        .zIndex(1f)
                        .background(Brush.verticalGradient(listOf(Color(0xE6070910), Color(0x00070910))))
                        .padding(top = top),
                )
                if (!keyboard) {
                    Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().zIndex(1f)) {
                        BottomNav(state, nav, onEvent)
                    }
                }
            }
            if (!nebulaLive) {
                Column(Modifier.fillMaxSize().padding(top = top + 8.dp)) {
                    if (!state.settingsOpen) TopBar(state, onEvent)
                    Box(Modifier.weight(1f).fillMaxWidth()) {
                        if (!state.settingsOpen) {
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
            }
            if (state.updatePhase.isNotBlank() && state.updatePhase != "latest") {
                UpdateCard(state, onEvent, Modifier.align(Alignment.BottomCenter).padding(start = 16.dp, end = 16.dp, bottom = nav + 76.dp))
            }
            if (state.toast.isNotBlank() && !state.settingsOpen && state.updatePhase.isBlank()) {
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
            if (state.settingsOpen) Box(Modifier.fillMaxSize().zIndex(3f)) { SettingsPane(state, top, nav, onEvent) }
            if (state.drawerOpen) Box(Modifier.fillMaxSize().zIndex(3f)) { Drawer(state, top, onEvent) }
        }
    }
}

@Composable
private fun TopBar(state: SkyState, onEvent: (SkyEvent) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (state.tab == SkyTab.Chat) {
            SkyIcon("menu", Accent, Modifier.size(26.dp).clickable { onEvent(SkyEvent.OpenDrawer) })
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(screenTitle(state), style = MaterialTheme.typography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (state.training) {
                Text(
                    skyText(state.lang, "consolidating"),
                    color = Gold,
                    fontSize = 12.sp,
                    letterSpacing = 0.4.sp,
                    modifier = Modifier
                        .padding(top = 4.dp)
                        .background(Gold.copy(alpha = 0.14f), Pill)
                        .border(1.dp, Gold.copy(alpha = 0.45f), Pill)
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
        }
        if (state.tab == SkyTab.Chat) {
            Box(
                Modifier
                    .size(36.dp)
                    .border(1.dp, Accent.copy(alpha = 0.45f), CircleShape)
                    .semantics { contentDescription = "newChat" }
                    .clickable { onEvent(SkyEvent.NewChat) },
                contentAlignment = Alignment.Center,
            ) {
                SkyIcon("plus", Accent, Modifier.size(16.dp))
            }
            Spacer(Modifier.width(10.dp))
        }
        Box(
            Modifier
                .size(36.dp)
                .border(1.dp, Accent.copy(alpha = 0.55f), CircleShape)
                .semantics { contentDescription = "settings" }
                .clickable { onEvent(SkyEvent.OpenSettings) },
            contentAlignment = Alignment.Center,
        ) {
            SkyIcon("gear", Accent, Modifier.size(16.dp))
        }
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
        Modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(Color(0x00070910), Color(0xE6070910))))
            .padding(start = 8.dp, end = 8.dp, top = 14.dp, bottom = nav + 8.dp),
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
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .semantics { contentDescription = "tab-$icon" }
            .background(if (on) Accent2.copy(alpha = 0.12f) else Color.Transparent, RoundedCornerShape(16.dp))
            .clickable(onClick = click)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        SkyIcon(icon, if (on) Accent2 else Muted, Modifier.size(22.dp))
        Text(label, color = if (on) Accent2 else Muted, fontSize = 12.sp, letterSpacing = 0.6.sp)
        Box(
            Modifier
                .padding(top = 3.dp)
                .size(width = 14.dp, height = 2.dp)
                .background(if (on) Gold else Color.Transparent, Pill),
        )
    }
}

@Composable
private fun Drawer(state: SkyState, top: Dp, onEvent: (SkyEvent) -> Unit) {
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color(0x99070910)).clickable { onEvent(SkyEvent.CloseDrawer) })
        Column(
            Modifier
                .fillMaxHeight()
                .width(300.dp)
                .background(Color(0xF2070910))
                .border(1.dp, GlassLine)
                .padding(top = top + 20.dp, start = 20.dp, end = 16.dp, bottom = 16.dp)
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
        Modifier.fillMaxSize().background(Night.copy(alpha = 0.82f)).verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, top = top + 16.dp, bottom = nav + 28.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(skyText(state.lang, "settings"), style = MaterialTheme.typography.titleLarge)
            SkyIcon("close", Accent, Modifier.size(28.dp).clickable { onEvent(SkyEvent.CloseSettings) })
        }
        Text(skyText(state.lang, "backend"), style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ModeChip(skyText(state.lang, "backendAuto"), state.backendMode == "auto") { onEvent(SkyEvent.BackendMode("auto")) }
            ModeChip(skyText(state.lang, "backendGpu"), state.backendMode == "gpu") { onEvent(SkyEvent.BackendMode("gpu")) }
            ModeChip(skyText(state.lang, "backendCpu"), state.backendMode == "cpu") { onEvent(SkyEvent.BackendMode("cpu")) }
        }
        if (state.backendLine.isNotBlank()) {
            Text(
                state.backendLine,
                color = Ink,
                fontSize = 14.sp,
                lineHeight = 20.sp,
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Glass, RoundedCornerShape(14.dp))
                    .border(1.dp, GlassLine, RoundedCornerShape(14.dp))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skyText(state.lang, "wifi"), color = Ink, modifier = Modifier.weight(1f))
            Switch(
                checked = state.wifiOnly,
                onCheckedChange = { onEvent(SkyEvent.WifiOnly(it)) },
                colors = SwitchDefaults.colors(
                    checkedTrackColor = Accent2.copy(alpha = 0.55f),
                    checkedThumbColor = Accent2,
                    uncheckedTrackColor = Color(0xFF1C2432),
                    uncheckedThumbColor = Muted,
                ),
            )
        }
        OutlinedTextField(
            value = state.manifestUrl,
            onValueChange = { onEvent(SkyEvent.ManifestUrl(it)) },
            label = { Text(skyText(state.lang, "manifest")) },
            modifier = Modifier.fillMaxWidth(),
        )
        Text(skyText(state.lang, "useUrl"), color = Gold, modifier = Modifier.clickable { onEvent(SkyEvent.ApplyManifest) })
        Text(skyText(state.lang, "language"), style = MaterialTheme.typography.labelLarge)
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
        Text(
            skyText(state.lang, "checkUpdate"),
            color = Gold,
            fontSize = 16.sp,
            modifier = Modifier.clickable { onEvent(SkyEvent.CheckUpdate) }.padding(vertical = 6.dp),
        )
        if (state.updatePhase == "latest") {
            Text(skyText(state.lang, "updateLatest"), color = Ink, fontSize = 14.sp)
        }
        if (state.updatePhase.isNotBlank() && state.updatePhase != "latest") {
            Text(state.updateMessage.ifBlank { skyText(state.lang, "updateReady") }, color = Ink, fontSize = 14.sp)
        }
        if (state.updatePhase == "available" || state.updatePhase == "need_permission" || state.updatePhase == "error") {
            Text(
                skyText(state.lang, "updateDownload"),
                color = Accent2,
                fontSize = 16.sp,
                modifier = Modifier.clickable { onEvent(SkyEvent.StartUpdate) }.padding(vertical = 4.dp),
            )
        }
        Text(skyText(state.lang, "advanced"), style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 8.dp))
        Text(skyText(state.lang, "import"), color = Accent, modifier = Modifier.clickable { onEvent(SkyEvent.ImportExperts) })
        Text(skyText(state.lang, "selfCheck"), color = Accent2, modifier = Modifier.clickable { onEvent(SkyEvent.SelfCheck) })
        if (state.note.isNotEmpty()) {
            Text(state.note, color = Ink, fontSize = 14.sp)
        }
    }
}

@Composable
private fun UpdateCard(state: SkyState, onEvent: (SkyEvent) -> Unit, modifier: Modifier) {
    Column(
        modifier
            .fillMaxWidth()
            .background(Color(0xF210141C), RoundedCornerShape(18.dp))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${skyText(state.lang, "updateReady")} ${state.updateVersion}".trim(),
                color = Gold,
                fontSize = 16.sp,
            )
            SkyIcon("close", Accent, Modifier.size(24.dp).clickable { onEvent(SkyEvent.DismissUpdate) })
        }
        if (state.updateNotes.isNotBlank()) {
            Text(
                state.updateNotes,
                color = Ink,
                fontSize = 14.sp,
                modifier = Modifier.heightIn(max = 160.dp).verticalScroll(rememberScrollState()),
            )
        }
        if (state.updateMessage.isNotBlank()) {
            Text(state.updateMessage, color = Ink, fontSize = 14.sp)
        }
        val action = when (state.updatePhase) {
            "need_permission" -> skyText(state.lang, "updatePermission")
            "installing" -> skyText(state.lang, "updateInstalling")
            else -> ""
        }
        if (action.isNotBlank() && state.updateMessage.isBlank()) {
            Text(action, color = Ink, fontSize = 14.sp)
        }
        if (state.updatePhase == "available" || state.updatePhase == "need_permission" || state.updatePhase == "error") {
            Text(
                skyText(state.lang, "updateDownload"),
                color = Accent2,
                fontSize = 16.sp,
                modifier = Modifier.clickable { onEvent(SkyEvent.StartUpdate) }.padding(vertical = 4.dp),
            )
        }
    }
}

@Composable
private fun ModeChip(label: String, on: Boolean, click: () -> Unit) {
    Text(
        label,
        color = if (on) Night else Ink,
        fontSize = 14.sp,
        modifier = Modifier
            .background(if (on) Gold else Color(0x6610141C), Pill)
            .border(1.dp, if (on) Gold else GlassLine, Pill)
            .clickable(onClick = click)
            .padding(horizontal = 14.dp, vertical = 7.dp),
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
                val left = w * 0.10f
                val top = h * 0.16f
                val right = w * 0.90f
                val bottom = h * 0.60f
                val bubble = Path().apply {
                    addRoundRect(
                        RoundRect(left, top, right, bottom, CornerRadius(w * 0.07f, h * 0.07f)),
                    )
                }
                drawPath(bubble, tint, style = Stroke(width = sw, cap = StrokeCap.Round, join = StrokeJoin.Round))
                val tail = Path().apply {
                    moveTo(w * 0.26f, bottom - 1f)
                    lineTo(w * 0.18f, h * 0.90f)
                    lineTo(w * 0.48f, bottom - 1f)
                    close()
                }
                drawPath(tail, tint)
                val y1 = top + (bottom - top) * 0.38f
                val y2 = top + (bottom - top) * 0.64f
                drawLine(tint, Offset(left + w * 0.12f, y1), Offset(right - w * 0.12f, y1), sw * 0.65f, StrokeCap.Round)
                drawLine(tint, Offset(left + w * 0.12f, y2), Offset(right - w * 0.30f, y2), sw * 0.65f, StrokeCap.Round)
            }
            "nebula" -> {
                drawCircle(tint, w * 0.18f, Offset(w * 0.38f, h * 0.56f), style = Stroke(sw))
                drawCircle(tint, w * 0.12f, Offset(w * 0.66f, h * 0.40f), style = Stroke(sw))
                drawCircle(tint, w * 0.045f, Offset(w * 0.66f, h * 0.40f))
            }
            "consolidate" -> {
                drawCircle(tint, w * 0.32f, style = Stroke(sw))
                val path = Path().apply {
                    moveTo(w * 0.32f, h * 0.52f)
                    lineTo(w * 0.46f, h * 0.66f)
                    lineTo(w * 0.72f, h * 0.38f)
                }
                drawPath(path, tint, style = Stroke(width = sw, cap = StrokeCap.Round, join = StrokeJoin.Round))
            }
            "library" -> {
                val left = Path().apply {
                    moveTo(w * 0.50f, h * 0.22f)
                    lineTo(w * 0.16f, h * 0.32f)
                    lineTo(w * 0.16f, h * 0.78f)
                    lineTo(w * 0.50f, h * 0.66f)
                    close()
                }
                val right = Path().apply {
                    moveTo(w * 0.50f, h * 0.22f)
                    lineTo(w * 0.84f, h * 0.32f)
                    lineTo(w * 0.84f, h * 0.78f)
                    lineTo(w * 0.50f, h * 0.66f)
                    close()
                }
                drawPath(left, tint, style = Stroke(width = sw, cap = StrokeCap.Round, join = StrokeJoin.Round))
                drawPath(right, tint, style = Stroke(width = sw, cap = StrokeCap.Round, join = StrokeJoin.Round))
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
        drawRect(
            Brush.verticalGradient(
                listOf(Color(0xFF10182C), Night, Color(0xFF0A0C16), Night),
            ),
        )
        drawCircle(
            Brush.radialGradient(
                listOf(Color(0x66402868), Color(0x22182040), Color.Transparent),
                center = Offset(size.width * 0.48f, size.height * 0.40f),
                radius = size.width * 0.85f,
            ),
            radius = size.maxDimension,
            center = Offset(size.width * 0.5f, size.height * 0.42f),
        )
        drawOval(
            Brush.radialGradient(
                listOf(Color(0x66B48A58), Color(0x33402820), Color.Transparent),
                center = Offset(size.width * 0.42f, size.height * 0.36f),
                radius = size.width * 0.72f,
            ),
            topLeft = Offset(-size.width * 0.2f, size.height * 0.12f),
            size = Size(size.width * 1.45f, size.height * 0.38f),
        )
        drawOval(
            Brush.radialGradient(
                listOf(Color(0x557EF0E0), Color(0x22184858), Color.Transparent),
                center = Offset(size.width * 0.70f, size.height * 0.46f),
                radius = size.width * 0.42f,
            ),
            topLeft = Offset(size.width * 0.32f, size.height * 0.30f),
            size = Size(size.width * 0.72f, size.height * 0.28f),
        )
        drawOval(
            Brush.radialGradient(
                listOf(Color(0x44E07068), Color(0x22181020), Color.Transparent),
                center = Offset(size.width * 0.28f, size.height * 0.50f),
                radius = size.width * 0.36f,
            ),
            topLeft = Offset(-size.width * 0.05f, size.height * 0.34f),
            size = Size(size.width * 0.55f, size.height * 0.26f),
        )
        drawCircle(
            Brush.radialGradient(
                listOf(Color(0x44F2D291), Color.Transparent),
                center = Offset(size.width * 0.52f, size.height * 0.38f),
                radius = size.width * 0.22f,
            ),
            radius = size.width * 0.28f,
            center = Offset(size.width * 0.52f, size.height * 0.38f),
        )
        val layers = intArrayOf(90, 160, 240)
        for (layer in layers.indices) {
            val count = layers[layer]
            val radius = if (layer == 0) size.minDimension * 0.0032f else if (layer == 1) size.minDimension * 0.0018f else size.minDimension * 0.001f
            for (i in 0 until count) {
                val px = ((i * 97 + layer * 53) % 1000) / 1000f * size.width
                val py = ((i * 57 + layer * 91) % 1000) / 1000f * size.height
                val nx = (px / size.width) - 0.5f
                val ny = (py / size.height) - 0.5f
                val rot = -0.42f
                val band = nx * sin(rot) + ny * cos(rot)
                val density = exp(-(band * band) / 0.045f)
                val tw = (0.16f + 0.7f * density) * (0.55f + 0.45f * ((sin(phase * 2f + i + layer) + 1f) / 2f))
                val warm = (i + layer) % 7 == 0
                val cool = (i + layer) % 11 == 0
                val tint = when {
                    warm -> Gold
                    cool -> Accent2
                    else -> Color.White
                }
                val center = Offset(px, py)
                if (density > 0.55f || layer == 0 && i % 4 == 0) {
                    drawCircle(tint.copy(alpha = (tw * 0.28f).coerceIn(0.04f, 0.35f)), radius * 5.5f, center)
                }
                drawCircle(tint.copy(alpha = tw.coerceIn(0.08f, 0.95f)), radius + if (density > 0.7f) radius else 0f, center)
            }
        }
        val heroes = arrayOf(
            0.16f to 0.18f,
            0.78f to 0.14f,
            0.86f to 0.62f,
            0.22f to 0.72f,
            0.58f to 0.84f,
            0.48f to 0.30f,
        )
        heroes.forEachIndexed { index, (fx, fy) ->
            val center = Offset(size.width * fx, size.height * fy)
            val glow = if (index % 2 == 0) Gold else Color(0xFFD7E6FF)
            val halo = size.minDimension * 0.02f
            drawCircle(glow.copy(alpha = 0.20f), halo, center)
            drawCircle(Color.White.copy(alpha = 0.95f), halo * 0.12f, center)
            val arm = halo * 0.85f
            drawLine(glow.copy(alpha = 0.55f), center - Offset(arm, 0f), center + Offset(arm, 0f), halo * 0.06f)
            drawLine(glow.copy(alpha = 0.40f), center - Offset(0f, arm), center + Offset(0f, arm), halo * 0.05f)
        }
    }
}

@Composable
@OptIn(ExperimentalComposeUiApi::class)
private fun ChatPane(state: SkyState, ime: Dp, onEvent: (SkyEvent) -> Unit) {
    val shown = state.messages + if (state.generating) {
        listOf(SkyMessage("assistant", state.streaming))
    } else {
        emptyList()
    }
    val listState = rememberLazyListState()
    val ordered = shown.asReversed()
    LaunchedEffect(shown.size, state.streaming, ime) {
        if (ordered.isNotEmpty()) listState.scrollToItem(0)
    }
    Column(Modifier.fillMaxSize().imePadding()) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (shown.isEmpty()) {
                Column(
                    Modifier.align(Alignment.Center).padding(horizontal = 28.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(skyText(state.lang, "appName"), style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
                    Spacer(Modifier.height(8.dp))
                    Text(
                        skyText(state.lang, "chatHint"),
                        color = Muted,
                        fontSize = 15.sp,
                        lineHeight = 22.sp,
                        textAlign = TextAlign.Center,
                    )
                }
            }
            LazyColumn(Modifier.fillMaxSize(), state = listState, reverseLayout = true) {
                items(ordered.size) { index ->
                    val live = state.generating && index == 0
                    Bubble(state.lang, ordered[index], live, if (live) state.waitSeconds else 0, state.liveMotion)
                }
            }
        }
        // 语义放在输入框外面。交给 OutlinedTextField 的 modifier 会被装饰层盖住，
        // 无障碍树里只剩一个没有 EditableText 的 View，真输入法和 UiAutomator 都打不进去。
        Box(
            Modifier.fillMaxWidth().semantics {
                testTagsAsResourceId = true
                testTag = "composer"
                contentDescription = "composer"
                editableText = AnnotatedString(state.draft)
                setText { updated ->
                    onEvent(SkyEvent.Draft(updated.text))
                    true
                }
            },
        ) {
            OutlinedTextField(
                value = state.draft,
                onValueChange = { onEvent(SkyEvent.Draft(it)) },
                modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
                placeholder = { Text(skyText(state.lang, "placeholder"), color = Muted) },
                textStyle = MaterialTheme.typography.bodyLarge,
                shape = RoundedCornerShape(22.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = Ink,
                    unfocusedTextColor = Ink,
                    focusedBorderColor = Gold.copy(alpha = 0.7f),
                    unfocusedBorderColor = GlassLine,
                    focusedContainerColor = Color(0xCC10141C),
                    unfocusedContainerColor = Color(0xB310141C),
                    cursorColor = Gold,
                    focusedPlaceholderColor = Muted,
                    unfocusedPlaceholderColor = Muted,
                ),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onEvent(SkyEvent.Send) }),
                trailingIcon = {
                    Box(
                        Modifier
                            .padding(end = 4.dp)
                            .size(36.dp)
                            .background(if (state.draft.isBlank()) Color.Transparent else Gold.copy(alpha = 0.16f), CircleShape)
                            .semantics { contentDescription = "send" }
                            .clickable { onEvent(SkyEvent.Send) },
                        contentAlignment = Alignment.Center,
                    ) {
                        SkyIcon("send", if (state.draft.isBlank()) Muted else Gold, Modifier.size(18.dp))
                    }
                },
                maxLines = 4,
            )
        }
        if (state.imeBottom > 0.dp) FakeKeyboard(state.imeBottom)
    }
}

@Composable
private fun Bubble(lang: String, message: SkyMessage, streaming: Boolean, waitSeconds: Int, liveMotion: Boolean) {
    val user = message.role == "user"
    val typing = streaming && message.text.isBlank()
    val shape = if (user) {
        RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomEnd = 6.dp, bottomStart = 18.dp)
    } else {
        RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomEnd = 18.dp, bottomStart = 6.dp)
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), horizontalArrangement = if (user) Arrangement.End else Arrangement.Start) {
        Column(Modifier.widthIn(max = 300.dp)) {
            if (typing) {
                TypingDots(liveMotion)
                if (waitSeconds >= 3) {
                    Text(
                        if (lang == "en") "Waited ${waitSeconds}s" else "已等待 ${waitSeconds} 秒",
                        color = Muted,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(start = 8.dp, top = 6.dp),
                    )
                }
            } else {
                Text(
                    message.text,
                    color = Ink,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier
                        .background(if (user) Color(0xE61C1810) else Color(0xE610161F), shape)
                        .border(1.dp, if (user) Gold.copy(alpha = 0.28f) else Accent.copy(alpha = 0.22f), shape)
                        .padding(horizontal = 14.dp, vertical = 10.dp),
                )
            }
            if (!user && !streaming) {
                if (message.noticed) {
                    SkyChip(skyText(lang, "noticed"), Gold)
                } else if (!message.expert.isNullOrBlank()) {
                    SkyChip(skyText(lang, "memoryUsed"), Gold)
                } else {
                    SkyChip(skyText(lang, "memoryNone"), Muted)
                }
            }
        }
    }
}

@Composable
private fun SkyChip(text: String, tone: Color) {
    Text(
        text,
        color = tone,
        fontSize = 12.sp,
        letterSpacing = 0.4.sp,
        modifier = Modifier
            .padding(start = 2.dp, top = 6.dp)
            .background(tone.copy(alpha = 0.12f), Pill)
            .border(1.dp, tone.copy(alpha = 0.4f), Pill)
            .padding(horizontal = 10.dp, vertical = 3.dp),
    )
}

@Composable
@OptIn(ExperimentalComposeUiApi::class)
private fun TypingDots(live: Boolean) {
    var phase by remember { mutableIntStateOf(0) }
    LaunchedEffect(live) {
        if (!live) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(280)
            phase = (phase + 1) % 3
        }
    }
    Row(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .clearAndSetSemantics {
                testTagsAsResourceId = true
                testTag = "typing"
                contentDescription = "typing-$phase"
            }
            .background(Color(0xE610161F), RoundedCornerShape(18.dp, 18.dp, 18.dp, 6.dp))
            .border(1.dp, Accent.copy(alpha = 0.22f), RoundedCornerShape(18.dp, 18.dp, 18.dp, 6.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        repeat(3) { index ->
            val on = !live || index == phase
            Box(
                Modifier
                    .size(if (on) 8.dp else 5.dp)
                    .background(if (on) Gold else Muted.copy(alpha = 0.4f), CircleShape),
            )
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

internal val stageIds = listOf("extract", "gate", "build", "train", "recall", "register")

internal fun stageStates(stage: String): List<String> {
    if (stage == "done") return stageIds.map { "done" }
    val at = stageIds.indexOf(stage)
    if (at < 0) return stageIds.map { "pending" }
    return stageIds.mapIndexed { index, _ ->
        when {
            index < at -> "done"
            index == at -> "active"
            else -> "pending"
        }
    }
}

private fun shownTrain(state: SkyState): TrainSnapshot {
    if (state.train.state.isNotBlank() || state.train.step > 0 || state.train.logTail.isNotBlank()) return state.train
    if (!state.training && state.loss.isEmpty()) return TrainSnapshot()
    return TrainSnapshot(
        state = if (state.training) "running" else "done",
        stage = if (state.training) "train" else "done",
        step = state.loss.size,
        total = state.loss.size,
        epoch = if (state.loss.isEmpty()) 0 else 1,
        epochs = if (state.loss.isEmpty()) 0 else 1,
        loss = state.loss.lastOrNull(),
    )
}

@Composable
private fun ConsolidatePane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        StageTimeline(state)
        val snap = shownTrain(state)
        val chartLoss = lossChartValues(snap, state.loss)
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            if (state.statement.isBlank() && state.entity.isBlank()) {
                Text(
                    skyText(state.lang, "stage.pending"),
                    color = Muted,
                    fontSize = 15.sp,
                    lineHeight = 22.sp,
                    modifier = Modifier.padding(vertical = 18.dp),
                )
            } else {
                FactCard(state, onEvent)
            }
            if (chartLoss.isNotEmpty() || state.training || snap.step > 0 || snap.state == "error") {
                Spacer(Modifier.height(12.dp))
                TrainBars(snap)
                val progress = formatTrainProgress(state.lang, snap)
                if (progress.isNotBlank()) {
                    Text(
                        progress,
                        color = if (snap.state == "error") Gold else Muted,
                        fontSize = 13.sp,
                        lineHeight = 18.sp,
                        modifier = Modifier
                            .padding(top = 8.dp)
                            .background(if (snap.state == "error") Gold.copy(alpha = 0.10f) else Color.Transparent, RoundedCornerShape(12.dp))
                            .padding(horizontal = if (snap.state == "error") 10.dp else 0.dp, vertical = if (snap.state == "error") 8.dp else 0.dp)
                            .semantics { contentDescription = "trainProgress" },
                    )
                }
                if (chartLoss.isNotEmpty() || (state.training && snap.step > 0)) {
                    Spacer(Modifier.height(8.dp))
                    LossChart(chartLoss, state.lang)
                }
            }
            if (state.status.isNotEmpty()) {
                val stageWord = skyText(state.lang, "stage.${snap.stage.ifBlank { "train" }}")
                if (state.status != stageWord) {
                    Text(
                        state.status,
                        color = if (snap.state == "error") Gold else Ink,
                        fontSize = 14.sp,
                        lineHeight = 20.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
        }
        if (trainActionsOpen(state.training, snap)) {
            TrainActionRow(state, onEvent)
        }
    }
}

@Composable
private fun TrainActionRow(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            skyText(state.lang, "train"),
            color = Night,
            fontSize = 15.sp,
            modifier = Modifier
                .background(Accent2, Pill)
                .clickable { onEvent(SkyEvent.Train) }
                .semantics { contentDescription = "confirmTrain" }
                .padding(vertical = 10.dp, horizontal = 14.dp),
        )
        Text(
            skyText(state.lang, "cancel"),
            color = Ink,
            fontSize = 15.sp,
            modifier = Modifier
                .border(1.dp, GlassLine, Pill)
                .clickable { onEvent(SkyEvent.CancelTrain) }
                .semantics { contentDescription = "cancelTrain" }
                .padding(vertical = 10.dp, horizontal = 14.dp),
        )
    }
}

@Composable
private fun TrainBars(snap: TrainSnapshot) {
    // One meter. Step and epoch used to be two gold bars; at 2/8 and 1/4 both were a quarter full.
    Meter(trainFraction(snap))
}

@Composable
private fun Meter(fraction: Float) {
    Box(Modifier.fillMaxWidth().height(4.dp).background(Color(0x33101828), Pill)) {
        Box(
            Modifier
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .height(4.dp)
                .background(Brush.horizontalGradient(listOf(Gold.copy(alpha = 0.7f), Gold)), Pill),
        )
    }
}

@Composable
private fun StageTimeline(state: SkyState) {
    val stage = when {
        state.training -> state.train.stage.ifBlank { "train" }
        state.train.state == "error" -> state.train.stage.ifBlank { "train" }
        state.train.state == "done" -> "done"
        state.entity.isNotBlank() || state.statement.isNotBlank() -> "gate"
        else -> ""
    }
    val states = stageStates(stage)
    var pulse by remember { mutableFloatStateOf(1f) }
    LaunchedEffect(state.liveMotion) {
        if (!state.liveMotion) {
            pulse = 1f
            return@LaunchedEffect
        }
        var dir = 1f
        while (true) {
            kotlinx.coroutines.delay(48)
            pulse += dir * 0.05f
            if (pulse > 1.35f) dir = -1f
            if (pulse < 0.85f) dir = 1f
        }
    }
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
                val radius = (if (mark == "active") 7f else if (on) 5.2f else 3.6f) * if (mark == "active") pulse else 1f
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
                    fontSize = 12.sp,
                    lineHeight = 15.sp,
                    letterSpacing = 0.2.sp,
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
                Text(skyText(state.lang, "factWrite"), color = Gold, fontSize = 13.sp, letterSpacing = 0.4.sp)
                BasicTextField(
                    value = state.statement,
                    onValueChange = { onEvent(SkyEvent.Field("statement", it)) },
                    textStyle = MaterialTheme.typography.titleLarge.copy(fontSize = 18.sp, lineHeight = 26.sp, letterSpacing = 0.2.sp),
                    modifier = Modifier.fillMaxWidth(),
                )
                FactLine(skyText(state.lang, "entity"), state.entity) { onEvent(SkyEvent.Field("entity", it)) }
                FactLine(skyText(state.lang, "value"), state.value) { onEvent(SkyEvent.Field("value", it)) }
                FactLine(skyText(state.lang, "question"), state.question) { onEvent(SkyEvent.Field("question", it)) }
                FactLine(skyText(state.lang, "answer"), state.answer) { onEvent(SkyEvent.Field("answer", it)) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = state.force,
                        onCheckedChange = { onEvent(SkyEvent.Force(it)) },
                        colors = CheckboxDefaults.colors(checkedColor = Gold, uncheckedColor = Muted, checkmarkColor = Night),
                    )
                    Text(
                        skyText(state.lang, "force"),
                        color = Muted,
                        fontSize = 14.sp,
                        modifier = Modifier.clickable { onEvent(SkyEvent.Force(!state.force)) },
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        skyText(state.lang, "train"),
                        color = Night,
                        fontSize = 15.sp,
                        modifier = Modifier
                            .background(Accent2, Pill)
                            .clickable { onEvent(SkyEvent.Train) }
                            .semantics { contentDescription = "confirmTrain" }
                            .padding(vertical = 8.dp, horizontal = 14.dp),
                    )
                    Text(
                        skyText(state.lang, "cancel"),
                        color = Ink,
                        fontSize = 15.sp,
                        modifier = Modifier
                            .border(1.dp, GlassLine, Pill)
                            .clickable { onEvent(SkyEvent.CancelTrain) }
                            .semantics { contentDescription = "cancelTrain" }
                            .padding(vertical = 8.dp, horizontal = 14.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun FactLine(label: String, value: String, onChange: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(top = 2.dp)) {
        Text(label, color = Muted, fontSize = 12.sp, letterSpacing = 0.3.sp)
        BasicTextField(
            value = value,
            onValueChange = onChange,
            textStyle = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 6.dp),
        )
        Box(Modifier.fillMaxWidth().height(1.dp).background(GlassLine))
    }
}

@Composable
private fun LossChart(loss: List<Float>, lang: String) {
    val latest = loss.lastOrNull()
    val caption = when {
        latest == null && lang == "en" -> "Loss not in yet"
        latest == null -> "损失还没出来"
        lang == "en" -> "Loss ${"%.2f".format(latest)}"
        else -> "损失 ${"%.2f".format(latest)}"
    }
    Column(
        Modifier
            .fillMaxWidth()
            .background(Glass, RoundedCornerShape(16.dp))
            .border(1.dp, GlassLine, RoundedCornerShape(16.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(caption, color = Gold, fontSize = 13.sp, letterSpacing = 0.3.sp, modifier = Modifier.padding(bottom = 4.dp))
        Canvas(Modifier.fillMaxWidth().height(112.dp)) {
            val left = 8f
            val right = size.width - 8f
            val top = 10f
            val bottom = size.height - 8f
            drawLine(Color(0x33B4C6DC), Offset(left, bottom), Offset(right, bottom), 1.2f)
            if (loss.isEmpty()) return@Canvas
            val maxL = (loss.maxOrNull() ?: 0.05f).coerceAtLeast(0.05f)
            fun yOf(value: Float): Float {
                val span = (bottom - top).coerceAtLeast(1f)
                return bottom - (value / maxL).coerceIn(0f, 1f) * span
            }
            fun xOf(index: Int): Float {
                if (loss.size == 1) return (left + right) / 2f
                return left + index / (loss.size - 1f) * (right - left)
            }
            if (loss.size >= 2) {
                val path = Path()
                loss.forEachIndexed { index, value ->
                    val x = xOf(index)
                    val y = yOf(value)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, Accent2, style = Stroke(width = 2.5f, cap = StrokeCap.Round, join = StrokeJoin.Round))
            }
            loss.forEachIndexed { index, value ->
                drawCircle(Accent2, if (index == loss.lastIndex) 4.5f else 3f, Offset(xOf(index), yOf(value)))
            }
        }
    }
}

@Composable
private fun NebulaFallback(state: SkyState) {
    if (state.experts.isEmpty()) {
        Text(skyText(state.lang, "emptyNebula"), color = Muted, fontSize = 15.sp, lineHeight = 22.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 48.dp))
        return
    }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val boardW = maxWidth
        val boardH = maxHeight
        Canvas(Modifier.fillMaxSize()) {
            state.experts.forEachIndexed { index, expert ->
                val cx = size.width * (0.28f + (index % 2) * 0.44f)
                val cy = size.height * (0.30f + (index / 2) * 0.36f)
                val hot = expert.name == state.highlightExpert
                drawCircle(if (hot) Accent2.copy(alpha = 0.22f) else Accent.copy(alpha = 0.10f), 110f, Offset(cx, cy))
                drawCircle(if (hot) Gold.copy(alpha = 0.16f) else Color(0x22C4A060), 58f, Offset(cx, cy))
                expert.facts.forEachIndexed { factIndex, _ ->
                    val ang = factIndex * 0.9f + index
                    val r = 42f + (factIndex % 5) * 16f
                    val at = Offset(cx + cos(ang) * r, cy + sin(ang) * r * 0.72f)
                    drawCircle(Gold.copy(alpha = 0.25f), if (hot) 8f else 5f, at)
                    drawCircle(if (hot) Gold else Gold.copy(alpha = 0.8f), if (hot) 2.6f else 1.8f, at)
                }
            }
        }
        if (state.recallBanner.isNotBlank()) {
            Text(
                state.recallBanner,
                color = Gold,
                fontSize = 14.sp,
                letterSpacing = 0.3.sp,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(4.dp)
                    .background(Color(0xE6070910), RoundedCornerShape(12.dp))
                    .border(1.dp, GlassLine, RoundedCornerShape(12.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
        state.experts.forEachIndexed { index, expert ->
            val hot = expert.name == state.highlightExpert
            val xFrac = 0.28f + (index % 2) * 0.44f
            val yFrac = 0.30f + (index / 2) * 0.36f
            Text(
                expert.label.ifBlank { skyText(state.lang, "library") },
                color = if (hot) Gold else Ink,
                fontSize = 15.sp,
                letterSpacing = 0.4.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .offset(x = boardW * xFrac - 78.dp, y = boardH * yFrac + 36.dp)
                    .widthIn(max = 168.dp)
                    .background(Color(0xE6070910), RoundedCornerShape(12.dp))
                    .border(1.dp, if (hot) Gold.copy(alpha = 0.45f) else GlassLine, RoundedCornerShape(12.dp))
                    .padding(horizontal = 10.dp, vertical = 6.dp),
            )
        }
    }
}

@Composable
private fun LibraryPane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        if (state.pendingFacts.isNotEmpty()) {
            Text(
                skyText(state.lang, "pendingHead"),
                color = Gold,
                fontSize = 13.sp,
                letterSpacing = 0.5.sp,
                modifier = Modifier.semantics { contentDescription = "pendingFacts" }.padding(bottom = 8.dp),
            )
            state.pendingFacts.forEach { line ->
                Text(
                    line,
                    color = Ink,
                    fontSize = 15.sp,
                    lineHeight = 22.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp)
                        .background(Gold.copy(alpha = 0.10f), RoundedCornerShape(14.dp))
                        .border(1.dp, Gold.copy(alpha = 0.35f), RoundedCornerShape(14.dp))
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                )
            }
            Spacer(Modifier.height(8.dp))
        }
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(state.experts) { expert ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .background(Glass, RoundedCornerShape(16.dp))
                        .border(1.dp, GlassLine, RoundedCornerShape(16.dp))
                        .padding(horizontal = 14.dp, vertical = 12.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(expert.label.ifBlank { skyText(state.lang, "library") }, color = Ink, fontSize = 18.sp, letterSpacing = 0.3.sp)
                        if (expert.facts.isNotEmpty()) {
                            Text(expert.facts.take(2).joinToString(" · "), color = Muted, fontSize = 13.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp))
                        }
                    }
                    Text(
                        skyText(state.lang, "delete"),
                        color = Gold,
                        fontSize = 13.sp,
                        modifier = Modifier
                            .padding(start = 8.dp)
                            .clickable { onEvent(SkyEvent.DeleteExpert(expert.name)) },
                    )
                }
            }
        }
    }
}
