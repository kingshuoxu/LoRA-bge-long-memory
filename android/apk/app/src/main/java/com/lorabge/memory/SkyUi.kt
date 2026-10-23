package com.lorabge.memory

import android.graphics.Typeface
import android.graphics.fonts.Font
import android.graphics.fonts.FontFamily
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily as ComposeFontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.cos
import kotlin.math.sin

private val Night = Color(0xFF070910)
private val Ink = Color(0xFFEEF3FB)
private val Muted = Color(0xFFA9B6C9)
private val Accent = Color(0xFFB7D7FF)
private val Accent2 = Color(0xFF7EF0E0)
private val Gold = Color(0xFFF2D291)
private val Glass = Color(0x6B080C16)

enum class SkyTab { Chat, Consolidate, Nebula, Library }

data class SkyMessage(val role: String, val text: String, val expert: String?)

data class SkyExpert(val name: String, val facts: List<String>)

data class PendingCorrection(val entity: String, val statement: String, val value: String)

data class SkyState(
    val lang: String = "zh",
    val tab: SkyTab = SkyTab.Chat,
    val training: Boolean = false,
    val status: String = "",
    val messages: List<SkyMessage> = emptyList(),
    val draft: String = "",
    val conversations: List<String> = emptyList(),
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
    val ready: String = "",
    val note: String = "",
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
    data object ToggleGpu : SkyEvent()
}

fun skyText(lang: String, key: String): String {
    val zh = mapOf(
        "chat" to "对话",
        "consolidate" to "巩固",
        "nebula" to "星云",
        "library" to "记忆库",
        "send" to "发送",
        "placeholder" to "要改一条记忆,直接说出新的事实",
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
        "paused" to "训练中,星空暂停",
        "emptyNebula" to "还没有专家。巩固之后,事实会变成星。",
        "recall" to "刚才路由到这里",
        "import" to "导入已推送的专家",
        "selfCheck" to "路由自检",
        "gpu" to "切换 CPU / GPU",
    )
    val en = mapOf(
        "chat" to "Chat",
        "consolidate" to "Consolidate",
        "nebula" to "Nebula",
        "library" to "Library",
        "send" to "Send",
        "placeholder" to "To correct a memory, state the new fact",
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
        "gpu" to "CPU / GPU",
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
        Box(Modifier.fillMaxSize().background(Night)) {
            MilkyWay(paused = state.training)
            Column(Modifier.fillMaxSize().padding(16.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text(if (state.lang == "en") "Long memory" else "长期记忆", style = MaterialTheme.typography.titleLarge)
                    Row {
                        LangChip("中文", state.lang == "zh") { onEvent(SkyEvent.Lang("zh")) }
                        LangChip("EN", state.lang == "en") { onEvent(SkyEvent.Lang("en")) }
                    }
                }
                Text(state.ready, color = Muted, modifier = Modifier.padding(bottom = 8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    TabChip(skyText(state.lang, "chat"), state.tab == SkyTab.Chat) { onEvent(SkyEvent.Tab(SkyTab.Chat)) }
                    TabChip(skyText(state.lang, "consolidate"), state.tab == SkyTab.Consolidate) { onEvent(SkyEvent.Tab(SkyTab.Consolidate)) }
                    TabChip(skyText(state.lang, "nebula"), state.tab == SkyTab.Nebula) { onEvent(SkyEvent.Tab(SkyTab.Nebula)) }
                    TabChip(skyText(state.lang, "library"), state.tab == SkyTab.Library) { onEvent(SkyEvent.Tab(SkyTab.Library)) }
                }
                if (state.training) {
                    Text(skyText(state.lang, "paused"), color = Gold, modifier = Modifier.padding(top = 6.dp))
                }
                Box(Modifier.weight(1f).fillMaxWidth().padding(top = 10.dp)) {
                    when (state.tab) {
                        SkyTab.Chat -> ChatPane(state, onEvent)
                        SkyTab.Consolidate -> ConsolidatePane(state, onEvent)
                        SkyTab.Nebula -> NebulaPane(state)
                        SkyTab.Library -> LibraryPane(state, onEvent)
                    }
                }
            }
        }
    }
}

@Composable
private fun rememberSerif(): ComposeFontFamily {
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
private fun LangChip(label: String, on: Boolean, click: () -> Unit) {
    Text(
        label,
        color = if (on) Night else Accent,
        modifier = Modifier
            .padding(start = 6.dp)
            .background(if (on) Accent else Color.Transparent, RoundedCornerShape(12.dp))
            .clickable(onClick = click)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    )
}

@Composable
private fun TabChip(label: String, on: Boolean, click: () -> Unit) {
    Text(
        label,
        color = if (on) Accent2 else Muted,
        modifier = Modifier.clickable(onClick = click).padding(vertical = 6.dp),
    )
}

@Composable
private fun MilkyWay(paused: Boolean) {
    var phase by remember { mutableFloatStateOf(0.4f) }
    LaunchedEffect(paused) {
        if (paused) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(48)
            phase += 0.004f
        }
    }
    Canvas(Modifier.fillMaxSize()) {
        val band = Path()
        val y0 = size.height * 0.42f
        band.moveTo(0f, y0)
        var x = 0f
        while (x <= size.width) {
            val y = y0 + sin((x / size.width) * 3.2f + phase) * size.height * 0.08f
            band.lineTo(x, y)
            x += 12f
        }
        drawPath(band, Color(0x33B7D7FF), style = Stroke(width = size.height * 0.18f))
        drawPath(band, Color(0x227EF0E0), style = Stroke(width = size.height * 0.06f))
        val count = 90
        for (i in 0 until count) {
            val px = ((i * 97) % 1000) / 1000f * size.width
            val py = ((i * 57) % 1000) / 1000f * size.height
            val tw = 0.35f + 0.65f * ((sin(phase * 2f + i) + 1f) / 2f)
            val r = if (i % 11 == 0) 2.2f else 1.1f
            drawCircle(Color.White.copy(alpha = tw), r, Offset(px, py))
        }
    }
}

@Composable
private fun ChatPane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Text(skyText(state.lang, "newChat"), color = Accent, modifier = Modifier.clickable { onEvent(SkyEvent.NewChat) })
        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            items(state.messages) { message ->
                val who = if (message.role == "user") if (state.lang == "en") "Me" else "我" else if (state.lang == "en") "Assistant" else "助手"
                val extra = message.expert?.let { " · $it" }.orEmpty()
                GlassText("$who$extra\n${message.text}")
            }
        }
        state.pending?.let { pending ->
            Column(Modifier.fillMaxWidth().background(Glass, RoundedCornerShape(12.dp)).padding(10.dp)) {
                Text(pending.statement, color = Gold)
                Text("${pending.entity} · ${pending.value}", color = Muted)
                Row {
                    Text(skyText(state.lang, "confirm"), color = Accent2, modifier = Modifier.clickable { onEvent(SkyEvent.ConfirmCorrection) }.padding(8.dp))
                    Text(skyText(state.lang, "dismiss"), color = Muted, modifier = Modifier.clickable { onEvent(SkyEvent.DismissCorrection) }.padding(8.dp))
                }
            }
        }
        OutlinedTextField(
            value = state.draft,
            onValueChange = { onEvent(SkyEvent.Draft(it)) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text(skyText(state.lang, "placeholder")) },
        )
        Text(skyText(state.lang, "send"), color = Accent, modifier = Modifier.padding(top = 6.dp).clickable { onEvent(SkyEvent.Send) })
        LazyColumn(Modifier.height(72.dp)) {
            items(state.conversations) { title ->
                Text(title, color = Muted, modifier = Modifier.padding(vertical = 2.dp))
            }
        }
    }
}

@Composable
private fun ConsolidatePane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Constellation(state.loss, state.training)
        Text("${skyText(state.lang, "loss")} · ${state.loss.size} ${skyText(state.lang, "steps")}", color = Muted)
        if (state.status.isNotEmpty()) Text(state.status, color = Ink, modifier = Modifier.padding(vertical = 4.dp))
        Field(skyText(state.lang, "entity"), state.entity) { onEvent(SkyEvent.Field("entity", it)) }
        Field(skyText(state.lang, "statement"), state.statement) { onEvent(SkyEvent.Field("statement", it)) }
        Field(skyText(state.lang, "value"), state.value) { onEvent(SkyEvent.Field("value", it)) }
        Field(skyText(state.lang, "question"), state.question) { onEvent(SkyEvent.Field("question", it)) }
        Field(skyText(state.lang, "answer"), state.answer) { onEvent(SkyEvent.Field("answer", it)) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = state.force, onCheckedChange = { onEvent(SkyEvent.Force(it)) })
            Text(skyText(state.lang, "force"), color = Muted)
        }
        Row {
            Text(skyText(state.lang, "train"), color = Accent2, modifier = Modifier.clickable { onEvent(SkyEvent.Train) }.padding(8.dp))
            Text(skyText(state.lang, "cancel"), color = Muted, modifier = Modifier.clickable { onEvent(SkyEvent.CancelTrain) }.padding(8.dp))
        }
    }
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = onChange, modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp), label = { Text(label) })
}

@Composable
private fun Constellation(loss: List<Float>, training: Boolean) {
    Canvas(Modifier.fillMaxWidth().height(180.dp)) {
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
            drawPath(path, Accent2, style = Stroke(width = 4f))
        }
        if (training) {
            drawCircle(Gold.copy(alpha = 0.15f), 18f, pts[loss.size.coerceAtMost(pts.lastIndex)])
        }
    }
}

@Composable
private fun NebulaPane(state: SkyState) {
    if (state.experts.isEmpty()) {
        Text(skyText(state.lang, "emptyNebula"), color = Muted)
        return
    }
    Box(Modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            state.experts.forEachIndexed { index, expert ->
                val cx = size.width * (0.22f + (index % 3) * 0.28f)
                val cy = size.height * (0.28f + (index / 3) * 0.34f)
                val hot = expert.name == state.highlightExpert
                drawCircle(if (hot) Accent2.copy(alpha = 0.18f) else Accent.copy(alpha = 0.08f), 78f, Offset(cx, cy))
                drawCircle(if (hot) Accent2 else Accent, 7f, Offset(cx, cy))
                expert.facts.forEachIndexed { factIndex, _ ->
                    val ang = factIndex * 0.9f + index
                    val r = 28f + (factIndex % 4) * 12f
                    val p = Offset(cx + cos(ang) * r, cy + sin(ang) * r * 0.72f)
                    drawCircle(if (hot) Gold else Gold.copy(alpha = 0.7f), if (hot) 3.4f else 2.2f, p)
                }
            }
        }
        Column(Modifier.align(Alignment.BottomStart)) {
            state.experts.forEach { expert ->
                val mark = if (expert.name == state.highlightExpert) " · ${skyText(state.lang, "recall")}" else ""
                Text("${expert.name}  ${expert.facts.size}$mark", color = if (expert.name == state.highlightExpert) Gold else Muted)
            }
        }
    }
}

@Composable
private fun LibraryPane(state: SkyState, onEvent: (SkyEvent) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(skyText(state.lang, "import"), color = Accent, modifier = Modifier.clickable { onEvent(SkyEvent.ImportExperts) })
            Text(skyText(state.lang, "selfCheck"), color = Accent2, modifier = Modifier.clickable { onEvent(SkyEvent.SelfCheck) })
            Text(skyText(state.lang, "gpu"), color = Gold, modifier = Modifier.clickable { onEvent(SkyEvent.ToggleGpu) })
        }
        if (state.note.isNotEmpty()) {
            Text(state.note, color = Muted, modifier = Modifier.padding(vertical = 6.dp))
        }
        LazyColumn(Modifier.weight(1f)) {
            items(state.experts) { expert ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Column(Modifier.weight(1f)) {
                        Text(expert.name, color = Ink)
                        Text(expert.facts.take(3).joinToString(" · "), color = Muted)
                    }
                    Text(skyText(state.lang, "delete"), color = Gold, modifier = Modifier.clickable { onEvent(SkyEvent.DeleteExpert(expert.name)) })
                }
            }
        }
    }
}

@Composable
private fun GlassText(text: String) {
    Text(
        text,
        color = Ink,
        modifier = Modifier
            .padding(vertical = 4.dp)
            .border(1.dp, Color(0x33B7D7FF), RoundedCornerShape(10.dp))
            .background(Glass, RoundedCornerShape(10.dp))
            .padding(8.dp),
    )
}
