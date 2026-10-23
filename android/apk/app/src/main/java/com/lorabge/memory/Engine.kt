package com.lorabge.memory

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit

class NativeCrash(val signal: Int, val detail: String) : RuntimeException("signal $signal")

class Engine(private val context: Context, private val store: MemoryStore) {
    private val nativeDir = context.applicationInfo.nativeLibraryDir
    @Volatile private var nglOverride: Int? = null

    fun tool(name: String): File? {
        val file = File(nativeDir, name)
        return if (file.exists()) file else null
    }

    fun modelsDir(): File {
        // 真机基准经 run-as 把模型放进私有目录。外部目录仍给手动 adb 推送用。
        val internal = File(context.filesDir, "models")
        if (File(internal, "base.gguf").exists() || File(internal, "Qwen2.5-0.5B-Instruct/config.json").exists()) {
            return internal
        }
        val dir = File(context.getExternalFilesDir(null), "models")
        dir.mkdirs()
        return dir
    }

    fun baseModel(): File? = File(modelsDir(), "base.gguf").takeIf { it.exists() }
    fun bgeModel(): File? = File(modelsDir(), "bge.gguf").takeIf { it.exists() }

    fun binariesReady(): Boolean =
        tool("libllama-cli.so") != null && tool("libllama-embedding.so") != null

    fun route(text: String): RouteHit = guarded("route") { routeOnce(text) }

    private fun routeOnce(text: String): RouteHit {
        val index = File(store.indexDir, "index.json")
        if (!index.exists()) rebuildIndex()
        if (!index.exists()) return RouteHit(null, false, "no_index", 0.0)
        val names = entityNames()
        val masked = maskQuery(text, names)
        val bge = bgeModel()
        val embedder = tool("libllama-embedding.so")
        if (bge == null || embedder == null) {
            return RouteHit(null, false, "no_bge", 0.0)
        }
        markNative("route", if (nglNow() > 0) "vulkan" else "cpu")
        val vectors = embed(embedder, bge, listOf(text, masked))
        markNative("route", "cpu")
        val json = NativeRouter.decide(index.absolutePath, text, vectors[0], vectors[1])
        val obj = JSONObject(json)
        val expert = if (obj.isNull("expert")) null else obj.optString("expert").ifBlank { null }
        return RouteHit(
            expert = expert,
            fired = obj.optBoolean("fired"),
            reason = obj.optString("reason"),
            sim = obj.optDouble("sim"),
        )
    }

    fun answer(question: String, expert: String?, onPartial: (String) -> Unit = {}): String =
        guarded("answer") { answerOnce(question, expert, onPartial) }

    private fun answerOnce(question: String, expert: String?, onPartial: (String) -> Unit): String {
        val cli = tool("libllama-cli.so") ?: return "没有 llama-cli。请安装带 QVAC 二进制的 APK。"
        val base = baseModel() ?: return "还没有基座。把 GGUF 推到 ${modelsDir().absolutePath}/base.gguf"
        val template = File(store.root, "qwen25_chat_template.jinja")
        if (!template.exists()) {
            context.assets.open("qwen25_chat_template.jinja").use { input ->
                template.writeBytes(input.readBytes())
            }
        }
        val threads = PhoneFacts.threads()
        val cmd = mutableListOf(
            cli.absolutePath, "-m", base.absolutePath,
            "--jinja", "--chat-template-file", template.absolutePath,
            "-sys", "你是助手。",
            "-p", question + " 请简短回答。",
            "--temp", "0", "--top-k", "1", "--top-p", "1", "--min-p", "0",
            "-n", "40", "--single-turn", "-ngl", nglNow().toString(),
            "-t", threads.toString(), "-tb", threads.toString(),
            "--no-warmup", "-c", "512",
        )
        if (expert != null) {
            val weight = File(store.expertsDir, "$expert/adapter.gguf")
            if (weight.exists()) {
                cmd.add(3, "--lora")
                cmd.add(4, weight.absolutePath)
            }
        }
        markNative("answer", if (nglNow() > 0) "vulkan" else "cpu")
        val output = runToolStream(cmd, File(context.cacheDir, "gen")) { raw ->
            onPartial(DeviceTune.extractReply(raw))
        }
        return DeviceTune.extractReply(output).ifBlank { "没有生成" }
    }

    fun embedTexts(texts: List<String>): List<FloatArray> = guarded("embed") { embedTextsOnce(texts) }

    private fun embedTextsOnce(texts: List<String>): List<FloatArray> {
        val embedder = tool("libllama-embedding.so") ?: error("没有 llama-embedding")
        val bge = bgeModel() ?: error("没有 bge.gguf")
        return embed(embedder, bge, texts)
    }

    fun rebuildIndex() {
        store.ensure()
        val experts = store.listExperts()
        val expertJson = JSONArray()
        val factRows = JSONArray()
        val factVectors = ArrayList<FloatArray>()
        for (record in experts) {
            val dir = File(store.expertsDir, record.expert)
            val keyFile = File(dir, "router_key.f32")
            val texts = File(dir, "key_texts.json").takeIf { it.exists() }?.readText() ?: "[]"
            val entities = try {
                markNative("extract", "cpu")
                JSONArray(NativeRouter.extract(texts))
            } catch (_: Throwable) {
                JSONArray()
            }
            val nKeys = if (keyFile.exists()) (keyFile.length() / (512 * 4)).toInt() else 0
            if (nKeys > 0) keyFile.copyTo(File(store.indexDir, "${record.expert}.f32"), overwrite = true)
            expertJson.put(
                JSONObject()
                    .put("name", record.expert)
                    .put("entities", entities)
                    .put("n_keys", nKeys)
                    .put("keys", if (nKeys > 0) "${record.expert}.f32" else ""),
            )
            val memoryFile = File(dir, "fact_memory.json")
            val factVec = File(dir, "fact_vectors.f32")
            if (memoryFile.exists() && factVec.exists()) {
                val rows = JSONArray(memoryFile.readText())
                val floats = readF32(factVec)
                var cursor = 0
                for (i in 0 until rows.length()) {
                    val row = rows.getJSONObject(i)
                    val questions = row.optJSONArray("questions")
                    val n = 1 + (questions?.length() ?: 0)
                    repeat(n) {
                        if (cursor + 512 <= floats.size) {
                            factRows.put(JSONObject().put("entity", row.getString("entity")))
                            factVectors.add(floats.copyOfRange(cursor, cursor + 512))
                            cursor += 512
                        }
                    }
                }
            }
        }
        if (factVectors.isNotEmpty()) writeF32(File(store.indexDir, "facts.f32"), factVectors)
        val index = JSONObject()
            .put("tau", 0.6)
            .put("dim", 512)
            .put("experts", expertJson)
        if (factVectors.isNotEmpty()) {
            index.put(
                "facts",
                JSONObject()
                    .put("tau", 0.622)
                    .put("mask", "某")
                    .put("vectors", "facts.f32")
                    .put("rows", factRows),
            )
        }
        File(store.indexDir, "index.json").writeText(index.toString())
    }

    fun importExternal() {
        val incoming = File(context.getExternalFilesDir(null), "import")
        importBundle(incoming)
    }

    fun importBundle(incoming: File) {
        if (!incoming.exists()) return
        val routerFile = File(incoming, "router.jsonl")
        if (routerFile.exists()) {
            val existing = store.listExperts().map { it.expert }.toMutableSet()
            for (line in routerFile.readLines().filter { it.isNotBlank() }) {
                val record = ExpertRecord.fromJson(line)
                if (record.expert in existing) continue
                val src = File(incoming, record.expert)
                if (!src.exists()) continue
                src.copyRecursively(File(store.expertsDir, record.expert), overwrite = true)
                store.writeRouter((store.listExperts() + record).sortedBy { it.batch })
                existing.add(record.expert)
            }
            val gate = File(incoming, "fact_gate.json")
            if (gate.exists()) gate.copyTo(File(store.expertsDir, "fact_gate.json"), overwrite = true)
        }
        rebuildIndex()
    }

    fun selfCheck(): String {
        val dir = File(store.root, "selfcheck")
        dir.mkdirs()
        val vec = FloatArray(4) { 0.5f }
        writeF32(File(dir, "e.f32"), listOf(vec))
        File(dir, "index.json").writeText(
            """
            {"tau":0.6,"dim":4,"experts":[{"name":"expert_0","entities":["塔佐巴洛"],"n_keys":1,"keys":"e.f32"}]}
            """.trimIndent(),
        )
        markNative("selfcheck", "cpu")
        val hit = NativeRouter.decide(
            File(dir, "index.json").absolutePath,
            "塔佐巴洛公司的总部在哪里?",
            vec,
            FloatArray(0),
        )
        val obj = JSONObject(hit)
        val ok = obj.optBoolean("fired") && obj.optString("expert") == "expert_0" && obj.optString("reason") == "entity"
        return if (ok) "路由自检通过" else "路由自检失败"
    }

    private fun entityNames(): List<String> {
        val index = File(store.indexDir, "index.json")
        if (!index.exists()) return emptyList()
        val experts = JSONObject(index.readText()).optJSONArray("experts") ?: return emptyList()
        val names = ArrayList<String>()
        for (i in 0 until experts.length()) {
            val ents = experts.getJSONObject(i).optJSONArray("entities") ?: continue
            for (j in 0 until ents.length()) names.add(ents.getString(j))
        }
        return names.distinct().sortedByDescending { it.length }
    }

    private fun embed(bin: File, model: File, texts: List<String>): List<FloatArray> {
        val work = File(context.cacheDir, "emb").apply { mkdirs() }
        File(work, "prompts.txt").writeText(texts.joinToString("\n") { it.replace("\n", " ") } + "\n")
        val threads = PhoneFacts.threads().toString()
        val output = runTool(
            listOf(
                bin.absolutePath, "-m", model.absolutePath, "-f", File(work, "prompts.txt").absolutePath,
                "--pooling", "mean", "--embd-normalize", "2", "-c", "128",
                "-ngl", nglNow().toString(),
                "-t", threads, "-tb", threads,
                "--embd-output-format", "array",
            ),
            work,
        )
        val raw = output.trim().substringAfterLast('\n').let { line ->
            val start = output.indexOf('[')
            if (start < 0) error("embedding 没有数组: ${output.take(200)}")
            output.substring(start).trim()
        }
        val parsed = JSONArray(raw)
        if (texts.size == 1 && parsed.length() > 0 && parsed.optJSONArray(0) == null) {
            return listOf(floatRow(parsed))
        }
        return (0 until parsed.length()).map { floatRow(parsed.getJSONArray(it)) }
    }

    fun backendRecord(): BackendRecord {
        val version = appVersion()
        val file = backendFile()
        if (!file.exists()) return DeviceTune.defaultRecord(version)
        return DeviceTune.parseRecord(file.readText(), version)
    }

    fun backendLabel(lang: String): String = DeviceTune.label(runtimeRecord(), lang)

    fun runtimeRecord(): BackendRecord {
        val stamp = DeviceTune.probeStamp(appVersion())
        val record = backendRecord()
        if (record.mode == "auto" && record.version != stamp) {
            return record.copy(probe = "cpu", probed = false, checking = true, reason = "pending")
        }
        if (record.mode == "auto" && record.probe == "vulkan" && record.mali && !record.isolated) {
            return record.copy(probe = "cpu")
        }
        return record
    }

    fun driverKey(): String {
        val record = backendRecord()
        val driver = record.vkDriverVersion.ifBlank { "unknown" }
        val name = record.vkName.ifBlank { PhoneFacts.socName() }.ifBlank { "device" }
        return "$name|$driver"
    }

    fun setBackendMode(mode: String) {
        val current = backendRecord()
        val stamp = DeviceTune.probeStamp(appVersion())
        if (mode == "auto" || mode == "gpu") LlmGuard(crashFile()).clearBad("vulkan")
        if (mode == "auto") {
            writeBackend(current.copy(mode = "auto", probed = false, checking = true, reason = "pending", version = stamp))
            return
        }
        val vulkan = tool("libggml-vulkan.so") != null
        val reason = when {
            mode == "gpu" && !vulkan -> "no_vulkan"
            else -> "forced"
        }
        val probe = if (mode == "gpu" && !vulkan) "cpu" else if (mode == "gpu") "vulkan" else "cpu"
        writeBackend(current.copy(mode = mode, probe = probe, reason = reason, probed = true, checking = false, version = stamp))
    }

    fun noteCpu(reason: String) {
        val current = backendRecord()
        val stamp = DeviceTune.probeStamp(appVersion())
        val suspect = current.mali || DeviceTune.suspectMali(
            PhoneFacts.socName(),
            android.os.Build.MODEL.orEmpty(),
            current.vkName + " " + current.glRenderer,
        )
        writeBackend(
            current.copy(
                mode = "auto",
                probe = "cpu",
                reason = reason,
                probed = true,
                version = stamp,
                checking = false,
                mali = suspect,
                isolated = false,
            ),
        )
    }

    fun disarmUnprovenMali() {
        val stamp = DeviceTune.probeStamp(appVersion())
        val record = backendRecord()
        if (record.mode != "auto") return
        val suspect = DeviceTune.suspectMali(
            PhoneFacts.socName(),
            android.os.Build.MODEL.orEmpty(),
            record.vkName + " " + record.glRenderer,
        )
        if (!suspect) return
        val proven = record.isolated && record.probe == "vulkan" && record.version == stamp && record.reason == "matched_faster"
        if (proven) return
        if (record.version == stamp && record.probed && record.probe == "cpu" && record.reason != "pending") return
        writeBackend(
            record.copy(
                probe = "cpu",
                reason = "mali_unproven",
                probed = false,
                version = stamp,
                checking = true,
                mali = true,
                isolated = false,
            ),
        )
    }

    fun withBackend(backend: String, block: () -> String): String {
        val previous = nglOverride
        nglOverride = if (backend == "vulkan") 99 else 0
        return try {
            block()
        } finally {
            nglOverride = previous
        }
    }

    fun ensureBackend() {
        val version = appVersion()
        val stamp = DeviceTune.probeStamp(version)
        val current = backendRecord()
        if (current.mode != "auto") {
            setBackendMode(current.mode)
            return
        }
        if (current.probed && current.version == stamp && current.reason != "no_model") return
        writeBackend(current.copy(checking = true, reason = "checking", version = stamp))
        val vulkan = tool("libggml-vulkan.so") != null && tool("libggml-cpu.so") != null
        val ready = baseModel() != null && bgeModel() != null && binariesReady()
        val gpuChat = if (vulkan && ready) probeChat(99) else TimedRun(2, "", "")
        val cpuChat = if (vulkan && ready && gpuChat.code == 0) probeChat(0) else TimedRun(1, "", "")
        val gpuReply = DeviceTune.extractReply(gpuChat.text)
        val cpuReply = DeviceTune.extractReply(cpuChat.text)
        val chatOk = gpuChat.code == 0 && DeviceTune.chatMatch(cpuReply, gpuReply)
        val gpuEmbed = if (vulkan && ready && chatOk) probeEmbed(99) else null
        val cpuEmbed = if (gpuEmbed != null && gpuEmbed.code == 0) probeEmbed(0) else null
        val gpuVec = gpuEmbed?.vector
        val cpuVec = cpuEmbed?.vector
        val embedOk = gpuVec != null && cpuVec != null && DeviceTune.vectorsMatch(cpuVec, gpuVec)
        val caps = DeviceTune.parseVulkanCaps(gpuChat.err)
        val renderer = try {
            markNative("selftest", "vulkan")
            PhoneFacts.glRenderer()
        } catch (_: Throwable) {
            ""
        }
        val mali = DeviceTune.looksLikeMali(caps, renderer) || DeviceTune.suspectMali(PhoneFacts.socName(), android.os.Build.MODEL.orEmpty(), caps.name + " " + renderer)
        if (gpuChat.code > 128) {
            LlmGuard(crashFile()).onDeath(
                "selftest",
                "vulkan",
                driverKey(caps, renderer),
                LlmGuard.signalName(gpuChat.code),
                gpuChat.err.take(800),
            )
        }
        var gpuPrefill = DeviceTune.parseTps(gpuChat.err).first
        var gpuDecode = DeviceTune.parseTps(gpuChat.err).second
        var cpuPrefill = DeviceTune.parseTps(cpuChat.err).first
        var cpuDecode = DeviceTune.parseTps(cpuChat.err).second
        var gpuSpeedStatus = -1
        if (mali && chatOk && embedOk) {
            val gpuSpeed = probeSpeed(99)
            gpuSpeedStatus = gpuSpeed.code
            if (gpuSpeed.code == 0) {
                val parsed = DeviceTune.parseTps(gpuSpeed.err)
                if (parsed.first > 0.0) gpuPrefill = parsed.first
                if (parsed.second > 0.0) gpuDecode = parsed.second
                val cpuSpeed = probeSpeed(0)
                if (cpuSpeed.code == 0) {
                    val parsedCpu = DeviceTune.parseTps(cpuSpeed.err)
                    if (parsedCpu.first > 0.0) cpuPrefill = parsedCpu.first
                    if (parsedCpu.second > 0.0) cpuDecode = parsedCpu.second
                    else gpuSpeedStatus = -1
                } else {
                    cpuDecode = 0.0
                    gpuSpeedStatus = -1
                }
            }
        }
        val decided = DeviceTune.decide(
            mode = "auto",
            vulkanPresent = vulkan,
            modelsReady = ready,
            gpuChatStatus = if (!vulkan || !ready) 0 else gpuChat.code,
            cpuReply = cpuReply,
            gpuReply = gpuReply,
            gpuEmbedStatus = gpuEmbed?.code ?: if (!vulkan || !ready || gpuChat.code != 0) 0 else 1,
            cpuVec = cpuEmbed?.vector,
            gpuVec = gpuEmbed?.vector,
            version = stamp,
            mali = mali,
            gpuSpeedStatus = if (mali && chatOk && embedOk) gpuSpeedStatus else 0,
            gpuDecodeTps = gpuDecode,
            cpuDecodeTps = cpuDecode,
            isolated = true,
        )
        if (backendRecord().mode != "auto") return
        writeBackend(
            decided.copy(
                gpuPrefillTps = gpuPrefill,
                gpuDecodeTps = gpuDecode,
                cpuPrefillTps = cpuPrefill,
                cpuDecodeTps = cpuDecode,
                vkName = caps.name,
                vkDriver = caps.driver,
                vkDriverVersion = caps.versionText(),
                vkSubgroup = caps.subgroup,
                vkFlags = caps.flags(),
                glRenderer = renderer.ifBlank { current.glRenderer },
            ),
        )
    }

    fun diagnostics(): String {
        val version = appVersion()
        val body = DeviceTune.renderDiagnostics(PhoneFacts.collect(this, version))
        val route = File(context.filesDir, "setup/last-route.json").takeIf { it.exists() }?.readText()?.trim().orEmpty()
        val gl = File(context.filesDir, "setup/nebula-gl.txt").takeIf { it.exists() }?.readText()?.trim().orEmpty()
        val console = File(context.filesDir, "setup/nebula-console.txt").takeIf { it.exists() }?.readText()?.trim().orEmpty()
        return buildString {
            append(body.trimEnd())
            append('\n')
            if (route.isNotEmpty()) {
                append("last-route:\n")
                append(route.take(2000))
                append('\n')
            }
            if (gl.isNotEmpty()) {
                append("nebula-gl:\n")
                append(gl.take(800))
                append('\n')
            }
            if (console.isNotEmpty()) {
                append("nebula-console:\n")
                append(console.take(2000))
                append('\n')
            }
        }
    }

    fun crashNotes(): String {
        val guardText = LlmGuard(crashFile()).render()
        val native = File(context.filesDir, "setup/native-crash.txt").takeIf { it.exists() }?.readText().orEmpty()
        return buildString {
            append(guardText)
            if (native.isNotBlank()) {
                appendLine("tombstone:")
                appendLine(native.take(4000))
            }
        }
    }

    private fun probeChat(ngl: Int): TimedRun {
        val cli = tool("libllama-cli.so") ?: return TimedRun(1, "", "")
        val base = baseModel() ?: return TimedRun(1, "", "")
        val threads = PhoneFacts.threads().toString()
        return runToolTimed(
            listOf(
                cli.absolutePath, "-m", base.absolutePath,
                "-p", DeviceTune.PROBE_PROMPT,
                "--temp", "0", "--top-k", "1", "--top-p", "1", "--min-p", "0",
                "-n", "8", "-ngl", ngl.toString(), "-t", threads, "-tb", threads,
                "--no-warmup", "-c", "64", "--single-turn",
            ),
            File(context.cacheDir, "probe-chat-$ngl"),
            180,
        )
    }

    private fun probeSpeed(ngl: Int): TimedRun {
        val cli = tool("libllama-cli.so") ?: return TimedRun(1, "", "")
        val base = baseModel() ?: return TimedRun(1, "", "")
        val threads = PhoneFacts.threads().toString()
        return runToolTimed(
            listOf(
                cli.absolutePath, "-m", base.absolutePath,
                "-p", DeviceTune.SPEED_PROMPT,
                "--temp", "0", "--top-k", "1", "--top-p", "1", "--min-p", "0",
                "-n", "16", "-ngl", ngl.toString(), "-t", threads, "-tb", threads,
                "-c", "256", "--single-turn",
            ),
            File(context.cacheDir, "probe-speed-$ngl"),
            180,
        )
    }

    private fun probeEmbed(ngl: Int): ToolRun {
        return try {
            val embedder = tool("libllama-embedding.so") ?: return ToolRun(1, "")
            val bge = bgeModel() ?: return ToolRun(1, "")
            val work = File(context.cacheDir, "probe-emb-$ngl").apply { mkdirs() }
            File(work, "prompts.txt").writeText("北京\n")
            val threads = PhoneFacts.threads().toString()
            val result = runToolTimed(
                listOf(
                    embedder.absolutePath, "-m", bge.absolutePath, "-f", File(work, "prompts.txt").absolutePath,
                    "--pooling", "mean", "--embd-normalize", "2", "-c", "32",
                    "-ngl", ngl.toString(), "-t", threads, "-tb", threads,
                    "--embd-output-format", "array",
                ),
                work,
                180,
            )
            if (result.code != 0) return ToolRun(result.code, "")
            val start = result.text.indexOf('[')
            if (start < 0) return ToolRun(1, "")
            val parsed = JSONArray(result.text.substring(start).trim())
            val row = if (parsed.length() > 0 && parsed.optJSONArray(0) != null) parsed.getJSONArray(0) else parsed
            val out = FloatArray(row.length())
            for (i in 0 until row.length()) out[i] = row.getDouble(i).toFloat()
            ToolRun(0, "", out)
        } catch (_: Throwable) {
            ToolRun(1, "")
        }
    }

    private fun appVersion(): String = try {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: ""
    } catch (_: Throwable) {
        ""
    }

    private fun backendFile(): File = File(context.filesDir, "setup/backend.json")

    private fun writeBackend(record: BackendRecord) {
        val file = backendFile()
        file.parentFile?.mkdirs()
        file.writeText(DeviceTune.writeRecord(record))
    }

    private fun runTool(cmd: List<String>, work: File): String = runToolStream(cmd, work) {}

    private fun runToolStream(cmd: List<String>, work: File, onRaw: (String) -> Unit): String {
        val result = runToolTimed(cmd, work, 180, onRaw)
        if (result.code > 128) throw NativeCrash(result.code - 128, result.err.take(800))
        if (result.code != 0 && result.text.isBlank()) {
            error(result.err.lineSequence().lastOrNull { it.isNotBlank() } ?: "exit ${result.code}")
        }
        return result.text.ifBlank { result.err }
    }

    private fun runToolTimed(cmd: List<String>, work: File, timeoutSec: Long, onRaw: (String) -> Unit = {}): TimedRun {
        work.mkdirs()
        val proc = ProcessBuilder(cmd)
            .directory(work)
            .redirectErrorStream(false)
            .apply { environment()["LD_LIBRARY_PATH"] = nativeDir }
            .start()
        val out = StringBuilder()
        val err = StringBuilder()
        val stdout = Thread {
            val reader = proc.inputStream.bufferedReader()
            val buf = CharArray(128)
            while (true) {
                val n = reader.read(buf)
                if (n < 0) break
                val snapshot = synchronized(out) {
                    out.append(buf, 0, n)
                    out.toString()
                }
                try {
                    onRaw(snapshot)
                } catch (_: Throwable) {
                }
            }
        }
        val stderr = Thread { err.append(proc.errorStream.bufferedReader().readText()) }
        stdout.start()
        stderr.start()
        val finished = proc.waitFor(timeoutSec, TimeUnit.SECONDS)
        if (!finished) proc.destroyForcibly()
        stdout.join(2000)
        stderr.join(2000)
        val code = if (!finished) 2 else proc.exitValue()
        return TimedRun(code, out.toString().ifBlank { "" }, err.toString())
    }

    private fun nglNow(): Int = nglOverride ?: DeviceTune.ngl(runtimeRecord())

    private fun <T> guarded(stage: String, block: () -> T): T {
        return try {
            block()
        } catch (crash: NativeCrash) {
            val backend = if (nglNow() > 0) "vulkan" else "cpu"
            LlmGuard(crashFile()).onDeath(
                stage,
                backend,
                driverKey(),
                LlmGuard.signalName(128 + crash.signal),
                crash.detail,
            )
            if (backend == "cpu") throw crash
            noteCpu("native_crash")
            val previous = nglOverride
            nglOverride = 0
            try {
                block()
            } finally {
                nglOverride = previous
            }
        }
    }

    private fun markNative(stage: String, backend: String) {
        try {
            NativeRouter.setStage(stage, backend)
        } catch (_: Throwable) {
        }
    }

    private fun crashFile() = File(context.filesDir, "setup/crashes.json")

    private fun driverKey(caps: VulkanCaps, renderer: String): String {
        val driver = caps.versionText().ifBlank { "unknown" }
        val name = caps.name.ifBlank { renderer }.ifBlank { PhoneFacts.socName() }.ifBlank { "device" }
        return "$name|$driver"
    }

    companion object {
        fun maskQuery(text: String, namesLongestFirst: List<String>): String {
            var out = text
            for (name in namesLongestFirst) {
                if (name.isNotEmpty() && name in out) out = out.replace(name, "某")
            }
            return out
        }

        fun writeF32(file: File, rows: List<FloatArray>) {
            file.outputStream().buffered().use { out ->
                val buf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
                for (row in rows) {
                    for (value in row) {
                        buf.clear()
                        buf.putFloat(value)
                        out.write(buf.array())
                    }
                }
            }
        }

        fun readF32(file: File): FloatArray {
            val bytes = file.readBytes()
            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val out = FloatArray(bytes.size / 4)
            for (i in out.indices) out[i] = buf.float
            return out
        }

        private fun floatRow(arr: JSONArray): FloatArray {
            val out = FloatArray(arr.length())
            for (i in 0 until arr.length()) out[i] = arr.getDouble(i).toFloat()
            return out
        }
    }
}

data class RouteHit(val expert: String?, val fired: Boolean, val reason: String, val sim: Double)

private data class ToolRun(val code: Int, val text: String, val vector: FloatArray? = null)

private data class TimedRun(val code: Int, val text: String, val err: String)
