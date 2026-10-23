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
    private var notice: String = ""

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
            if (retry) bad.add(key(backend, driverKey))
            notice = if (retry) "cpu_fallback" else "cpu_failed"
            save()
            GuardDecision(retryOnCpu = retry, notice = notice)
        }
    }

    fun isBad(backend: String, driverKey: String): Boolean {
        if (backend == "cpu") return false
        return locked { key(backend, driverKey) in bad }
    }

    fun clearBad(backend: String) {
        locked {
            bad.removeAll { it.startsWith("$backend|") }
            if (notice == "cpu_fallback") notice = ""
            save()
        }
    }

    fun notice(lang: String): String {
        val code = locked { notice }
        if (code.isBlank()) return ""
        val zh = code == "cpu_fallback"
        return if (lang == "en") {
            if (zh) "Graphics backend failed, switched to CPU" else "Generation failed"
        } else {
            if (zh) "图形后端异常，已改用 CPU" else "生成失败"
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
        val badArr = obj.optJSONArray("bad")
        if (badArr != null) {
            for (i in 0 until badArr.length()) bad.add(badArr.getString(i))
        }
        val rows = obj.optJSONArray("crashes") ?: return
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
        target.writeText(JSONObject().put("notice", notice).put("bad", badArr).put("crashes", rows).toString())
    }

    companion object {
        private val processGate = Any()

        fun key(backend: String, driverKey: String) = "$backend|$driverKey"

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
