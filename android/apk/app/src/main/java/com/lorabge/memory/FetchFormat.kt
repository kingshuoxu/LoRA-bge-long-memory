package com.lorabge.memory

import java.util.Locale

fun formatBytes(bytes: Long): String {
    val n = bytes.coerceAtLeast(0)
    if (n < 1024) return "$n B"
    val kb = n / 1024.0
    if (kb < 1024) {
        return if (kb < 10) String.format(Locale.US, "%.1f KB", kb) else "${n / 1024} KB"
    }
    val mb = kb / 1024.0
    if (mb < 1024) {
        return if (mb < 10) String.format(Locale.US, "%.1f MB", mb) else "${n / (1024 * 1024)} MB"
    }
    return String.format(Locale.US, "%.2f GB", mb / 1024.0)
}

fun remainingEtaSeconds(remainingBytes: Long, speedBps: Long): Long {
    if (remainingBytes <= 0 || speedBps <= 0) return -1
    return remainingBytes / speedBps
}

fun formatEta(remainingBytes: Long, speedBps: Long, lang: String): String {
    val seconds = remainingEtaSeconds(remainingBytes, speedBps)
    if (seconds < 0) return if (lang == "en") "ETA —" else "剩余 —"
    if (seconds == 0L) return if (lang == "en") "ETA under 1s" else "不到 1 秒"
    if (seconds < 60) return if (lang == "en") "ETA ${seconds}s" else "剩余 ${seconds} 秒"
    val minutes = (seconds + 59) / 60
    return if (lang == "en") "ETA ${minutes} min" else "剩余 ${minutes} 分"
}

fun fileStateLabel(lang: String, state: String): String {
    val zh = mapOf(
        "running" to "下载中",
        "wait" to "等待",
        "done" to "完成",
        "paused" to "已暂停",
        "error" to "失败",
        "checking" to "校验中",
    )
    val en = mapOf(
        "running" to "downloading",
        "wait" to "waiting",
        "done" to "done",
        "paused" to "paused",
        "error" to "failed",
        "checking" to "checking",
    )
    return (if (lang == "en") en else zh)[state] ?: state
}

fun overallBytes(files: List<FileSnap>): Pair<Long, Long> {
    var got = 0L
    var total = 0L
    for (file in files) {
        got += file.bytes.coerceAtLeast(0)
        total += file.size.coerceAtLeast(0)
    }
    return got to total
}
