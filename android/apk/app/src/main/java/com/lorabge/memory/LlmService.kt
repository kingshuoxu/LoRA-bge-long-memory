package com.lorabge.memory

import android.app.Service
import android.content.Intent
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import org.json.JSONObject
import java.io.File

/** 对话、嵌入、路由和 GPU 自检都在这个进程里。原生崩溃只会杀掉 :llm,界面还在。 */
class LlmService : Service() {
    private val worker = HandlerThread("llm-work")
    private var handler: Handler? = null
    private var engine: Engine? = null

    override fun onCreate() {
        super.onCreate()
        val crash = File(filesDir, "setup/native-crash.txt")
        crash.parentFile?.mkdirs()
        try {
            NativeRouter.armCrashLog(crash.absolutePath)
            NativeRouter.setStage("idle", "cpu")
        } catch (_: Throwable) {
        }
        engine = Engine(this, MemoryStore(File(filesDir, "memory")).also { it.ensure() })
        worker.start()
        handler = Handler(worker.looper) { msg ->
            if (msg.what == LlmClient.WHAT_REQ) handle(msg)
            true
        }
    }

    override fun onBind(intent: Intent?): IBinder? = handler?.let { Messenger(it).binder }

    override fun onDestroy() {
        worker.quitSafely()
        super.onDestroy()
    }

    private fun handle(msg: Message) {
        val op = msg.data.getString("op").orEmpty()
        val backend = msg.data.getString("backend").orEmpty().ifBlank { "cpu" }
        val payload = msg.data.getString("payload").orEmpty()
        val replyTo = msg.replyTo ?: return
        mark(op, backend)
        try {
            val text = dispatch(op, backend, payload, replyTo)
            send(replyTo, LlmClient.WHAT_DONE, text)
        } catch (ex: Throwable) {
            send(replyTo, LlmClient.WHAT_FAIL, ex.message ?: "failed")
        }
    }

    private fun dispatch(op: String, backend: String, payload: String, replyTo: Messenger): String {
        val current = engine ?: error("engine")
        if (op == "ensure") {
            if (backend == "vulkan") current.ensureBackend()
            else current.noteCpu(if (current.tool("libggml-vulkan.so") == null) "no_vulkan" else "native_crash")
            return "ok"
        }
        return current.withBackend(backend) {
            when (op) {
                "route" -> {
                    val hit = current.route(JSONObject(payload).getString("text"))
                    JSONObject()
                        .put("expert", hit.expert ?: "")
                        .put("fired", hit.fired)
                        .put("reason", hit.reason)
                        .put("sim", hit.sim)
                        .toString()
                }
                "answer" -> {
                    val obj = JSONObject(payload)
                    val expert = obj.optString("expert").ifBlank { null }
                    current.answer(obj.getString("text"), expert) { partial ->
                        send(replyTo, LlmClient.WHAT_TOKEN, partial)
                    }
                }
                "rebuild" -> {
                    current.rebuildIndex()
                    "ok"
                }
                "selfcheck" -> current.selfCheck()
                "import" -> {
                    current.importExternal()
                    "ok"
                }
                else -> error("unknown $op")
            }
        }
    }

    private fun mark(stage: String, backend: String) {
        val dir = File(filesDir, "setup")
        dir.mkdirs()
        File(dir, "llm-stage.txt").writeText("stage=$stage\nbackend=$backend\n")
        try {
            NativeRouter.setStage(stage, backend)
        } catch (_: Throwable) {
        }
    }

    private fun send(replyTo: Messenger, what: Int, text: String) {
        val msg = Message.obtain()
        msg.what = what
        msg.data.putString("text", text)
        try {
            replyTo.send(msg)
        } catch (_: Throwable) {
        }
    }
}
