package com.lorabge.memory

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import org.json.JSONObject
import java.io.File
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin

/**
 * WebGL 完全不可用时的星云。粒子云、星、连线都能拖、能缩放、能点开事实。
 */
@Composable
internal fun NebulaCanvas(
    json: String,
    lang: String,
    animate: Boolean,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scene = remember(json) { parseNebulaScene(json) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    var zoom by remember { mutableFloatStateOf(1f) }
    var selected by remember { mutableIntStateOf(-1) }
    var spin by remember { mutableFloatStateOf(0f) }
    var touches by remember { mutableIntStateOf(0) }
    var canvasWidth by remember { mutableFloatStateOf(1f) }
    var canvasHeight by remember { mutableFloatStateOf(1f) }
    LaunchedEffect(scene) {
        val file = File(context.filesDir, "setup/nebula-status.json")
        file.parentFile?.mkdirs()
        var frames = 0
        while (isActive) {
            frames += 1
            val picked = scene.nodes.getOrNull(selected)
            val hit = scene.nodes.firstOrNull()?.let { node ->
                nebulaCenter(node, canvasWidth, canvasHeight, pan, zoom)
            }
            val body = JSONObject()
                .put("renderer", "compose-canvas")
                .put("version", "canvas")
                .put("path", "canvas")
                .put("fallback", "canvas")
                .put("frames", frames)
                .put("zoom", zoom.toDouble())
                .put("cameraX", pan.x.toDouble())
                .put("cameraZ", pan.y.toDouble())
                .put("touches", touches)
                .put("dpr", 1.0)
                .put("hitX", hit?.x?.toDouble() ?: 0.0)
                .put("hitY", hit?.y?.toDouble() ?: 0.0)
                .put("freshLabels", 0)
                .put("detail", picked != null)
                .put("detailText", picked?.facts?.firstOrNull().orEmpty().ifBlank { picked?.label.orEmpty() })
                .put("kind", "canvas")
            file.writeText(body.toString())
            delay(250)
        }
    }
    LaunchedEffect(animate) {
        if (!animate) return@LaunchedEffect
        val start = withFrameNanos { it }
        while (isActive) {
            withFrameNanos { now ->
                spin = ((now - start) / 1_000_000_000f) % 1000f
            }
        }
    }
    Box(
        modifier
            .semantics { contentDescription = "nebula" }
            .onSizeChanged {
                canvasWidth = it.width.toFloat().coerceAtLeast(1f)
                canvasHeight = it.height.toFloat().coerceAtLeast(1f)
            }
            .pointerInput(scene) {
                awaitPointerEventScope {
                    while (true) {
                        val down = awaitPointerEvent()
                        val first = down.changes.firstOrNull { it.pressed } ?: continue
                        touches += 1
                        var moved = false
                        var pinch = 0f
                        while (true) {
                            val event = awaitPointerEvent()
                            val pressed = event.changes.filter { it.pressed }
                            if (pressed.isEmpty()) {
                                if (!moved) {
                                    selected = hitNebula(scene, first.position, size.width.toFloat(), size.height.toFloat(), pan, zoom)
                                }
                                break
                            }
                            if (pressed.size >= 2) {
                                val dist = hypot(
                                    (pressed[0].position.x - pressed[1].position.x).toDouble(),
                                    (pressed[0].position.y - pressed[1].position.y).toDouble(),
                                ).toFloat().coerceAtLeast(1f)
                                if (pinch > 0f) zoom = (zoom * (dist / pinch)).coerceIn(0.45f, 3.5f)
                                pinch = dist
                                moved = true
                            } else {
                                val delta = pressed[0].position - pressed[0].previousPosition
                                if (delta.getDistance() > 2f) {
                                    pan += delta
                                    moved = true
                                }
                            }
                            event.changes.forEach { change ->
                                if (change.positionChanged()) change.consume()
                            }
                        }
                    }
                }
            },
    ) {
        Canvas(Modifier.fillMaxSize()) {
            drawRect(Color(0xFF070910))
            val t = spin
            for (i in 0 until 70) {
                val sx = ((i * 97) % 1000) / 1000f
                val sy = ((i * 57) % 1000) / 1000f
                val tw = 0.35f + 0.65f * ((sin(t * 1.3f + i) + 1f) / 2f)
                drawCircle(Color(0xFFEED9A8).copy(alpha = 0.35f * tw), 1.2f + (i % 3) * 0.6f, Offset(sx * size.width, sy * size.height))
            }
            val centers = scene.nodes.map { node -> nebulaCenter(node, size.width, size.height, pan, zoom) }
            scene.links.forEach { (a, b) ->
                val pa = centers.getOrNull(a) ?: return@forEach
                val pb = centers.getOrNull(b) ?: return@forEach
                drawLine(Color(0x66E4C98A), pa, pb, strokeWidth = 1.5f)
            }
            scene.nodes.forEachIndexed { index, node ->
                val center = centers[index]
                val rgb = NEBULA_COLORS[index % NEBULA_COLORS.size]
                for (p in 0 until 36) {
                    val ang = p * 0.55f + index + t * 0.15f
                    val rad = (8f + (p % 7) * 7f) * zoom
                    val wobble = sin(t * 0.8f + p) * 4f * zoom
                    val at = Offset(center.x + cos(ang) * rad + wobble, center.y + sin(ang) * rad * 0.72f)
                    drawCircle(rgb.copy(alpha = 0.22f), (3.5f + (p % 4)) * zoom.coerceAtMost(2f), at)
                }
                for (s in 0 until 10) {
                    val ang = s * 0.9f + t * 0.4f
                    val rad = (12f + s * 6f) * zoom
                    val tw = 0.5f + 0.5f * sin(t * 2f + s)
                    drawCircle(Color(0xFFFFF4D2).copy(alpha = 0.75f * tw), 1.6f * zoom.coerceAtMost(2f), Offset(center.x + cos(ang) * rad, center.y + sin(ang) * rad * 0.66f))
                }
                drawCircle(rgb.copy(alpha = 0.9f), 4f * zoom.coerceAtMost(2.2f), center)
            }
        }
        val picked = scene.nodes.getOrNull(selected)
        if (picked != null) {
            val body = picked.facts.firstOrNull().orEmpty().ifBlank { picked.label }
            Text(
                body,
                color = Color(0xFFEEF3FB),
                fontSize = 16.sp,
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(16.dp)
                    .background(Color(0xF210141C), RoundedCornerShape(16.dp))
                    .semantics { contentDescription = "factCard" }
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            )
        }
    }
}

private val NEBULA_COLORS = listOf(
    Color(0xFFFF8A62),
    Color(0xFF3EE0C8),
    Color(0xFFFFD15A),
    Color(0xFFB48CFF),
    Color(0xFFFF8AA0),
    Color(0xFF7EB6FF),
)

internal data class NebulaNode(
    val name: String,
    val label: String,
    val facts: List<String>,
    val nx: Float,
    val ny: Float,
)

internal data class NebulaScene(
    val nodes: List<NebulaNode>,
    val links: List<Pair<Int, Int>>,
)

internal fun parseNebulaScene(json: String): NebulaScene {
    if (json.isBlank()) return NebulaScene(emptyList(), emptyList())
    val doc = try {
        JSONObject(json)
    } catch (_: Throwable) {
        return NebulaScene(emptyList(), emptyList())
    }
    val experts = doc.optJSONArray("experts") ?: return NebulaScene(emptyList(), emptyList())
    val facts = doc.optJSONArray("facts")
    val nodes = ArrayList<NebulaNode>()
    val indexOf = HashMap<String, Int>()
    val count = experts.length().coerceAtLeast(1)
    for (i in 0 until experts.length()) {
        val expert = experts.getJSONObject(i)
        val name = expert.optString("name")
        val ang = (i / count.toFloat()) * (Math.PI * 2).toFloat() - (Math.PI / 2).toFloat()
        val ring = if (experts.length() <= 1) 0f else 1f
        val statements = ArrayList<String>()
        if (facts != null) {
            for (f in 0 until facts.length()) {
                val fact = facts.getJSONObject(f)
                if (fact.optString("expert") == name && !fact.optBoolean("superseded")) {
                    statements.add(fact.optString("statement").ifBlank { fact.optString("value") })
                }
            }
        }
        indexOf[name] = nodes.size
        nodes.add(
            NebulaNode(
                name = name,
                label = expert.optString("display_name").ifBlank { name },
                facts = statements,
                nx = kotlin.math.cos(ang) * ring,
                ny = kotlin.math.sin(ang) * ring * 0.72f,
            ),
        )
    }
    val factExpert = HashMap<String, Int>()
    if (facts != null) {
        for (f in 0 until facts.length()) {
            val fact = facts.getJSONObject(f)
            val idx = indexOf[fact.optString("expert")] ?: continue
            factExpert[fact.optString("id")] = idx
        }
    }
    val links = ArrayList<Pair<Int, Int>>()
    val rawLinks = doc.optJSONArray("links")
    if (rawLinks != null) {
        for (i in 0 until rawLinks.length()) {
            val link = rawLinks.getJSONObject(i)
            val kind = link.optString("kind")
            if (kind != "entity" && kind != "semantic") continue
            val a = factExpert[link.optString("source")] ?: continue
            val b = factExpert[link.optString("target")] ?: continue
            if (a != b) links.add(a to b)
        }
    }
    return NebulaScene(nodes, links)
}

private fun nebulaCenter(node: NebulaNode, width: Float, height: Float, pan: Offset, zoom: Float): Offset {
    val span = minOf(width, height) * 0.28f * zoom
    return Offset(width / 2f + node.nx * span + pan.x, height / 2f + node.ny * span + pan.y)
}

private fun hitNebula(scene: NebulaScene, at: Offset, width: Float, height: Float, pan: Offset, zoom: Float): Int {
    var best = -1
    var bestDist = 78f * zoom.coerceAtLeast(0.8f)
    scene.nodes.forEachIndexed { index, node ->
        val center = nebulaCenter(node, width, height, pan, zoom)
        val dist = (at - center).getDistance()
        if (dist < bestDist) {
            best = index
            bestDist = dist
        }
    }
    return best
}
