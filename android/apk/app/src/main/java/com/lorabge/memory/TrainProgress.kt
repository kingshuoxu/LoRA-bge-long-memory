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
)

fun parseStepLine(line: String): Triple<Int, Int, Float>? {
    val match = Regex("""\[step\s+(\d+)\s*/\s*(\d+)\].*?loss=([0-9]*\.?[0-9]+)""").find(line) ?: return null
    val loss = match.groupValues[3].toFloatOrNull() ?: return null
    return Triple(match.groupValues[1].toInt(), match.groupValues[2].toInt(), loss)
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
    )
}

fun formatTrainProgress(lang: String, snap: TrainSnapshot): String {
    if (snap.state == "error") {
        val head = if (lang == "en") "Failed" else "失败"
        val tail = snap.logTail.ifBlank { snap.detail }
        return if (tail.isBlank()) head else "$head\n$tail"
    }
    if (snap.state == "running" && snap.step <= 0) {
        val waited = if (lang == "en") "Still computing this step · ${snap.elapsedSec}s" else "这一步还在计算 · 已过 ${snap.elapsedSec} 秒"
        return waited
    }
    if (snap.step <= 0 && snap.detail.isBlank()) return ""
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
    val steps = if (snap.total > 0) {
        if (lang == "en") "Step ${snap.step}/${snap.total}" else "第 ${snap.step}/${snap.total} 步"
    } else {
        if (lang == "en") "Step ${snap.step}" else "第 ${snap.step} 步"
    }
    val epoch = if (snap.epochs > 0 && snap.epoch > 0) {
        if (lang == "en") " · epoch ${snap.epoch}/${snap.epochs}" else " · 第 ${snap.epoch}/${snap.epochs} 轮"
    } else {
        ""
    }
    return steps + epoch + loss + elapsed + eta
}
