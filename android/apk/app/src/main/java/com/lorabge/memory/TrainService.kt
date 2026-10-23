package com.lorabge.memory

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant

class TrainService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val channel = "train"
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(channel, "记忆训练", NotificationManager.IMPORTANCE_LOW))
        val notification = Notification.Builder(this, channel)
            .setContentTitle("正在把对话写进 LoRA")
            .setContentText("准备中")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(7, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(7, notification)
        }
        if (intent?.action == ACTION_CANCEL) {
            File(memoryRoot(), "train/cancel").writeText("1")
            return START_NOT_STICKY
        }
        Thread { runJob() }.start()
        return START_NOT_STICKY
    }

    private fun memoryRoot() = File(filesDir, "memory")

    private fun runJob() {
        val store = MemoryStore(memoryRoot())
        store.ensure()
        val status = File(store.trainDir, "status.json")
        val cancel = File(store.trainDir, "cancel")
        if (cancel.exists()) {
            writeStatus(status, "cancelled", "已取消")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }
        try {
            val charging = (getSystemService(BATTERY_SERVICE) as BatteryManager).isCharging
            val screenOn = (getSystemService(POWER_SERVICE) as PowerManager).isInteractive
            val force = File(store.trainDir, "force").exists()
            if ((!charging || screenOn) && !force) {
                writeStatus(status, "waiting", "要等充电并且屏幕关闭。想现在训,在整理页勾选立即训练。")
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            val job = JSONObject(File(store.trainDir, "job.json").readText())
            val facts = job.getJSONArray("facts")
            val reviewed = ArrayList<ReviewedFact>()
            for (i in 0 until facts.length()) {
                val row = facts.getJSONObject(i)
                val qa = row.getJSONArray("qa")
                val pairs = ArrayList<Pair<String, String>>()
                for (j in 0 until qa.length()) {
                    val turn = qa.getJSONObject(j)
                    pairs.add(turn.getString("q") to turn.getString("a"))
                }
                reviewed.add(
                    ReviewedFact(
                        entity = row.getString("entity"),
                        statement = row.getString("statement"),
                        value = row.getString("value"),
                        qa = pairs,
                        sources = emptyList(),
                    ),
                )
            }
            val jsonl = File(store.trainDir, "facts.jsonl")
            jsonl.writeText(factsJsonl(reviewed))
            val bin = File(applicationInfo.nativeLibraryDir, "libtrain-mft.so")
            val models = File(getExternalFilesDir(null), "models")
            // 对话仍用 f16 GGUF。训练读的是同一份 Qwen2.5-0.5B-Instruct 的 safetensors,进内存后按 fp32 做反向。
            val base = File(models, "Qwen2.5-0.5B-Instruct")
            if (!bin.exists() || !File(base, "model.safetensors").exists() || !File(base, "config.json").exists()) {
                writeStatus(status, "error", "缺少训练程序,或 models/Qwen2.5-0.5B-Instruct 里没有 safetensors")
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            val expert = job.getString("expert")
            val outDir = File(store.trainDir, "mft").apply { mkdirs() }
            val adapter = File(store.trainDir, "$expert.gguf")
            val rank = job.optInt("rank", 32)
            val cmd = mutableListOf(
                bin.absolutePath,
                "--model_dir", base.absolutePath,
                "--facts_jsonl", jsonl.absolutePath,
                "--output_dir", outDir.absolutePath,
                "--output_gguf", adapter.absolutePath,
                "--epochs", job.optInt("epochs", 4).toString(),
                "--batch_size", "1",
                // 8 次微批再更新一次,等效 batch 8。batch 1 直接更新时第 1 个 epoch 是 0/50,答案塌成重复字符。
                "--grad_accum_steps", "8",
                "--lr", job.optString("lr", "5e-4"),
                "--max_grad_norm", "1.0",
                "--lora_r", rank.toString(),
                "--lora_alpha", (rank * 2).toString(),
                "--lora_dropout", "0",
                "--mlp",
                "--base_weight_storage", "fp32",
                "--seed", "42",
                "--save_every", "20",
            )
            writeStatus(status, "running", "开始训练 ${reviewed.size} 条")
            val log = File(store.trainDir, "train.log")
            val telemetry = File(store.trainDir, "telemetry.tsv")
            telemetry.appendText("wall_s\trss_kb\tthermal\tbattery\n")
            val proc = ProcessBuilder(cmd)
                .redirectErrorStream(true)
                .apply { environment()["LD_LIBRARY_PATH"] = applicationInfo.nativeLibraryDir }
                .start()
            val started = System.currentTimeMillis()
            proc.inputStream.bufferedReader().useLines { lines ->
                for (line in lines) {
                    log.appendText(line + "\n")
                    if (cancel.exists()) {
                        proc.destroy()
                        writeStatus(status, "cancelled", "已取消,检查点留在 ${outDir.name}")
                        break
                    }
                    val compact = line.replace('\r', '\n').lineSequence().lastOrNull { it.contains("loss=") } ?: continue
                    val rss = File("/proc/${pidOf(proc)}/status").takeIf { it.exists() }
                        ?.readLines()?.firstOrNull { it.startsWith("VmRSS") }?.substringAfter(":")?.trim() ?: ""
                    val thermal = File("/sys/class/thermal").listFiles()
                        ?.mapNotNull { zone ->
                            File(zone, "temp").takeIf { it.exists() }?.readText()?.trim()
                        }?.joinToString(",") ?: ""
                    val battery = (getSystemService(BATTERY_SERVICE) as BatteryManager).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
                    telemetry.appendText("${(System.currentTimeMillis() - started) / 1000}\t$rss\t$thermal\t$battery\n")
                    writeStatus(status, "running", compact.take(180))
                    notify(compact.take(80))
                }
            }
            val code = if (proc.isAlive) proc.waitFor() else proc.exitValue()
            if (cancel.exists()) {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            if (code != 0 || !adapter.exists()) {
                writeStatus(status, "error", "训练退出 $code,见 train/train.log")
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            val dir = File(store.expertsDir, expert)
            dir.mkdirs()
            adapter.copyTo(File(dir, "adapter.gguf"), overwrite = true)
            val engine = Engine(this, store)
            val keys = MemoryStore.keyTexts(reviewed)
            val keyVecs = engine.embedTexts(keys)
            Engine.writeF32(File(dir, "router_key.f32"), keyVecs)
            val masked = maskedFactTexts(reviewed)
            val factVecs = engine.embedTexts(masked)
            Engine.writeF32(File(dir, "fact_vectors.f32"), factVecs)
            val batch = (store.listExperts().maxOfOrNull { it.batch } ?: -1) + 1
            store.registerExpert(
                ExpertRecord(
                    expert = expert,
                    batch = batch,
                    nFacts = reviewed.size,
                    rank = job.optInt("rank", 32),
                    keyPath = "experts/$expert/router_key.f32",
                    weight = "experts/$expert/adapter.gguf",
                ),
                reviewed,
            )
            engine.rebuildIndex()
            writeStatus(status, "done", "已登记 $expert")
        } catch (ex: Throwable) {
            writeStatus(status, "error", ex.message ?: ex.toString())
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun maskedFactTexts(facts: List<ReviewedFact>): List<String> {
        val out = ArrayList<String>()
        for (fact in facts) {
            out.add(maskFact(fact.statement, fact.entity, fact.value))
            for ((q, _) in fact.qa) out.add(maskFact(q, fact.entity, fact.value))
        }
        return out
    }

    private fun maskFact(text: String, entity: String, value: String): String {
        var out = text
        if (entity.isNotEmpty()) out = out.replace(entity, "某")
        val bare = value.removeSuffix("年")
        if (bare.isNotEmpty()) out = out.replace(bare, "某值")
        return out
    }

    private fun writeStatus(file: File, state: String, detail: String) {
        file.writeText(JSONObject().put("state", state).put("detail", detail).put("updated", Instant.now().toString()).toString())
    }

    private fun notify(text: String) {
        val notification = Notification.Builder(this, "train")
            .setContentTitle("正在把对话写进 LoRA")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .build()
        getSystemService(NotificationManager::class.java).notify(7, notification)
    }

    private fun pidOf(proc: Process): Int = try {
        proc.javaClass.getMethod("pid").invoke(proc) as Int
    } catch (_: Throwable) {
        -1
    }

    private fun factsJsonl(facts: List<ReviewedFact>): String {
        val rows = ArrayList<String>()
        for (fact in facts) {
            val qa = JSONArray()
            val pairs = if (fact.qa.isEmpty()) listOf(fact.statement to fact.value) else fact.qa
            for ((q, a) in pairs) qa.put(JSONObject().put("q", q).put("a", a))
            rows.add(
                JSONObject()
                    .put("statement", fact.statement)
                    .put("qa", qa)
                    .toString(),
            )
        }
        return rows.joinToString("\n") + "\n"
    }

    companion object {
        const val ACTION_CANCEL = "com.lorabge.memory.CANCEL_TRAIN"

        fun writeJob(store: MemoryStore, expert: String, facts: List<ReviewedFact>, force: Boolean) {
            store.ensure()
            val arr = JSONArray()
            for (fact in facts) {
                val qa = JSONArray()
                for ((q, a) in fact.qa) qa.put(JSONObject().put("q", q).put("a", a))
                arr.put(
                    JSONObject()
                        .put("entity", fact.entity)
                        .put("statement", fact.statement)
                        .put("value", fact.value)
                        .put("qa", qa),
                )
            }
            File(store.trainDir, "job.json").writeText(
                JSONObject()
                    .put("expert", expert)
                    .put("rank", 32)
                    .put("lr", "5e-4")
                    .put("epochs", 4)
                    .put("facts", arr)
                    .toString(),
            )
            val forceFile = File(store.trainDir, "force")
            if (force) forceFile.writeText("1") else forceFile.delete()
            File(store.trainDir, "cancel").delete()
        }
    }
}
