package com.lorabge.memory

import android.os.Process
import java.io.File

/**
 * The chat model and its Vulkan device live in :llm and in llama-cli children.
 * They stay mapped after a reply returns only while that process is still up.
 * Training's fp32 weights sit on top of them, and the low-memory killer then
 * takes the trainer. Release those processes before a run, and leave :train alone.
 */
object ChatRuntime {
    fun shouldReleaseForTrain(processName: String, cmdline: String): Boolean {
        val blob = "${processName.trim()} ${cmdline.trim()}"
        if (blob.isBlank()) return false
        if (blob.contains(":train") || blob.contains("libtrain-mft")) return false
        if (blob.contains(":llm")) return true
        if (blob.contains("libllama-cli") || blob.contains("llama-cli")) return true
        if (blob.contains("libllama-embedding") || blob.contains("llama-embedding")) return true
        return false
    }

    fun releaseHeldModels() {
        val self = Process.myPid()
        val uid = Process.myUid()
        for (pid in processIds()) {
            if (pid == self || pid <= 1) continue
            if (!shouldReleaseForTrain(commOf(pid), commandLine(pid))) continue
            if (uidOf(pid) != uid) continue
            runCatching { Process.killProcess(pid) }
        }
    }

    fun heldModelsAlive(): Boolean {
        val self = Process.myPid()
        val uid = Process.myUid()
        for (pid in processIds()) {
            if (pid == self || pid <= 1) continue
            if (!shouldReleaseForTrain(commOf(pid), commandLine(pid))) continue
            if (uidOf(pid) == uid) return true
        }
        return false
    }

    fun waitUntilReleased(attempts: Int = 25, pauseMs: Long = 100) {
        repeat(attempts) {
            releaseHeldModels()
            if (!heldModelsAlive()) {
                Thread.sleep(pauseMs)
                releaseHeldModels()
                if (!heldModelsAlive()) return
            }
            Thread.sleep(pauseMs)
        }
    }

    fun preferTrainer(pid: Int) {
        if (pid <= 0) return
        runCatching { File("/proc/$pid/oom_score_adj").writeText("0\n") }
    }

    private fun processIds(): List<Int> {
        return File("/proc").listFiles()?.mapNotNull { it.name.toIntOrNull() } ?: emptyList()
    }

    private fun commandLine(pid: Int): String {
        return File("/proc/$pid/cmdline").takeIf { it.canRead() }
            ?.readText()
            ?.replace('\u0000', ' ')
            ?.trim()
            .orEmpty()
    }

    private fun commOf(pid: Int): String {
        return File("/proc/$pid/comm").takeIf { it.canRead() }?.readText()?.trim().orEmpty()
    }

    private fun uidOf(pid: Int): Int {
        val text = File("/proc/$pid/status").takeIf { it.canRead() }?.readText().orEmpty()
        return Regex("""Uid:\s+(\d+)""").find(text)?.groupValues?.get(1)?.toIntOrNull() ?: -1
    }
}
