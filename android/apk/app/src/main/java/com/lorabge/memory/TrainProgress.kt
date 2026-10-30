package com.lorabge.memory

import org.json.JSONObject
import java.io.File

data class TrainSnapshot(
    val state: String = "",
    val stage: String = "",
    val step: Int = 0,
    val total: Int = 0,
    val epoch: Int = 0,
    val epochs: Int = 0,
    val loss: Float? = null,
    val elapsedSec: Long = 0,
    val etaSec: Long = 0,
    val detail: String = "",
    val logTail: String = "",
    val pendingStep: Int = 0,
    val micro: Int = 0,
    val microTotal: Int = 0,
    val microElapsedSec: Long = 0,
    val updated: String = "",
)

fun parseStepLine(line: String): Triple<Int, Int, Float>? {
    val match = Regex("""\[step\s+(\d+)\s*/\s*(\d+)\].*?loss=([0-9]*\.?[0-9]+)""").find(line) ?: return null
    val loss = match.groupValues[3].toFloatOrNull() ?: return null
    return Triple(match.groupValues[1].toInt(), match.groupValues[2].toInt(), loss)
}

data class MicroMark(val micro: Int, val microTotal: Int, val pendingStep: Int, val total: Int)

/** Printed before each forward. `[Dataset] epochs=4 max_steps=8` is not a step. */
fun parseMicroLine(line: String): MicroMark? {
    val match = Regex("""\[micro\s+(\d+)\s*/\s*(\d+)\].*?step\s+(\d+)\s*/\s*(\d+)""").find(line) ?: return null
    val micro = match.groupValues[1].toIntOrNull() ?: return null
    val microTotal = match.groupValues[2].toIntOrNull() ?: return null
    val pending = match.groupValues[3].toIntOrNull() ?: return null
    val total = match.groupValues[4].toIntOrNull() ?: return null
    if (micro <= 0 || microTotal <= 0 || pending <= 0 || total <= 0) return null
    if (micro > microTotal || pending > total) return null
    return MicroMark(micro, microTotal, pending, total)
}

/** No new trainer line for this long means the process is not advancing. */
const val TRAIN_STALL_MS = 180_000L

/**
 * `[facts]` is printed after tokenization and before the weights load.
 * That load is quiet. A line here is not a training step.
 */
fun isTrainSetupLine(line: String): Boolean {
    val text = line.trim()
    return text.startsWith("[facts]") ||
        text.startsWith("[Config]") ||
        text.startsWith("[Dataset]") ||
        text.startsWith("[LoRA]") ||
        text.startsWith("[load]") ||
        text.startsWith("开始训练") ||
        text.startsWith("生成样本") ||
        text.startsWith("抽取事实") ||
        text.startsWith("写闸门")
}

/** Resident set moved enough that the silent loader is still doing work. */
fun rssMoved(previousKb: Long, currentKb: Long): Boolean {
    if (currentKb <= 0L) return false
    if (previousKb <= 0L) return true
    return kotlin.math.abs(currentKb - previousKb) >= 256L
}

fun trainLoadHeartbeat(elapsedSec: Long, rssKb: Long): String {
    val mem = if (rssKb > 0L) " · 内存 ${rssKb / 1024} MB" else ""
    return "正在加载模型 · 已过 ${elapsedSec} 秒$mem"
}

fun trainLoadStallDetail(@Suppress("UNUSED_PARAMETER") lastLine: String): String {
    return "加载模型没有进展。点「重试」再试一次，或点「放弃」。"
}

/** Failure before any loss should not keep a curve from an older log. */
fun lossChartValues(snap: TrainSnapshot, parsed: List<Float>): List<Float> {
    if (snap.state == "error" && snap.step <= 0 && snap.loss == null) return emptyList()
    return parsed
}

fun trainActionsOpen(training: Boolean, snap: TrainSnapshot): Boolean {
    return training || snap.state == "running" || snap.state == "error" || snap.state == "waiting"
}

fun trainQuietTooLong(lastAdvanceMs: Long, nowMs: Long, stallMs: Long = TRAIN_STALL_MS): Boolean {
    if (lastAdvanceMs < 0 || nowMs < lastAdvanceMs) return false
    return nowMs - lastAdvanceMs >= stallMs
}

/** After the last logged step the process writes the adapter and may be quiet. */
fun trainStillExpected(step: Int, total: Int): Boolean = total <= 0 || step < total

/**
 * One microbatch printed `[micro]` and then the native forward never returned.
 * 45s is long enough for a real 0.5B step on two big cores, and short enough
 * that a deadlock is not left on screen for the old 3-minute stall.
 */
const val MICRO_STALL_MS = 45_000L

/** The service writes this file every couple of seconds. A frozen process stops. */
const val TRAIN_HEARTBEAT_STALE_MS = 20_000L

data class TrainRecipe(
    val threads: Int,
    val gradAccum: Int,
    val attempt: Int,
    val rank: Int = 0,
    val seqCap: Int = 0,
)

/** First try is already CPU. Two threads, and the trainer drops the tape after every sample. */
fun initialTrainRecipe(performanceThreads: Int): TrainRecipe {
    return TrainRecipe(threads = performanceThreads.coerceIn(1, 2), gradAccum = 4, attempt = 0)
}

/**
 * A hung step retries on one CPU thread. If that still dies, the next attempt
 * updates every sample, caps the sequence, and shrinks the rank.
 */
fun lighterTrainRecipe(current: TrainRecipe): TrainRecipe? {
    if (current.threads > 1 || current.gradAccum > 2) {
        return TrainRecipe(threads = 1, gradAccum = 2, attempt = current.attempt + 1)
    }
    if (current.gradAccum > 1 || current.seqCap <= 0) {
        return TrainRecipe(threads = 1, gradAccum = 1, attempt = current.attempt + 1, rank = 8, seqCap = 64)
    }
    return null
}

fun microStalled(lastMicroMs: Long, nowMs: Long, seenMicro: Boolean, stallMs: Long = MICRO_STALL_MS): Boolean {
    if (!seenMicro || lastMicroMs < 0 || nowMs < lastMicroMs) return false
    return nowMs - lastMicroMs >= stallMs
}

fun trainRetryDetail(threads: Int): String {
    return "这一微批超过 45 秒没有新输出，改用 $threads 个 CPU 线程重试"
}

fun trainRetryDetail(recipe: TrainRecipe): String {
    if (recipe.seqCap > 0 && recipe.gradAccum <= 1) {
        return "这一微批还是没有往前走。改成 1 个线程，句子收到 ${recipe.seqCap}，秩 ${recipe.rank}，每条样本都放开计算图"
    }
    return trainRetryDetail(recipe.threads)
}

/** Replace flags in the trainer argv. rank 0 and seqCap 0 keep the job's own values. */
fun applyTrainRecipe(args: MutableList<String>, recipe: TrainRecipe, jobRank: Int) {
    fun setFlag(flag: String, value: String) {
        val at = args.indexOf(flag)
        if (at >= 0 && at + 1 < args.size) {
            args[at + 1] = value
        } else {
            args.add(flag)
            args.add(value)
        }
    }
    fun clearFlag(flag: String) {
        val at = args.indexOf(flag)
        if (at >= 0 && at + 1 < args.size) {
            args.removeAt(at + 1)
            args.removeAt(at)
        }
    }
    setFlag("--grad_accum_steps", recipe.gradAccum.toString())
    val rank = if (recipe.rank > 0) recipe.rank else jobRank
    setFlag("--lora_r", rank.toString())
    setFlag("--lora_alpha", (rank * 2).toString())
    if (recipe.seqCap > 0) setFlag("--seq_cap", recipe.seqCap.toString()) else clearFlag("--seq_cap")
}

/**
 * status.json is replaced in place. A reader can see an empty or cut-off file.
 * Write the temp file in the same directory, then rename, so a poll never
 * observes the truncate.
 */
fun writeTextAtomic(file: File, text: String) {
    val dir = file.parentFile ?: throw IllegalArgumentException(file.path)
    dir.mkdirs()
    val tmp = File(dir, file.name + ".tmp")
    tmp.writeText(text)
    if (file.exists()) file.delete()
    if (!tmp.renameTo(file)) {
        file.writeText(text)
        tmp.delete()
    }
}

/**
 * What the consolidate page actually paints. A failure card does not show
 * elapsed seconds, so a rewrite of those fields is not a new frame.
 */
fun trainFrameKey(snap: TrainSnapshot): String {
    val live = snap.state == "running"
    return listOf(
        snap.state,
        snap.stage,
        snap.step.toString(),
        snap.total.toString(),
        snap.epoch.toString(),
        snap.epochs.toString(),
        snap.loss?.let { java.lang.Float.toString(it) } ?: "",
        snap.detail,
        snap.logTail,
        snap.pendingStep.toString(),
        snap.micro.toString(),
        snap.microTotal.toString(),
        (if (live) snap.elapsedSec else 0L).toString(),
        (if (live) snap.etaSec else 0L).toString(),
        (if (live) snap.microElapsedSec else 0L).toString(),
    ).joinToString("\u0000")
}

/**
 * One poll of status.json. Null means the page must not recompose: the read
 * was empty or cut off, the visible frame is unchanged, or a blank "running"
 * reset is trying to cover a failure the user is already looking at.
 * A missing file is the user tapping 放弃, so the failure card has to go.
 * An empty read of a file that is still there is a torn write, and is ignored.
 */
fun acceptTrainStatus(previous: TrainSnapshot, raw: String, fileExists: Boolean = true): TrainSnapshot? {
    if (!fileExists) {
        val cleared = TrainSnapshot()
        return if (trainFrameKey(cleared) == trainFrameKey(previous)) null else cleared
    }
    val trimmed = raw.trim()
    if (trimmed.isEmpty()) return null
    if (runCatching { JSONObject(trimmed) }.isFailure) return null
    val next = parseTrainSnapshot(trimmed)
    if (next.state.isEmpty() && previous.state.isNotEmpty()) return null
    if (previous.state == "error" && next.state == "running" && next.detail.isBlank() && next.step == 0 && next.micro == 0) {
        return null
    }
    if (trainFrameKey(next) == trainFrameKey(previous)) return null
    return next
}

/** The dead-trainer write runs once, while status still says the run is going. */
fun shouldRemarkFailedTrain(state: String): Boolean = state == "running"

fun isSettledFailure(raw: String): Boolean {
    val snap = parseTrainSnapshot(raw)
    return snap.state == "error" && snap.detail.isNotBlank()
}

fun trainDeadDetail(): String {
    return "训练进程已经停住。点「重试」再开始，或点「放弃」。"
}

/**
 * Running in the status file is not proof the trainer is alive.
 * A pid that existed and is gone is a dead trainer. No pid yet means the
 * service has not spawned it; that is only a failure once the heartbeat stops.
 */
fun trainRunIsStale(
    state: String,
    pidAlive: Boolean,
    heartbeatAgeMs: Long,
    limitMs: Long = TRAIN_HEARTBEAT_STALE_MS,
    pidKnown: Boolean = true,
): Boolean {
    if (state != "running") return false
    if (pidKnown && !pidAlive) return true
    if (heartbeatAgeMs < 0) return false
    return heartbeatAgeMs >= limitMs
}

fun finishedMicros(completedSteps: Int, microIndex: Int, microTotal: Int): Int {
    if (microTotal <= 0) return completedSteps.coerceAtLeast(0)
    val into = (microIndex - 1).coerceAtLeast(0)
    return completedSteps.coerceAtLeast(0) * microTotal + into
}

fun etaFromMicros(elapsedSec: Long, finished: Int, totalMicros: Int): Long {
    if (elapsedSec <= 0 || finished <= 0 || totalMicros <= finished) return 0
    return elapsedSec * (totalMicros - finished) / finished
}

fun trainStallDetail(pendingStep: Int, micro: Int): String {
    val head = "这一微批没有再往前走。点「重试」再训一次，或点「放弃」。"
    if (pendingStep <= 0 || micro <= 0) return head
    return "$head\n停在第 $pendingStep 步的第 $micro 个微批"
}

/** The trainer has logged a micro of a step that does not have a loss line yet. */
fun countingMicro(snap: TrainSnapshot): Boolean {
    if (snap.pendingStep <= snap.step || snap.pendingStep <= 0 || snap.microTotal <= 0) return false
    return snap.micro > 0 || snap.step <= 0
}

fun trainFraction(snap: TrainSnapshot): Float {
    if (snap.total <= 0) return 0f
    if (countingMicro(snap)) {
        val into = (snap.pendingStep - 1) + snap.micro.toFloat() / snap.microTotal
        return (into / snap.total).coerceIn(0f, 1f)
    }
    if (snap.step > 0) return (snap.step.toFloat() / snap.total).coerceIn(0f, 1f)
    return 0f
}

fun epochOf(step: Int, total: Int, epochs: Int): Int {
    if (step <= 0 || total <= 0 || epochs <= 0) return 0
    val per = (total + epochs - 1) / epochs
    if (per <= 0) return 0
    return ((step - 1) / per + 1).coerceAtMost(epochs)
}

private fun liveMicro(snap: TrainSnapshot): Boolean {
    return snap.pendingStep > snap.step && snap.micro > 0 && snap.microTotal > 0
}

fun etaPhrase(lang: String, etaSec: Long): String {
    return when {
        etaSec <= 0 -> ""
        etaSec < 60 -> if (lang == "en") " · ETA ${etaSec}s" else " · 剩余 ${etaSec} 秒"
        else -> {
            val minutes = (etaSec + 59) / 60
            if (lang == "en") " · ETA ${minutes} min" else " · 剩余 ${minutes} 分"
        }
    }
}

fun etaSeconds(elapsedSec: Long, step: Int, total: Int): Long {
    if (elapsedSec < 0 || step <= 0 || total <= step) return 0
    return elapsedSec * (total - step) / step
}

fun trainSnapshotJson(
    state: String,
    stage: String,
    step: Int,
    total: Int,
    epochs: Int,
    loss: Float?,
    elapsedSec: Long,
    detail: String,
    logTail: String,
    pendingStep: Int = 0,
    micro: Int = 0,
    microTotal: Int = 0,
    microElapsedSec: Long = 0,
    updated: String = "",
): String {
    val epoch = epochOf(step, total, epochs)
    val finished = finishedMicros((pendingStep - 1).coerceAtLeast(0), micro, microTotal)
    val totalMicros = if (total > 0 && microTotal > 0) total * microTotal else 0
    val eta = if (totalMicros > 0) etaFromMicros(elapsedSec, finished, totalMicros) else etaSeconds(elapsedSec, step, total)
    return JSONObject()
        .put("state", state)
        .put("stage", stage)
        .put("step", step)
        .put("total", total)
        .put("epoch", epoch)
        .put("epochs", epochs)
        .put("elapsedSec", elapsedSec)
        .put("etaSec", eta)
        .put("detail", detail)
        .put("logTail", logTail)
        .put("pendingStep", pendingStep)
        .put("micro", micro)
        .put("microTotal", microTotal)
        .put("microElapsedSec", microElapsedSec)
        .apply {
            if (loss != null) put("loss", loss.toDouble())
            if (updated.isNotBlank()) put("updated", updated)
        }
        .toString()
}

fun parseTrainSnapshot(raw: String): TrainSnapshot {
    val trimmed = raw.trim()
    if (trimmed.isEmpty()) return TrainSnapshot()
    val obj = runCatching { JSONObject(trimmed) }.getOrNull() ?: return TrainSnapshot(detail = trimmed)
    val loss = if (obj.has("loss")) obj.optDouble("loss").toFloat() else null
    return TrainSnapshot(
        state = obj.optString("state"),
        stage = obj.optString("stage"),
        step = obj.optInt("step"),
        total = obj.optInt("total"),
        epoch = obj.optInt("epoch"),
        epochs = obj.optInt("epochs"),
        loss = loss,
        elapsedSec = obj.optLong("elapsedSec"),
        etaSec = obj.optLong("etaSec"),
        detail = obj.optString("detail"),
        logTail = obj.optString("logTail"),
        pendingStep = obj.optInt("pendingStep"),
        micro = obj.optInt("micro"),
        microTotal = obj.optInt("microTotal"),
        microElapsedSec = obj.optLong("microElapsedSec"),
        updated = obj.optString("updated"),
    )
}

fun formatTrainProgress(lang: String, snap: TrainSnapshot): String {
    if (snap.state == "error") {
        val head = if (lang == "en") "Failed" else "失败"
        val tail = snap.logTail.ifBlank { snap.detail }
        return if (tail.isBlank()) head else "$head\n$tail"
    }
    // Step 4/4 is published before the expert is written. Only "done" means recall can see the fact.
    if (snap.state == "done") {
        val head = if (lang == "en") "Finished" else "已完成"
        val registered = if (snap.detail.contains("已登记") || snap.detail.contains("registered", ignoreCase = true)) {
            if (lang == "en") "Registered" else "已登记"
        } else {
            ""
        }
        return listOf(head, registered).filter { it.isNotBlank() }.joinToString(" · ")
    }
    if (snap.step <= 0) {
        if (snap.state == "running" && snap.micro > 0 && snap.microTotal > 0 && snap.pendingStep > 0) {
            val steps = if (snap.total > 0) {
                if (lang == "en") "Step ${snap.pendingStep}/${snap.total}" else "第 ${snap.pendingStep}/${snap.total} 步"
            } else {
                if (lang == "en") "Step ${snap.pendingStep}" else "第 ${snap.pendingStep} 步"
            }
            val micro = if (lang == "en") " · micro ${snap.micro}/${snap.microTotal}" else " · 微批 ${snap.micro}/${snap.microTotal}"
            val microAge = if (snap.microElapsedSec > 0) {
                if (lang == "en") " · this micro ${snap.microElapsedSec}s" else " · 这一微批 ${snap.microElapsedSec} 秒"
            } else {
                ""
            }
            val elapsed = if (snap.elapsedSec > 0) {
                if (lang == "en") " · ${snap.elapsedSec}s" else " · 已过 ${snap.elapsedSec} 秒"
            } else {
                ""
            }
            val eta = etaPhrase(lang, snap.etaSec)
            return steps + micro + microAge + elapsed + eta
        }
        if (snap.state == "running") {
            return if (lang == "en") "Still computing this step · ${snap.elapsedSec}s" else "这一步还在计算 · 已过 ${snap.elapsedSec} 秒"
        }
        return snap.detail
    }
    val loss = snap.loss?.let { " · loss ${"%.2f".format(it)}" }.orEmpty()
    val eta = etaPhrase(lang, snap.etaSec)
    val microAge = if (liveMicro(snap) && snap.microElapsedSec > 0) {
        if (lang == "en") " · this micro ${snap.microElapsedSec}s" else " · 这一微批 ${snap.microElapsedSec} 秒"
    } else {
        ""
    }
    val elapsed = if (snap.elapsedSec > 0) {
        if (lang == "en") " · ${snap.elapsedSec}s" else " · 已过 ${snap.elapsedSec} 秒"
    } else {
        ""
    }
    // A micro line means that step is the one on screen. The stored step is the last loss.
    val live = snap.pendingStep > snap.step && snap.micro > 0 && snap.microTotal > 0
    val shownStep = if (live) snap.pendingStep else snap.step
    val shownEpoch = if (live) epochOf(shownStep, snap.total, snap.epochs) else snap.epoch
    val steps = if (snap.total > 0) {
        if (lang == "en") "Step ${shownStep}/${snap.total}" else "第 ${shownStep}/${snap.total} 步"
    } else {
        if (lang == "en") "Step $shownStep" else "第 $shownStep 步"
    }
    val micro = if (live) {
        if (lang == "en") " · micro ${snap.micro}/${snap.microTotal}" else " · 微批 ${snap.micro}/${snap.microTotal}"
    } else {
        ""
    }
    val epoch = if (snap.epochs > 0 && shownEpoch > 0) {
        if (lang == "en") " · epoch ${shownEpoch}/${snap.epochs}" else " · 第 ${shownEpoch}/${snap.epochs} 轮"
    } else {
        ""
    }
    return steps + micro + microAge + epoch + loss + elapsed + eta
}
