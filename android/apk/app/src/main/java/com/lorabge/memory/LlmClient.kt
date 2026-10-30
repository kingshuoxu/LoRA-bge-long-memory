package com.lorabge.memory

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** 界面进程只跟 :llm 说话。对方进程没了,就按 LlmGuard 改走 CPU 再问一次。 */
class LlmClient(context: Context) {
    private val app = context.applicationContext
    private val engine = Engine(app, MemoryStore(File(app.filesDir, "memory")).also { it.ensure() })
    private val guard = LlmGuard(File(app.filesDir, "setup/crashes.json"))
    private val replyThread = HandlerThread("llm-reply").apply { start() }
    private val remote = AtomicReference<Messenger?>(null)
    private val bindLock = Any()
    @Volatile private var bindLatch = CountDownLatch(0)
    @Volatile private var parked = false

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            remote.set(Messenger(binder))
            bindLatch.countDown()
        }

        override fun onServiceDisconnected(name: ComponentName) {
            remote.set(null)
        }
    }

    private val supervisor = LlmSupervisor(guard) { backend -> RemoteWorker(backend) }

    /** Drop :llm and any llama-cli / Vulkan child so training can use the RAM. */
    fun park() {
        parked = true
        synchronized(bindLock) {
            remote.set(null)
            try {
                app.unbindService(connection)
            } catch (_: Throwable) {
            }
            bindLatch.countDown()
        }
        try {
            app.stopService(Intent(app, LlmService::class.java))
        } catch (_: Throwable) {
        }
        ChatRuntime.waitUntilReleased()
    }

    /** Allow the next chat or route to load the model again. */
    fun resume() {
        parked = false
    }

    fun ensure() {
        if (parked) return
        settleGpuBan()
        if (guard.vulkanStrikes() >= 2) return
        if (!engine.needsGpuProbe()) return
        val key = engine.driverKey()
        if (engine.tool("libggml-vulkan.so") == null || guard.isBad("vulkan", key)) return
        supervisor.call("ensure", "vulkan", key, "")
        settleGpuBan()
    }

    fun route(text: String): RouteHit {
        if (parked) return RouteHit(null, false, "", 0.0)
        try {
            val json = supervisor.call(
                "route",
                chatBackend(),
                engine.driverKey(),
                JSONObject().put("text", text).toString(),
            )
            val obj = JSONObject(json)
            val expert = obj.optString("expert").ifBlank { null }
            return RouteHit(expert, obj.optBoolean("fired"), obj.optString("reason"), obj.optDouble("sim"))
        } finally {
            settleGpuBan()
        }
    }

    fun answer(text: String, expert: String?, onPartial: (String) -> Unit): String {
        if (parked) throw ChatParked()
        try {
            val payload = JSONObject().put("text", text).put("expert", expert ?: "").toString()
            return supervisor.call("answer", chatBackend(), engine.driverKey(), payload, onPartial)
        } finally {
            settleGpuBan()
        }
    }

    fun rebuild() {
        supervisor.call("rebuild", "cpu", engine.driverKey(), "")
    }

    fun selfCheck(): String = supervisor.call("selfcheck", "cpu", engine.driverKey(), "")

    fun importExternal() {
        supervisor.call("import", "cpu", engine.driverKey(), "")
    }

    fun notice(lang: String): String = guard.notice(lang)

    fun acknowledgeNotice() = guard.acknowledge()

    private fun settleGpuBan() {
        val record = engine.backendRecord()
        if (record.mode == "gpu") return
        if (guard.vulkanStrikes() >= 2 && record.probe == "vulkan") engine.noteCpu("native_crash")
    }

    private fun chatBackend(): String {
        val record = engine.runtimeRecord()
        val selected = DeviceTune.active(record)
        if (selected != "vulkan") return "cpu"
        if (record.mode != "gpu" && guard.isBad("vulkan", engine.driverKey())) return "cpu"
        return "vulkan"
    }

    private inner class RemoteWorker(private val pinned: String) : LlmWorker {
        override fun call(stage: String, backend: String, payload: String, onText: (String) -> Unit): String {
            return transact(stage, pinned, payload, onText)
        }
    }

    private fun transact(stage: String, backend: String, payload: String, onText: (String) -> Unit): String {
        val messenger = bind()
        val latch = CountDownLatch(1)
        val result = AtomicReference<String?>(null)
        val failure = AtomicReference<Throwable?>(null)
        val replyTo = Messenger(Handler(replyThread.looper) { msg ->
            when (msg.what) {
                WHAT_TOKEN -> onText(msg.data.getString("text").orEmpty())
                WHAT_DONE -> {
                    result.set(msg.data.getString("text").orEmpty())
                    latch.countDown()
                }
                WHAT_FAIL -> {
                    failure.set(IllegalStateException(msg.data.getString("text").orEmpty()))
                    latch.countDown()
                }
            }
            true
        })
        val binder = messenger.binder
        val death = IBinder.DeathRecipient {
            failure.compareAndSet(null, if (parked) ChatParked() else deathOf(stage, backend))
            latch.countDown()
        }
        binder.linkToDeath(death, 0)
        try {
            val msg = Message.obtain()
            msg.what = WHAT_REQ
            msg.replyTo = replyTo
            msg.data.putString("op", stage)
            msg.data.putString("backend", backend)
            msg.data.putString("payload", payload)
            messenger.send(msg)
            if (!latch.await(200, TimeUnit.SECONDS)) {
                if (parked) throw ChatParked()
                throw deathOf(stage, backend)
            }
        } finally {
            try {
                binder.unlinkToDeath(death, 0)
            } catch (_: Throwable) {
            }
        }
        failure.get()?.let { throw it }
        return result.get().orEmpty()
    }

    private fun deathOf(stage: String, backend: String): WorkerDied {
        val native = File(app.filesDir, "setup/native-crash.txt")
        val stageFile = File(app.filesDir, "setup/llm-stage.txt")
        val text = if (native.exists()) native.readText() else ""
        if (native.exists()) native.delete()
        val parsed = LlmGuard.parseNativeCrash(text)
        val stageText = if (stageFile.exists()) stageFile.readText() else ""
        val staged = LlmGuard.parseNativeCrash(stageText)
        return WorkerDied(
            signal = parsed.signal.ifBlank { "binder" },
            detail = parsed.body.ifBlank { stageText.ifBlank { "binder death" } },
            stage = parsed.stage.ifBlank { staged.stage }.ifBlank { stage },
            backend = parsed.backend.ifBlank { staged.backend }.ifBlank { backend },
        )
    }

    private fun bind(): Messenger {
        if (parked) throw ChatParked()
        val alive = remote.get()
        if (alive != null && alive.binder.isBinderAlive) return alive
        synchronized(bindLock) {
            if (parked) throw ChatParked()
            val again = remote.get()
            if (again != null && again.binder.isBinderAlive) return again
            try {
                app.unbindService(connection)
            } catch (_: Throwable) {
            }
            remote.set(null)
            val latch = CountDownLatch(1)
            bindLatch = latch
            val ok = app.bindService(Intent(app, LlmService::class.java), connection, Context.BIND_AUTO_CREATE)
            if (parked) throw ChatParked()
            if (!ok || !latch.await(20, TimeUnit.SECONDS)) {
                if (parked) throw ChatParked()
                throw WorkerDied("bind", "bind failed", "bind")
            }
            if (parked) throw ChatParked()
            return remote.get() ?: throw WorkerDied("bind", "no binder", "bind")
        }
    }

    companion object {
        const val WHAT_REQ = 1
        const val WHAT_TOKEN = 2
        const val WHAT_DONE = 3
        const val WHAT_FAIL = 4
    }
}
