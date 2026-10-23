package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.math.sqrt

/**
 * 纯逻辑：按 cpufreq 丢掉小核，并决定 Vulkan 自检之后用哪套后端。
 * 小米 15 的两档 Oryon 都算性能核。天玑 9400 的 1+3+4 只留超大核和大核。
 */
object DeviceTune {
    const val PROBE_PROMPT = "1+1="
    const val SPEED_PROMPT = "The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog."
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

    // 0.1.2 起,Mali 只有在独立进程里自检并且比 CPU 快才升到 GPU。旧记录的戳对不上,会重新测。
    fun probeStamp(version: String) = "$version+iso1"

    fun suspectMali(soc: String, model: String, gpu: String): Boolean {
        val blob = "$soc $model $gpu".lowercase()
        return blob.contains("mali") || blob.contains("immortalis") || blob.contains("dimensity") ||
            blob.contains("mediatek") || blob.contains("mt699")
    }

    fun parseTps(log: String): Pair<Double, Double> {
        val clean = log.replace(Regex("\u001B\\[[0-9;]*m"), "")
        var prefill = 0.0
        var decode = 0.0
        val num = Regex("([0-9]*\\.?[0-9]+)\\s+tokens per second")
        for (line in clean.lineSequence()) {
            val match = num.find(line) ?: continue
            val value = match.groupValues[1].toDoubleOrNull() ?: continue
            if (!value.isFinite() || value < 0.0) continue
            if (line.contains("prompt eval time")) {
                prefill = value
            } else if (line.contains("eval time")) {
                decode = value
            }
        }
        return prefill to decode
    }

    fun parseVulkanCaps(log: String): VulkanCaps {
        val clean = log.replace(Regex("\u001B\\[[0-9;]*m"), "")
        val line = clean.lineSequence().lastOrNull { it.contains("ggml_vulkan: caps ") } ?: return VulkanCaps()
        fun quoted(key: String) = Regex("""$key="([^"]*)"""").find(line)?.groupValues?.get(1).orEmpty()
        fun integer(key: String) = Regex("""(?:^|\s)$key=([0-9]+)""").find(line)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        fun hex(key: String) = Regex("""$key=0x([0-9a-fA-F]+)""").find(line)?.groupValues?.get(1)?.toLongOrNull(16) ?: 0L
        return VulkanCaps(
            name = quoted("name"),
            driver = quoted("driver"),
            driverInfo = quoted("driver_info"),
            driverVersion = integer("driver_version"),
            vendor = hex("vendor"),
            subgroup = integer("subgroup").toInt(),
            fp16 = integer("fp16").toInt(),
            bf16 = integer("bf16").toInt(),
            coopmat = integer("coopmat").toInt(),
            coopmat2 = integer("coopmat2").toInt(),
            intDot = integer("int_dot").toInt(),
            uma = integer("uma").toInt(),
            maxAlloc = integer("max_alloc"),
            maxBuffer = integer("max_buffer"),
            suballoc = integer("suballoc"),
            storageBuffers = integer("storage_buffers").toInt(),
            wgInvocations = integer("wg_invocations").toInt(),
            mali = integer("mali").toInt(),
        )
    }

    fun looksLikeMali(caps: VulkanCaps, glRenderer: String): Boolean {
        if (caps.mali == 1 || caps.vendor == 0x13B5L) return true
        val blob = (caps.name + " " + glRenderer).lowercase()
        return blob.contains("mali") || blob.contains("immortalis")
    }

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
                gpuPrefillTps = obj.optDouble("gpu_prefill_tps", 0.0),
                gpuDecodeTps = obj.optDouble("gpu_decode_tps", 0.0),
                cpuPrefillTps = obj.optDouble("cpu_prefill_tps", 0.0),
                cpuDecodeTps = obj.optDouble("cpu_decode_tps", 0.0),
                vkName = obj.optString("vk_name"),
                vkDriver = obj.optString("vk_driver"),
                vkDriverVersion = obj.optString("vk_driver_version"),
                vkSubgroup = obj.optInt("vk_subgroup"),
                vkFlags = obj.optString("vk_flags"),
                glRenderer = obj.optString("gl_renderer"),
                mali = obj.optBoolean("mali"),
                isolated = obj.optBoolean("isolated"),
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
            .put("gpu_prefill_tps", record.gpuPrefillTps)
            .put("gpu_decode_tps", record.gpuDecodeTps)
            .put("cpu_prefill_tps", record.cpuPrefillTps)
            .put("cpu_decode_tps", record.cpuDecodeTps)
            .put("vk_name", record.vkName)
            .put("vk_driver", record.vkDriver)
            .put("vk_driver_version", record.vkDriverVersion)
            .put("vk_subgroup", record.vkSubgroup)
            .put("vk_flags", record.vkFlags)
            .put("gl_renderer", record.glRenderer)
            .put("mali", record.mali)
            .put("isolated", record.isolated)
            .toString()
    }

    fun active(record: BackendRecord): String {
        val selected = when (record.mode) {
            "cpu" -> "cpu"
            "gpu" -> if (record.reason == "no_vulkan") "cpu" else "vulkan"
            else -> if (record.checking || !record.probed || record.version.isEmpty()) "cpu" else record.probe
        }
        if (record.mode == "auto" && selected == "vulkan" && record.mali && !record.isolated) return "cpu"
        return selected
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
     * Mali 在独立进程证明对得上、并且短解码比 CPU 快之前,保持 CPU。Adreno 只看对不对,不看快慢。
     * 强制 GPU 仍走 Vulkan，除非包里没有那份库。
     * gpuSpeedStatus：0 测完，1 进程失败，2 超时，负数表示没测到。
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
        mali: Boolean = false,
        gpuSpeedStatus: Int = 0,
        gpuDecodeTps: Double = 0.0,
        cpuDecodeTps: Double = 0.0,
        isolated: Boolean = false,
    ): BackendRecord {
        fun finish(record: BackendRecord) = record.copy(
            mali = mali,
            isolated = isolated && record.probe == "vulkan",
        )
        if (mode == "cpu") {
            return finish(BackendRecord("cpu", "cpu", "forced", true, version, false))
        }
        if (mode == "gpu") {
            return if (vulkanPresent) {
                finish(BackendRecord("gpu", "vulkan", "forced", true, version, false))
            } else {
                finish(BackendRecord("gpu", "cpu", "no_vulkan", true, version, false))
            }
        }
        if (!vulkanPresent) {
            return finish(BackendRecord("auto", "cpu", "no_vulkan", true, version, false))
        }
        if (!modelsReady) {
            return finish(BackendRecord("auto", "cpu", "no_model", false, version, false))
        }
        if (gpuChatStatus != 0) {
            val reason = if (gpuChatStatus == 2) "chat_timeout" else "chat_exit"
            return finish(BackendRecord("auto", "cpu", reason, true, version, false))
        }
        if (!chatMatch(cpuReply, gpuReply)) {
            return finish(BackendRecord("auto", "cpu", "chat_mismatch", true, version, false))
        }
        if (gpuEmbedStatus != 0 || cpuVec == null || gpuVec == null) {
            val reason = if (gpuEmbedStatus == 2) "embed_timeout" else "embed_exit"
            return finish(BackendRecord("auto", "cpu", reason, true, version, false))
        }
        if (!vectorsMatch(cpuVec, gpuVec)) {
            return finish(BackendRecord("auto", "cpu", "embed_mismatch", true, version, false))
        }
        if (mali && !isolated) {
            return finish(BackendRecord("auto", "cpu", "mali_unproven", true, version, false))
        }
        if (mali) {
            if (gpuSpeedStatus == 2) {
                return finish(BackendRecord("auto", "cpu", "speed_timeout", true, version, false))
            }
            if (gpuSpeedStatus != 0) {
                val reason = if (gpuSpeedStatus < 0) "speed_unknown" else "speed_exit"
                return finish(BackendRecord("auto", "cpu", reason, true, version, false))
            }
            if (gpuDecodeTps <= 0.0 || cpuDecodeTps <= 0.0) {
                return finish(BackendRecord("auto", "cpu", "speed_unknown", true, version, false))
            }
            if (gpuDecodeTps <= cpuDecodeTps) {
                return finish(BackendRecord("auto", "cpu", "gpu_slower", true, version, false))
            }
            return finish(BackendRecord("auto", "vulkan", "matched_faster", true, version, false))
        }
        return finish(BackendRecord("auto", "vulkan", "matched", true, version, false))
    }

    private fun tpsText(value: Double): String {
        if (value <= 0.0 || !value.isFinite()) return "未测"
        return "%.1f".format(Locale.US, value)
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
            appendLine("GPU 预填充 tok/s: ${tpsText(facts.gpuPrefillTps)}")
            appendLine("GPU 解码 tok/s: ${tpsText(facts.gpuDecodeTps)}")
            appendLine("CPU 预填充 tok/s: ${tpsText(facts.cpuPrefillTps)}")
            appendLine("CPU 解码 tok/s: ${tpsText(facts.cpuDecodeTps)}")
            appendLine("Vulkan 设备: ${facts.vkName.ifBlank { "未知" }}")
            appendLine("Vulkan 驱动: ${facts.vkDriverVersion.ifBlank { "未知" }}")
            appendLine("Vulkan 子组: ${if (facts.vkSubgroup > 0) facts.vkSubgroup.toString() else "未知"}")
            appendLine("Vulkan 特性: ${facts.vkFlags.ifBlank { "未知" }}")
            if (facts.crashes.isNotBlank()) {
                appendLine(facts.crashes.trimEnd())
            }
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
            .put("gpu_prefill_tps", facts.gpuPrefillTps)
            .put("gpu_decode_tps", facts.gpuDecodeTps)
            .put("cpu_prefill_tps", facts.cpuPrefillTps)
            .put("cpu_decode_tps", facts.cpuDecodeTps)
            .put("vk_name", facts.vkName)
            .put("vk_driver", facts.vkDriver)
            .put("vk_driver_version", facts.vkDriverVersion)
            .put("vk_subgroup", facts.vkSubgroup)
            .put("vk_flags", facts.vkFlags)
    }
}

data class BackendRecord(
    val mode: String,
    val probe: String,
    val reason: String,
    val probed: Boolean,
    val version: String,
    val checking: Boolean,
    val gpuPrefillTps: Double = 0.0,
    val gpuDecodeTps: Double = 0.0,
    val cpuPrefillTps: Double = 0.0,
    val cpuDecodeTps: Double = 0.0,
    val vkName: String = "",
    val vkDriver: String = "",
    val vkDriverVersion: String = "",
    val vkSubgroup: Int = 0,
    val vkFlags: String = "",
    val glRenderer: String = "",
    val mali: Boolean = false,
    val isolated: Boolean = false,
)

data class VulkanCaps(
    val name: String = "",
    val driver: String = "",
    val driverInfo: String = "",
    val driverVersion: Long = 0,
    val vendor: Long = 0,
    val subgroup: Int = 0,
    val fp16: Int = -1,
    val bf16: Int = -1,
    val coopmat: Int = -1,
    val coopmat2: Int = -1,
    val intDot: Int = -1,
    val uma: Int = -1,
    val maxAlloc: Long = 0,
    val maxBuffer: Long = 0,
    val suballoc: Long = 0,
    val storageBuffers: Int = 0,
    val wgInvocations: Int = 0,
    val mali: Int = 0,
) {
    fun versionText(): String {
        val info = driverInfo.ifBlank { driver }
        return if (driverVersion > 0) "$info ($driverVersion)" else info
    }

    fun flags(): String {
        if (vendor == 0L && name.isEmpty()) return ""
        return "fp16=$fp16 bf16=$bf16 coopmat=$coopmat coopmat2=$coopmat2 int_dot=$intDot uma=$uma max_alloc=$maxAlloc max_buffer=$maxBuffer suballoc=$suballoc storage_buffers=$storageBuffers wg_invocations=$wgInvocations"
    }
}

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
    val gpuPrefillTps: Double = 0.0,
    val gpuDecodeTps: Double = 0.0,
    val cpuPrefillTps: Double = 0.0,
    val cpuDecodeTps: Double = 0.0,
    val vkName: String = "",
    val vkDriver: String = "",
    val vkDriverVersion: String = "",
    val vkSubgroup: Int = 0,
    val vkFlags: String = "",
    val crashes: String = "",
)
