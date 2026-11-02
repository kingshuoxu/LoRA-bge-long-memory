package com.lorabge.memory

import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * Imports the Chrome print of 《雾港灯塔志》 through the system document picker,
 * asks three questions that are in the book and one that is not, then reviews,
 * queues, and deletes the document.
 */
class DocumentImportE2eTest {
    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val shots = File(context.filesDir, "e2e")
    private val report = StringBuilder()

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
        File(context.filesDir, "docs").deleteRecursively()
        File(context.filesDir, "memory/train").mkdirs()
        File(context.filesDir, "memory/train/simulate").writeText("1")
        File(context.filesDir, "memory/train/status.json").delete()
        File(context.filesDir, "memory/train/job.json").delete()
        shots.mkdirs()
        listOf(
            "doc-01-picker.png", "doc-02-imported.png", "doc-03-year.png", "doc-04-salt.png",
            "doc-05-gull.png", "doc-06-mayor.png", "doc-07-review.png", "doc-08-pending.png",
            "doc-09-library.png", "doc-10-deleted.png", "doc-11-trained.png", "doc-12-memory.png",
            "e2e-report.md", "picker.xml",
        ).forEach { File(shots, it).delete() }
        device.executeShellCommand("pm grant ${context.packageName} android.permission.POST_NOTIFICATIONS")
    }

    @Test(timeout = 360_000)
    fun importChromePdfAndAsk() {
        val listed = device.executeShellCommand("ls /sdcard/Download/wugang_chrome.pdf")
        if (!listed.contains("wugang_chrome.pdf")) {
            error("missing /sdcard/Download/wugang_chrome.pdf\n$listed")
        }
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(intent)
        waitDesc("composer", 25_000)
        dismissEmulatorOverlays(device)
        clickDesc("importDocument")
        pickPdf()
        val imported = waitUntil(120_000) { importReady() }
        shot("doc-02-imported.png")
        if (device.hasObject(By.textContains("没有文字层"))) {
            error("pdf text layer was not read\n" + dump())
        }
        if (!imported) {
            device.dumpWindowHierarchy(File(shots, "import.xml"))
            error("import did not finish\n" + dump())
        }
        val dismissed = waitUntil(15_000) {
            val skip = device.findObject(By.text("先不加入"))
            if (skip != null) {
                try {
                    skip.click()
                } catch (_: StaleObjectException) {
                }
            }
            !device.hasObject(By.text("先不加入")) && !device.hasObject(By.textContains("选择要巩固的重点"))
        }
        if (!dismissed) error("review stayed open\n" + dump())
        clickTab("tab-chat")
        ask("白鹭塔建于哪一年？", "1873", "第3页", "doc-03-year.png")
        ask("星砂盐什么时候晾晒？", "霜降", "第6页", "doc-04-salt.png")
        ask("柯小满的海鸥叫什么？", "阿哨", "第9页", "doc-05-gull.png")
        ask("雾港的市长是谁？", "没有找到", null, "doc-06-mayor.png")
        waitText("雾港灯塔志", 8_000)
        clickTab("tab-library")
        val book = waitText("雾港灯塔志", 15_000)
        book.click()
        waitText("选择要巩固的重点", 15_000)
        shot("doc-07-review.png")
        val add = waitText("加入待巩固", 8_000)
        add.click()
        clickTab("tab-consolidate")
        waitText("1873年", 15_000)
        waitText("四十二米", 8_000)
        waitText("霜降", 8_000)
        waitText("阿哨", 8_000)
        if (device.hasObject(By.textContains("年，塔高"))) error("tower fact was split\n" + dump())
        shot("doc-08-pending.png")
        clickTab("tab-library")
        waitText("导入文档", 8_000)
        waitText("1873年", 8_000)
        waitText("霜降", 8_000)
        waitText("雾港灯塔志", 8_000)
        shot("doc-09-library.png")
        clickTab("tab-consolidate")
        clickDesc("trainAll")
        val started = waitUntil(20_000) {
            device.hasObject(By.textContains("排队")) || device.hasObject(By.textContains("第 "))
        }
        if (!started) error("training did not start\n" + dump())
        val trained = waitUntil(90_000) {
            device.hasObject(By.textContains("已登记")) && !device.hasObject(By.textContains("排队中"))
        }
        shot("doc-11-trained.png")
        if (!trained) error("consolidate did not finish\n" + dump())
        clickTab("tab-library")
        waitText("雾港灯塔志", 8_000)
        clickDesc("deleteDoc")
        waitText("删除这份文档", 8_000)
        clickDesc("confirmDeleteDoc")
        val gone = waitUntil(12_000) { !device.hasObject(By.text("雾港灯塔志")) }
        shot("doc-10-deleted.png")
        if (!gone) error("document stayed in the library\n" + dump())
        clickTab("tab-chat")
        clickDesc("newChat")
        ask("白鹭塔建于哪一年？", "1873", null, "doc-12-memory.png")
        if (device.hasObject(By.textContains("没有找到"))) {
            error("year came from a missing-document reply\n" + dump())
        }
        File(shots, "e2e-report.md").writeText(report.toString() + "\n训练在模拟器上走 simulate（4 步，没有真 LoRA）。\n")
    }

    private fun importReady(): Boolean {
        return device.hasObject(By.textContains("选择要巩固的重点")) ||
            device.hasObject(By.text("先不加入")) ||
            device.hasObject(By.textContains("没有文字层"))
    }

    private fun ask(question: String, expect: String, page: String?, shotName: String) {
        if (device.hasObject(By.text("先不加入"))) {
            device.findObject(By.text("先不加入"))?.click()
            clickTab("tab-chat")
        }
        sendComposer(question)
        waitText(expect, 20_000)
        if (page != null) waitText(page, 8_000)
        shot(shotName)
        val pageText = device.findObjects(By.pkg(context.packageName)).joinToString("\n") { it.text ?: "" }
        report.append("Q: ").append(question).append('\n')
        report.append("expect: ").append(expect)
        if (page != null) report.append(" / ").append(page)
        report.append('\n')
        pageText.lineSequence().filter { line ->
            expect in line || (page != null && page in line) || question in line
        }.distinct().take(8).forEach { report.append("screen: ").append(it).append('\n') }
        report.append('\n')
    }

    private fun pickPdf() {
        var shotTaken = false
        var clicked = false
        val deadline = System.currentTimeMillis() + 40_000
        while (System.currentTimeMillis() < deadline) {
            dismissEmulatorOverlays(device)
            val file = device.findObject(By.textContains("wugang_chrome"))
                ?: device.findObject(By.textContains("wugang"))
            val recent = device.findObject(By.text("Recent"))
            val backInApp = file == null && recent == null &&
                (device.findObject(By.desc("composer")) != null || device.findObject(By.desc("tab-chat")) != null)
            if (clicked && (backInApp || importReady())) return
            if (file != null) {
                if (!shotTaken) {
                    shot("doc-01-picker.png")
                    shotTaken = true
                }
                try {
                    file.click()
                } catch (_: StaleObjectException) {
                    continue
                }
                clicked = true
                Thread.sleep(500)
                val open = device.findObject(By.text("Open"))
                    ?: device.findObject(By.text("OPEN"))
                    ?: device.findObject(By.text("选择"))
                    ?: device.findObject(By.text("打开"))
                open?.click()
                Thread.sleep(400)
                continue
            }
            val downloads = device.findObject(By.textContains("Downloads"))
                ?: device.findObject(By.textContains("Download"))
                ?: device.findObject(By.text("下载"))
                ?: device.findObject(By.textContains("下载"))
            if (downloads != null) {
                downloads.click()
            } else {
                val roots = device.findObject(By.descContains("Show roots"))
                    ?: device.findObject(By.descContains("显示根目录"))
                    ?: device.findObject(By.descContains("根"))
                roots?.click()
            }
            Thread.sleep(600)
        }
        device.dumpWindowHierarchy(File(shots, "picker.xml"))
        error("system picker did not list wugang_chrome.pdf\n" + dump())
    }

    private fun sendComposer(text: String) {
        File(context.filesDir, "setup").mkdirs()
        File(context.filesDir, "setup/e2e-draft.txt").writeText(text)
        val shown = waitUntil(8_000) {
            device.findObject(By.desc("composer"))?.text?.contains(text) == true
        }
        if (!shown) error("composer never held [$text]\n" + dump())
        clickDesc("send")
        val posted = waitUntil(8_000) {
            device.findObject(By.textContains(text)) != null &&
                device.findObject(By.desc("composer"))?.text.orEmpty().contains(text).not()
        }
        if (!posted) error("send did not post [$text]\n" + dump())
    }

    private fun clickTab(desc: String) {
        waitDesc(desc, 8_000).click()
    }

    private fun waitDesc(desc: String, timeoutMs: Long): UiObject2 {
        return device.wait(Until.findObject(By.desc(desc)), timeoutMs) ?: error("missing $desc\n" + dump())
    }

    private fun clickDesc(desc: String) {
        val deadline = System.currentTimeMillis() + 8_000
        while (System.currentTimeMillis() < deadline) {
            dismissEmulatorOverlays(device)
            val node = device.findObject(By.desc(desc))
            if (node == null) {
                Thread.sleep(200)
                continue
            }
            try {
                node.click()
                return
            } catch (_: StaleObjectException) {
                Thread.sleep(200)
            }
        }
        error("missing $desc\n" + dump())
    }

    private fun waitText(text: String, timeoutMs: Long): UiObject2 {
        val found = device.wait(Until.findObject(By.textContains(text)), timeoutMs)
        if (found != null) return found
        error("missing text $text\n" + dump())
    }

    private fun waitUntil(timeoutMs: Long, probe: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (probe()) return true
            Thread.sleep(250)
        }
        return false
    }

    private fun shot(name: String) {
        device.takeScreenshot(File(shots, name))
    }

    private fun dump(): String {
        val nodes = device.findObjects(By.clazz("android.widget.TextView"))
        val shown = if (nodes.isEmpty()) device.findObjects(By.pkg(context.packageName)) else nodes
        return shown.take(30).joinToString("\n") { node ->
            val desc = node.contentDescription?.take(40).orEmpty()
            val text = node.text?.take(60).orEmpty()
            "$desc | $text"
        }
    }
}
