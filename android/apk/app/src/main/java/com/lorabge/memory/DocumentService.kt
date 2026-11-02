package com.lorabge.memory

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/** Reads an imported book in the foreground so a large file can finish if the screen locks. */
class DocumentService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "文档导入", NotificationManager.IMPORTANCE_LOW))
        val notification = notification("准备", 0)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(9, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(9, notification)
        }
        when (intent?.action) {
            ACTION_CANCEL -> File(filesDir, "docs/cancel").apply { parentFile?.mkdirs() }.writeText("1")
            else -> {
                val saved = readDocJob(File(filesDir, "docs/job.json"))
                val path = intent?.getStringExtra(EXTRA_PATH).orEmpty().ifBlank { saved.source }
                if (path.isNotBlank()) startWork(path)
            }
        }
        return START_STICKY
    }

    private fun startWork(path: String) {
        if (!running.compareAndSet(false, true)) return
        Thread {
            try {
                File(filesDir, "docs/cancel").delete()
                val store = MemoryStore(File(filesDir, "memory"))
                store.ensure()
                val engine = Engine(this, store)
                val embed = if (engine.binariesReady() && engine.bgeModel() != null) {
                    { lines: List<String> -> engine.embedTexts(lines) }
                } else {
                    null
                }
                val ask = if (engine.binariesReady() && (engine.baseModel()?.length() ?: 0L) > 1_000_000L) {
                    { prompt: String -> engine.answer(prompt, null) }
                } else {
                    null
                }
                runDocumentImport(
                    source = File(path),
                    store = store,
                    embed = embed,
                    ask = ask,
                    cancelled = { File(filesDir, "docs/cancel").exists() },
                ) { job ->
                    val label = docPhaseLabel(job.phase, "zh")
                    val text = job.message.ifBlank { "$label ${job.percent}%" }
                    getSystemService(NotificationManager::class.java).notify(9, notification(text, job.percent))
                }
            } finally {
                running.set(false)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }.start()
    }

    private fun notification(text: String, percent: Int): Notification {
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("正在读入文档")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setProgress(100, percent.coerceIn(0, 100), percent <= 0)
            .build()
    }

    companion object {
        const val CHANNEL = "documents"
        const val ACTION_CANCEL = "com.lorabge.memory.DOC_CANCEL"
        const val EXTRA_PATH = "path"
        private val running = AtomicBoolean(false)
    }
}
