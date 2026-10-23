package com.lorabge.memory

import android.content.Intent
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
            status.optInt("frames") >= 1 &&
                status.optString("renderer").isNotBlank() &&
                status.optDouble("hitX") > 1.0 &&
                status.optString("fallback") != "canvas"
        }
        assertEqualsFresh(ready)
        File(shots, "nebula-renderer.txt").writeText(
            "renderer=${ready.optString("renderer")}\nversion=${ready.optString("version")}\nfallback=${ready.optString("fallback")}\n",
        )
        // aosp_atd 没有可用的屏幕编码器，screenrecord 会写出 0 字节。
        // 主机在看到 record.on 之后用 screencap 自己串成 mp4。
        File(shots, "record.on").writeText("1")
        val recorder = Thread {
            device.executeShellCommand("screenrecord --time-limit 22 --bit-rate 4000000 /sdcard/nebula-gesture.mp4")
        }
        try {
        recorder.start()
        Thread.sleep(700)
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
        Thread.sleep(900)
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
        assertTrue(
            "pinch did not change zoom from $beforeZoom\n$zoomed",
            abs(zoomed.optDouble("zoom") - beforeZoom) > 0.15,
        )
        assertTrue(
            "pan did not move the camera from z=$beforeZ x=$beforeX\n$moved",
            abs(moved.optDouble("cameraZ") - beforeZ) > 0.15 || abs(moved.optDouble("cameraX") - beforeX) > 0.05,
        )
        assertTrue("fact card did not open\n${opened ?: hit}", opened != null)
        Thread.sleep(1500)
        } finally {
            File(shots, "record.on").delete()
            recorder.join(3_000)
        }
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
