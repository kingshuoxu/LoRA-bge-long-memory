package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * CI 没有 Mali,也起不了 arm64 模拟器。这里拉起一个真的子进程当作 :llm,
 * 在请求中途把它杀掉,确认 UI 侧会记下崩溃并改走 CPU。
 */
class LlmIsolationTest {
    @Test
    fun killingLlmProcessDuringRequestFallsBackToCpu() {
        val root = tempRoot()
        val guard = LlmGuard(File(root, "crashes.json"))
        val script = workerScript(root)
        val opens = ArrayList<String>()
        val supervisor = LlmSupervisor(guard) { backend ->
            opens.add(backend)
            ScriptWorker(script, backend, mode = "gpu-crash")
        }
        val driver = "Mali-G925|v1.r47p0"
        val text = supervisor.call("answer", "vulkan", driver, "我的猫猫叫咪咪")
        assertEquals("ok:我的猫猫叫咪咪", text)
        assertEquals(listOf("vulkan", "cpu"), opens)
        assertTrue(guard.isBad("vulkan", driver))
        val rendered = guard.render()
        assertTrue(rendered.contains("SIGSEGV"))
        assertTrue(rendered.contains("answer"))
        assertTrue(rendered.contains("vulkan"))
        assertTrue(rendered.contains(driver))
        assertEquals(
            "图形后端异常（生成 SIGSEGV），这条已改用 CPU。设置里把图形后端改成「自动」可再试。",
            guard.notice("zh"),
        )
        assertTrue(guard.notice("en").contains("CPU"))
        assertTrue(guard.notice("en").contains("Auto"))

        val again = supervisor.call("answer", "vulkan", driver, "hi")
        assertEquals("ok:hi", again)
        assertEquals("cpu", opens.last())
        assertFalse(opens.drop(2).contains("vulkan"))
    }

    @Test
    fun cpuCrashDoesNotRetryForever() {
        val root = tempRoot()
        val guard = LlmGuard(File(root, "crashes.json"))
        val script = workerScript(root)
        val opens = AtomicInteger()
        val supervisor = LlmSupervisor(guard) { backend ->
            opens.incrementAndGet()
            ScriptWorker(script, backend, mode = "always")
        }
        try {
            supervisor.call("answer", "cpu", "device|unknown", "x")
            throw AssertionError("cpu crash should surface")
        } catch (dead: WorkerDied) {
            assertEquals("SIGKILL", dead.signal)
        }
        assertEquals(1, opens.get())
        assertFalse(guard.isBad("cpu", "device|unknown"))
        assertTrue(guard.render().contains("SIGKILL"))
    }

    @Test
    fun oneCrashDoesNotBanTheNextLaunch() {
        val root = tempRoot()
        val file = File(root, "crashes.json")
        val first = LlmGuard(file)
        first.onDeath("selftest", "vulkan", "Mali-G925|r47", "SIGSEGV", "probe child")
        assertTrue(first.isBad("vulkan", "Mali-G925|r47"))
        assertTrue(first.notice("zh").contains("自检"))
        assertTrue(first.notice("zh").contains("SIGSEGV"))
        first.acknowledge()
        assertEquals("", first.notice("zh"))

        val second = LlmGuard(file)
        assertFalse(second.isBad("vulkan", "Mali-G925|r47"))
        assertEquals(1, second.vulkanStrikes())
        assertEquals("", second.notice("zh"))
        second.onDeath("answer", "vulkan", "Mali-G925|r47", "SIGSEGV", "again")
        val third = LlmGuard(file)
        assertTrue(third.isBad("vulkan", "Mali-G925|r47"))
        assertEquals(2, third.vulkanStrikes())
        third.clearBad("vulkan")
        val forgiven = LlmGuard(file)
        assertFalse(forgiven.isBad("vulkan", "Mali-G925|r47"))
        assertEquals(0, forgiven.vulkanStrikes())
    }

    @Test
    fun ensureBinderDeathDoesNotRetireAFasterGpu() {
        val root = tempRoot()
        val file = File(root, "crashes.json")
        val driver = "Mali-G925-Immortalis MC12|v1.r49p1-03bet0"
        val first = LlmGuard(file)
        val detail = "stage=ensure\nbackend=vulkan\n"
        first.onDeath("ensure", "vulkan", driver, "binder", detail)
        assertFalse(first.isBad("vulkan", driver))
        assertEquals(0, first.vulkanStrikes())
        val toast = first.notice("zh")
        assertTrue(toast.contains("stage=ensure"))
        assertTrue(toast.contains("binder"))
        assertTrue(toast.contains("没有停用 GPU"))
        first.onDeath("ensure", "vulkan", driver, "binder", detail)
        val second = LlmGuard(file)
        assertFalse(second.isBad("vulkan", driver))
        assertEquals(0, second.vulkanStrikes())
        assertTrue(second.render().contains("ensure"))
        second.onDeath("answer", "vulkan", driver, "SIGSEGV", "chat")
        assertEquals(1, second.vulkanStrikes())
        assertTrue(second.isBad("vulkan", driver))
    }

    @Test
    fun tombstoneTextKeepsSignalStageAndBackend() {
        val note = LlmGuard.parseNativeCrash(
            """
            signal=11
            stage=selftest
            backend=vulkan
            addr=0x10
            trace:
            0x1000
            """.trimIndent(),
        )
        assertEquals("SIGSEGV", note.signal)
        assertEquals("selftest", note.stage)
        assertEquals("vulkan", note.backend)
        assertTrue(note.body.contains("trace:"))
    }

    @Test
    fun catFactIsAQuietNoteAndAQuestionIsNot() {
        assertTrue(FactNotice.noticed("我的猫猫叫咪咪"))
        assertEquals("咪咪", FactNotice.guess("我的猫猫叫咪咪").value)
        assertFalse(FactNotice.noticed("塔佐巴洛公司是哪一年成立的?"))
        assertTrue(FactNotice.noticed("不对,总部是特希市"))
    }

    private fun workerScript(root: File): File {
        val script = File(root, "llm_worker.py")
        script.writeText(
            """
            import os, sys, signal
            backend = sys.stdin.readline().strip()
            stage = sys.stdin.readline().strip()
            payload = sys.stdin.readline().strip()
            mode = os.environ.get("LLM_MODE", "gpu-crash")
            if mode == "always" or backend != "cpu":
                sig = signal.SIGKILL if mode == "always" else signal.SIGSEGV
                os.kill(os.getpid(), sig)
            sys.stdout.write("ok:" + payload + "\n")
            sys.stdout.flush()
            """.trimIndent() + "\n",
        )
        return script
    }

    private fun tempRoot(): File {
        val dir = File(System.getProperty("java.io.tmpdir"), "llm-iso-" + System.nanoTime())
        dir.mkdirs()
        return dir
    }
}

private class ScriptWorker(private val script: File, private val backend: String, private val mode: String) : LlmWorker {
    override fun call(stage: String, backend: String, payload: String, onText: (String) -> Unit): String {
        val proc = ProcessBuilder("python3", "-u", script.absolutePath)
            .apply { environment()["LLM_MODE"] = mode }
            .start()
        proc.outputStream.bufferedWriter().use { writer ->
            writer.write(this.backend)
            writer.newLine()
            writer.write(stage)
            writer.newLine()
            writer.write(payload.replace("\n", " "))
            writer.newLine()
        }
        val finished = proc.waitFor(8, TimeUnit.SECONDS)
        val stdout = proc.inputStream.bufferedReader().readText().trim()
        val code = if (!finished) {
            proc.destroyForcibly()
            -1
        } else {
            proc.exitValue()
        }
        if (code != 0) {
            throw WorkerDied(LlmGuard.signalName(code), "exit $code", stage, this.backend)
        }
        onText(stdout)
        return stdout
    }
}
