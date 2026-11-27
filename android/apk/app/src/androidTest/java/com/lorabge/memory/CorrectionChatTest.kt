package com.lorabge.memory

import android.content.Intent
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/** Runs through the real composer, send action, chat renderer, and on-disk memory. */
class CorrectionChatTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val device = UiDevice.getInstance(instrumentation)
    private val root = context.filesDir
    private val memory = MemoryStore(File(root, "memory"))
    private val correction = "不对，星舟测试公司的总部是苏州。"
    private val ask = "星舟测试公司的总部在哪里？"

    private val mode = InstrumentationRegistry.getArguments().getString("correctionMode").orEmpty()

    @Before
    fun seed() {
        if (mode == "restart") {
            launch()
            return
        }
        // Empty suite-specific app storage on a disposable emulator only.
        File(root, "memory").deleteRecursively()
        memory.ensure()
        File(root, "setup").mkdirs()
        File(root, "setup/e2e").writeText("1")
        val expert = File(memory.expertsDir, "expert_correction_fixture").apply { mkdirs() }
        File(expert, "fact_memory.json").writeText(
            """[
              {"entity":"星舟测试","statement":"星舟测试公司的总部在杭州。","value":"杭州","attr":"总部"},
              {"entity":"星舟测试","statement":"星舟测试公司成立于1979年。","value":"1979","attr":"成立年份"}
            ]""".trimIndent(),
        )
        memory.writeRouter(listOf(ExpertRecord(expert.name, 0, 2, 32, "", "")))
        launch()
    }

    @Test(timeout = 120_000)
    fun explicitCorrection() {
        if (mode == "restart") {
            verifyNewConversation()
            return
        }
        send(correction)
        if (mode == "legacy") {
            waitText("好的，记住了。")
            assertFalse(device.hasObject(By.text("确认更新")))
            send(ask)
            waitText("星舟测试公司的总部在杭州。")
            assertTrue("legacy app still recalled the old city", replies().last().contains("杭州"))
            return
        }
        waitText("请确认要更新的记忆。")
        assertFalse(replies().any { it.contains("记住了") })
        send(ask)
        waitText("星舟测试公司的总部在杭州。")
        device.wait(Until.findObject(By.text("确认更新")), 8_000)?.click() ?: error("missing confirmation")
        waitText("记忆已更新")
        send(ask)
        waitText("星舟测试公司的总部是苏州。")
        waitSavedReply("星舟测试公司的总部是苏州。")
    }

    private fun verifyNewConversation() {
        device.wait(Until.findObject(By.desc("newChat")), 8_000)?.click() ?: error("missing new chat")
        send(ask)
        waitText("星舟测试公司的总部是苏州。")
        waitSavedReply("星舟测试公司的总部是苏州。")
        send("星舟测试公司是哪一年成立的？")
        waitText("星舟测试公司成立于1979年。")
        waitSavedReply("星舟测试公司成立于1979年。")
    }

    private fun launch() {
        context.startActivity(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        check(device.wait(Until.hasObject(By.desc("composer")), 25_000)) { "composer missing" }
    }

    private fun send(text: String) {
        val composer = device.wait(Until.findObject(By.desc("composer")), 8_000) ?: error("composer missing")
        composer.text = text
        check(device.wait(Until.hasObject(By.desc("composer").text(text)), 8_000)) { "composer did not show $text" }
        device.wait(Until.findObject(By.desc("send")), 8_000)?.click() ?: error("send missing")
        check(device.wait(Until.hasObject(By.text(text)), 8_000)) { "chat did not show sent message $text" }
    }

    private fun waitText(text: String) {
        check(device.wait(Until.hasObject(By.text(text)), 20_000)) { "missing reply: $text; persisted replies: ${replies()}" }
    }

    private fun waitSavedReply(expected: String) {
        val until = SystemClock.elapsedRealtime() + 15_000
        while (SystemClock.elapsedRealtime() < until && replies().lastOrNull() != expected) {
            SystemClock.sleep(150)
        }
        assertEquals(expected, replies().lastOrNull())
    }

    private fun replies() = memory.listConversations().first().messages.filter { it.role == "assistant" }.map { it.content }
}
