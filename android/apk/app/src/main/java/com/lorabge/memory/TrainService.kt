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
        try {
            val crash = java.io.File(filesDir, "setup/native-crash.txt")
            crash.parentFile?.mkdirs()
            NativeRouter.armCrashLog(crash.absolutePath)
            NativeRouter.setStage("train", "cpu")
        } catch (_: Throwable) {
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
                reviewed.add(factFromJson(facts.getJSONObject(i)))
            }
            val expanded = reviewed.map { FactExpand.expand(it) }.filter { FactExpand.keepForTraining(it) }
            if (expanded.isEmpty()) {
                writeStatus(status, "error", "没有要写入的事实")
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            val jsonl = File(store.trainDir, "facts.jsonl")
            jsonl.writeText(FactExpand.toFactsJsonl(expanded))
            val expert = job.getString("expert")
            val epochs = job.optInt("epochs", 4)
            val started = System.currentTimeMillis()
            publish(status, "running", "extract", 0, 0, epochs, null, started, "抽取事实", "")
            publish(status, "running", "gate", 0, 0, epochs, null, started, "写闸门", "")
            if (File(store.trainDir, "simulate").exists()) {
                simulateTrain(store, status, expanded, expert, epochs, started)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            val bin = File(applicationInfo.nativeLibraryDir, "libtrain-mft.so")
            val internal = File(filesDir, "models/Qwen2.5-0.5B-Instruct")
            val external = File(getExternalFilesDir(null), "models/Qwen2.5-0.5B-Instruct")
            // 对话仍用 f16 GGUF。训练读的是同一份 Qwen2.5-0.5B-Instruct 的 safetensors,进内存后按 fp32 做反向。
            val base = if (File(internal, "model.safetensors").exists()) internal else external
            if (!bin.exists() || !File(base, "model.safetensors").exists() || !File(base, "config.json").exists()) {
                writeStatus(status, "error", "缺少训练程序,或 models/Qwen2.5-0.5B-Instruct 里没有 safetensors")
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
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
            publish(status, "running", "build", 0, 0, epochs, null, started, "生成样本 ${expanded.size} 条", "")
            val log = File(store.trainDir, "train.log")
            val telemetry = File(store.trainDir, "telemetry.tsv")
            telemetry.writeText("wall_s\trss_kb\tthermal\tbattery\n")
            val threads = PhoneFacts.threads()
            val proc = ProcessBuilder(cmd)
                .redirectErrorStream(true)
                .apply {
                    environment()["LD_LIBRARY_PATH"] = applicationInfo.nativeLibraryDir
                    // 只占超大核和大核。天玑 9400 的 1+3+4 是 4 线程，小米 15 两档 Oryon 仍是 8。
                    environment()["OPENBLAS_NUM_THREADS"] = threads.toString()
                    environment()["OMP_NUM_THREADS"] = "1"
                }
                .start()
            val pending = java.util.concurrent.ConcurrentLinkedQueue<String>()
            val reader = Thread {
                proc.inputStream.bufferedReader().use { input ->
                    while (true) {
                        val line = input.readLine() ?: break
                        log.appendText(line + "\n")
                        pending.add(line)
                    }
                }
            }
            reader.isDaemon = true
            reader.start()
            var step = 0
            var total = 0
            var loss: Float? = null
            var lastLine = "开始训练 ${expanded.size} 条事实"
            while (reader.isAlive || pending.isNotEmpty()) {
                if (cancel.exists()) {
                    proc.destroy()
                    publish(status, "cancelled", "train", step, total, epochs, loss, started, "已取消,检查点留在 ${outDir.name}", tailOf(log))
                    break
                }
                var line = pending.poll()
                while (line != null) {
                    val parsed = parseStepLine(line)
                    if (parsed != null) {
                        step = parsed.first
                        total = parsed.second
                        loss = parsed.third
                        lastLine = line.take(180)
                        val rss = File("/proc/${pidOf(proc)}/status").takeIf { it.exists() }
                            ?.readLines()?.firstOrNull { it.startsWith("VmRSS") }?.substringAfter(":")?.trim() ?: ""
                        val thermal = File("/sys/class/thermal").listFiles()
                            ?.mapNotNull { zone ->
                                File(zone, "temp").takeIf { it.exists() }?.readText()?.trim()
                            }?.joinToString(",") ?: ""
                        val battery = (getSystemService(BATTERY_SERVICE) as BatteryManager).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
                        telemetry.appendText("${(System.currentTimeMillis() - started) / 1000}\t$rss\t$thermal\t$battery\n")
                    } else if (line.isNotBlank()) {
                        lastLine = line.take(180)
                    }
                    line = pending.poll()
                }
                publish(status, "running", "train", step, total, epochs, loss, started, lastLine, "")
                notify(if (total > 0) "第 $step/$total 步" else "这一步还在计算")
                if (!reader.isAlive && pending.isEmpty()) break
                Thread.sleep(1000)
            }
            reader.join(2000)
            val code = if (proc.isAlive) proc.waitFor() else proc.exitValue()
            if (cancel.exists()) {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            if (code != 0 || !adapter.exists()) {
                publish(status, "error", "train", step, total, epochs, loss, started, "训练退出 $code", tailOf(log))
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            val dir = File(store.expertsDir, expert)
            dir.mkdirs()
            adapter.copyTo(File(dir, "adapter.gguf"), overwrite = true)
            val engine = Engine(this, store)
            val keys = MemoryStore.keyTexts(expanded)
            val keyVecs = engine.embedTexts(keys)
            Engine.writeF32(File(dir, "router_key.f32"), keyVecs)
            val masked = maskedFactTexts(expanded)
            val factVecs = engine.embedTexts(masked)
            Engine.writeF32(File(dir, "fact_vectors.f32"), factVecs)
            val batch = (store.listExperts().maxOfOrNull { it.batch } ?: -1) + 1
            store.registerExpert(
                ExpertRecord(
                    expert = expert,
                    batch = batch,
                    nFacts = expanded.size,
                    rank = job.optInt("rank", 32),
                    keyPath = "experts/$expert/router_key.f32",
                    weight = "experts/$expert/adapter.gguf",
                ),
                expanded,
            )
            NebulaGraph.rememberSession(store, expert)
            publish(status, "running", "recall", step, total, epochs, loss, started, "回忆检查", "")
            engine.rebuildIndex()
            if (job.optBoolean("benchmark")) {
                writeBenchmark(store, engine, job, expanded, started)
            }
            publish(status, "running", "register", step, total, epochs, loss, started, "注册专家", "")
            publish(status, "done", "done", step, total, epochs, loss, started, "已登记 $expert", "")
        } catch (ex: Throwable) {
            writeStatus(status, "error", ex.message ?: ex.toString())
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun publish(
        file: File,
        state: String,
        stage: String,
        step: Int,
        total: Int,
        epochs: Int,
        loss: Float?,
        startedMs: Long,
        detail: String,
        logTail: String,
    ) {
        val elapsed = (System.currentTimeMillis() - startedMs) / 1000
        file.writeText(trainSnapshotJson(state, stage, step, total, epochs, loss, elapsed, detail, logTail))
    }

    private fun tailOf(log: File): String {
        if (!log.exists()) return ""
        return log.readLines().takeLast(12).joinToString("\n").take(800)
    }

    private fun simulateTrain(
        store: MemoryStore,
        status: File,
        expanded: List<ReviewedFact>,
        expert: String,
        epochs: Int,
        started: Long,
    ) {
        val log = File(store.trainDir, "train.log")
        val total = 4
        for (step in 1..total) {
            val loss = 1.4f - step * 0.2f
            log.appendText("[step $step/$total] loss=$loss\n")
            publish(status, "running", "train", step, total, epochs, loss, started, "训练 LoRA", "")
            notify("第 $step/$total 步")
            Thread.sleep(700)
        }
        publish(status, "running", "recall", total, total, epochs, 0.6f, started, "回忆检查", "")
        Thread.sleep(400)
        val batch = (store.listExperts().maxOfOrNull { it.batch } ?: -1) + 1
        store.registerExpert(
            ExpertRecord(expert, batch, expanded.size, 32, "experts/$expert/router_key.f32", "experts/$expert/adapter.gguf"),
            expanded,
        )
        NebulaGraph.rememberSession(store, expert)
        publish(status, "running", "register", total, total, epochs, 0.6f, started, "注册专家", "")
        publish(status, "done", "done", total, total, epochs, 0.6f, started, "已登记 $expert", "")
    }

    private fun maskedFactTexts(facts: List<ReviewedFact>): List<String> {
        val out = ArrayList<String>()
        for (fact in facts) {
            out.add(maskFact(fact.statement, fact.entity, fact.value))
            for ((q, _) in fact.qa) out.add(maskFact(q, fact.entity, fact.value))
            // 改写键只进事实闸,不进训练样本。
            for (question in fact.gateQuestions) out.add(maskFact(question, fact.entity, fact.value))
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
            .setOngoing(true)
            .build()
        getSystemService(NotificationManager::class.java).notify(7, notification)
    }

    private fun pidOf(proc: Process): Int = try {
        proc.javaClass.getMethod("pid").invoke(proc) as Int
    } catch (_: Throwable) {
        -1
    }

    private fun writeBenchmark(
        store: MemoryStore,
        engine: Engine,
        job: JSONObject,
        trained: List<ReviewedFact>,
        startedMs: Long,
    ) {
        val report = JSONObject()
        val primaryHits = JSONArray()
        var primaryOk = 0
        for (fact in trained) {
            val pair = fact.qa.firstOrNull() ?: continue
            val answer = engine.answer(pair.first, job.getString("expert"))
            val ok = answer.contains(fact.value.removeSuffix("年"))
            if (ok) primaryOk++
            primaryHits.put(JSONObject().put("q", pair.first).put("gold", fact.value).put("answer", answer).put("hit", ok))
        }
        val held = job.optJSONArray("held_out") ?: JSONArray()
        val heldHits = JSONArray()
        var heldOk = 0
        for (i in 0 until held.length()) {
            val row = held.getJSONObject(i)
            val answer = engine.answer(row.getString("q"), job.getString("expert"))
            val gold = row.getString("a")
            val ok = answer.contains(gold.removeSuffix("年"))
            if (ok) heldOk++
            heldHits.put(JSONObject().put("q", row.getString("q")).put("gold", gold).put("answer", answer).put("hit", ok))
        }
        val never = job.optJSONArray("never_written") ?: JSONArray()
        val abstainHits = JSONArray()
        var abstainOk = 0
        for (i in 0 until never.length()) {
            val question = never.getString(i)
            val route = engine.route(question)
            val ok = !route.fired
            if (ok) abstainOk++
            abstainHits.put(
                JSONObject()
                    .put("q", question)
                    .put("fired", route.fired)
                    .put("reason", route.reason)
                    .put("sim", route.sim)
                    .put("abstained", ok),
            )
        }
        val telemetry = File(store.trainDir, "telemetry.tsv")
        var peakRss = 0
        var maxThermal = 0
        if (telemetry.exists()) {
            for (line in telemetry.readLines().drop(1)) {
                val cols = line.split('\t')
                val rss = cols.getOrNull(1)?.filter { it.isDigit() }?.toIntOrNull() ?: 0
                if (rss > peakRss) peakRss = rss
                val thermal = cols.getOrNull(2).orEmpty()
                for (part in thermal.split(',')) {
                    val temp = part.trim().toIntOrNull() ?: continue
                    if (temp > maxThermal) maxThermal = temp
                }
            }
        }
        engine.ensureBackend()
        val facts = PhoneFacts.collect(engine, packageManager.getPackageInfo(packageName, 0).versionName ?: "")
        report
            .put("device", DeviceTune.deviceJson(facts))
            .put("wall_s", (System.currentTimeMillis() - startedMs) / 1000)
            .put("peak_rss_kb", peakRss)
            .put("max_thermal_millic", maxThermal)
            .put("n_facts", trained.size)
            .put("n_train_questions", trained.sumOf { it.qa.size })
            .put("primary", "$primaryOk/${primaryHits.length()}")
            .put("held_out_paraphrase", "$heldOk/${heldHits.length()}")
            .put("never_written_abstain", "$abstainOk/${abstainHits.length()}")
            .put("primary_rows", primaryHits)
            .put("held_out_rows", heldHits)
            .put("abstain_rows", abstainHits)
        File(store.trainDir, "benchmark.json").writeText(report.toString(2))
    }

    companion object {
        const val ACTION_CANCEL = "com.lorabge.memory.CANCEL_TRAIN"
        const val ACTION_BENCHMARK = "com.lorabge.memory.BENCHMARK"

        fun factFromJson(row: JSONObject): ReviewedFact {
            val qa = row.optJSONArray("qa") ?: JSONArray()
            val pairs = ArrayList<Pair<String, String>>()
            for (j in 0 until qa.length()) {
                val turn = qa.getJSONObject(j)
                pairs.add(turn.getString("q") to turn.getString("a"))
            }
            if (pairs.isEmpty() && row.optString("question").isNotBlank()) {
                pairs.add(row.getString("question") to row.optString("answer", row.optString("value")))
            }
            val gates = row.optJSONArray("gate_questions") ?: JSONArray()
            val gateQuestions = ArrayList<String>()
            for (j in 0 until gates.length()) gateQuestions.add(gates.getString(j))
            return ReviewedFact(
                entity = row.getString("entity"),
                statement = row.getString("statement"),
                value = row.getString("value"),
                qa = pairs,
                sources = emptyList(),
                attr = row.optString("attr"),
                gateQuestions = gateQuestions,
                selected = row.optBoolean("selected", true),
                gate = row.optString("gate"),
            )
        }

        fun writeJob(
            store: MemoryStore,
            expert: String,
            facts: List<ReviewedFact>,
            force: Boolean,
            epochs: Int = 4,
            benchmark: Boolean = false,
            heldOut: JSONArray? = null,
            neverWritten: JSONArray? = null,
        ) {
            store.ensure()
            val arr = JSONArray()
            for (fact in facts) {
                val qa = JSONArray()
                for ((q, a) in fact.qa) qa.put(JSONObject().put("q", q).put("a", a))
                val gates = JSONArray()
                for (question in fact.gateQuestions) gates.put(question)
                arr.put(
                    JSONObject()
                        .put("entity", fact.entity)
                        .put("attr", fact.attr)
                        .put("statement", fact.statement)
                        .put("value", fact.value)
                        .put("qa", qa)
                        .put("gate_questions", gates)
                        .put("selected", fact.selected)
                        .put("gate", fact.gate),
                )
            }
            val job = JSONObject()
                .put("expert", expert)
                .put("rank", 32)
                .put("lr", "5e-4")
                .put("epochs", epochs)
                .put("facts", arr)
                .put("benchmark", benchmark)
            if (heldOut != null) job.put("held_out", heldOut)
            if (neverWritten != null) job.put("never_written", neverWritten)
            File(store.trainDir, "job.json").writeText(job.toString())
            val forceFile = File(store.trainDir, "force")
            if (force) forceFile.writeText("1") else forceFile.delete()
            File(store.trainDir, "cancel").delete()
        }
    }
}
