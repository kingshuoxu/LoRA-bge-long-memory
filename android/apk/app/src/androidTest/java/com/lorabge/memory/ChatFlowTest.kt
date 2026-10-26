package com.lorabge.memory

import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 模拟器上用真输入法走一遍：输入栏不被键盘挡住，等待时圆点在跳，
 * 巩固能看见步数，新对话能想起咪咪，开放问题能答出佐雷公司的 1979。
 */
class ChatFlowTest {
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
        File(setup, "e2e-draft.txt").delete()
        val store = MemoryStore(File(context.filesDir, "memory"))
        store.ensure()
        store.conversationsDir.listFiles()?.forEach { it.delete() }
        File(store.trainDir, "status.json").delete()
        File(store.trainDir, "train.log").delete()
        File(store.trainDir, "cancel").delete()
        File(store.trainDir, "simulate").writeText("1")
        val expert = File(store.expertsDir, "expert_0")
        expert.mkdirs()
        File(expert, "fact_memory.json").writeText(
            """[{"entity":"佐雷","value":"1979","statement":"佐雷公司成立于1979年。","questions":["佐雷公司是哪一年成立的?"]}]""",
        )
        store.writeRouter(
            listOf(ExpertRecord("expert_0", 0, 1, 32, "experts/expert_0/router_key.f32", "experts/expert_0/adapter.gguf")),
        )
        shots.mkdirs()
        listOf(
            "01-ime.png", "02-typing.png", "03-ack.png", "04-pending.png",
            "05-train.png", "06-recall-cat.png", "07-zore.png", "ime-window.txt",
        ).forEach { File(shots, it).delete() }
        device.executeShellCommand("pm grant ${context.packageName} android.permission.POST_NOTIFICATIONS")
        device.executeShellCommand("settings put secure show_ime_with_hard_keyboard 1")
        device.executeShellCommand("ime enable com.android.inputmethod.latin/.LatinIME")
        device.executeShellCommand("ime set com.android.inputmethod.latin/.LatinIME")
    }

    @Test(timeout = 180_000)
    fun keyboardProgressAndRecall() {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(intent)
        val composer = waitDesc("composer", 25_000)
        assertTrue(
            "composer is ${composer.className} with no editable text; semantics did not expose an EditText",
            composer.className.contains("EditText"),
        )
        composer.click()
        val imeTop = waitForIme()
        typeWithIme("hello")
        val held = waitUntil(8_000) {
            device.findObject(By.desc("composer"))?.text?.contains("hello") == true
        }
        if (!held) {
            val hierarchy = File(shots, "composer-missing.xml")
            device.dumpWindowHierarchy(hierarchy)
            val desc = device.findObject(By.desc("composer"))
            error("focused field never received IME text hello, class=${desc?.className} text=${desc?.text}\n" + hierarchy.readText().take(2500))
        }
        val field = device.findObject(By.desc("composer")) ?: composer
        val send = waitDesc("send", 5_000)
        val bottom = field.visibleBounds.bottom
        val sendBottom = send.visibleBounds.bottom
        File(shots, "ime-window.txt").writeText(device.executeShellCommand("dumpsys window"))
        shot("01-ime.png")
        assertTrue("input bottom $bottom is under ime $imeTop", bottom <= imeTop + 8)
        assertTrue("send bottom $sendBottom is under ime $imeTop", sendBottom <= imeTop + 8)
        send.click()
        waitText("hello", 8_000)
        val settled = waitUntil(25_000) {
            device.findObject(By.descStartsWith("typing-")) == null && (
                device.hasObject(By.textContains("llama-cli")) ||
                    device.hasObject(By.textContains("没有生成")) ||
                    device.hasObject(By.textContains("生成失败")) ||
                    device.hasObject(By.textContains("Couldn't"))
                )
        }
        assertTrue("hello was sent but the reply never settled, so later sends would be ignored", settled)

        fillComposer("__e2e_wait__")
        clickDesc("send")
        val typingNode = device.wait(Until.findObject(By.descStartsWith("typing-")), 15_000)
            ?: device.wait(Until.findObject(By.res(context.packageName, "typing")), 2_000)
        if (typingNode == null) {
            error("missing typing-\n" + visibleNodes())
        }
        val first = typingNode.contentDescription
        val changed = waitUntil(6_000) {
            device.findObject(By.descStartsWith("typing-"))?.contentDescription?.let { it != first } == true
        }
        assertTrue("typing dots stayed on $first", changed)
        waitText("已等待", 8_000)
        shot("02-typing.png")
        waitUntil(8_000) { device.findObject(By.descStartsWith("typing-")) == null }

        sendComposer("我的猫猫叫咪咪")
        waitText("好的，记住了，你的猫叫咪咪。", 8_000)
        if (imeTopOrNull() != null) device.pressBack()
        shot("03-ack.png")

        clickTab("tab-library")
        waitText("待巩固", 8_000)
        waitText("我的猫猫叫咪咪", 8_000)
        shot("04-pending.png")

        clickTab("tab-consolidate")
        scrollToText("立即训练").click()
        val train = waitText("确认并训练", 8_000)
        if (!train.visibleBounds.isEmpty) train.click() else {
            device.swipe(device.displayWidth / 2, device.displayHeight * 3 / 4, device.displayWidth / 2, device.displayHeight / 3, 12)
            waitText("确认并训练", 5_000).click()
        }
        val progress = waitUntil(20_000) {
            val node = device.findObject(By.desc("trainProgress")) ?: return@waitUntil false
            val text = node.text.orEmpty()
            text.contains("第 ") && text.contains("步") && !text.contains("0 步")
        }
        assertTrue("training never left 0 steps", progress)
        val shown = device.findObject(By.desc("trainProgress"))?.text.orEmpty()
        assertFalse(shown.contains("0 步"))
        assertTrue(shown, Regex("第 \\d+/\\d+ 步").containsMatchIn(shown))
        shot("05-train.png")
        waitUntil(20_000) {
            val text = device.findObject(By.desc("trainProgress"))?.text.orEmpty()
            text.contains("第 4/4 步") || text.contains("已完成") || text.contains("已登记")
        }

        clickTab("tab-chat")
        clickDesc("newChat")
        ask("我的猫叫什么名字？", "咪咪")
        shot("06-recall-cat.png")
        ask("告诉我佐雷公司相关信息", "1979")
        val hierarchy = File(shots, "ui.xml")
        device.dumpWindowHierarchy(hierarchy)
        val page = hierarchy.readText()
        assertFalse(page.contains("1998"))
        assertTrue(page.contains("1979"))
        shot("07-zore.png")
    }

    private fun ask(question: String, expect: String) {
        sendComposer(question)
        waitText(expect, 8_000)
    }

    /** ASCII only. This is a real soft-keyboard commit into the focused field. */
    private fun typeWithIme(text: String) {
        val encoded = buildString(text.length) {
            for (ch in text) {
                when (ch) {
                    ' ' -> append("%s")
                    '%' -> append("%%")
                    else -> append(ch)
                }
            }
        }
        device.executeShellCommand("input text $encoded")
    }

    /**
     * 中文走仪器测试才编译进来的草稿文件。`input text` 打不了汉字。
     * 键盘是否挡住输入栏由上面的 hello 断言负责，不靠这个文件。
     */
    private fun fillComposer(text: String) {
        File(context.filesDir, "setup").mkdirs()
        File(context.filesDir, "setup/e2e-draft.txt").writeText(text)
        val shown = waitUntil(8_000) {
            device.findObject(By.desc("composer"))?.text?.contains(text) == true
        }
        if (shown) return
        val node = device.findObject(By.desc("composer"))
        error("composer never held [$text], class=${node?.className} text=${node?.text}")
    }

    private fun sendComposer(text: String) {
        fillComposer(text)
        clickDesc("send")
        val posted = waitUntil(8_000) {
            device.findObject(By.textContains(text)) != null &&
                device.findObject(By.desc("composer"))?.text.orEmpty().contains(text).not()
        }
        if (posted) return
        val node = device.findObject(By.desc("composer"))
        error("send did not post [$text], class=${node?.className} text=${node?.text}")
    }

    private fun waitForIme(): Int {
        val top = waitUntilValue(10_000) { imeTopOrNull() }
        assertNotNull("keyboard did not open\n" + device.executeShellCommand("dumpsys input_method").take(1500), top)
        return top!!
    }

    private fun imeTopOrNull(): Int? {
        val window = device.executeShellCommand("dumpsys window")
        val patterns = listOf(
            Regex("""InputMethod[\s\S]{0,500}?mFrame=\[(\d+),(\d+)\]\[(\d+),(\d+)\]"""),
            Regex("""InsetsSource[^\n]*type=ime[^\n]*frame=\[(\d+),(\d+)\]\[(\d+),(\d+)\]"""),
            Regex("""imeFrame=\[(\d+),(\d+)\]\[(\d+),(\d+)\]"""),
        )
        for (pattern in patterns) {
            val match = pattern.find(window) ?: continue
            val top = match.groupValues[2].toIntOrNull() ?: continue
            val bottom = match.groupValues[4].toIntOrNull() ?: continue
            if (bottom > top && top > 0) return top
        }
        val method = device.executeShellCommand("dumpsys input_method")
        if (!method.contains("mInputShown=true") && !method.contains("mImeWindowVis=2")) return null
        val inset = Regex("""ime=\[(\d+),(\d+),(\d+),(\d+)\]""").find(window)
        if (inset != null) {
            val bottomInset = inset.groupValues[4].toIntOrNull() ?: 0
            if (bottomInset > 80) return device.displayHeight - bottomInset
        }
        return null
    }

    private fun waitDesc(desc: String, timeoutMs: Long): UiObject2 {
        return device.wait(Until.findObject(By.desc(desc)), timeoutMs) ?: error("missing $desc")
    }

    private fun clickDesc(desc: String) {
        waitDesc(desc, 8_000).click()
    }

    private fun clickText(text: String) {
        waitText(text, 8_000).click()
    }

    /** 底栏在键盘打开时会收起。「巩固」也不能用包含匹配，否则会点到「待巩固」。 */
    private fun clickTab(desc: String) {
        if (imeTopOrNull() != null) device.pressBack()
        waitDesc(desc, 8_000).click()
    }

    private fun scrollToText(text: String): UiObject2 {
        val first = device.wait(Until.findObject(By.text(text)), 2_000)
        if (first != null && !first.visibleBounds.isEmpty) return first
        repeat(4) {
            device.swipe(
                device.displayWidth / 2,
                device.displayHeight * 3 / 4,
                device.displayWidth / 2,
                device.displayHeight / 5,
                18,
            )
            val found = device.wait(Until.findObject(By.text(text)), 1_500)
            if (found != null && !found.visibleBounds.isEmpty) return found
        }
        return device.wait(Until.findObject(By.text(text)), 2_000) ?: error("missing text $text")
    }

    private fun waitText(text: String, timeoutMs: Long): UiObject2 {
        val found = device.wait(Until.findObject(By.textContains(text)), timeoutMs)
        if (found != null) return found
        device.swipe(device.displayWidth / 2, device.displayHeight * 3 / 4, device.displayWidth / 2, device.displayHeight / 3, 12)
        return device.wait(Until.findObject(By.textContains(text)), 4_000) ?: error("missing text $text")
    }

    private fun waitUntil(timeoutMs: Long, probe: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (probe()) return true
            Thread.sleep(200)
        }
        return false
    }

    private fun <T> waitUntilValue(timeoutMs: Long, probe: () -> T?): T? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val value = probe()
            if (value != null) return value
            Thread.sleep(250)
        }
        return null
    }

    private fun shot(name: String) {
        device.takeScreenshot(File(shots, name))
    }

    private fun visibleNodes(): String {
        return device.findObjects(By.pkg(context.packageName)).take(40).joinToString("\n") { node ->
            val desc = node.contentDescription?.take(60).orEmpty()
            val text = node.text?.take(60).orEmpty()
            "${node.className} desc=$desc text=$text"
        }
    }
}
