package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile

/**
 * 记下一次原生崩溃,并决定要不要改走 CPU 再试一次。
 * 同一个设备、同一版驱动记成坏后端。进程死了 Kotlin 的 try/catch 接不住,所以由调用方在 binder 死亡或子进程信号退出时进来。
 */
class LlmGuard(private val file: File?) {
    private val crashes = ArrayList<CrashNote>()
    private val bad = HashSet<String>()
    private val sessionBad = HashSet<String>()
    private var notice: String = ""
    private var recoveredAt: Long = 0L

    init {
        if (file != null) load()
    }

    fun onDeath(stage: String, backend: String, driverKey: String, signal: String, detail: String): GuardDecision {
        return locked {
            crashes.add(
                CrashNote(
                    stage = stage.ifBlank { "unknown" },
                    backend = backend.ifBlank { "unknown" },
                    signal = signal.ifBlank { "unknown" },
                    detail = detail.take(2000),
                    driverKey = driverKey,
                    atMillis = System.currentTimeMillis(),
                ),
            )
            while (crashes.size > 8) crashes.removeAt(0)
            val retry = backend != "cpu" && backend != "unknown"
            val counts = countsTowardBan(crashes.last().stage, crashes.last().signal)
            // A real crash pins this process to CPU. Two of those stay on CPU until
            // Settings picks Auto or GPU. ensure/bind dying with no native signal
            // (the :llm process vanished) does not retire a GPU that already won the benchmark.
            if (retry && counts) sessionBad.add(key(backend, driverKey))
            recomputeBan()
            notice = when {
                !retry -> "cpu_failed"
                !counts -> "ensure_lost"
                else -> "cpu_fallback"
            }
            save()
            GuardDecision(retryOnCpu = retry, notice = notice)
        }
    }

    fun isBad(backend: String, driverKey: String): Boolean {
        if (backend == "cpu") return false
        val id = key(backend, driverKey)
        return locked { id in sessionBad || id in bad }
    }

    fun vulkanStrikes(): Int = locked { strikes("vulkan") }

    fun clearBad(backend: String) {
        locked {
            sessionBad.removeAll { it.startsWith("$backend|") }
            val newest = crashes.maxOfOrNull { it.atMillis } ?: 0L
            recoveredAt = maxOf(System.currentTimeMillis(), newest)
            recomputeBan()
            if (notice == "cpu_fallback") notice = ""
            save()
        }
    }

    fun acknowledge() {
        locked {
            if (notice.isNotBlank()) {
                notice = ""
                save()
            }
        }
    }

    fun notice(lang: String): String {
        val (code, stage, signal) = locked {
            val last = crashes.lastOrNull { it.backend != "cpu" && it.backend != "unknown" && it.backend.isNotBlank() }
            Triple(notice, last?.stage.orEmpty(), last?.signal.orEmpty())
        }
        if (code.isBlank()) return ""
        val zh = lang != "en"
        val where = stageName(stage, zh)
        val how = signal.ifBlank { if (zh) "退出" else "exit" }
        if (code == "ensure_lost") {
            val raw = stage.ifBlank { "ensure" }
            return if (zh) {
                "图形后端在启动时退出（stage=$raw，$how）。这一次改用 CPU，没有停用 GPU。设置里把图形后端改成「自动」会再测。"
            } else {
                "Graphics backend exited during startup (stage=$raw, $how). This attempt used CPU. GPU stays available. Set Graphics to Auto to measure again."
            }
        }
        if (code != "cpu_fallback") return if (zh) "生成失败" else "Generation failed"
        return if (zh) {
            "图形后端异常（$where $how），这条已改用 CPU。设置里把图形后端改成「自动」可再试。"
        } else {
            "Graphics backend failed ($where $how). This reply used CPU. Set Graphics to Auto in Settings to try the GPU again."
        }
    }

    fun render(): String {
        val copy = locked { crashes.toList() }
        if (copy.isEmpty()) return ""
        return buildString {
            appendLine("原生崩溃:")
            for (crash in copy) {
                appendLine("- ${crash.stage} / ${crash.backend} / ${crash.signal} / ${crash.driverKey}")
                if (crash.detail.isNotBlank()) appendLine(crash.detail.take(1500))
            }
        }
    }

    private fun <T> locked(block: () -> T): T {
        val target = file ?: return block()
        synchronized(processGate) {
            target.parentFile?.mkdirs()
            RandomAccessFile(target, "rw").use { raf ->
                raf.channel.lock().use {
                    loadFrom(target)
                    return block()
                }
            }
        }
    }

    private fun load() {
        locked { }
    }

    private fun loadFrom(target: File) {
        crashes.clear()
        bad.clear()
        notice = ""
        if (!target.exists() || target.length() == 0L) return
        val obj = try {
            JSONObject(target.readText())
        } catch (_: Throwable) {
            return
        }
        notice = obj.optString("notice")
        recoveredAt = obj.optLong("recoveredAt")
        val rows = obj.optJSONArray("crashes") ?: run {
            recomputeBan()
            return
        }
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            crashes.add(
                CrashNote(
                    stage = row.optString("stage"),
                    backend = row.optString("backend"),
                    signal = row.optString("signal"),
                    detail = row.optString("detail"),
                    driverKey = row.optString("driver"),
                    atMillis = row.optLong("at"),
                ),
            )
        }
        recomputeBan()
    }

    private fun strikes(backend: String): Int {
        return crashes.count {
            it.backend == backend && it.atMillis > recoveredAt && countsTowardBan(it.stage, it.signal)
        }
    }

    private fun recomputeBan() {
        bad.clear()
        val counts = HashMap<String, Int>()
        for (crash in crashes) {
            if (crash.atMillis <= recoveredAt) continue
            if (!countsTowardBan(crash.stage, crash.signal)) continue
            if (crash.backend == "cpu" || crash.backend == "unknown" || crash.backend.isBlank()) continue
            val id = key(crash.backend, crash.driverKey)
            counts[id] = (counts[id] ?: 0) + 1
        }
        for ((id, count) in counts) {
            if (count >= 2) bad.add(id)
        }
    }

    private fun save() {
        val target = file ?: return
        val rows = JSONArray()
        for (crash in crashes) {
            rows.put(
                JSONObject()
                    .put("stage", crash.stage)
                    .put("backend", crash.backend)
                    .put("signal", crash.signal)
                    .put("detail", crash.detail)
                    .put("driver", crash.driverKey)
                    .put("at", crash.atMillis),
            )
        }
        val badArr = JSONArray()
        for (item in bad) badArr.put(item)
        target.writeText(
            JSONObject()
                .put("notice", notice)
                .put("recoveredAt", recoveredAt)
                .put("bad", badArr)
                .put("crashes", rows)
                .toString(),
        )
    }

    companion object {
        fun stageName(stage: String, zh: Boolean): String = when (stage) {
            "selftest" -> if (zh) "自检" else "self-test"
            "answer" -> if (zh) "生成" else "generation"
            "route" -> if (zh) "路由" else "routing"
            "ensure", "bind" -> if (zh) "启动" else "startup"
            else -> stage.ifBlank { if (zh) "未知" else "unknown" }
        }

        private val processGate = Any()

        fun key(backend: String, driverKey: String) = "$backend|$driverKey"

        /** ensure/bind with no native signal means the service process vanished, not a Vulkan fault. */
        fun countsTowardBan(stage: String, signal: String): Boolean {
            if (stage == "ensure" || stage == "bind") {
                if (signal == "binder" || signal == "SIGKILL" || signal == "killed") return false
            }
            return true
        }

        fun signalName(exitCode: Int): String {
            if (exitCode > 128) {
                return when (val sig = exitCode - 128) {
                    4 -> "SIGILL"
                    6 -> "SIGABRT"
                    7 -> "SIGBUS"
                    8 -> "SIGFPE"
                    9 -> "SIGKILL"
                    11 -> "SIGSEGV"
                    else -> "SIG$sig"
                }
            }
            if (exitCode < 0) return "killed"
            return "exit $exitCode"
        }

        fun parseNativeCrash(text: String): NativeCrashNote {
            if (text.isBlank()) return NativeCrashNote("", "", "", text)
            var signal = ""
            var stage = ""
            var backend = ""
            for (line in text.lineSequence()) {
                when {
                    line.startsWith("signal=") -> signal = line.substringAfter("=").trim()
                    line.startsWith("stage=") -> stage = line.substringAfter("=").trim()
                    line.startsWith("backend=") -> backend = line.substringAfter("=").trim()
                }
            }
            val named = signal.toIntOrNull()?.let { signalName(128 + it) } ?: signal
            return NativeCrashNote(named, stage, backend, text.trim())
        }
    }
}

data class CrashNote(
    val stage: String,
    val backend: String,
    val signal: String,
    val detail: String,
    val driverKey: String,
    val atMillis: Long,
)

data class GuardDecision(val retryOnCpu: Boolean, val notice: String)

data class NativeCrashNote(val signal: String, val stage: String, val backend: String, val body: String)
