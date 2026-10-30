package com.lorabge.memory

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import org.json.JSONObject
import java.io.File

/** Same integers as ActivityManager.ApplicationExitInfo. */
const val TRAIN_EXIT_UNKNOWN = 0
const val TRAIN_EXIT_SELF = 1
const val TRAIN_EXIT_SIGNALED = 2
const val TRAIN_EXIT_LOW_MEMORY = 3
const val TRAIN_EXIT_CRASH = 4
const val TRAIN_EXIT_CRASH_NATIVE = 5
const val TRAIN_EXIT_ANR = 6
const val TRAIN_EXIT_EXCESSIVE = 9

data class TrainConfig(
    val rank: Int,
    val seqLen: Int,
    val batch: Int,
    val gradAccum: Int,
    val backend: String,
    val threads: Int,
    val chatReleased: Boolean = false,
    val startedMs: Long = 0,
)

data class TrainExit(
    val reason: Int,
    val reasonName: String,
    val status: Int,
    val description: String,
    val importance: Int,
    val pssKb: Long,
    val rssKb: Long,
    val timestampMs: Long,
    val process: String,
)

fun trainConfigOf(recipe: TrainRecipe, jobRank: Int, batch: Int = 1, startedMs: Long = 0, chatReleased: Boolean = false): TrainConfig {
    val rank = if (recipe.rank > 0) recipe.rank else jobRank
    return TrainConfig(
        rank = rank,
        seqLen = recipe.seqCap,
        batch = batch,
        gradAccum = recipe.gradAccum,
        backend = "CPU",
        threads = recipe.threads,
        chatReleased = chatReleased,
        startedMs = startedMs,
    )
}

fun trainConfigJson(config: TrainConfig, updated: String = ""): String {
    return JSONObject()
        .put("rank", config.rank)
        .put("seq", config.seqLen)
        .put("batch", config.batch)
        .put("gradAccum", config.gradAccum)
        .put("backend", config.backend)
        .put("threads", config.threads)
        .put("chatReleased", config.chatReleased)
        .put("startedMs", config.startedMs)
        .put("updated", updated)
        .toString()
}

fun parseTrainConfig(raw: String): TrainConfig? {
    val obj = runCatching { JSONObject(raw) }.getOrNull() ?: return null
    if (!obj.has("rank") && !obj.has("threads")) return null
    return TrainConfig(
        rank = obj.optInt("rank"),
        seqLen = obj.optInt("seq"),
        batch = obj.optInt("batch", 1),
        gradAccum = obj.optInt("gradAccum", 1),
        backend = obj.optString("backend").ifBlank { "CPU" },
        threads = obj.optInt("threads"),
        chatReleased = obj.optBoolean("chatReleased"),
        startedMs = obj.optLong("startedMs"),
    )
}

fun trainExitReasonName(reason: Int): String = when (reason) {
    TRAIN_EXIT_UNKNOWN -> "UNKNOWN"
    TRAIN_EXIT_SELF -> "EXIT_SELF"
    TRAIN_EXIT_SIGNALED -> "SIGNALED"
    TRAIN_EXIT_LOW_MEMORY -> "LOW_MEMORY"
    TRAIN_EXIT_CRASH -> "CRASH"
    TRAIN_EXIT_CRASH_NATIVE -> "CRASH_NATIVE"
    TRAIN_EXIT_ANR -> "ANR"
    TRAIN_EXIT_EXCESSIVE -> "EXCESSIVE_RESOURCE_USAGE"
    else -> "REASON_$reason"
}

fun importanceLabel(importance: Int): String = when (importance) {
    100 -> "FOREGROUND"
    125 -> "FOREGROUND_SERVICE"
    200 -> "VISIBLE"
    230 -> "PERCEPTIBLE"
    300 -> "SERVICE"
    325 -> "TOP_SLEEPING"
    400 -> "CACHED"
    1000 -> "GONE"
    else -> ""
}

fun trainKilledForMemory(exit: TrainExit): Boolean {
    if (exit.reason == TRAIN_EXIT_LOW_MEMORY) return true
    val desc = exit.description.lowercase()
    return desc.contains("lmk") || desc.contains("low memory") || desc.contains("lowmemory")
}

/** Plain sentence for the failure card. Technical fields stay in the diagnostics export. */
fun trainFailurePhrase(exit: TrainExit?): String {
    if (exit == null || exit.reason == TRAIN_EXIT_SELF) return trainDeadDetail()
    if (trainKilledForMemory(exit)) return "内存不足被系统终止"
    if (exit.reason == TRAIN_EXIT_EXCESSIVE) return "占用过高被系统终止"
    if (exit.reason == TRAIN_EXIT_ANR) return "训练进程没有响应"
    if (exit.reason == TRAIN_EXIT_CRASH || exit.reason == TRAIN_EXIT_CRASH_NATIVE) return "训练进程崩溃"
    if (exit.reason == TRAIN_EXIT_SIGNALED) {
        return when (exit.status) {
            9 -> "内存不足被系统终止"
            11, 6, 7 -> "训练进程崩溃"
            else -> "训练进程被系统终止"
        }
    }
    return "训练进程被系统终止"
}

/**
 * The trainer child is not an app process, so ActivityManager often has no row for it.
 * SIGKILL with no native crash line is the low-memory killer on this phone.
 */
fun exitFromChildCode(code: Int, nowMs: Long = 0L): TrainExit? {
    val sig = when {
        code > 128 -> code - 128
        code == 9 -> 9
        else -> return null
    }
    if (sig <= 0 || sig > 64) return null
    val memory = sig == 9
    return TrainExit(
        reason = if (memory) TRAIN_EXIT_LOW_MEMORY else TRAIN_EXIT_SIGNALED,
        reasonName = if (memory) "LOW_MEMORY" else "SIGNALED",
        status = sig,
        description = if (memory) "trainer child SIGKILL" else "trainer child signal $sig",
        importance = 0,
        pssKb = 0,
        rssKb = 0,
        timestampMs = nowMs,
        process = "libtrain-mft",
    )
}

fun trainExitJson(exit: TrainExit): String {
    return JSONObject()
        .put("reason", exit.reason)
        .put("reasonName", exit.reasonName)
        .put("status", exit.status)
        .put("description", exit.description)
        .put("importance", exit.importance)
        .put("pssKb", exit.pssKb)
        .put("rssKb", exit.rssKb)
        .put("timestampMs", exit.timestampMs)
        .put("process", exit.process)
        .toString()
}

fun parseTrainExit(raw: String): TrainExit? {
    val obj = runCatching { JSONObject(raw) }.getOrNull() ?: return null
    if (!obj.has("reason") && !obj.has("reasonName")) return null
    val reason = obj.optInt("reason")
    return TrainExit(
        reason = reason,
        reasonName = obj.optString("reasonName").ifBlank { trainExitReasonName(reason) },
        status = obj.optInt("status"),
        description = obj.optString("description"),
        importance = obj.optInt("importance"),
        pssKb = obj.optLong("pssKb"),
        rssKb = obj.optLong("rssKb"),
        timestampMs = obj.optLong("timestampMs"),
        process = obj.optString("process"),
    )
}

fun pickTrainExit(records: List<TrainExit>, fallback: TrainExit?, processSuffix: String, notBeforeMs: Long): TrainExit? {
    val mine = records.filter { exit ->
        exit.process.endsWith(processSuffix) && (notBeforeMs <= 0L || exit.timestampMs >= notBeforeMs - 5_000L)
    }
    val newest = mine.maxByOrNull { it.timestampMs }
    if (fallback != null && fallback.reason == TRAIN_EXIT_SELF) {
        if (newest != null && newest.reason != TRAIN_EXIT_SIGNALED && newest.reason != TRAIN_EXIT_SELF) return newest
        return fallback
    }
    if (newest != null && (fallback == null || newest.timestampMs >= fallback.timestampMs)) return newest
    return fallback ?: newest
}

fun observedMaxLen(log: String): Int? {
    return Regex("""max_len=(\d+)""").findAll(log).mapNotNull { it.groupValues[1].toIntOrNull() }.lastOrNull()
}

fun tailText(text: String, lines: Int = 40, maxChars: Int = 4000): String {
    val kept = text.lineSequence().map { it.trimEnd() }.filter { it.isNotBlank() }.toList().takeLast(lines)
    val joined = kept.joinToString("\n")
    if (joined.length <= maxChars) return joined
    return joined.takeLast(maxChars)
}

fun renderTrainSection(config: TrainConfig?, snap: TrainSnapshot, exit: TrainExit?, logTail: String): String {
    val longest = observedMaxLen(logTail)
    return buildString {
        appendLine("训练")
        if (config == null && snap.state.isBlank() && snap.step <= 0 && snap.loss == null && exit == null && logTail.isBlank()) {
            appendLine("无记录")
            return@buildString
        }
        if (config != null) {
            val seq = when {
                config.seqLen > 0 -> config.seqLen.toString()
                longest != null -> longest.toString()
                else -> "未限制"
            }
            appendLine("秩: ${config.rank}")
            appendLine("序列: $seq")
            appendLine("批大小: ${config.batch}")
            appendLine("累积: ${config.gradAccum}")
            appendLine("后端: ${config.backend}")
            appendLine("线程: ${config.threads}")
            appendLine("对话与 Vulkan: ${if (config.chatReleased) "已卸下" else "未卸下"}")
        } else {
            appendLine("配置: 无")
        }
        if (snap.state.isNotBlank() || snap.step > 0 || snap.loss != null) {
            val loss = snap.loss?.let { " · loss ${String.format(java.util.Locale.US, "%.4f", it)}" }.orEmpty()
            val epoch = if (snap.epochs > 0 && snap.epoch > 0) " · 第 ${snap.epoch}/${snap.epochs} 轮" else ""
            val step = if (snap.total > 0) "第 ${snap.step}/${snap.total} 步" else "第 ${snap.step} 步"
            appendLine("进度: $step$epoch$loss")
            appendLine("状态: ${snap.state}")
        } else {
            appendLine("进度: 无")
        }
        appendLine("进度时间: ${snap.updated.ifBlank { "无" }}")
        if (exit != null) {
            val importance = importanceLabel(exit.importance).let { if (it.isBlank()) "" else " $it" }
            appendLine(
                "退出: ${exit.reasonName} reason=${exit.reason} signal=${exit.status} importance=${exit.importance}$importance 峰值RSS=${exit.rssKb}KB 峰值PSS=${exit.pssKb}KB",
            )
            appendLine("退出说明: ${exit.description.ifBlank { "无" }}")
            appendLine("退出进程: ${exit.process.ifBlank { "无" }}")
        } else {
            appendLine("退出: 无")
        }
        appendLine("日志:")
        appendLine(if (logTail.isBlank()) "无" else logTail.trimEnd())
    }
}

fun readHistoricalTrainExits(context: Context): List<TrainExit> {
    if (Build.VERSION.SDK_INT < 30) return emptyList()
    return try {
        val manager = context.getSystemService(ActivityManager::class.java) ?: return emptyList()
        manager.getHistoricalProcessExitReasons(context.packageName, 0, 20).map { info ->
            TrainExit(
                reason = info.reason,
                reasonName = trainExitReasonName(info.reason),
                status = info.status,
                description = info.description.orEmpty(),
                importance = info.importance,
                pssKb = info.pss,
                rssKb = info.rss,
                timestampMs = info.timestamp,
                process = info.processName.orEmpty(),
            )
        }
    } catch (_: Throwable) {
        emptyList()
    }
}

fun loadTrainReport(trainDir: File, live: List<TrainExit> = emptyList()): String {
    val config = File(trainDir, "config.json").takeIf { it.exists() }?.readText()?.let { parseTrainConfig(it) }
    val statusRaw = File(trainDir, "status.json").takeIf { it.exists() }?.readText().orEmpty()
    val snap = parseTrainSnapshot(statusRaw)
    val stored = File(trainDir, "exit.json").takeIf { it.exists() }?.readText()?.let { parseTrainExit(it) }
    val started = config?.startedMs ?: 0L
    val exit = pickTrainExit(live, stored, ":train", started)
    val log = File(trainDir, "train.log").takeIf { it.exists() }?.readText().orEmpty()
    return renderTrainSection(config, snap, exit, tailText(log))
}
