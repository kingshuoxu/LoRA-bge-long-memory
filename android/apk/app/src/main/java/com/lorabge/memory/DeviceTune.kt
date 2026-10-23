package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.sqrt

/**
 * 纯逻辑：按 cpufreq 丢掉小核，并决定 Vulkan 自检之后用哪套后端。
 * 小米 15 的两档 Oryon 都算性能核。天玑 9400 的 1+3+4 只留超大核和大核。
 */
object DeviceTune {
    const val PROBE_PROMPT = "1+1="
    private const val BIG_FRACTION_NUM = 3
    private const val BIG_FRACTION_DEN = 4

    fun performanceThreads(maxFreqKhz: List<Long>, fallbackProcessors: Int): Int {
        val freqs = maxFreqKhz.filter { it > 0 }
        if (freqs.isEmpty()) return fallbackProcessors.coerceIn(1, 8)
        val fastest = freqs.max()
        val cut = fastest * BIG_FRACTION_NUM / BIG_FRACTION_DEN
        return freqs.count { it >= cut }.coerceIn(1, 8)
    }

    fun extractReply(output: String): String {
        val mark = "assistant\n"
        val body = if (output.contains(mark)) {
            output.substringAfterLast(mark)
        } else {
            output.lineSequence().lastOrNull { it.isNotBlank() }.orEmpty()
        }
        return body.replace("[end of text]", "").trim()
    }

    fun chatMatch(cpu: String, gpu: String): Boolean {
        val left = cpu.replace(Regex("\\s+"), " ").trim()
        val right = gpu.replace(Regex("\\s+"), " ").trim()
        return left.isNotEmpty() && left == right
    }

    fun cosine(cpu: FloatArray, gpu: FloatArray): Double {
        if (cpu.size != gpu.size || cpu.isEmpty()) return 0.0
        var dot = 0.0
        var left = 0.0
        var right = 0.0
        for (i in cpu.indices) {
            val x = cpu[i].toDouble()
            val y = gpu[i].toDouble()
            if (!x.isFinite() || !y.isFinite()) return 0.0
            dot += x * y
            left += x * x
            right += y * y
        }
        if (left == 0.0 || right == 0.0) return 0.0
        return dot / sqrt(left * right)
    }

    fun vectorsMatch(cpu: FloatArray, gpu: FloatArray): Boolean = cosine(cpu, gpu) >= 0.99

    fun defaultRecord(version: String) = BackendRecord(
        mode = "auto",
        probe = "cpu",
        reason = "pending",
        probed = false,
        version = version,
        checking = false,
    )

    fun parseRecord(raw: String, version: String): BackendRecord {
        return try {
            val obj = JSONObject(raw)
            BackendRecord(
                mode = obj.optString("mode", "auto").ifBlank { "auto" },
                probe = obj.optString("probe", "cpu").ifBlank { "cpu" },
                reason = obj.optString("reason", "pending"),
                probed = obj.optBoolean("probed"),
                version = obj.optString("version"),
                checking = obj.optBoolean("checking"),
            )
        } catch (_: Throwable) {
            defaultRecord(version)
        }
    }

    fun writeRecord(record: BackendRecord): String {
        return JSONObject()
            .put("mode", record.mode)
            .put("probe", record.probe)
            .put("reason", record.reason)
            .put("probed", record.probed)
            .put("version", record.version)
            .put("checking", record.checking)
            .toString()
    }

    fun active(record: BackendRecord): String = when (record.mode) {
        "cpu" -> "cpu"
        "gpu" -> if (record.reason == "no_vulkan") "cpu" else "vulkan"
        else -> if (record.checking || !record.probed || record.version.isEmpty()) "cpu" else record.probe
    }

    fun ngl(record: BackendRecord): Int = if (active(record) == "vulkan") 99 else 0

    fun explain(record: BackendRecord): String = when (record.mode) {
        "cpu" -> "forced"
        "gpu" -> if (record.reason == "no_vulkan") "no_vulkan" else "forced"
        else -> if (record.checking) "checking" else record.reason
    }

    fun label(record: BackendRecord, lang: String): String {
        if (record.mode == "auto" && record.checking) return if (lang == "en") "checking" else "检测中"
        return if (active(record) == "vulkan") "Vulkan" else "CPU"
    }

    /**
     * 自动模式：Vulkan 对话和嵌入都要跟 CPU 对上，否则记住 CPU。
     * 强制 GPU 仍走 Vulkan，除非包里没有那份库。
     */
    fun decide(
        mode: String,
        vulkanPresent: Boolean,
        modelsReady: Boolean,
        gpuChatStatus: Int,
        cpuReply: String,
        gpuReply: String,
        gpuEmbedStatus: Int,
        cpuVec: FloatArray?,
        gpuVec: FloatArray?,
        version: String,
    ): BackendRecord {
        if (mode == "cpu") {
            return BackendRecord("cpu", "cpu", "forced", true, version, false)
        }
        if (mode == "gpu") {
            return if (vulkanPresent) {
                BackendRecord("gpu", "vulkan", "forced", true, version, false)
            } else {
                BackendRecord("gpu", "cpu", "no_vulkan", true, version, false)
            }
        }
        if (!vulkanPresent) {
            return BackendRecord("auto", "cpu", "no_vulkan", true, version, false)
        }
        if (!modelsReady) {
            return BackendRecord("auto", "cpu", "no_model", false, version, false)
        }
        if (gpuChatStatus != 0) {
            val reason = if (gpuChatStatus == 2) "chat_timeout" else "chat_exit"
            return BackendRecord("auto", "cpu", reason, true, version, false)
        }
        if (!chatMatch(cpuReply, gpuReply)) {
            return BackendRecord("auto", "cpu", "chat_mismatch", true, version, false)
        }
        if (gpuEmbedStatus != 0 || cpuVec == null || gpuVec == null) {
            val reason = if (gpuEmbedStatus == 2) "embed_timeout" else "embed_exit"
            return BackendRecord("auto", "cpu", reason, true, version, false)
        }
        if (!vectorsMatch(cpuVec, gpuVec)) {
            return BackendRecord("auto", "cpu", "embed_mismatch", true, version, false)
        }
        return BackendRecord("auto", "vulkan", "matched", true, version, false)
    }

    fun renderDiagnostics(facts: DiagnosticFacts): String {
        val freqs = if (facts.freqsKhz.isEmpty()) "读不到" else facts.freqsKhz.joinToString(",")
        return buildString {
            appendLine("lorabge-memory 诊断")
            appendLine("时间: ${facts.whenIso}")
            appendLine("厂商: ${facts.manufacturer}")
            appendLine("型号: ${facts.model}")
            appendLine("SoC: ${facts.soc.ifBlank { "未知" }}")
            appendLine("GPU: ${facts.gpu.ifBlank { "未知" }}")
            appendLine("Android: ${facts.androidRelease}")
            appendLine("应用: ${facts.appVersion}")
            appendLine("后端: ${facts.backend}")
            appendLine("模式: ${facts.mode}")
            appendLine("原因: ${facts.reason}")
            appendLine("线程: ${facts.threads}")
            appendLine("频率kHz: $freqs")
            appendLine("Vulkan 库: ${if (facts.vulkanLib) "有" else "无"}")
            appendLine("CPU 库: ${if (facts.cpuLib) "有" else "无"}")
            appendLine("基座: ${if (facts.base) "有" else "无"}")
            appendLine("bge: ${if (facts.bge) "有" else "无"}")
        }
    }

    fun deviceJson(facts: DiagnosticFacts): JSONObject {
        val freqs = JSONArray()
        for (freq in facts.freqsKhz) freqs.put(freq)
        return JSONObject()
            .put("manufacturer", facts.manufacturer)
            .put("model", facts.model)
            .put("soc", facts.soc)
            .put("gpu", facts.gpu)
            .put("android", facts.androidRelease)
            .put("app", facts.appVersion)
            .put("backend", facts.backend)
            .put("mode", facts.mode)
            .put("reason", facts.reason)
            .put("threads", facts.threads)
            .put("freqs_khz", freqs)
    }
}

data class BackendRecord(
    val mode: String,
    val probe: String,
    val reason: String,
    val probed: Boolean,
    val version: String,
    val checking: Boolean,
)

data class DiagnosticFacts(
    val whenIso: String,
    val manufacturer: String,
    val model: String,
    val soc: String,
    val gpu: String,
    val androidRelease: String,
    val appVersion: String,
    val backend: String,
    val mode: String,
    val reason: String,
    val threads: Int,
    val freqsKhz: List<Long>,
    val vulkanLib: Boolean,
    val cpuLib: Boolean,
    val base: Boolean,
    val bge: Boolean,
)
