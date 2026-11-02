package com.lorabge.memory

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.IBinder
import android.os.StatFs
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class FetchService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "模型下载", NotificationManager.IMPORTANCE_LOW))
        val notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("正在下载模型")
            .setContentText("准备中")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(8, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(8, notification)
        }
        when (intent?.action) {
            ACTION_PAUSE -> control.pause = true
            else -> {
                control.pause = false
                startWork()
            }
        }
        return START_NOT_STICKY
    }

    private fun startWork() {
        if (!running.compareAndSet(false, true)) return
        control.onlineCheck = { !wifiOnly(this) || onWifi(this) }
        Thread {
            try {
                while (true) {
                    if (control.pause || !control.online) {
                        Thread.sleep(400)
                        continue
                    }
                    val result = runDownload()
                    if (result == "done" || result.startsWith("error")) break
                }
            } finally {
                running.set(false)
            }
        }.start()
    }

    private fun runDownload(): String {
        val setup = File(filesDir, "setup").apply { mkdirs() }
        val status = File(setup, "status.json")
        try {
            val manifest = resolveManifest()
            val fetch = ModelFetch(
                root = filesDir,
                opener = RemoteOpener { url, offset -> httpOpen(url, offset) },
                control = control,
                freeBytes = { freeBytes(filesDir) },
            )
            val result = fetch.download(manifest) { snap ->
                status.writeText(snapJson(snap))
                updateNotification(snap)
            }
            if (result == "done") {
                val store = MemoryStore(File(filesDir, "memory"))
                store.ensure()
                val engine = Engine(this, store)
                engine.importBundle(File(filesDir, "import"))
                val check = engine.selfCheck()
                File(setup, "complete").writeText(check)
                val done = JSONObject(status.readText())
                    .put("state", "done")
                    .put("message", check)
                status.writeText(done.toString())
            }
            return result
        } catch (err: Exception) {
            status.writeText(
                JSONObject()
                    .put("state", "error")
                    .put("message", err.message ?: "下载失败")
                    .put("mirror", "")
                    .put("speedBps", 0)
                    .put("files", JSONArray())
                    .toString(),
            )
            return "error: ${err.message ?: "下载失败"}"
        }
    }

    private fun resolveManifest(): FetchManifest {
        val custom = manifestUrl(this)
        if (custom.isNotBlank()) return parseManifest(bytesOfText(listOf(custom)))
        val bundled = assets.open("setup_manifest.json").bufferedReader().use { it.readText() }
        val parsed = parseManifest(bundled)
        if (parsed.published && parsed.files.isNotEmpty()) return parsed
        return parseManifest(bytesOfText(DEFAULT_MANIFEST_URLS))
    }

    private fun updateNotification(snap: FetchSnapshot) {
        val current = snap.files.firstOrNull { it.state == "running" }
        val text = when (snap.state) {
            "paused" -> snap.message
            "error" -> snap.message
            "done" -> "完成"
            else -> current?.dest?.substringAfterLast('/') ?: snap.message
        }
        val notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("正在下载模型")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .build()
        getSystemService(NotificationManager::class.java).notify(8, notification)
    }

    companion object {
        const val CHANNEL = "fetch"
        const val ACTION_PAUSE = "com.lorabge.memory.FETCH_PAUSE"
        const val ACTION_RESUME = "com.lorabge.memory.FETCH_RESUME"
        val DEFAULT_MANIFEST_URLS = listOf(
            "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/android-v0.1.0/manifest.json",
        )
        private val running = AtomicBoolean(false)
        private val control = FetchControl()

        fun manifestUrl(context: Context): String =
            context.getSharedPreferences("setup", MODE_PRIVATE).getString("manifest_url", "").orEmpty()

        fun setManifestUrl(context: Context, url: String) {
            context.getSharedPreferences("setup", MODE_PRIVATE).edit().putString("manifest_url", url.trim()).apply()
        }

        fun wifiOnly(context: Context): Boolean =
            context.getSharedPreferences("setup", MODE_PRIVATE).getBoolean("wifi_only", false)

        fun setWifiOnly(context: Context, on: Boolean) {
            context.getSharedPreferences("setup", MODE_PRIVATE).edit().putBoolean("wifi_only", on).apply()
        }

        fun onWifi(context: Context): Boolean {
            val manager = context.getSystemService(ConnectivityManager::class.java) ?: return false
            val network = manager.activeNetwork ?: return false
            val caps = manager.getNetworkCapabilities(network) ?: return false
            return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        }

        fun needsSetup(context: Context): Boolean {
            if (File(context.filesDir, "setup/complete").exists() && modelsPresent(context)) return false
            return !modelsPresent(context)
        }

        fun modelsPresent(context: Context): Boolean {
            val internal = File(context.filesDir, "models")
            val external = context.getExternalFilesDir(null)?.let { File(it, "models") }
            fun has(name: String) = File(internal, name).exists() || (external != null && File(external, name).exists())
            return has("base.gguf") && has("bge.gguf") && has("Qwen2.5-0.5B-Instruct/model.safetensors")
        }
    }
}

internal fun freeBytes(dir: File): Long {
    val stat = StatFs(dir.absolutePath)
    return stat.availableBytes
}

internal fun snapJson(snap: FetchSnapshot): String {
    val files = JSONArray()
    for (file in snap.files) {
        files.put(
            JSONObject()
                .put("dest", file.dest)
                .put("bytes", file.bytes)
                .put("size", file.size)
                .put("state", file.state),
        )
    }
    return JSONObject()
        .put("state", snap.state)
        .put("message", snap.message)
        .put("mirror", snap.mirror)
        .put("speedBps", snap.speedBps)
        .put("files", files)
        .toString()
}
