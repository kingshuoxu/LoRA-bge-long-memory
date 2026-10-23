package com.lorabge.memory

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Rect
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs

/**
 * 在 SwiftShader 的系统 WebView 上捏合、拖动、点专家。
 * 断言来自 JS 桥写下的 nebula-status.json，不看 Paparazzi。
 */
class NebulaGestureTest {
    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val shots = File(context.filesDir, "e2e")

    @Before
    fun seed() {
        val models = File(context.filesDir, "models")
        File(models, "base.gguf").apply { parentFile?.mkdirs(); writeBytes(byteArrayOf(1)) }
        File(models, "bge.gguf").writeBytes(byteArrayOf(1))
        val weights = File(models, "Qwen2.5-0.5B-Instruct")
        weights.mkdirs()
        File(weights, "model.safetensors").writeBytes(byteArrayOf(1))
        File(weights, "config.json").writeText("{}")
        val setup = File(context.filesDir, "setup")
        setup.mkdirs()
        File(setup, "complete").writeText("ok")
        File(setup, "e2e").writeText("1")
        File(setup, "nebula-status.json").delete()
        File(setup, "nebula-gl.txt").delete()
        File(setup, "nebula-console.txt").delete()
        File(setup, "nebula-fallback-noted").delete()
        val store = MemoryStore(File(context.filesDir, "memory"))
        store.ensure()
        File(store.trainDir, "session-new.txt").delete()
        val expert = File(store.expertsDir, "expert_0")
        expert.mkdirs()
        File(expert, "fact_memory.json").writeText(
            """[{"entity":"佐雷","value":"1979","statement":"佐雷公司成立于1979年。","questions":["佐雷公司是哪一年成立的?"],"attr":"成立年份"}]""",
        )
        store.writeRouter(
            listOf(ExpertRecord("expert_0", 0, 1, 32, "experts/expert_0/router_key.f32", "experts/expert_0/adapter.gguf")),
        )
        shots.mkdirs()
        File(shots, "nebula-ready").delete()
    }

    @Test(timeout = 180_000)
    fun pinchPanAndOpenFact() {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(intent)
        device.wait(Until.hasObject(By.text("星云")), 20_000)
        val tab = device.findObject(By.text("星云")) ?: error("missing nebula tab")
        tab.click()
        val nebula = device.wait(Until.findObject(By.desc("nebula")), 20_000) ?: error("missing nebula webview")
        val gear = device.wait(Until.findObject(By.desc("settings")), 8_000) ?: error("missing gear")
        assertTrue("gear has no size", gear.visibleBounds.width() > 8 && gear.visibleBounds.height() > 8)
        assertFalse(
            "gear is covered by the webview ${gear.visibleBounds} vs ${nebula.visibleBounds}",
            contains(nebula.visibleBounds, gear.visibleBounds.centerX(), gear.visibleBounds.centerY()),
        )
        val ready = waitStatus(25_000) { status ->
            val path = renderPath(status)
            status.optInt("frames") >= 1 && path.isNotBlank() && when (path) {
                "canvas" -> status.optString("renderer") == "compose-canvas"
                else -> status.optString("renderer").isNotBlank() && status.optDouble("hitX") > 1.0
            }
        }
        assertEqualsFresh(ready)
        // 主机在看到这个文件之后才开始 adb emu screenrecord。UiAutomation 截不到 WebView 的 GL 层。
        File(shots, "nebula-ready").writeText(renderPath(ready))
        Thread.sleep(1500)
        val beforeStill = capture("09-nebula-before.png")
        val area = region(beforeStill, nebula.visibleBounds)
        Thread.sleep(450)
        val idleStill = capture("09-nebula-idle.png")
        val variance = lumaVariance(idleStill, area)
        val idleDiff = meanAbsDiff(beforeStill, idleStill, area)
        beforeStill.recycle()
        idleStill.recycle()
        File(shots, "uiautomation-variance.txt").writeText("variance=$variance\nidleDiff=$idleDiff\n")
        val touchesBefore = ready.optInt("touches")
        // aosp_atd 的 screenrecord 和 adb screencap 都是空的。UiAutomation.takeScreenshot 才包含 WebView 的 GL 画面。
        val frames = File(shots, "frames")
        frames.mkdirs()
        frames.listFiles()?.forEach { it.delete() }
        val stop = AtomicBoolean(false)
        val grabber = Thread {
            var index = 0
            while (!stop.get() && index < 80) {
                val file = File(frames, "%04d.png".format(index))
                if (device.takeScreenshot(file) && file.length() > 500) index++
                Thread.sleep(250)
            }
        }
        grabber.start()
        try {
        Thread.sleep(400)
        val before = waitStatus(4_000) { it.optInt("frames") >= 1 }
        val beforeZoom = before.optDouble("zoom")
        nebula.pinchOpen(0.6f, 18)
        device.waitForIdle()
        val zoomed = waitStatus(12_000) { abs(it.optDouble("zoom") - beforeZoom) > 0.15 }
        Thread.sleep(900)
        val beforeZ = zoomed.optDouble("cameraZ")
        val beforeX = zoomed.optDouble("cameraX")
        nebula.swipe(Direction.LEFT, 0.5f)
        device.waitForIdle()
        val moved = waitStatus(12_000) { status ->
            abs(status.optDouble("cameraZ") - beforeZ) > 0.15 ||
                abs(status.optDouble("cameraX") - beforeX) > 0.05
        }
        Thread.sleep(700)
        val afterStill = capture("10-nebula-after.png")
        val idleAgain = BitmapFactory.decodeFile(File(shots, "09-nebula-idle.png").absolutePath)
            ?: error("idle nebula frame missing")
        val afterArea = region(afterStill, (device.findObject(By.desc("nebula")) ?: nebula).visibleBounds)
        val pixelDiff = meanAbsDiff(idleAgain, afterStill, afterArea)
        idleAgain.recycle()
        afterStill.recycle()
        val view = device.findObject(By.desc("nebula")) ?: nebula
        val hit = waitStatus(4_000) { it.optDouble("hitX") > 1.0 }
        val dpr = hit.optDouble("dpr", 1.0).coerceAtLeast(1.0)
        val x = (view.visibleBounds.left + hit.optDouble("hitX") * dpr).toInt()
            .coerceIn(view.visibleBounds.left + 2, view.visibleBounds.right - 2)
        val y = (view.visibleBounds.top + hit.optDouble("hitY") * dpr).toInt()
            .coerceIn(view.visibleBounds.top + 2, view.visibleBounds.bottom - 2)
        device.click(x, y)
        device.waitForIdle()
        var opened = waitStatusOrNull(6_000) { status ->
            status.optBoolean("detail") && (
                status.optString("detailText").contains("1979") || status.optString("detailText").contains("佐雷")
                )
        }
        if (opened == null) {
            device.findObject(By.textContains("条事实"))?.click()
            opened = waitStatusOrNull(6_000) { status ->
                status.optBoolean("detail") && (
                    status.optString("detailText").contains("1979") || status.optString("detailText").contains("佐雷")
                    )
            }
        }
        File(shots, "nebula-status.json").writeText(File(context.filesDir, "setup/nebula-status.json").readText())
        device.takeScreenshot(File(shots, "08-nebula-fact.png"))
        File(shots, "nebula-renderer.txt").writeText(
            "renderer=${ready.optString("renderer")}\n" +
                "version=${ready.optString("version")}\n" +
                "path=${renderPath(moved)}\n" +
                "fallback=${moved.optString("fallback")}\n" +
                "touches=${moved.optInt("touches")}\n" +
                "variance=$variance\n" +
                "idleDiff=$idleDiff\n" +
                "pixelDiff=$pixelDiff\n",
        )
        assertTrue(
            "renderer received no touch events before=${touchesBefore} after=${moved.optInt("touches")} path=${renderPath(moved)}",
            moved.optInt("touches") > touchesBefore,
        )
        assertTrue(
            "pinch did not change zoom from $beforeZoom\n$zoomed",
            abs(zoomed.optDouble("zoom") - beforeZoom) > 0.15,
        )
        assertTrue(
            "pan did not move the camera from z=$beforeZ x=$beforeX\n$moved",
            abs(moved.optDouble("cameraZ") - beforeZ) > 0.15 || abs(moved.optDouble("cameraX") - beforeX) > 0.05,
        )
        assertTrue("fact card did not open\n${opened ?: hit}", opened != null)
        Thread.sleep(1200)
        } finally {
            stop.set(true)
            grabber.join(4_000)
        }
    }

    private fun renderPath(status: JSONObject): String {
        val path = status.optString("path")
        if (path == "webgl2" || path == "webgl1" || path == "canvas") return path
        return when (status.optString("version")) {
            "webgl2" -> "webgl2"
            "webgl", "webgl1" -> "webgl1"
            "canvas" -> "canvas"
            else -> when (status.optString("fallback")) {
                "webgl1" -> "webgl1"
                "canvas" -> "canvas"
                else -> ""
            }
        }
    }

    private fun capture(name: String): Bitmap {
        val file = File(shots, name)
        assertTrue("UiAutomation screenshot failed for $name", device.takeScreenshot(file))
        return BitmapFactory.decodeFile(file.absolutePath) ?: error("could not decode $name")
    }

    private fun region(bitmap: Bitmap, bounds: Rect): Rect {
        val sx = bitmap.width.toFloat() / device.displayWidth.coerceAtLeast(1)
        val sy = bitmap.height.toFloat() / device.displayHeight.coerceAtLeast(1)
        val left = (bounds.left * sx).toInt().coerceIn(0, bitmap.width - 2)
        val top = (bounds.top * sy).toInt().coerceIn(0, bitmap.height - 2)
        val right = (bounds.right * sx).toInt().coerceIn(left + 1, bitmap.width)
        val bottom = (bounds.bottom * sy).toInt().coerceIn(top + 1, bitmap.height)
        return Rect(left, top, right, bottom)
    }

    private fun lumaVariance(bitmap: Bitmap, area: Rect): Double {
        var count = 0
        var mean = 0.0
        var m2 = 0.0
        var y = area.top
        while (y < area.bottom) {
            var x = area.left
            while (x < area.right) {
                val pixel = bitmap.getPixel(x, y)
                val luma = (Color.red(pixel) + Color.green(pixel) + Color.blue(pixel)) / 3.0
                count += 1
                val delta = luma - mean
                mean += delta / count
                m2 += delta * (luma - mean)
                x += 4
            }
            y += 4
        }
        return if (count < 2) 0.0 else m2 / (count - 1)
    }

    private fun meanAbsDiff(first: Bitmap, second: Bitmap, area: Rect): Double {
        val right = minOf(area.right, first.width, second.width)
        val bottom = minOf(area.bottom, first.height, second.height)
        val left = area.left.coerceAtLeast(0)
        val top = area.top.coerceAtLeast(0)
        if (right <= left || bottom <= top) return 0.0
        var sum = 0.0
        var count = 0
        var y = top
        while (y < bottom) {
            var x = left
            while (x < right) {
                val a = first.getPixel(x, y)
                val b = second.getPixel(x, y)
                sum += abs(Color.red(a) - Color.red(b)) +
                    abs(Color.green(a) - Color.green(b)) +
                    abs(Color.blue(a) - Color.blue(b))
                count += 1
                x += 4
            }
            y += 4
        }
        return if (count == 0) 0.0 else sum / count
    }

    private fun assertEqualsFresh(status: JSONObject) {
        assertTrue("imported expert was marked new: $status", status.optInt("freshLabels", 0) == 0)
    }

    private fun contains(rect: Rect, x: Int, y: Int): Boolean {
        return x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom
    }

    private fun waitStatus(timeoutMs: Long, ready: (JSONObject) -> Boolean): JSONObject {
        return waitStatusOrNull(timeoutMs, ready) ?: error("nebula status timeout\n" + readStatusText())
    }

    private fun waitStatusOrNull(timeoutMs: Long, ready: (JSONObject) -> Boolean): JSONObject? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val obj = readStatus()
            if (obj != null && ready(obj)) return obj
            Thread.sleep(250)
        }
        return null
    }

    private fun readStatus(): JSONObject? {
        val file = File(context.filesDir, "setup/nebula-status.json")
        if (!file.exists()) return null
        return try {
            JSONObject(file.readText())
        } catch (_: Throwable) {
            null
        }
    }

    private fun readStatusText(): String {
        val status = File(context.filesDir, "setup/nebula-status.json")
        val console = File(context.filesDir, "setup/nebula-console.txt")
        return (if (status.exists()) status.readText() else "no status") + "\n" +
            (if (console.exists()) console.readText().take(1500) else "")
    }
}
