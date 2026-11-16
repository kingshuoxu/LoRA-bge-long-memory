package com.lorabge.memory

/**
 * UI 进程侧的调用。worker 代表 :llm 进程。它死了就记一笔,坏掉的 GPU 驱动改走 CPU,同一条请求只重试一次。
 */
class LlmSupervisor(
    private val guard: LlmGuard,
    private val open: (backend: String) -> LlmWorker,
) {
    fun call(
        stage: String,
        preferred: String,
        driverKey: String,
        payload: String,
        onText: (String) -> Unit = {},
    ): String {
        var backend = preferred.ifBlank { "cpu" }
        if (backend != "cpu" && guard.isBad(backend, driverKey)) backend = "cpu"
        var retried = false
        while (true) {
            val worker = open(backend)
            try {
                return worker.call(stage, backend, payload, onText)
            } catch (dead: WorkerDied) {
                val usedStage = dead.stage.ifBlank { stage }
                val usedBackend = dead.backend.ifBlank { backend }
                val decision = guard.onDeath(usedStage, usedBackend, driverKey, dead.signal, dead.detail)
                if (decision.retryOnCpu && !retried && backend != "cpu") {
                    retried = true
                    backend = "cpu"
                    continue
                }
                throw dead
            } finally {
                worker.close()
            }
        }
    }
}

interface LlmWorker {
    fun call(stage: String, backend: String, payload: String, onText: (String) -> Unit): String
    fun close() {}
}

class WorkerDied(val signal: String, val detail: String, val stage: String, val backend: String = "") : RuntimeException(detail)

/** Training asked the chat model to stay unloaded. This is not a GPU fault. */
class ChatParked : RuntimeException("parked")
