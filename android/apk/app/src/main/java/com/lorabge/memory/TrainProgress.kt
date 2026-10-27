package com.lorabge.memory

import org.json.JSONObject

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

fun trainQuietTooLong(lastAdvanceMs: Long, nowMs: Long, stallMs: Long = TRAIN_STALL_MS): Boolean {
    if (lastAdvanceMs < 0 || nowMs < lastAdvanceMs) return false
    return nowMs - lastAdvanceMs >= stallMs
}

/** After the last logged step the process writes the adapter and may be quiet. */
fun trainStillExpected(step: Int, total: Int): Boolean = total <= 0 || step < total

fun trainStallDetail(lastLine: String): String {
    val head = "超过 3 分钟没有新的训练输出，这一步没有打出 loss。点「确认并训练」重试，或点「取消训练」。"
    val where = lastLine.trim().take(180)
    return if (where.isEmpty()) head else "$head\n停在: $where"
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
): String {
    val epoch = epochOf(step, total, epochs)
    val eta = etaSeconds(elapsedSec, step, total)
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
        .apply { if (loss != null) put("loss", loss.toDouble()) }
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
    )
}

fun formatTrainProgress(lang: String, snap: TrainSnapshot): String {
    if (snap.state == "error") {
        val head = if (lang == "en") "Failed" else "失败"
        val tail = snap.logTail.ifBlank { snap.detail }
        return if (tail.isBlank()) head else "$head\n$tail"
    }
    if (snap.step <= 0) {
        if (snap.state == "running" && snap.micro > 0 && snap.microTotal > 0 && snap.pendingStep > 0) {
            val steps = if (snap.total > 0) {
                if (lang == "en") "Step ${snap.pendingStep}/${snap.total}" else "第 ${snap.pendingStep}/${snap.total} 步"
            } else {
                if (lang == "en") "Step ${snap.pendingStep}" else "第 ${snap.pendingStep} 步"
            }
            val micro = if (lang == "en") " · micro ${snap.micro}/${snap.microTotal}" else " · 微批 ${snap.micro}/${snap.microTotal}"
            val elapsed = if (snap.elapsedSec > 0) {
                if (lang == "en") " · ${snap.elapsedSec}s" else " · 已过 ${snap.elapsedSec} 秒"
            } else {
                ""
            }
            return steps + micro + elapsed
        }
        if (snap.state == "running") {
            return if (lang == "en") "Still computing this step · ${snap.elapsedSec}s" else "这一步还在计算 · 已过 ${snap.elapsedSec} 秒"
        }
        return snap.detail
    }
    val loss = snap.loss?.let { " · loss ${"%.2f".format(it)}" }.orEmpty()
    val eta = when {
        snap.etaSec <= 0 -> ""
        snap.etaSec < 60 -> if (lang == "en") " · ETA ${snap.etaSec}s" else " · 剩余 ${snap.etaSec} 秒"
        else -> {
            val minutes = (snap.etaSec + 59) / 60
            if (lang == "en") " · ETA ${minutes} min" else " · 剩余 ${minutes} 分"
        }
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
    return steps + micro + epoch + loss + elapsed + eta
}
